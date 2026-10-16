"""Profile lifecycle wiring with a fake SSH transport and local-only commands."""
import json
import os
from contextlib import contextmanager
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import executor as executor_module, poller as module, remote_fs
from lib.audit import AuditLog
from lib.profiles import create_profile
from lib.sandbox import require_execution_policy, safe_environment


@pytest.fixture(autouse=True)
def explicit_lifecycle_test_process_adapter(monkeypatch, tmp_path, request):
    """Local process adapter; the stdlib environment smoke keeps the real one."""
    calls = []
    if request.node.name == "test_real_offline_venv_survives_pull_and_is_used_by_requests":
        return calls
    scratch = tmp_path / "lifecycle-test-scratch"
    scratch.mkdir()

    @contextmanager
    def adapter(cfg, argv, **kwargs):
        require_execution_policy(cfg)
        calls.append(list(argv))
        yield list(argv), {**safe_environment(), "TMPDIR": str(scratch)}

    monkeypatch.setattr(executor_module, "command_context", adapter)
    return calls


def make_profile(tmp_path, name="demo"):
    key = tmp_path / "key"
    key.touch(exist_ok=True)
    return create_profile(name, ssh_host="host", ssh_key=str(key), remote_repo_root="/srv/" + name,
                          environment={"mode": "command", "python": sys.executable, "command": "true"},
                          profiles_dir=tmp_path / "profiles")


def transport(monkeypatch, request, events, uploads):
    ok = remote_fs.CmdResult(True, "", "", 0, 1)
    def download(cfg, remote, local):
        Path(local).write_text(json.dumps(request))
        return ok
    def pull(cfg, remote, local, excludes):
        events.append("pull")
        shutil.rmtree(local)
        Path(local).mkdir()
        (Path(local) / "source.py").write_text("VALUE = 1\n")
        (Path(local) / "pyproject.toml").write_text('[project]\nname="synthetic"\nversion="0.0.0"\n')
        return ok
    def upload(cfg, local, remote):
        uploads.append(json.loads(Path(local).read_text()))
        return ok
    monkeypatch.setattr(remote_fs, "download_file", download)
    monkeypatch.setattr(remote_fs, "tar_sync_from_remote", pull)
    monkeypatch.setattr(remote_fs, "upload_file", upload)
    monkeypatch.setattr(remote_fs, "remote_move", lambda *args: ok)


def request(command="echo request-ran"):
    return {"request_id": "first", "commands": [{"cmd": command}], "sync": "pull"}


def test_prepare_after_pull_before_request_and_report(tmp_path, monkeypatch):
    cfg = make_profile(tmp_path)
    events, uploads = [], []
    transport(monkeypatch, request(), events, uploads)
    original = module.execute_request
    def prepare(cfg):
        events.append("prepare")
        assert (cfg.local_repo_root / "source.py").exists()
        return {"status": "ready", "fingerprint": "a" * 64}
    def execute(*args, **kwargs):
        events.append("execute")
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "prepare_environment", prepare)
    monkeypatch.setattr(module, "execute_request", execute)
    assert module.Poller(cfg, AuditLog(cfg.audit_log_path))._handle_request("first.json")
    assert events == ["pull", "prepare", "execute"]
    assert uploads[0]["overall_status"] == "success"
    assert uploads[0]["environment"]["status"] == "ready"
    assert cfg.prepared_environment_fingerprint == "a" * 64


def test_failed_setup_stops_commands_and_push(tmp_path, monkeypatch):
    cfg = make_profile(tmp_path)
    req = request()
    events, uploads = [], []
    transport(monkeypatch, req, events, uploads)
    monkeypatch.setattr(module, "prepare_environment", lambda cfg: {"status": "error", "error": "installation exit 1"})
    def forbidden(*args, **kwargs):
        pytest.fail("execution and push must not run")
    monkeypatch.setattr(module, "execute_request", forbidden)
    monkeypatch.setattr(remote_fs, "tar_sync_to_remote", forbidden)
    assert module.Poller(cfg, AuditLog(cfg.audit_log_path))._handle_request("first.json")
    assert uploads[0]["overall_status"] == "error"
    assert uploads[0]["environment"]["status"] == "error"
    assert uploads[0]["sync"]["push"]["reason"] == "environment_failed"
    assert uploads[0]["results"] == []


