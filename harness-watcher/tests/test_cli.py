"""The first-run wizard is local-only; existing TOML invocations still work."""
from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import watcher
from lib.profiles import create_profile, load_profile, profile_lock


def profile(tmp_path, name="demo", environment=None):
    key = tmp_path / "key"
    key.touch(exist_ok=True)
    return create_profile(name, ssh_host="user@host", ssh_key=str(key),
                          remote_repo_root="/srv/target", environment=environment,
                          profiles_dir=tmp_path / "profiles")


def forbid(*args, **kwargs):
    raise AssertionError("no connection or installation should happen")


def test_add_uv_wizard_saves_without_running(tmp_path, monkeypatch, capsys):
    key = tmp_path / "key"
    key.touch()
    answers = iter(["user@host", "22", str(key), "/srv/target", "uv", "3.12.3", "", "", "да"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(watcher, "Poller", forbid)
    assert watcher.main(["add", "demo", "--profiles-dir", str(tmp_path / "profiles")]) == 0
    cfg = load_profile("demo", profiles_dir=tmp_path / "profiles")
    assert cfg.environment["command"] == "uv sync --locked"
    assert cfg.environment["python"] == "3.12.3"
    assert cfg.execution_sandbox == "commands"
    assert cfg.sandbox_install_network is False
    assert not (cfg.managed_root / "venv").exists()
    assert not cfg.state_path.exists()
    assert "Подключений и установки пока не было" in capsys.readouterr().out


def test_declining_install_writes_no_profile(tmp_path, monkeypatch):
    answers = iter(["host", "22", "/key", "/srv/repo", "uv", "3.12", "", "", "нет"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert watcher.main(["add", "demo", "--profiles-dir", str(tmp_path / "profiles")]) == 1
    assert not (tmp_path / "profiles").exists()


def test_reuse_connection_only_asks_project_and_recipe(tmp_path, monkeypatch):
    first = profile(tmp_path, "one")
    answers = iter(["/srv/second", "none"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(watcher, "Poller", forbid)
    assert watcher.main(["add", "two", "--connection-from", "one", "--profiles-dir", str(tmp_path / "profiles")]) == 0
    second = load_profile("two", profiles_dir=tmp_path / "profiles")
    assert second.ssh_host == first.ssh_host
    assert second.ssh_key == first.ssh_key
    assert second.local_repo_root != first.local_repo_root
    assert second.state_path != first.state_path


@pytest.mark.parametrize("action", ["list", "status", "check"])
def test_diagnostics_do_not_prepare_or_poll(tmp_path, monkeypatch, action):
    profile(tmp_path)
    class DiagnosticPoller:
        def __init__(self, *args, **kwargs):
            pass
        def check_connection(self, **kwargs):
            return {"ok": True}
        run_once = loop = forbid
    monkeypatch.setattr(watcher, "Poller", DiagnosticPoller)
    args = ["list"] if action == "list" else ["start", "demo", "--" + action]
    assert watcher.main([*args, "--profiles-dir", str(tmp_path / "profiles")]) == 0


def test_duplicate_start_is_rejected_before_poller(tmp_path, monkeypatch):
    cfg = profile(tmp_path)
    monkeypatch.setattr(watcher, "Poller", forbid)
    with profile_lock(cfg):
        assert watcher.main(["start", "demo", "--once", "--profiles-dir", str(tmp_path / "profiles")]) == 2


def test_start_passes_profile_to_runtime(tmp_path, monkeypatch):
    expected = profile(tmp_path)
    received = []
    class OncePoller:
        def __init__(self, cfg, audit, verbose=False):
            received.append(cfg)
        def ensure_remote_dirs(self):
            return True, ""
        def run_once(self):
            return 0
    monkeypatch.setattr(watcher, "Poller", OncePoller)
    assert watcher.main(["start", "demo", "--once", "--profiles-dir", str(tmp_path / "profiles")]) == 0
    assert received[0].local_repo_root == expected.local_repo_root


def test_legacy_toml_status_remains_supported(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.touch()
    config = tmp_path / "old.toml"
    config.write_text(f'''[remote]
ssh_host="host"
ssh_key="{key}"
remote_repo_root="/srv/repo"
[local]
local_repo_root="{tmp_path / 'mirror'}"
[paths]
audit_log_path="{tmp_path / 'audit.log'}"
state_path="{tmp_path / 'state.json'}"
''')
    monkeypatch.setattr(watcher, "Poller", forbid)
    assert watcher.main(["--config", str(config), "--status"]) == 0


def test_noninteractive_add_exits_cleanly(tmp_path, monkeypatch):
    def no_input(_):
        raise EOFError
    monkeypatch.setattr("builtins.input", no_input)
    assert watcher.main(["add", "demo", "--profiles-dir", str(tmp_path / "profiles")]) == 130
    assert not (tmp_path / "profiles").exists()


def test_help_does_not_require_an_external_agent_cli(capsys):
    with pytest.raises(SystemExit) as error:
        watcher.main(["--help"])
    assert error.value.code == 0
    assert "codex" not in capsys.readouterr().out.lower()


@pytest.mark.parametrize("args", [["start"], ["list", "demo"], ["add", "demo", "--once"],
                                   ["start", "demo", "--config", "old.toml"]])
def test_incompatible_cli_options_are_explicit(args):
    with pytest.raises(SystemExit) as error:
        watcher.main(args)
    assert error.value.code == 2


def test_legacy_protected_add_persists_command_filter_without_execution(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.touch()
    answers = iter(["host", "22", str(key), "/srv/repo", "none"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(watcher, "Poller", forbid)
    assert watcher.main(["add", "guarded", "--protected", "--profiles-dir", str(tmp_path / "profiles")]) == 0
    cfg = load_profile("guarded", profiles_dir=tmp_path / "profiles")
    assert cfg.execution_sandbox == "commands"
    assert cfg.sandbox_install_network is False


def test_legacy_protected_start_uses_filter_without_rewriting_profile(tmp_path, monkeypatch):
    cfg = profile(tmp_path)
    data = json.loads(cfg.config_path.read_text())
    data["sandbox"]["mode"] = "none"
    cfg.config_path.write_text(json.dumps(data))
    received = []
    monkeypatch.setattr(watcher, "_run", lambda cfg, args: received.append(cfg) or 0)
    assert watcher.main(["start", "demo", "--protected", "--check",
                         "--sandbox-read-root", str(tmp_path / "runtime"),
                         "--profiles-dir", str(tmp_path / "profiles")]) == 0
    assert received[0].execution_sandbox == "commands"
    assert str(received[0].sandbox_read_roots[-1]) == str(tmp_path / "runtime")
    assert load_profile("demo", profiles_dir=tmp_path / "profiles").execution_sandbox == "commands"
    assert json.loads(cfg.config_path.read_text())["sandbox"]["mode"] == "none"


@pytest.mark.parametrize("extra", [[], ["--protected"]])
def test_sandbox_flags_cannot_enable_network(extra, capsys):
    with pytest.raises(SystemExit) as error:
        watcher.main(["start", "demo", "--sandbox-install-network", *extra])
    assert error.value.code == 2
    assert "--sandbox-install-network больше не поддерживается" in capsys.readouterr().err


def test_sandbox_read_options_work_without_redundant_protected_flag(tmp_path, monkeypatch):
    profile(tmp_path)
    received = []
    monkeypatch.setattr(watcher, "_run", lambda cfg, args: received.append(cfg) or 0)
    assert watcher.main(["start", "demo", "--check", "--sandbox-binary", "/opt/tools/codex",
                         "--sandbox-read-root", str(tmp_path / "runtime"),
                         "--profiles-dir", str(tmp_path / "profiles")]) == 0
    assert received[0].execution_sandbox == "commands"
    assert received[0].sandbox_binary == "/opt/tools/codex"
    assert str(received[0].sandbox_read_roots[-1]) == str(tmp_path / "runtime")
