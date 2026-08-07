"""Тесты executor — выполнение команд локально."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib import poller as poller_module
from lib import remote_fs
from lib.audit import AuditLog
from lib.config import Config
from lib.executor import execute_request
from lib.poller import (
    Poller,
    _capture_source_snapshot,
    _commands_fingerprint,
    _dependency_fingerprint,
    _execution_profile_fingerprint,
    _request_identity,
)


def make_cfg(tmp_path: Path) -> Config:
    fake_key = tmp_path / "key"
    fake_key.write_text("k")
    local = tmp_path / "local"
    local.mkdir()
    return Config(
        ssh_host="u@h",
        ssh_port=22,
        ssh_key=str(fake_key),
        remote_repo_root="/remote",
        local_repo_root=local,
        default_timeout_seconds=30,
        stdout_max_chars=1000,
        stderr_max_chars=500,
        audit_log_path=tmp_path / "audit.jsonl",
        state_path=tmp_path / "state.json",
    )


def test_simple_echo(tmp_path):
    cfg = make_cfg(tmp_path)
    req = {
        "request_id": "test-1",
        "task_id": "T-1",
        "commands": [{"cmd": "echo hello world", "cwd": "."}],
        "timeout_seconds": 10,
    }
    r = execute_request(cfg, req)
    assert r.overall_status == "success"
    assert len(r.results) == 1
    assert r.results[0].exit_code == 0
    assert "hello world" in r.results[0].stdout


def test_multiple_commands_success(tmp_path):
    cfg = make_cfg(tmp_path)
    req = {
        "request_id": "test-2",
        "commands": [
            {"cmd": "echo step1", "cwd": "."},
            {"cmd": "echo step2", "cwd": "."},
            {"cmd": "echo step3", "cwd": "."},
        ],
    }
    r = execute_request(cfg, req)
    assert r.overall_status == "success"
    assert len(r.results) == 3
    assert all(cr.exit_code == 0 for cr in r.results)


def test_stop_on_failure(tmp_path):
    cfg = make_cfg(tmp_path)
    req = {
        "request_id": "test-3",
        "commands": [
            {"cmd": "echo ok", "cwd": "."},
            {"cmd": "false", "cwd": "."},
            {"cmd": "echo never-reached", "cwd": "."},
        ],
        "stop_on_failure": True,
    }
    r = execute_request(cfg, req)
    assert r.overall_status == "failure"
    # Должен остановиться на 2-й команде
    assert len(r.results) == 2
    assert r.results[0].exit_code == 0
    assert r.results[1].exit_code != 0


def test_continue_on_failure(tmp_path):
    cfg = make_cfg(tmp_path)
    req = {
        "request_id": "test-4",
        "commands": [
            {"cmd": "false", "cwd": "."},
            {"cmd": "echo still-runs", "cwd": "."},
        ],
        "stop_on_failure": False,
    }
    r = execute_request(cfg, req)
    assert r.overall_status == "failure"
    assert len(r.results) == 2
    assert "still-runs" in r.results[1].stdout


def test_cwd_subdirectory(tmp_path):
    cfg = make_cfg(tmp_path)
    sub = cfg.local_repo_root / "subdir"
    sub.mkdir()
    (sub / "marker").write_text("found")

    req = {
        "request_id": "test-5",
        "commands": [{"cmd": "cat marker", "cwd": "subdir"}],
    }
    r = execute_request(cfg, req)
    assert r.results[0].exit_code == 0
    assert "found" in r.results[0].stdout


def test_cwd_escape_blocked(tmp_path):
    cfg = make_cfg(tmp_path)
    req = {
        "request_id": "test-6",
        "commands": [{"cmd": "ls", "cwd": "../../../etc"}],
    }
    r = execute_request(cfg, req)
    assert r.overall_status == "error"
    assert "escape" in (r.error or "").lower() or any("escape" in cr.stderr.lower() for cr in r.results)


def test_empty_commands(tmp_path):
    cfg = make_cfg(tmp_path)
    req = {"request_id": "test-7", "commands": []}
    r = execute_request(cfg, req)
    assert r.overall_status == "error"
    assert "no commands" in (r.error or "").lower()


def test_stdout_truncation(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.stdout_max_chars = 100
    # Команда генерит 1000 символов
    req = {
        "request_id": "test-8",
        "commands": [{"cmd": "python3 -c \"print('A' * 1000)\"", "cwd": "."}],
    }
    r = execute_request(cfg, req)
    assert len(r.results[0].stdout) < 500  # 100 + префикс про truncation
    assert "truncated" in r.results[0].stdout


def test_timeout(tmp_path):
    cfg = make_cfg(tmp_path)
    req = {
        "request_id": "test-9",
        "commands": [{"cmd": "sleep 5", "cwd": "."}],
        "timeout_seconds": 1,
    }
    r = execute_request(cfg, req)
    assert r.overall_status == "timeout"
    assert r.results[0].timed_out


def test_timeout_terminates_the_whole_process_group(tmp_path):
    cfg = make_cfg(tmp_path)
    req = {
        "request_id": "test-timeout-group",
        "commands": [{
            "cmd": (
                "python3 -c 'import pathlib,time; p=pathlib.Path(\"heartbeat.txt\"); "
                "[(p.write_text(str(i)), time.sleep(.1)) for i in range(300)]' "
                "& child=$!; echo $child > child.pid; wait $child"
            ),
            "cwd": ".",
        }],
        "timeout_seconds": 1,
    }

    result = execute_request(cfg, req)
    child_pid = int((cfg.local_repo_root / "child.pid").read_text())
    heartbeat = cfg.local_repo_root / "heartbeat.txt"
    try:
        assert result.overall_status == "timeout"
        before = heartbeat.read_text()
        time.sleep(0.4)
        assert heartbeat.read_text() == before
    finally:
        # Test cleanup in case a regression leaves the child alive.
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_pre_exec_hook_applies(tmp_path):
    """pre_exec_hook выполняется перед командой и его env видна команде."""
    cfg = make_cfg(tmp_path)
    cfg.pre_exec_hook = "export FOO=hello_from_hook"
    req = {
        "request_id": "test-hook",
        "commands": [{"cmd": "echo $FOO", "cwd": "."}],
    }
    r = execute_request(cfg, req)
    assert r.overall_status == "success"
    assert "hello_from_hook" in r.results[0].stdout


def test_pre_exec_hook_empty_default(tmp_path):
    """Если pre_exec_hook не задан — команда работает как раньше."""
    cfg = make_cfg(tmp_path)
    # cfg.pre_exec_hook = "" — по умолчанию
    req = {
        "request_id": "test-no-hook",
        "commands": [{"cmd": "echo plain", "cwd": "."}],
    }
    r = execute_request(cfg, req)
    assert r.overall_status == "success"
    assert "plain" in r.results[0].stdout


def test_pre_exec_hook_failure_blocks_command(tmp_path):
    """Если hook упал — основная команда не запускается (set -e)."""
    cfg = make_cfg(tmp_path)
    cfg.pre_exec_hook = "false"  # сразу exit 1
    req = {
        "request_id": "test-hook-fail",
        "commands": [{"cmd": "echo should_not_appear", "cwd": "."}],
    }
    r = execute_request(cfg, req)
    assert r.overall_status == "failure"
    assert "should_not_appear" not in r.results[0].stdout


def test_failed_requested_pull_skips_commands_and_uploads_error_report(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    cfg.rsync_exclude = [".git"]
    (cfg.local_repo_root / "stale.py").write_text("print('stale')")
    filename = "sync-failed.json"
    request = {
        "request_id": "sync-failed",
        "task_id": "T-001",
        "commands": [{"cmd": "echo must-not-run", "cwd": "."}],
        "sync": "pull",
        "context": {
            "branch": "feature/T-001",
            "commit": "a" * 40,
            "purpose": "verify before commit",
            "verification_level": "scoped",
            "tree_fingerprint": "b" * 64,
            "lock_fingerprint": "N/A",
            "access_token": "must-not-leak",
            "notes": "must-not-leak",
        },
    }
    request["context"]["execution_profile"] = _execution_profile_fingerprint(cfg)
    request["context"]["commands_fingerprint"] = _commands_fingerprint(request)
    uploaded: dict = {}
    moved: list[tuple[str, str]] = []

    def fake_download(_cfg, _remote_path, local_path):
        Path(local_path).write_text(json.dumps(request), encoding="utf-8")
        return remote_fs.CmdResult(True, "", "", 0, 1)

    def fake_upload(_cfg, local_path, _remote_path):
        uploaded.update(json.loads(Path(local_path).read_text(encoding="utf-8")))
        return remote_fs.CmdResult(True, "", "", 0, 1)

    def fake_move(_cfg, src, dst):
        moved.append((src, dst))
        return remote_fs.CmdResult(True, "", "", 0, 1)

    monkeypatch.setattr(remote_fs, "download_file", fake_download)
    monkeypatch.setattr(
        remote_fs,
        "tar_sync_from_remote",
        lambda *_args: remote_fs.CmdResult(False, "", "/remote: sync unavailable", 23, 10),
    )
    monkeypatch.setattr(remote_fs, "upload_file", fake_upload)
    monkeypatch.setattr(remote_fs, "remote_move", fake_move)

    def forbidden_execute(*_args, **_kwargs):
        raise AssertionError("commands must not execute after a failed requested pull")

    monkeypatch.setattr(poller_module, "execute_request", forbidden_execute)
    poller = Poller(cfg, AuditLog(tmp_path / "audit.jsonl"))

    assert poller._handle_request(filename) is True
    assert uploaded["overall_status"] == "error"
    assert uploaded["results"] == []
    assert uploaded["sync"]["pull"]["status"] == "failed"
    assert uploaded["source_snapshot"] == {"status": "unavailable", "reason": "pull_failed"}
    safe_keys = {
        "branch",
        "commit",
        "purpose",
        "verification_level",
        "tree_fingerprint",
        "lock_fingerprint",
        "execution_profile",
        "commands_fingerprint",
    }
    assert uploaded["request_context"] == {
        key: value for key, value in request["context"].items() if key in safe_keys
    }
    assert "access_token" not in uploaded["request_context"]
    assert "notes" not in uploaded["request_context"]
    assert uploaded["evidence"]["observed"]["tree_fingerprint"] is None
    assert uploaded["evidence"]["observed"]["lock_fingerprint"] is None
    assert uploaded["evidence"]["observed"]["execution_profile"] == request["context"]["execution_profile"]
    assert uploaded["evidence"]["observed"]["commands_fingerprint"] == request["context"]["commands_fingerprint"]
    assert uploaded["evidence"]["requested_matches"]["all"] is False
    assert "must-not-leak" not in json.dumps(uploaded)
    assert len(moved) == 1


def test_report_fingerprints_actual_local_tree_not_requested_commit(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    cfg.sync_before_exec = False
    cfg.rsync_exclude = [".git", "*.pyc"]
    cfg.pre_exec_hook = "export WATCHER_TEST_SECRET=never-report-this"
    source = cfg.local_repo_root / "service.py"
    source.write_text("VALUE = 1\n")
    (cfg.local_repo_root / "uv.lock").write_text("version = 1\n")
    filename = "fingerprint.json"
    request = {
        "request_id": "fingerprint",
        "commands": [{"cmd": "test -f service.py", "cwd": "."}],
        "sync": "none",
        "context": {},
    }
    expected_snapshot = _capture_source_snapshot(cfg.local_repo_root, cfg.rsync_exclude)
    expected_lock, _ = _dependency_fingerprint(cfg.local_repo_root, cfg.rsync_exclude)
    request["context"] = {
        "commit": "f" * 40,
        "purpose": "verify before commit",
        "verification_level": "bundle",
        "tree_fingerprint": expected_snapshot["tree_sha256"],
        "lock_fingerprint": expected_lock,
        "execution_profile": _execution_profile_fingerprint(cfg),
        "commands_fingerprint": _commands_fingerprint(request),
    }
    uploaded: dict = {}

    def fake_download(_cfg, _remote_path, local_path):
        Path(local_path).write_text(json.dumps(request), encoding="utf-8")
        return remote_fs.CmdResult(True, "", "", 0, 1)

    def fake_upload(_cfg, local_path, _remote_path):
        uploaded.update(json.loads(Path(local_path).read_text(encoding="utf-8")))
        return remote_fs.CmdResult(True, "", "", 0, 1)

    monkeypatch.setattr(remote_fs, "download_file", fake_download)
    monkeypatch.setattr(remote_fs, "upload_file", fake_upload)
    monkeypatch.setattr(
        remote_fs,
        "remote_move",
        lambda *_args: remote_fs.CmdResult(True, "", "", 0, 1),
    )

    poller = Poller(cfg, AuditLog(tmp_path / "audit.jsonl"))
    assert poller._handle_request(filename) is True

    snapshot = uploaded["source_snapshot"]
    assert uploaded["overall_status"] == "success", json.dumps(uploaded["results"], ensure_ascii=False)
    assert snapshot["status"] == "captured"
    assert snapshot["basis"] == "post_sync_pre_execution"
    assert len(snapshot["tree_sha256"]) == 64
    assert snapshot["tree_sha256"] != uploaded["request_context"]["commit"]
    assert snapshot["git_head"] is None
    assert uploaded["sync"]["mode"] == "none"
    observed = uploaded["evidence"]["observed"]
    assert observed["tree_fingerprint"] == expected_snapshot["tree_sha256"]
    assert observed["lock_fingerprint"] == expected_lock
    assert observed["execution_profile"] == request["context"]["execution_profile"]
    assert observed["commands_fingerprint"] == request["context"]["commands_fingerprint"]
    assert uploaded["evidence"]["requested_matches"] == {
        "tree_fingerprint": True,
        "lock_fingerprint": True,
        "execution_profile": True,
        "commands_fingerprint": True,
        "all": True,
    }
    assert "never-report-this" not in json.dumps(uploaded)

    source.write_text("VALUE = 2\n")
    changed = _capture_source_snapshot(cfg.local_repo_root, cfg.rsync_exclude)
    assert changed["tree_sha256"] != snapshot["tree_sha256"]


def test_source_fingerprint_excludes_transport_and_generated_caches(tmp_path):
    cfg = make_cfg(tmp_path)
    source = cfg.local_repo_root / "service.py"
    source.write_text("VALUE = 1\n")
    transport = cfg.local_repo_root / "docs" / "harness" / "exec-requests"
    transport.mkdir(parents=True)
    (transport / "request-a.json").write_text("{}")
    cache = cfg.local_repo_root / "__pycache__"
    cache.mkdir()
    (cache / "service.pyc").write_bytes(b"first")

    before = _capture_source_snapshot(cfg.local_repo_root, [])
    (transport / "request-a.json").write_text('{"changed": true}')
    (cache / "service.pyc").write_bytes(b"second")
    after_transport_change = _capture_source_snapshot(cfg.local_repo_root, [])
    assert after_transport_change["tree_sha256"] == before["tree_sha256"]

    source.write_text("VALUE = 2\n")
    after_source_change = _capture_source_snapshot(cfg.local_repo_root, [])
    assert after_source_change["tree_sha256"] != before["tree_sha256"]


def test_request_id_replay_is_not_executed_and_preserves_existing_report(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    cfg.sync_before_exec = False
    (cfg.local_repo_root / "service.py").write_text("VALUE = 1\n")
    filename = "replay-001.json"
    request = {
        "request_id": "replay-001",
        "commands": [{"cmd": "test -f service.py", "cwd": "."}],
        "sync": "none",
    }
    uploads: list[dict] = []
    moves: list[tuple[str, str]] = []
    executions: list[str] = []

    def fake_download(_cfg, _remote_path, local_path):
        Path(local_path).write_text(json.dumps(request), encoding="utf-8")
        return remote_fs.CmdResult(True, "", "", 0, 1)

    def fake_upload(_cfg, local_path, _remote_path):
        uploads.append(json.loads(Path(local_path).read_text(encoding="utf-8")))
        return remote_fs.CmdResult(True, "", "", 0, 1)

    def fake_move(_cfg, src, dst):
        moves.append((src, dst))
        return remote_fs.CmdResult(True, "", "", 0, 1)

    real_execute = execute_request

    def counted_execute(*args, **kwargs):
        executions.append("executed")
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(remote_fs, "download_file", fake_download)
    monkeypatch.setattr(remote_fs, "upload_file", fake_upload)
    monkeypatch.setattr(remote_fs, "remote_move", fake_move)
    monkeypatch.setattr(
        remote_fs,
        "remote_file_exists",
        lambda *_args: remote_fs.CmdResult(True, "EXISTS\n", "", 0, 1),
    )
    monkeypatch.setattr(poller_module, "execute_request", counted_execute)

    first_poller = Poller(cfg, AuditLog(tmp_path / "audit-first.jsonl"))
    assert first_poller._handle_request(filename) is True
    assert uploads[0]["overall_status"] == "success"

    # A fresh watcher process loads the persisted claim and must not execute
    # an identically named replay after the original request was moved.
    restarted_poller = Poller(cfg, AuditLog(tmp_path / "audit-second.jsonl"))
    assert restarted_poller._handle_request(filename) is True
    assert executions == ["executed"]
    assert len(uploads) == 1
    assert len(moves) == 2
    persisted = json.loads(cfg.state_path.read_text(encoding="utf-8"))
    assert persisted["claimed_request_ids"] == ["replay-001"]


def test_filename_must_match_request_id_before_execution(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    cfg.sync_before_exec = False
    filename = "different-name.json"
    request = {
        "request_id": "canonical-001",
        "commands": [{"cmd": "echo must-not-run", "cwd": "."}],
        "sync": "none",
    }
    uploaded: dict = {}

    def fake_download(_cfg, _remote_path, local_path):
        Path(local_path).write_text(json.dumps(request), encoding="utf-8")
        return remote_fs.CmdResult(True, "", "", 0, 1)

    def fake_upload(_cfg, local_path, _remote_path):
        uploaded.update(json.loads(Path(local_path).read_text(encoding="utf-8")))
        return remote_fs.CmdResult(True, "", "", 0, 1)

    monkeypatch.setattr(remote_fs, "download_file", fake_download)
    monkeypatch.setattr(remote_fs, "upload_file", fake_upload)
    monkeypatch.setattr(
        remote_fs,
        "remote_move",
        lambda *_args: remote_fs.CmdResult(True, "", "", 0, 1),
    )
    monkeypatch.setattr(
        poller_module,
        "execute_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not execute")),
    )

    poller = Poller(cfg, AuditLog(tmp_path / "audit.jsonl"))
    assert poller._handle_request(filename) is True
    assert uploaded["overall_status"] == "error"
    assert uploaded["results"] == []
    assert uploaded["request_identity"]["filename_matches_request_id"] is False
    assert uploaded["request_identity"]["status"] == "invalid"
    assert not cfg.state_path.exists()


def test_legacy_colon_request_id_is_allowed_only_with_exact_filename():
    legacy_id = "2026-07-17T12:00:37-manual"
    exact = _request_identity(f"{legacy_id}.json", legacy_id)
    assert exact["status"] == "valid"
    assert exact["legacy"] is True
    assert exact["canonical"] is False

    transformed = _request_identity("2026-07-17T12-00-37-manual.json", legacy_id)
    assert transformed["status"] == "invalid"
    assert transformed["filename_matches_request_id"] is False


def test_corrupted_idempotency_state_fails_closed(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    cfg.state_path.write_text("{broken", encoding="utf-8")
    filename = "state-guard.json"
    request = {
        "request_id": "state-guard",
        "commands": [{"cmd": "echo must-not-run", "cwd": "."}],
        "sync": "none",
    }
    uploaded: dict = {}

    def fake_download(_cfg, _remote_path, local_path):
        Path(local_path).write_text(json.dumps(request), encoding="utf-8")
        return remote_fs.CmdResult(True, "", "", 0, 1)

    def fake_upload(_cfg, local_path, _remote_path):
        uploaded.update(json.loads(Path(local_path).read_text(encoding="utf-8")))
        return remote_fs.CmdResult(True, "", "", 0, 1)

    monkeypatch.setattr(remote_fs, "download_file", fake_download)
    monkeypatch.setattr(remote_fs, "upload_file", fake_upload)
    monkeypatch.setattr(
        remote_fs,
        "remote_move",
        lambda *_args: remote_fs.CmdResult(True, "", "", 0, 1),
    )
    monkeypatch.setattr(
        poller_module,
        "execute_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not execute")),
    )

    poller = Poller(cfg, AuditLog(tmp_path / "audit.jsonl"))
    assert poller._handle_request(filename) is True
    assert uploaded["overall_status"] == "error"
    assert uploaded["sync"]["reason"] == "idempotency_state_unavailable"
    assert uploaded["request_identity"]["claim_status"] == "rejected"
