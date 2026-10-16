"""Command runtime tests use disposable data and require no external CLI."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.config import Config, ConfigError
from lib.executor import execute_request
from lib.sandbox import (SandboxError, command_context, require_execution_policy,
                         safe_environment, shell_argv, validate_sandbox)


def settings(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return Config(ssh_host="synthetic", ssh_port=22, ssh_key=str(tmp_path / "key"),
                  remote_repo_root="/synthetic", local_repo_root=root)


@pytest.mark.parametrize("spec", [
    {"mode": "unknown"}, {"mode": []}, {"install_network": "false"},
    {"read_roots": ["/"]}, {"secret_roots": ["relative"]},
    {"secret_roots": ["/tmp/*.private"]}, {"binary": "./legacy-cli"}, {"extra": True},
])
def test_bad_configuration_is_rejected(spec):
    with pytest.raises(ConfigError):
        validate_sandbox(spec)


@pytest.mark.parametrize("legacy_mode", ["commands", "none", "codex"])
def test_legacy_modes_normalize_to_command_filter(legacy_mode):
    assert validate_sandbox({"mode": legacy_mode})["mode"] == "commands"


def test_environment_is_allowlist_not_secret_blacklist(monkeypatch):
    for key in ("SYNTHETIC_UNRECOGNIZED", "BASH_ENV", "ENV", "PYTHONPATH", "LD_PRELOAD", "SSH_AUTH_SOCK", "CODEX_HOME"):
        monkeypatch.setenv(key, "synthetic-placeholder")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    result = safe_environment()
    assert set(result) == {"PATH", "LANG", "LC_ALL"}
    assert result["PATH"] == "/usr/bin:/bin"


@pytest.mark.parametrize("installation", [False, True])
def test_context_uses_unchanged_argv_and_private_temporary_paths(tmp_path, installation):
    cfg = settings(tmp_path)
    with command_context(cfg, ["/bin/true"], installation=installation) as (argv, environment):
        assert argv == ["/bin/true"]
        scratch = Path(environment["TMPDIR"])
        home = Path(environment["HOME"])
        output = Path(environment["HARNESS_OUTPUT_DIR"])
        assert scratch.is_dir() and home.is_dir() and output.is_dir()
        assert not scratch.is_relative_to(cfg.local_repo_root)
        assert "BASH_ENV" not in environment
        assert "CODEX_HOME" not in environment
        if installation:
            assert environment["UV_OFFLINE"] == "1"
            assert environment["PIP_NO_INDEX"] == "1"
    assert not scratch.exists()
    assert not home.exists()
    assert not output.exists()


def test_shell_never_loads_login_or_interactive_profiles(tmp_path):
    assert shell_argv(settings(tmp_path), "true") == ["/bin/bash", "--noprofile", "--norc", "-c", "true"]


@pytest.mark.parametrize("legacy_binary", ["", "/synthetic/not-installed", "/usr/bin/false"])
def test_execution_does_not_require_or_invoke_external_cli(tmp_path, legacy_binary):
    cfg = settings(tmp_path)
    cfg.sandbox_binary = legacy_binary
    result = execute_request(cfg, {"commands": [{"cmd": "echo CLI_INDEPENDENT"}]})
    assert result.overall_status == "success", result
    assert result.results[0].stdout.strip() == "CLI_INDEPENDENT"


def test_network_installer_enablement_is_rejected(tmp_path):
    cfg = settings(tmp_path)
    cfg.sandbox_install_network = True
    with pytest.raises(SandboxError, match="network"):
        require_execution_policy(cfg)


def test_existing_hardlink_alias_is_rejected_before_any_command(tmp_path):
    cfg = settings(tmp_path)
    private = cfg.local_repo_root / ".env"
    private.write_text("SYNTHETIC-NOT-PRINTED")
    os.link(private, cfg.local_repo_root / "ordinary-alias")
    result = execute_request(cfg, {"commands": [{"cmd": "echo must-not-run"}]})
    assert result.overall_status == "error"
    assert "hardlinks" in result.results[0].stderr
    assert not result.results[0].stdout


def test_context_does_not_claim_operating_system_file_isolation(tmp_path):
    """A filter cannot inspect arbitrary helper contents or enforce OS rights."""
    cfg = settings(tmp_path)
    outside = tmp_path / "disposable-outside-file.txt"
    outside.write_text("synthetic original")
    helper = cfg.local_repo_root / "helper.py"
    helper.write_text(
        "from pathlib import Path\nimport sys\n"
        "Path(sys.argv[1]).write_text('synthetic changed')\n"
    )
    with command_context(cfg, [sys.executable, str(helper), str(outside)]) as (argv, environment):
        subprocess.run(argv, env=environment, cwd=cfg.local_repo_root, check=True, timeout=5)
    assert outside.read_text() == "synthetic changed"
