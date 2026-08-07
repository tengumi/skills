"""Tests for shared secure SSH/SCP option construction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.config import Config
from lib.remote_fs import _scp_base, _ssh_base, _ssh_options


def make_cfg(tmp_path: Path, **overrides) -> Config:
    values = {
        "ssh_host": "executor@example.invalid",
        "ssh_port": 22,
        "ssh_key": str(tmp_path / "key"),
        "remote_repo_root": "/remote/service",
        "local_repo_root": tmp_path / "mirror",
    }
    values.update(overrides)
    return Config(**values)


def test_host_key_checking_is_strict_by_default(tmp_path):
    cfg = make_cfg(tmp_path)
    options = _ssh_options(cfg)
    assert "StrictHostKeyChecking=yes" in options
    assert "StrictHostKeyChecking=no" not in options
    assert "UserKnownHostsFile=/dev/null" not in options


def test_custom_known_hosts_is_shared_by_ssh_and_scp(tmp_path):
    known_hosts = tmp_path / "known hosts"
    cfg = make_cfg(tmp_path, user_known_hosts_file=str(known_hosts))
    expected = f"UserKnownHostsFile={known_hosts}"
    assert expected in _ssh_base(cfg)
    assert expected in _scp_base(cfg)


def test_explicit_high_risk_opt_out(tmp_path):
    cfg = make_cfg(tmp_path, strict_host_key_checking=False)
    options = _ssh_options(cfg)
    assert "StrictHostKeyChecking=no" in options
    assert "StrictHostKeyChecking=yes" not in options
