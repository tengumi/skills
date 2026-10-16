"""Integration checks for the command filter, not OS/network isolation."""
from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.config import Config
from lib.executor import execute_request


def settings(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return Config(ssh_host="synthetic", ssh_port=22, ssh_key=str(tmp_path / "key"),
                  remote_repo_root="/synthetic", local_repo_root=root)


@pytest.mark.parametrize("unsafe_setting", ["unknown_mode", "installer_network"])
def test_unsupported_execution_configuration_never_starts_a_process(tmp_path, monkeypatch, unsafe_setting):
    cfg = settings(tmp_path)
    if unsafe_setting == "unknown_mode":
        cfg.execution_sandbox = "unsupported"
    else:
        cfg.sandbox_install_network = True
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("unsupported policy spawned a process"))
    result = execute_request(cfg, {"commands": [{"cmd": "true"}]})
    assert result.overall_status == "error"
    assert result.error
    assert not any(item.stdout for item in result.results)


@pytest.mark.parametrize("command", [
    "curl https://example.invalid", "wget https://example.invalid",
    "ssh synthetic@host true", "rm original.txt", "find . -delete", "cat .env",
])
def test_forbidden_commands_are_rejected_before_process_spawn(tmp_path, monkeypatch, command):
    cfg = settings(tmp_path)
    preserved = cfg.local_repo_root / "original.txt"
    preserved.write_text("synthetic original")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("blocked command spawned a process"))
    result = execute_request(cfg, {"commands": [{"cmd": command}]})
    assert result.overall_status == "error"
    assert preserved.read_text() == "synthetic original"


def test_filter_keeps_offline_project_script_and_requested_cwd_working(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    subdirectory = cfg.local_repo_root / "nested"
    subdirectory.mkdir()
    helper = subdirectory / "check.py"
    helper.write_text(
        "from pathlib import Path\nimport os\n"
        "assert 'SYNTHETIC_UNRECOGNIZED' not in os.environ\n"
        "assert 'BASH_ENV' not in os.environ\n"
        "Path(os.environ['HARNESS_OUTPUT_DIR'], 'result.txt').write_text('synthetic')\n"
        "print(Path.cwd().name)\n"
    )
    monkeypatch.setenv("SYNTHETIC_UNRECOGNIZED", "synthetic-placeholder")
    monkeypatch.setenv("BASH_ENV", str(tmp_path / "not-to-be-loaded"))
    result = execute_request(cfg, {"commands": [{"cmd": shlex.join([sys.executable, "check.py"]), "cwd": "nested"}]})
    assert result.overall_status == "success", result
    assert result.results[0].stdout.strip() == "nested"
    assert not (subdirectory / "result.txt").exists()