@pytest.mark.parametrize("sync_mode", ["push", "both"])
def test_source_push_rejected_before_pull_setup_or_commands(tmp_path, monkeypatch, sync_mode,
                                                         explicit_lifecycle_test_process_adapter):
    cfg = make_profile(tmp_path)
    req = {**request(), "sync": sync_mode}
    events, uploads = [], []
    transport(monkeypatch, req, events, uploads)

    def forbidden(*args, **kwargs):
        pytest.fail("source push must be rejected before setup or command execution")

    monkeypatch.setattr(module, "prepare_environment", forbidden)
    monkeypatch.setattr(module, "execute_request", forbidden)
    monkeypatch.setattr(remote_fs, "tar_sync_to_remote", forbidden)
    assert module.Poller(cfg, AuditLog(cfg.audit_log_path))._handle_request("first.json")
    assert not events
    assert uploads[0]["overall_status"] == "error"
    assert uploads[0]["sync"] == {"status": "not_started", "reason": "execution_policy"}
    assert uploads[0]["results"] == []
    assert explicit_lifecycle_test_process_adapter == []


@pytest.mark.parametrize("unsafe_setting", ["unknown_mode", "installer_network"])
def test_unsafe_policy_rejected_before_lifecycle_adapter(tmp_path, monkeypatch, unsafe_setting,
                                                        explicit_lifecycle_test_process_adapter):
    cfg = make_profile(tmp_path)
    if unsafe_setting == "unknown_mode":
        cfg.execution_sandbox = "unsupported"
    else:
        cfg.sandbox_install_network = True
    events, uploads = [], []
    transport(monkeypatch, request(), events, uploads)
    monkeypatch.setattr(module, "prepare_environment", lambda cfg: pytest.fail("no setup for unsafe policy"))
    assert module.Poller(cfg, AuditLog(cfg.audit_log_path))._handle_request("first.json")
    assert not events
    assert uploads[0]["overall_status"] == "error"
    assert uploads[0]["sync"]["reason"] == "execution_policy"
    assert explicit_lifecycle_test_process_adapter == []


def test_unsafe_request_cannot_trigger_setup(tmp_path, monkeypatch):
    cfg = make_profile(tmp_path)
    events, uploads = [], []
    transport(monkeypatch, request("printenv"), events, uploads)
    def forbidden(*args):
        pytest.fail("unsafe request must not prepare environment")
    monkeypatch.setattr(module, "prepare_environment", forbidden)
    assert module.Poller(cfg, AuditLog(cfg.audit_log_path))._handle_request("first.json")
    assert not events
    assert uploads[0]["overall_status"] == "error"


def test_same_request_id_is_independent_between_projects(tmp_path, monkeypatch):
    events, uploads = [], []
    transport(monkeypatch, request(), events, uploads)
    monkeypatch.setattr(module, "prepare_environment", lambda cfg: {"status": "reused", "fingerprint": "a" * 64})
    for name in ("one", "two"):
        cfg = make_profile(tmp_path, name)
        assert module.Poller(cfg, AuditLog(cfg.audit_log_path))._handle_request("first.json")
    assert len(uploads) == 2
    assert all(report["overall_status"] == "success" for report in uploads)


@pytest.mark.parametrize("legacy_entry", ["file", "symlink"])
def test_each_request_uses_fresh_transfer_scratch_and_preserves_legacy_path(tmp_path, monkeypatch, legacy_entry):
    cfg = make_profile(tmp_path)
    legacy = cfg.local_repo_root.parent / ".harness-watcher-tmp"
    legacy.mkdir()
    protected_targets = {}
    for request_id in ("first", "second"):
        path = legacy / f"{request_id}.json"
        if legacy_entry == "symlink":
            target = tmp_path / f"preexisting-{request_id}.json"
            target.write_text(f"synthetic original {request_id}")
            path.symlink_to(target)
        else:
            path.write_text(f"synthetic original {request_id}")
            target = path
        protected_targets[path] = target

    req = request()
    events, uploads, downloaded_paths = [], [], []
    transport(monkeypatch, req, events, uploads)
    original_download = remote_fs.download_file

    def record_download(cfg, remote, local):
        downloaded_paths.append(Path(local))
        return original_download(cfg, remote, local)

    monkeypatch.setattr(remote_fs, "download_file", record_download)
    monkeypatch.setattr(module, "prepare_environment", lambda cfg: {"status": "ready", "fingerprint": "a" * 64})
    poller = module.Poller(cfg, AuditLog(cfg.audit_log_path))
    for request_id in ("first", "second"):
        req["request_id"] = request_id
        assert poller._handle_request(f"{request_id}.json")

    assert all(report["overall_status"] == "success" for report in uploads)
    assert len(downloaded_paths) == 2
    assert downloaded_paths[0].parent != downloaded_paths[1].parent
    for path in downloaded_paths:
        assert path.parent.name.startswith("harness-transfer-")
        assert path.parent != legacy
        assert not path.parent.exists(), "fresh request scratch must be cleaned after reporting"
    for path, target in protected_targets.items():
        expected = f"synthetic original {path.stem}"
        assert path.is_symlink() == (legacy_entry == "symlink")
        assert path.read_text() == expected
        assert target.read_text() == expected


