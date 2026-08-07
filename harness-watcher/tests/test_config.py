"""Тесты config."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.config import ConfigError, load_config, _parse_toml_simple


def write_cfg(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.toml"
    p.write_text(content)
    return p


def test_missing_config_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nonexistent.toml")


def test_valid_config_loads(tmp_path):
    fake_key = tmp_path / "k"
    fake_key.write_text("k")
    cfg_file = write_cfg(tmp_path, f"""
[remote]
ssh_host = "u@h"
ssh_port = 22
ssh_key = "{fake_key}"
remote_repo_root = "/r"

[local]
local_repo_root = "/l"
""")
    cfg = load_config(cfg_file)
    assert cfg.ssh_host == "u@h"
    assert cfg.poll_interval_seconds == 3  # default
    assert cfg.sync_before_exec is True  # default
    assert cfg.strict_host_key_checking is True
    assert cfg.user_known_hosts_file is None


def test_missing_required_field(tmp_path):
    cfg_file = write_cfg(tmp_path, """
[remote]
ssh_port = 22
""")
    with pytest.raises(ConfigError, match="ssh_host"):
        load_config(cfg_file)


def test_nonexistent_key(tmp_path):
    cfg_file = write_cfg(tmp_path, """
[remote]
ssh_host = "u@h"
ssh_key = "/nonexistent"
remote_repo_root = "/r"

[local]
local_repo_root = "/l"
""")
    with pytest.raises(ConfigError, match="ssh_key not found"):
        load_config(cfg_file)


def test_overrides_defaults(tmp_path):
    fake_key = tmp_path / "k"
    fake_key.write_text("k")
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("example.invalid ssh-ed25519 AAAA-test\n")
    cfg_file = write_cfg(tmp_path, f"""
[remote]
ssh_host = "u@h"
ssh_key = "{fake_key}"
remote_repo_root = "/r"
strict_host_key_checking = false
user_known_hosts_file = "{known_hosts}"

[local]
local_repo_root = "/l"

[poller]
poll_interval_seconds = 7
default_timeout_seconds = 1200

[executor]
sync_before_exec = false
sync_after_exec = true

[rsync]
exclude = ["custom", "another"]
""")
    cfg = load_config(cfg_file)
    assert cfg.poll_interval_seconds == 7
    assert cfg.default_timeout_seconds == 1200
    assert cfg.sync_before_exec is False
    assert cfg.sync_after_exec is True
    assert cfg.rsync_exclude == ["custom", "another"]
    assert cfg.strict_host_key_checking is False
    assert cfg.user_known_hosts_file == str(known_hosts)


def test_nonexistent_known_hosts_file(tmp_path):
    fake_key = tmp_path / "k"
    fake_key.write_text("k")
    cfg_file = write_cfg(tmp_path, f"""
[remote]
ssh_host = "u@h"
ssh_key = "{fake_key}"
remote_repo_root = "/r"
user_known_hosts_file = "{tmp_path / 'missing-known-hosts'}"

[local]
local_repo_root = "/l"
""")
    with pytest.raises(ConfigError, match="user_known_hosts_file not found"):
        load_config(cfg_file)


def test_simple_parser_handles_multiline_list():
    text = """
    [a]
    items = [
        "x",
        "y",
        "z",
    ]
    """
    r = _parse_toml_simple(text)
    assert r["a"]["items"] == ["x", "y", "z"]
