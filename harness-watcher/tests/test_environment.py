"""Target environment preparation uses only local synthetic inputs in tests."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib import environment as env
from lib.config import ConfigError


def make_cfg(tmp_path, mode="uv", name="project"):
    root = (tmp_path / name).resolve()
    mirror = root / "mirror"
    mirror.mkdir(parents=True)
    (mirror / "pyproject.toml").write_text('[project]\nname = "synthetic"\nversion = "0.0.0"\n')
    (mirror / "uv.lock").write_text('version = 1\n[[package]]\nname = "synthetic"\nsource = { editable = "." }\n')
    spec = {"mode": mode, "python": "3.12" if mode == "uv" else sys.executable}
    if mode == "command":
        spec["command"] = "make install"
    return SimpleNamespace(managed_root=root, local_repo_root=mirror, environment=spec, profile_name=name)


class FakeToolchain:
    def __init__(self, monkeypatch, cfg):
        self.cfg = cfg
        self.calls = []
        self.installs = 0
        self.fail_install = False
        self.mutate_lock = False
        monkeypatch.setattr(env.shutil, "which", lambda command: sys.executable)
        monkeypatch.setattr(env, "_run", self.run)

    def run(self, argv, cwd, deadline, stage, capture=False, cfg=None):
        assert cfg is self.cfg
        self.calls.append((argv, stage))
        venv = self.cfg.managed_root / "venv"
        if stage == "local Python lookup":
            assert "--no-python-downloads" in argv
            return str(Path(sys.executable).resolve())
        if stage == "venv creation":
            (venv / "bin").mkdir(parents=True)
            (venv / "pyvenv.cfg").write_text("synthetic = true\n")
            (venv / "bin/python").symlink_to(Path(sys.executable).resolve())
            return ""
        if stage == "environment Python validation":
            return json.dumps([str(venv), "/synthetic-base", str(Path(sys.executable).resolve())])
        if stage == "dependency installation":
            self.installs += 1
            assert "UV_PROJECT_ENVIRONMENT=" in argv[-1]
            assert "UV_PYTHON_DOWNLOADS=never" in argv[-1]
            assert "UV_NO_ENV_FILE=1" in argv[-1]
            if self.fail_install:
                raise env._SetupError("dependency installation failed (exit 9); installer output withheld")
            if self.mutate_lock:
                (self.cfg.local_repo_root / "uv.lock").write_text("changed by installer\n")
            return ""
        raise AssertionError(stage)


def test_disabled_does_not_touch_paths_or_run(monkeypatch):
    monkeypatch.setattr(env, "_run", lambda *a, **kw: pytest.fail("must not execute"))
    cfg = SimpleNamespace(environment={"mode": "none"})
    assert env.prepare_environment(cfg) == {"status": "disabled"}
    assert env.environment_hook(cfg) == ""


@pytest.mark.parametrize("command", ["uv lock && make test", "uv lock; printenv", "uv lock --project /tmp/other", "uv sync", "uv lock --python 3.13"])
def test_lock_maintenance_is_not_a_generic_bypass(command):
    cfg = SimpleNamespace(environment={"mode": "uv"})
    assert not env.is_lock_maintenance_request(cfg, {"commands": [{"cmd": command}]})


def test_lock_maintenance_must_be_a_single_root_command():
    cfg = SimpleNamespace(environment={"mode": "uv"})
    assert env.is_lock_maintenance_request(cfg, {"commands": [{"cmd": "uv lock --offline"}]})
    assert not env.is_lock_maintenance_request(cfg, {"commands": [{"cmd": "uv lock", "cwd": "sub"}]})
    assert not env.is_lock_maintenance_request(cfg, {"commands": [{"cmd": "uv lock"}, {"cmd": "make test"}]})


def test_lock_maintenance_cannot_discover_parent_project(tmp_path):
    cfg = make_cfg(tmp_path)
    (cfg.local_repo_root / "pyproject.toml").unlink()
    (cfg.managed_root / "pyproject.toml").write_text('[project]\nname="parent"\n')
    assert env.invalidate_for_lock_maintenance(cfg)["status"] == "error"


@pytest.mark.parametrize("spec", [
    {"mode": "invalid"}, {"mode": []}, {"mode": "uv"},
    {"mode": "uv", "python": "$(which python)"},
    {"mode": "command", "python": "python3"},
    {"mode": "uv", "python": "3.12", "command": "uv sync --frozen"},
    {"mode": "uv", "python": "3.12", "command": "uv sync --locked --no-editable"},
    {"mode": "uv", "python": "3.12", "timeout_seconds": True},
    {"mode": "uv", "python": "3.12", "inputs": ["../external"]},
    {"mode": "uv", "python": "3.12", "inputs": [".env"]},
    {"mode": "uv", "python": "3.12", "inputs": ["certs/key.pem"]},
])
def test_invalid_recipes_rejected(spec):
    with pytest.raises(ConfigError):
        env.validate_environment(spec)


@pytest.mark.parametrize("command", [
    "printenv", "cat .env", "sudo make install", "uv python install 3.12",
    "uv tool install pytest", "pip install --user pytest", "pip install --target /tmp/x pytest",
    "TOKEN=synthetic make install", "make install && printenv", "bash -c 'make install'",
    "pip install --index-url https://synthetic:secret@example.invalid/simple pytest",
    "uv sync --locked --config-file .env", "make install > output.txt",
])
def test_unsafe_recipe_not_saved(command):
    with pytest.raises(ConfigError):
        env.validate_environment({"mode": "command", "python": "python3", "command": command})


def test_uv_first_install_then_reuse_source_edit_and_lock_change(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    tools = FakeToolchain(monkeypatch, cfg)
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert (cfg.managed_root / "environment.json").is_file()
    assert env.prepare_environment(cfg)["status"] == "reused"
    (cfg.local_repo_root / "module.py").write_text("x = 1\n")
    assert env.prepare_environment(cfg)["status"] == "reused"
    (cfg.local_repo_root / "uv.lock").write_text("version = 2\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert tools.installs == 2


def test_workspace_and_generated_manifest_invalidate(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    tools = FakeToolchain(monkeypatch, cfg)
    assert env.prepare_environment(cfg)["status"] == "ready"
    manifest = cfg.local_repo_root / "generated/client/pyproject.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("synthetic = true\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert tools.installs == 2


def test_noneditable_local_uv_package_tracks_source(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    tools = FakeToolchain(monkeypatch, cfg)
    (cfg.local_repo_root / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "synthetic"\nsource = { editable = "." }\n'
        '[[package]]\nname = "client"\nsource = { directory = "libs/client" }\n')
    with (cfg.local_repo_root / "pyproject.toml").open("a") as stream:
        stream.write('\n[tool.uv.sources]\nclient = { path = "libs/client", editable = false }\n')
    source = cfg.local_repo_root / "libs/client/client.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    source.write_text("value = 2\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert tools.installs == 2


def test_unrecognized_uv_lock_conservatively_tracks_source(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    tools = FakeToolchain(monkeypatch, cfg)
    (cfg.local_repo_root / "uv.lock").write_text("version = 1\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    (cfg.local_repo_root / "module.py").write_text("value = 2\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert tools.installs == 2


@pytest.mark.parametrize("source", ["../outside", "/absolute/local/package", "certs"])
def test_local_uv_dependency_cannot_escape_mirror(tmp_path, monkeypatch, source):
    cfg = make_cfg(tmp_path)
    tools = FakeToolchain(monkeypatch, cfg)
    (cfg.local_repo_root / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "synthetic"\nsource = { directory = ' + json.dumps(source) + ' }\n')
    assert env.prepare_environment(cfg)["status"] == "error"
    assert tools.installs == 0


def test_custom_command_tracks_source_but_not_secret_or_request_queue(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, mode="command")
    tools = FakeToolchain(monkeypatch, cfg)
    assert env.prepare_environment(cfg)["status"] == "ready"
    (cfg.local_repo_root / ".env").write_text("SYNTHETIC=must-not-be-read")
    request = cfg.local_repo_root / "docs/harness/exec-requests/a.json"
    request.parent.mkdir(parents=True)
    request.write_text("{}")
    assert env.prepare_environment(cfg)["status"] == "reused"
    (cfg.local_repo_root / "module.py").write_text("x = 1\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert tools.installs == 2


def test_extra_input_directory_invalidates_uv(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    cfg.environment["inputs"] = ["scripts"]
    tools = FakeToolchain(monkeypatch, cfg)
    assert env.prepare_environment(cfg)["status"] == "ready"
    scripts = cfg.local_repo_root / "scripts"
    scripts.mkdir()
    (scripts / "build.py").write_text("# synthetic\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert tools.installs == 2


def test_failure_invalidates_previous_success_and_does_not_cache(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    tools = FakeToolchain(monkeypatch, cfg)
    assert env.prepare_environment(cfg)["status"] == "ready"
    stamp = cfg.managed_root / "environment.json"
    (cfg.local_repo_root / "uv.lock").write_text("changed")
    tools.fail_install = True
    assert env.prepare_environment(cfg)["status"] == "error"
    assert not stamp.exists()
    tools.fail_install = False
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert tools.installs == 3


def test_lock_mutation_is_not_success(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    tools = FakeToolchain(monkeypatch, cfg)
    tools.mutate_lock = True
    result = env.prepare_environment(cfg)
    assert result["status"] == "error"
    assert "changed its inputs" in result["error"]
    assert not (cfg.managed_root / "environment.json").exists()


@pytest.mark.parametrize("relative", ["pyproject.toml", "scripts"])
def test_symlink_input_not_followed(tmp_path, monkeypatch, relative):
    cfg = make_cfg(tmp_path)
    FakeToolchain(monkeypatch, cfg)
    path = cfg.local_repo_root / relative
    if path.exists():
        path.unlink()
    destination = tmp_path / "outside"
    destination.write_text("SYNTHETIC-DO-NOT-READ")
    path.symlink_to(destination)
    cfg.environment["inputs"] = [relative]
    assert env.prepare_environment(cfg)["status"] == "error"


def test_missing_mirror_never_creates_env(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.local_repo_root = cfg.managed_root / "missing"
    assert env.prepare_environment(cfg)["status"] == "error"
    assert not (cfg.managed_root / "venv").exists()


def test_uv_missing_root_lock_does_not_discover_parent_project(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    (cfg.local_repo_root / "uv.lock").unlink()
    monkeypatch.setattr(env, "_run", lambda *args, **kwargs: pytest.fail("must not run a package manager"))
    result = env.prepare_environment(cfg)
    assert result["status"] == "error"
    assert "repository root" in result["error"]


def test_environment_replacement_invalidates_cache(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    tools = FakeToolchain(monkeypatch, cfg)
    assert env.prepare_environment(cfg)["status"] == "ready"
    (cfg.managed_root / "venv/pyvenv.cfg").write_text("replacement = true\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert tools.installs == 2


def test_distinct_profiles_have_distinct_venvs_and_stamps(tmp_path, monkeypatch):
    first = make_cfg(tmp_path, name="first")
    second = make_cfg(tmp_path, name="second")
    FakeToolchain(monkeypatch, first)
    assert env.prepare_environment(first)["status"] == "ready"
    FakeToolchain(monkeypatch, second)
    assert env.prepare_environment(second)["status"] == "ready"
    assert (first.managed_root / "venv").is_dir()
    assert (second.managed_root / "venv").is_dir()
    assert (first.managed_root / "environment.json").read_bytes() != (second.managed_root / "environment.json").read_bytes()


def test_python_change_fails_closed_without_deleting_existing_env(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    fake = FakeToolchain(monkeypatch, cfg)
    assert env.prepare_environment(cfg)["status"] == "ready"
    original = fake.run
    def changed(argv, cwd, deadline, stage, capture=False, cfg=None):
        if stage == "environment Python validation":
            return json.dumps([str(cfg.managed_root / "venv"), "/other-base", "/other-python"])
        return original(argv, cwd, deadline, stage, capture, cfg=cfg)
    monkeypatch.setattr(env, "_run", changed)
    assert env.prepare_environment(cfg)["status"] == "error"
    assert (cfg.managed_root / "venv").is_dir()
    assert not (cfg.managed_root / "environment.json").exists()


def test_existing_unowned_venv_is_not_adopted_or_changed(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    fake = FakeToolchain(monkeypatch, cfg)
    venv = cfg.managed_root / "venv"
    venv.mkdir()
    owner_file = venv / "owners-notes.txt"
    owner_file.write_text("keep")
    identity = owner_file.stat().st_ino
    assert env.prepare_environment(cfg)["status"] == "error"
    assert fake.installs == 0
    assert owner_file.read_text() == "keep"
    assert owner_file.stat().st_ino == identity
    assert not list(cfg.managed_root.glob("venv-retained-*"))


def test_reinstall_preserves_previous_owned_venv(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    FakeToolchain(monkeypatch, cfg)
    assert env.prepare_environment(cfg)["status"] == "ready"
    owner_file = cfg.managed_root / "venv" / "owners-notes.txt"
    owner_file.write_text("keep even if added by owner")
    identity = owner_file.stat().st_ino
    with (cfg.local_repo_root / "uv.lock").open("a") as stream:
        stream.write("\n# changed input\n")
    assert env.prepare_environment(cfg)["status"] == "ready"
    preserved = list(cfg.managed_root.glob("venv-retained-*/venv/owners-notes.txt"))
    assert len(preserved) == 1
    assert preserved[0].read_text() == "keep even if added by owner"
    assert preserved[0].stat().st_ino == identity


def test_successful_installer_cleans_up_background_children(tmp_path):
    marker = tmp_path / "orphan-would-write"
    child = "import time; from pathlib import Path; time.sleep(0.6); Path(" + repr(str(marker)) + ").write_text('orphan')"
    program = ("import subprocess,sys; subprocess.Popen([sys.executable,'-c'," + repr(child)
               + "],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)")
    assert env._run_process([sys.executable, "-c", program], tmp_path,
                            time.monotonic() + 5, "synthetic", capture=True) == ""
    time.sleep(0.7)
    assert not marker.exists()


def test_actual_stdlib_venv_and_quoted_hook_without_network(tmp_path):
    cfg = make_cfg(tmp_path, mode="command", name="project with spaces;literal")
    cfg.environment["command"] = "python -m pip --version"
    first = env.prepare_environment(cfg)
    assert first["status"] == "ready", first
    assert env.prepare_environment(cfg)["status"] == "reused"
    result = subprocess.run(["bash", "-lc", env.environment_hook(cfg) + "\npython -c " + shlex.quote("import sys; print(sys.prefix)")],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == str(cfg.managed_root / "venv")
    assert not (cfg.local_repo_root / ".venv").exists()


def test_timeout_kills_process_group(tmp_path):
    marker = tmp_path / "orphan-would-write"
    program = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
               + repr("import time; from pathlib import Path; time.sleep(0.6); Path(" + repr(str(marker)) + ").write_text('orphan')")
               + "]); time.sleep(10)")
    with pytest.raises(env._SetupError, match="timed out"):
        env._run_process([sys.executable, "-c", program], tmp_path, time.monotonic() + 0.2, "synthetic")
    time.sleep(0.7)
    assert not marker.exists()


def test_installer_output_is_never_returned(tmp_path):
    with pytest.raises(env._SetupError) as caught:
        env._run_process([sys.executable, "-c", "import sys; print('SYNTHETIC-SECRET'); sys.exit(7)"],
                 tmp_path, time.monotonic() + 5, "dependency installation")
    assert "exit 7" in str(caught.value)
    assert "SYNTHETIC-SECRET" not in str(caught.value)


def test_hardlinked_stamp_not_read_or_truncated(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    FakeToolchain(monkeypatch, cfg)
    outside = tmp_path / "outside-record"
    outside.write_text("SYNTHETIC-OUTSIDE-CONTENT")
    os.link(outside, cfg.managed_root / "environment.json")
    result = env.prepare_environment(cfg)
    assert result["status"] == "error"
    assert "SYNTHETIC" not in json.dumps(result)
    assert outside.read_text() == "SYNTHETIC-OUTSIDE-CONTENT"


def test_stamp_writer_ignores_preexisting_fixed_temp_hardlink(tmp_path):
    outside = tmp_path / "outside-record"
    outside.write_text("SYNTHETIC-OUTSIDE-CONTENT")
    target = tmp_path / "environment.json"
    os.link(outside, tmp_path / "environment.json.tmp")
    env._write_stamp(target, {"schema_version": 1})
    assert json.loads(target.read_text()) == {"schema_version": 1}
    assert outside.read_text() == "SYNTHETIC-OUTSIDE-CONTENT"


def test_network_enablement_cannot_reuse_or_reinstall_environment(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, mode="command")
    tools = FakeToolchain(monkeypatch, cfg)
    assert env.prepare_environment(cfg)["status"] == "ready"
    cfg.sandbox_install_network = True
    assert env.prepare_environment(cfg)["status"] == "error"
    assert tools.installs == 1


def test_configured_secret_root_is_never_fingerprinted(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, mode="command")
    FakeToolchain(monkeypatch, cfg)
    secret = cfg.local_repo_root / "nonstandard-private-store"
    secret.mkdir()
    sentinel = secret / "ordinary-name"
    sentinel.write_text("SYNTHETIC-NEVER-READ")
    cfg.sandbox_secret_roots = [str(secret)]
    original = Path.read_bytes
    def guarded(path):
        assert path != sentinel, "configured secret was read by fingerprinting"
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    assert env.prepare_environment(cfg)["status"] == "ready"
    assert env.prepare_environment(cfg)["status"] == "reused"


def test_bootstrap_requires_no_external_cli(tmp_path):
    cfg = make_cfg(tmp_path, mode="command")
    cfg.execution_sandbox = "codex"
    cfg.sandbox_binary = str(tmp_path / "not-installed")
    cfg.environment["command"] = "python -m pip --version"
    result = env.prepare_environment(cfg)
    assert result["status"] == "ready", result
    assert (cfg.managed_root / "venv").exists()
    assert (cfg.managed_root / "environment.json").exists()


@pytest.mark.parametrize("relative", ["mirror/uv.lock", "mirror/pyproject.toml", "environment.json", "venv/pyvenv.cfg"])
def test_explicit_secret_collision_rejected_before_read_or_invalidation(tmp_path, monkeypatch, relative):
    cfg = make_cfg(tmp_path)
    path = cfg.managed_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("SYNTHETIC-DO-NOT-OPEN")
    cfg.sandbox_secret_roots = [str(path)]
    original_text = Path.read_text
    original_bytes = Path.read_bytes
    def text(path_, *args, **kwargs):
        assert path_ != path, "configured secret metadata was read"
        return original_text(path_, *args, **kwargs)
    def read_bytes(path_, *args, **kwargs):
        assert path_ != path, "configured secret metadata was read"
        return original_bytes(path_, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    result = env.prepare_environment(cfg)
    assert result["status"] == "error"
    assert "overlaps" in result["error"]
    assert path.exists()


def test_bootstrap_helper_gets_offline_settings_and_keeps_venv_cache(tmp_path):
    cfg = make_cfg(tmp_path, mode="command")
    cfg.environment["command"] = "python installer.py"
    root = cfg.local_repo_root
    (root / "installer.py").write_text(
        "from pathlib import Path\nimport os, sys\n"
        "assert os.environ['UV_OFFLINE'] == '1'\n"
        "assert os.environ['PIP_NO_INDEX'] == '1'\n"
        "assert 'SSH_AUTH_SOCK' not in os.environ\n"
        "Path(sys.prefix, 'installed-marker').write_text('ok')\n"
    )
    first = env.prepare_environment(cfg)
    assert first["status"] == "ready", first
    assert (cfg.managed_root / "venv/installed-marker").is_file()
    second = env.prepare_environment(cfg)
    assert second["status"] == "reused", second
    assert second["fingerprint"] == first["fingerprint"]