def test_filename_traversal_rejected_before_download(tmp_path, monkeypatch):
    cfg = make_profile(tmp_path)
    def forbidden(*args):
        pytest.fail("must not download to an unsafe local path")
    monkeypatch.setattr(remote_fs, "download_file", forbidden)
    assert not module.Poller(cfg, AuditLog(cfg.audit_log_path))._handle_request("../../outside.json")


def test_uv_lock_repair_invalidates_stamp_without_bootstrap(tmp_path, monkeypatch):
    cfg = make_profile(tmp_path)
    stamp = cfg.managed_root / "environment.json"
    stamp.write_text('{"old": "success"}')
    events, uploads = [], []
    transport(monkeypatch, request("uv lock --offline"), events, uploads)
    monkeypatch.setattr(module, "prepare_environment", lambda cfg: pytest.fail("lock repair must work before bootstrap"))
    def execute(cfg, req, **kwargs):
        assert not stamp.exists()
        events.append("repair-lock")
        return module.ExecResult("first", None, "now", "now", 1, "success")
    monkeypatch.setattr(module, "execute_request", execute)
    assert module.Poller(cfg, AuditLog(cfg.audit_log_path), verbose=True)._handle_request("first.json")
    assert events == ["pull", "repair-lock"]
    assert uploads[0]["environment"]["status"] == "maintenance"
    assert "push" in uploads[0]["environment"]["warning"]
    assert "disabled" in uploads[0]["environment"]["warning"]
    assert not stamp.exists()


@pytest.mark.parametrize("override", [{"commands": [{"cmd": "echo safe", "cwd": "../../outside"}]},
                                      {"timeout_seconds": "bad"}, {"timeout_seconds": 0}])
def test_malformed_request_does_not_trigger_setup(tmp_path, monkeypatch, override):
    cfg = make_profile(tmp_path)
    events, uploads = [], []
    transport(monkeypatch, {**request(), **override}, events, uploads)
    monkeypatch.setattr(module, "prepare_environment", lambda cfg: pytest.fail("no setup for invalid requests"))
    assert module.Poller(cfg, AuditLog(cfg.audit_log_path))._handle_request("first.json")
    assert not events
    assert uploads[0]["overall_status"] == "error"


def test_real_offline_venv_survives_pull_and_is_used_by_requests(tmp_path, monkeypatch):
    cfg = make_profile(tmp_path)
    cfg.sandbox_binary = str(tmp_path / "not-installed")
    req = request('python -c "import sys; print(sys.prefix)"')
    events, uploads = [], []
    transport(monkeypatch, req, events, uploads)
    poller = module.Poller(cfg, AuditLog(cfg.audit_log_path))
    assert poller._handle_request("first.json")
    assert uploads[0]["overall_status"] == "success"
    assert uploads[0]["environment"]["status"] == "ready"
    assert uploads[0]["results"][0]["stdout"].strip() == str(cfg.managed_root / "venv")
    req["request_id"] = "second"
    assert poller._handle_request("second.json")
    assert uploads[1]["overall_status"] == "success"
    assert uploads[1]["environment"]["status"] == "reused"
    assert uploads[1]["results"][0]["stdout"].strip() == str(cfg.managed_root / "venv")
    assert events == ["pull", "pull"]
