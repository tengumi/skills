"""Connection diagnostics execute remote snippets locally on synthetic files only."""
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.audit import AuditLog
from lib.config import Config
from lib.poller import Poller
from lib import remote_fs


def diagnostic(tmp_path):
    remote = tmp_path / "remote repo with spaces"
    remote.mkdir()
    key = tmp_path / "synthetic-key"
    key.touch()
    cfg = Config(ssh_host="synthetic.invalid", ssh_port=22, ssh_key=str(key),
                 remote_repo_root=str(remote), local_repo_root=tmp_path / "mirror",
                 audit_log_path=tmp_path / "audit.jsonl", state_path=tmp_path / "state.json")
    return Poller(cfg, AuditLog(cfg.audit_log_path)), remote


def local_ssh(monkeypatch, *, missing=None, collision=False, false_success=False):
    calls = []
    def result(ok, text=""):
        return remote_fs.CmdResult(ok, text, "", 0 if ok else 3, 1)
    def run(argv, timeout):
        command = argv[-1]
        calls.append(command)
        assert argv[0] == "ssh"  # Never execute this argv: replace transport.
        if command.startswith("echo PING"):
            return result(True, "PING\nsynthetic\n")
        if command.startswith("which rsync"):
            return result(False)
        if command.startswith("command -v tar"):
            return result(missing != "tar", "TAR_OK\n")
        if command.startswith("test -d"):
            root = shlex.split(command)[2]
            return result(Path(root).is_dir(), "EXISTS\n")
        args = shlex.split(command)
        assert args[:4] == ["python3", "-I", "-S", "-c"]
        if "PYTHON_OK" in args[4] and missing == "python3":
            return result(False, "PYTHON_OK\n")
        if "candidate =" in args[4]:
            if false_success:
                return result(False, "WRITE_OK\n")
            if collision:
                args[4] = args[4].replace(
                    "candidate = '.harness-watcher-probe-' + os.urandom(16).hex()",
                    "candidate = '.harness-watcher-probe-collision'",
                )
        completed = subprocess.run([sys.executable, *args[1:]], capture_output=True,
                                   text=True, timeout=timeout, check=False)
        return remote_fs.CmdResult(completed.returncode == 0, completed.stdout,
                                   completed.stderr, completed.returncode, 1)
    monkeypatch.setattr(remote_fs, "_run", run)
    return calls


def test_exclusive_probe_preserves_former_fixed_name(tmp_path, monkeypatch):
    poller, remote = diagnostic(tmp_path)
    sentinel = remote / ".harness-watcher-write-test"
    sentinel.write_text("unrelated user file")
    calls = local_ssh(monkeypatch)
    result = poller.check_connection()
    assert result["ok"] and result["write_ok"]
    assert result["remote_python3_available"] and result["remote_tar_available"]
    assert result["remote_rsync_available"] is False  # Optional legacy tool.
    assert sentinel.read_text() == "unrelated user file"
    assert list(remote.iterdir()) == [sentinel]
    assert not any("touch " in command or "&& rm " in command for command in calls)


def test_probe_collision_never_truncates_or_deletes_existing_file(tmp_path, monkeypatch):
    poller, remote = diagnostic(tmp_path)
    sentinel = remote / ".harness-watcher-probe-collision"
    sentinel.write_text("keep")
    local_ssh(monkeypatch, collision=True)
    result = poller.check_connection()
    assert result["ok"] is False and result["write_ok"] is False
    assert sentinel.read_text() == "keep"


@pytest.mark.parametrize("missing", ["python3", "tar"])
def test_missing_required_tool_fails_before_write(tmp_path, monkeypatch, missing):
    poller, remote = diagnostic(tmp_path)
    calls = local_ssh(monkeypatch, missing=missing)
    result = poller.check_connection()
    assert result["ok"] is False
    assert result["remote_" + missing + "_available"] is False
    assert not any("candidate =" in command for command in calls)
    assert list(remote.iterdir()) == []


def test_failed_probe_cannot_claim_success_by_stdout(tmp_path, monkeypatch):
    poller, remote = diagnostic(tmp_path)
    local_ssh(monkeypatch, false_success=True)
    result = poller.check_connection()
    assert result["ok"] is False and result["write_ok"] is False
    assert list(remote.iterdir()) == []


def test_remote_symlink_directory_is_not_followed(tmp_path, monkeypatch):
    poller, remote = diagnostic(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(remote, target_is_directory=True)
    poller.cfg.remote_repo_root = str(alias)
    local_ssh(monkeypatch)
    result = poller.check_connection()
    assert result["ok"] is False and result["write_ok"] is False
    assert list(remote.iterdir()) == []


def test_missing_remote_directory_fails_before_write(tmp_path, monkeypatch):
    poller, remote = diagnostic(tmp_path)
    remote.rmdir()
    calls = local_ssh(monkeypatch)
    result = poller.check_connection()
    assert result["ok"] is False and result["repo_root_exists"] is False
    assert not any("candidate =" in command for command in calls)
