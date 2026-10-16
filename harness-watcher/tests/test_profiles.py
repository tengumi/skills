"""Project profile storage is private, isolated, and never follows redirects."""

from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.config import Config, ConfigError
from lib.profiles import create_profile, list_profiles, load_profile, profile_lock, validate_managed_paths


@pytest.fixture
def inputs(tmp_path):
    key = tmp_path / "key with spaces"
    key.write_text("synthetic key placeholder; never read")
    return {
        "ssh_host": "worker@host.example",
        "ssh_key": str(key),
        "remote_repo_root": "/work/repository with spaces",
        "profiles_dir": tmp_path / "watcher projects" / "profiles",
    }


def test_profile_roundtrip_and_safe_defaults(inputs):
    recipe = {"mode": "uv", "python": "3.12", "inputs": ["pyproject.toml", "uv.lock"]}
    cfg = create_profile("contractors-1", environment=recipe, **inputs)
    saved = load_profile("contractors-1", profiles_dir=inputs["profiles_dir"])
    assert saved == cfg
    assert cfg.environment == recipe
    assert cfg.local_repo_root == cfg.managed_root / "repo"
    assert cfg.local_repo_root.is_dir()
    assert not (cfg.managed_root / "venv").exists()
    assert cfg.strict_host_key_checking is True
    assert cfg.pre_exec_hook == ""
    assert cfg.sync_before_exec is True
    assert cfg.sync_after_exec is False
    assert ".env*" in cfg.rsync_exclude and "certs" in cfg.rsync_exclude
    assert list_profiles(inputs["profiles_dir"]) == ["contractors-1"]
    recipe["python"] = "changed"
    assert cfg.environment["python"] == "3.12"
    assert cfg.execution_sandbox == "commands"


def test_legacy_profile_settings_roundtrip_without_cli_dependency(inputs, tmp_path):
    cfg = create_profile("protected", sandbox={"mode": "codex", "binary": "/usr/local/bin/codex",
                         "secret_roots": [str(tmp_path / "private-store")], "install_network": False}, **inputs)
    loaded = load_profile("protected", profiles_dir=inputs["profiles_dir"])
    assert loaded == cfg
    assert loaded.execution_sandbox == "commands"
    assert loaded.sandbox_binary == "/usr/local/bin/codex"
    assert loaded.sandbox_secret_roots == [str(tmp_path / "private-store")]
    assert loaded.sandbox_install_network is False


def test_legacy_profile_without_sandbox_still_loads(inputs):
    cfg = create_profile("legacy", **inputs)
    data = json.loads(cfg.config_path.read_text())
    del data["sandbox"]
    cfg.config_path.write_text(json.dumps(data))
    assert load_profile("legacy", profiles_dir=inputs["profiles_dir"]).execution_sandbox == "commands"


@pytest.mark.parametrize("sandbox", [{"mode": "unsupported"}, {"mode": "commands", "install_network": True}])
def test_new_profiles_reject_unsupported_modes_or_network_installation(inputs, sandbox):
    with pytest.raises(ConfigError):
        create_profile("unsafe", sandbox=sandbox, **inputs)
    assert not inputs["profiles_dir"].exists()


def test_legacy_unsafe_profile_is_readable_for_diagnostics(inputs):
    cfg = create_profile("legacy", **inputs)
    data = json.loads(cfg.config_path.read_text())
    data["sandbox"] = {"mode": "none", "install_network": True}
    cfg.config_path.write_text(json.dumps(data))
    loaded = load_profile("legacy", profiles_dir=inputs["profiles_dir"])
    assert loaded.execution_sandbox == "commands"
    assert loaded.sandbox_install_network is True


