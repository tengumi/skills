"""Tests for shared secure SSH/SCP option construction."""

from __future__ import annotations

import sys
import shlex
import os
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.config import Config
from lib.remote_fs import _scp_base, _ssh_base, _ssh_options, _quote
from lib import remote_fs


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


def test_remote_path_shell_quoting_roundtrip():
    for path in ("/srv/owner's repo", "/srv/space and ; dollar$", "/srv/simple"):
        assert shlex.split("cd " + _quote(path)) == ["cd", path]


@pytest.fixture
def local_protocol_ssh(monkeypatch):
    """Exercise the actual remote protocol script locally, without network."""
    actual_popen = subprocess.Popen

    def popen(argv, **kwargs):
        if argv[0] == "synthetic-ssh":
            argv = ["sh", "-c", argv[-1]]
        return actual_popen(argv, **kwargs)

    monkeypatch.setattr(remote_fs, "_ssh_base", lambda cfg: ["synthetic-ssh"])
    monkeypatch.setattr(remote_fs.subprocess, "Popen", popen)


@pytest.mark.parametrize("operation", ["upload", "move"])
@pytest.mark.parametrize("existing", ["file", "symlink", "directory"])
def test_protocol_publication_never_overwrites_existing_destination(tmp_path, local_protocol_ssh, operation, existing):
    source = tmp_path / "source.json"
    source.write_text('{"value":"SYNTHETIC_NEW"}')
    destination = tmp_path / "owner's report.json"
    original = tmp_path / "owner.json"
    original.write_text("SYNTHETIC_OWNER")
    if existing == "file":
        destination.write_text("SYNTHETIC_OWNER")
    elif existing == "symlink":
        destination.symlink_to(original)
    else:
        destination.mkdir()
        (destination / "keep").write_text("SYNTHETIC_OWNER")
    function = remote_fs.upload_file if operation == "upload" else remote_fs.remote_move
    result = function(make_cfg(tmp_path), str(source), str(destination))
    assert not result.ok
    assert "SYNTHETIC" not in result.stdout + result.stderr
    assert source.read_text() == '{"value":"SYNTHETIC_NEW"}'
    assert original.read_text() == "SYNTHETIC_OWNER"
    if existing == "directory":
        assert (destination / "keep").read_text() == "SYNTHETIC_OWNER"
    else:
        assert destination.read_text() == "SYNTHETIC_OWNER"
    assert not list(tmp_path.glob(".harness-report-*"))


@pytest.mark.parametrize("operation", ["upload", "move"])
def test_protocol_publication_refuses_symlinked_destination_parent(tmp_path, local_protocol_ssh, operation):
    source = tmp_path / "source.json"
    source.write_text("synthetic report")
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    function = remote_fs.upload_file if operation == "upload" else remote_fs.remote_move
    result = function(make_cfg(tmp_path), str(source), str(alias / "new.json"))
    assert not result.ok
    assert source.exists()
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("operation", ["upload", "move"])
def test_protocol_publication_creates_only_new_destination(tmp_path, local_protocol_ssh, operation):
    source = tmp_path / "source.json"
    source.write_text("synthetic report")
    destination = tmp_path / "new.json"
    function = remote_fs.upload_file if operation == "upload" else remote_fs.remote_move
    result = function(make_cfg(tmp_path), str(source), str(destination))
    assert result.ok, result.stderr
    assert destination.read_text() == "synthetic report"
    assert source.exists() is (operation == "upload")
    if operation == "upload":
        assert destination.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".harness-report-*"))


@pytest.mark.parametrize("operation", ["upload", "move"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_protocol_publication_rejects_linked_source(tmp_path, local_protocol_ssh, operation, kind):
    original = tmp_path / "owner.json"
    original.write_text("SYNTHETIC_OWNER")
    source = tmp_path / "source.json"
    if kind == "symlink":
        source.symlink_to(original)
    else:
        os.link(original, source)
    destination = tmp_path / "new.json"
    function = remote_fs.upload_file if operation == "upload" else remote_fs.remote_move
    result = function(make_cfg(tmp_path), str(source), str(destination))
    assert not result.ok
    assert not destination.exists()
    assert source.exists()
    assert original.read_text() == "SYNTHETIC_OWNER"
    assert "SYNTHETIC" not in result.stdout + result.stderr