def test_private_directories_and_files(inputs):
    cfg = create_profile("example", **inputs)
    assert stat.S_IMODE(cfg.config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(cfg.managed_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(inputs["profiles_dir"].stat().st_mode) == 0o700
    assert stat.S_IMODE((cfg.managed_root / ".harness-watcher-project.json").stat().st_mode) == 0o600


def test_same_remote_basename_has_separate_storage_and_state(inputs):
    first = create_profile("one", **inputs)
    second = create_profile("two", **{**inputs, "remote_repo_root": "/other/repository with spaces"})
    for field in ("managed_root", "local_repo_root", "state_path", "audit_log_path"):
        assert getattr(first, field) != getattr(second, field)
    first.state_path.write_text('{"same-request-id": "done"}')
    assert not second.state_path.exists()
    assert list_profiles(inputs["profiles_dir"]) == ["one", "two"]


def test_create_does_not_overwrite(inputs):
    cfg = create_profile("one", **inputs)
    original = cfg.config_path.read_bytes()
    with pytest.raises(ConfigError, match="already exists"):
        create_profile("one", **inputs)
    assert cfg.config_path.read_bytes() == original


def test_same_remote_cannot_create_two_queue_consumers(inputs):
    cfg = create_profile("one", **inputs)
    with pytest.raises(ConfigError, match="already has profile one"):
        create_profile("two", **inputs)
    assert list_profiles(inputs["profiles_dir"]) == ["one"]
    assert len(list(cfg.managed_root.parent.iterdir())) == 1


@pytest.mark.parametrize("name", ["", "../escape", "a/b", "-option", "white space", "кириллица", "a" * 65, "a\n"])
def test_invalid_name_never_creates_storage(inputs, name):
    with pytest.raises(ConfigError, match="profile name"):
        create_profile(name, **inputs)
    assert not inputs["profiles_dir"].exists()


@pytest.mark.parametrize("host", ["-oProxyCommand=x", "host;whoami", "u@host\n", "host name", "u@a@b", "$(command)"])
def test_connection_rejects_options_and_controls(inputs, host):
    with pytest.raises(ConfigError, match="ssh_host"):
        create_profile("one", **{**inputs, "ssh_host": host})


@pytest.mark.parametrize("port", [True, 0, 65536, "22", 22.5])
def test_invalid_port(inputs, port):
    with pytest.raises(ConfigError, match="ssh_port"):
        create_profile("one", ssh_port=port, **inputs)


@pytest.mark.parametrize("root", ["relative/repo", "/", "//", "/foo/../bar", "/foo\nbar"])
def test_invalid_remote_root(inputs, root):
    with pytest.raises(ConfigError, match="remote_repo_root"):
        create_profile("one", **{**inputs, "remote_repo_root": root})


def test_key_metadata_only_and_missing_key(inputs, monkeypatch):
    key = Path(inputs["ssh_key"])
    original = Path.open
    def guarded_open(self, *args, **kwargs):
        assert self != key, "key contents must never be opened"
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded_open)
    create_profile("one", **inputs)
    key.unlink()
    with pytest.raises(ConfigError, match="ssh_key"):
        load_profile("one", inputs["profiles_dir"])


def test_profile_and_storage_symlinks_rejected(inputs, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    inputs["profiles_dir"].parent.mkdir()
    inputs["profiles_dir"].symlink_to(target, target_is_directory=True)
    with pytest.raises(ConfigError, match="symlink"):
        create_profile("one", **inputs)
    assert not list(target.iterdir())


@pytest.mark.parametrize("filename", ["state.json", "audit.log", "environment.json", "environment.json.tmp", ".watcher.lock", ".harness-watcher-project.json"])
def test_metadata_redirect_rejected(inputs, tmp_path, filename):
    cfg = create_profile("one", **inputs)
    target = tmp_path / "do-not-read"
    target.write_text("synthetic private data")
    path = cfg.managed_root / filename
    path.unlink(missing_ok=True)
    path.symlink_to(target)
    with pytest.raises(ConfigError, match="symlink"):
        validate_managed_paths(cfg)


@pytest.mark.parametrize("directory", ["repo", "venv", ".harness-watcher-tmp"])
def test_directory_redirect_rejected(inputs, tmp_path, directory):
    cfg = create_profile("one", **inputs)
    path = cfg.managed_root / directory
    if path.exists():
        path.rmdir()
    path.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ConfigError, match="symlink"):
        validate_managed_paths(cfg)


def test_profile_file_redirect_and_arbitrary_local_path_rejected(inputs, tmp_path):
    cfg = create_profile("one", **inputs)
    with pytest.raises(ConfigError, match="local_repo_root"):
        validate_managed_paths(replace(cfg, local_repo_root=tmp_path))
    moved = cfg.config_path.with_suffix(".backup")
    cfg.config_path.rename(moved)
    cfg.config_path.symlink_to(moved)
    with pytest.raises(ConfigError, match="symlink"):
        load_profile("one", inputs["profiles_dir"])


def test_marker_is_required_and_remote_edit_is_not_accepted(inputs):
    cfg = create_profile("one", **inputs)
    data = json.loads(cfg.config_path.read_text())
    data["remote"]["remote_repo_root"] = "/different/repo"
    cfg.config_path.write_text(json.dumps(data))
    with pytest.raises(ConfigError, match="marker"):
        load_profile("one", inputs["profiles_dir"])
    (cfg.managed_root / ".harness-watcher-project.json").unlink()
    with pytest.raises(ConfigError):
        load_profile("one", inputs["profiles_dir"])


def test_profile_path_fields_cannot_be_injected(inputs, tmp_path):
    cfg = create_profile("one", **inputs)
    data = json.loads(cfg.config_path.read_text())
    data["local_repo_root"] = str(tmp_path)
    cfg.config_path.write_text(json.dumps(data))
    with pytest.raises(ConfigError, match="local paths"):
        load_profile("one", inputs["profiles_dir"])


def test_metadata_hardlink_is_rejected_before_read(inputs, tmp_path):
    cfg = create_profile("one", **inputs)
    target = tmp_path / "synthetic-sensitive-data"
    target.write_text("do not parse or expose this value")
    os.link(target, cfg.state_path)
    with pytest.raises(ConfigError, match="regular file"):
        validate_managed_paths(cfg)


def test_duplicate_profile_json_fields_rejected(inputs):
    cfg = create_profile("one", **inputs)
    cfg.config_path.write_text('{"name":"one","name":"two"}')
    with pytest.raises(ConfigError, match="metadata"):
        load_profile("one", inputs["profiles_dir"])


@pytest.mark.parametrize("change", [{"remote": None}, {"environment": []}, {"storage_id": "../escape"}, {"schema": True}])
def test_invalid_profile_shapes_fail_with_config_error(inputs, change):
    cfg = create_profile("one", **inputs)
    data = json.loads(cfg.config_path.read_text())
    data.update(change)
    cfg.config_path.write_text(json.dumps(data))
    with pytest.raises(ConfigError):
        load_profile("one", inputs["profiles_dir"])


def test_lock_is_per_profile_and_released_after_error(inputs):
    first = create_profile("one", **inputs)
    second = create_profile("two", **{**inputs, "remote_repo_root": "/other/target"})
    with pytest.raises(RuntimeError):
        with profile_lock(first):
            with pytest.raises(ConfigError, match="already running"):
                with profile_lock(first):
                    pytest.fail("second owner acquired same profile")
            with profile_lock(second):
                pass
            raise RuntimeError("synthetic failure")
    with profile_lock(first):
        pass


def test_legacy_config_is_unchanged(tmp_path):
    cfg = Config(ssh_host="h", ssh_port=22, ssh_key="not-used", remote_repo_root="/r", local_repo_root=tmp_path)
    validate_managed_paths(cfg)
    with profile_lock(cfg):
        pass
    assert list(tmp_path.iterdir()) == []


def test_missing_profiles_directory_is_empty(tmp_path):
    assert list_profiles(tmp_path / "not-created") == []
