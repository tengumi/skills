"""Synthetic-only regressions for mandatory source transport boundaries."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.config import Config
from lib import poller, remote_fs
from lib.secret_paths import MANDATORY_SECRET_EXCLUDES, effective_excludes, is_secret_path, matches_excludes, with_secret_excludes


SECRET_NAMES = [
    ".env", ".env.local", ".env.example", "nested/.env.production", "service.env",
    ".netrc", ".npmrc", ".pypirc", "secrets/token.txt", ".aws/credentials",
    "credentials.json", "id_rsa", "nested/id_ed25519", "certs/client.pem",
    "private.key", "client.p12", "client.pfx", ".config/gcloud/config.json", ".git/config",
    "nested/.config/gcloud/config.json", ".kube/config", ".docker/config.json",
    ".codex/auth.json", ".claude/.credentials.json",
]


def source_tree(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "service.py").write_text("VALUE = 1\n")
    (source / ".codex" / "skills").mkdir(parents=True)
    (source / ".codex" / "skills" / "helper.md").write_text("synthetic skill")
    for relative in SECRET_NAMES:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SYNTHETIC_MUST_NOT_TRANSFER\n")
    return source


def config(tmp_path):
    return Config(ssh_host="synthetic.invalid", ssh_port=22, ssh_key="synthetic-key",
                  remote_repo_root=str(tmp_path / "remote"), local_repo_root=tmp_path / "mirror")


@pytest.fixture
def local_ssh(monkeypatch):
    """Run the generated remote shell commands locally, without SSH/network."""
    real_popen = subprocess.Popen

    def popen(argv, **kwargs):
        if argv[0] == "synthetic-ssh":
            argv = ["sh", "-c", argv[-1]]
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(remote_fs, "_ssh_base", lambda cfg: ["synthetic-ssh"])
    monkeypatch.setattr(remote_fs.subprocess, "Popen", popen)


def test_tar_always_excludes_secret_paths_with_empty_legacy_settings(tmp_path, local_ssh):
    source = source_tree(tmp_path)
    target = tmp_path / "target"
    cfg = config(tmp_path)
    result = remote_fs.tar_sync_from_remote(cfg, str(source), str(target), [])
    assert result.ok, result.stderr
    assert (target / "service.py").read_text() == "VALUE = 1\n"
    assert (target / ".codex" / "skills" / "helper.md").read_text() == "synthetic skill"
    assert all(not (target / name).exists() for name in SECRET_NAMES)
    assert "SYNTHETIC" not in result.stdout + result.stderr


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_included_aliases_and_special_files_fail_before_transfer(tmp_path, local_ssh, kind):
    source = source_tree(tmp_path)
    alias = source / "innocent.txt"
    if kind == "symlink":
        alias.symlink_to(source / ".env")
    elif kind == "hardlink":
        os.link(source / ".env", alias)
    else:
        os.mkfifo(alias)
    target = tmp_path / "target"
    cfg = config(tmp_path)
    result = remote_fs.tar_sync_from_remote(cfg, str(source), str(target), [])
    assert not result.ok
    assert "safety check failed" in result.stderr
    assert "innocent" not in result.stderr and "SYNTHETIC" not in result.stderr
    assert not target.exists()
    assert not (target / "service.py").exists()


def test_excluded_symlink_is_not_followed(tmp_path, local_ssh):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "value").write_text("SYNTHETIC_OUTSIDE")
    (source / "secrets").symlink_to(outside, target_is_directory=True)
    (source / "ok.txt").write_text("ok")
    target = tmp_path / "target"
    result = remote_fs.tar_sync_from_remote(config(tmp_path), str(source), str(target), [])
    assert result.ok
    assert not (target / "secrets").exists()
    assert (target / "ok.txt").read_text() == "ok"


def test_rsync_entrypoints_include_mandatory_excludes(tmp_path, monkeypatch):
    source = source_tree(tmp_path)
    calls = []

    def run(argv, timeout):
        calls.append(argv)
        return remote_fs.CmdResult(True, "", "", 0, 0)

    monkeypatch.setattr(remote_fs, "_run", run)
    cfg = config(tmp_path)
    result = remote_fs.rsync_to_local(cfg, str(source), str(tmp_path / "target"), [])
    assert result.ok
    argv = next(argv for argv in calls if argv[0] == "rsync")
    for pattern in MANDATORY_SECRET_EXCLUDES:
        assert any(argv[index:index + 2] == ["--exclude", pattern] for index in range(len(argv)))
    assert "--delete-excluded" not in argv
    assert "--delete" not in argv
    assert "--ignore-existing" in argv


@pytest.mark.parametrize("missing", ["local", "remote"])
def test_rsync_fallback_is_filtered_tar(tmp_path, monkeypatch, missing):
    source = source_tree(tmp_path)
    observed = []

    def run(argv, timeout):
        if argv[0] == "which" and missing == "local":
            return remote_fs.CmdResult(False, "", "not found", 1, 0)
        if argv[0] == "rsync":
            return remote_fs.CmdResult(False, "", "rsync: command not found", 127, 0)
        assert "scp" not in argv
        return remote_fs.CmdResult(True, "", "", 0, 0)

    def tar(cfg, first, second, exclude):
        observed.extend(exclude)
        return remote_fs.CmdResult(True, "", "", 0, 0)

    monkeypatch.setattr(remote_fs, "_run", run)
    monkeypatch.setattr(remote_fs, "_tar_into_fresh", tar)
    cfg = config(tmp_path)
    assert remote_fs.rsync_to_local(cfg, str(source), str(tmp_path / "target"), ["custom"]).ok
    assert set(MANDATORY_SECRET_EXCLUDES).issubset(observed)
    assert "custom" in observed


def test_tree_and_lock_fingerprints_never_open_excluded_files(tmp_path, monkeypatch):
    source = source_tree(tmp_path)
    (source / "secrets" / "pyproject.toml").write_text("SYNTHETIC_SECRET_MANIFEST")
    (source / "pyproject.toml").write_text('[project]\nname = "synthetic"\n')
    real_open = os.open

    def guarded_open(path, *args, **kwargs):
        relative = Path(path).relative_to(source)
        assert not is_secret_path(relative), "excluded content must not be opened"
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(poller.os, "open", guarded_open)
    before = poller._fingerprint_tree(source, [])
    lock = poller._dependency_fingerprint(source, [])
    (source / ".env").write_text("SYNTHETIC_CHANGED")
    assert poller._fingerprint_tree(source, []) == before
    assert poller._dependency_fingerprint(source, []) == lock
    assert lock[1] == 1


@pytest.mark.parametrize("name", ["innocent.txt", "pyproject.toml"])
def test_fingerprint_rejects_hardlink_alias_without_opening(tmp_path, monkeypatch, name):
    source = source_tree(tmp_path)
    os.link(source / ".env", source / name)

    def forbidden(*args, **kwargs):
        raise AssertionError("hardlinked secret must never be opened")

    # Sort the alias first, and remove the only ordinary file, so any open is wrong.
    (source / "service.py").unlink()
    (source / ".codex" / "skills" / "helper.md").unlink()
    monkeypatch.setattr(poller.os, "open", forbidden)
    with pytest.raises(ValueError, match="linked"):
        poller._fingerprint_tree(source, [])
    if name == "pyproject.toml":
        with pytest.raises(ValueError, match="unlinked regular"):
            poller._dependency_fingerprint(source, [])


def test_symlink_fingerprint_uses_metadata_not_target_content(tmp_path):
    source = source_tree(tmp_path)
    (source / "alias").symlink_to(source / ".env")
    before = poller._fingerprint_tree(source, [])
    (source / ".env").write_text("SYNTHETIC_CHANGED")
    assert poller._fingerprint_tree(source, []) == before


def test_source_snapshot_never_runs_git_for_retained_legacy_metadata(tmp_path, monkeypatch):
    source = source_tree(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("git can inspect tracked secret files and run config hooks")

    monkeypatch.setattr(poller, "_git_revision", forbidden)
    monkeypatch.setattr(poller, "_git_dirty", forbidden)
    snapshot = poller._capture_source_snapshot(source, [])
    assert snapshot["status"] == "captured"
    assert snapshot["git_head"] is snapshot["git_tree"] is snapshot["git_dirty"] is None
    assert snapshot["git_metadata_reason"] == "excluded_by_secret_boundary"


def test_execution_fingerprint_tracks_normalized_runtime_settings(tmp_path, monkeypatch):
    # Do not inspect the test runner's real inherited environment.
    monkeypatch.setattr(poller.os, "environ", {"HOME": "/synthetic/home", "PATH": "/usr/bin"})
    cfg = config(tmp_path)
    original = poller._execution_profile_fingerprint(cfg)
    for field, value in [
        ("sandbox_binary", "/synthetic/codex"),
        ("sandbox_read_roots", ["/synthetic/readonly"]),
        ("sandbox_secret_roots", ["/synthetic/private"]),
        ("sandbox_install_network", True),
    ]:
        prior = getattr(cfg, field)
        setattr(cfg, field, value)
        assert poller._execution_profile_fingerprint(cfg) != original, field
        setattr(cfg, field, prior)
    assert poller._execution_profile_fingerprint(cfg) == original
    for legacy_mode in ("none", "codex", "commands"):
        cfg.execution_sandbox = legacy_mode
        assert poller._execution_profile_fingerprint(cfg) == original


def test_custom_excludes_cannot_replace_or_duplicate_boundary():
    effective = with_secret_excludes(["custom", ".env*"])
    assert effective.count(".env*") == 1
    assert "custom" in effective
    assert set(MANDATORY_SECRET_EXCLUDES).issubset(effective)


@pytest.mark.parametrize("direction", ["pull", "push"])
def test_sync_errors_do_not_echo_source_output(tmp_path, monkeypatch, direction):
    source = source_tree(tmp_path)

    def run(argv, timeout):
        if argv[0] == "which":
            return remote_fs.CmdResult(True, "", "", 0, 0)
        return remote_fs.CmdResult(False, "SYNTHETIC_OUTPUT", "SYNTHETIC_ERROR", 1, 0)

    monkeypatch.setattr(remote_fs, "_run", run)
    function = remote_fs.rsync_to_local if direction == "pull" else remote_fs.rsync_to_remote
    result = function(config(tmp_path), str(source), str(tmp_path / "target"), [])
    assert not result.ok
    assert "SYNTHETIC" not in result.stdout + result.stderr


@pytest.mark.parametrize("path", [".config/gcloud/config.json", "nested/.config/gcloud/config.json",
                                  ".config/gh/hosts.yml", "secrets/plain-name.txt"])
def test_secret_directory_prefix_protects_explicit_descendant(path):
    assert is_secret_path(Path(path))
    assert matches_excludes(Path("nested/private/settings.json"), ["nested/private"])
    assert not matches_excludes(Path("nested/private-other/settings.json"), ["nested/private"])


def test_custom_secret_root_is_excluded_from_tar(tmp_path, local_ssh):
    source = source_tree(tmp_path)
    (source / "private-settings.json").write_text("SYNTHETIC_PRIVATE_SETTINGS")
    target = tmp_path / "target"
    cfg = config(tmp_path)
    cfg.local_repo_root = target
    cfg.sandbox_secret_roots = [str(cfg.local_repo_root / "private-settings.json")]
    result = remote_fs.tar_sync_from_remote(cfg, str(source), str(target), [])
    assert result.ok, result.stderr
    assert (target / "service.py").exists()
    assert not (target / "private-settings.json").exists()


def test_custom_secret_root_is_excluded_from_rsync(tmp_path, monkeypatch):
    source = source_tree(tmp_path)
    target = tmp_path / "target"
    cfg = config(tmp_path)
    cfg.local_repo_root = target
    cfg.sandbox_secret_roots = [str(cfg.local_repo_root / "private-settings.json")]
    calls = []

    def run(argv, timeout):
        calls.append(argv)
        return remote_fs.CmdResult(True, "", "", 0, 0)

    monkeypatch.setattr(remote_fs, "_run", run)
    assert remote_fs.rsync_to_local(cfg, str(source), str(target), []).ok
    argv = next(argv for argv in calls if argv[0] == "rsync")
    assert "private-settings.json" in argv


@pytest.mark.parametrize("protected", [".env", ".git/config", "private-settings.json", "nested/.config/gcloud/token.json",
                                      " private-settings.json", "private-settings.json "])
def test_tar_pull_never_deletes_preexisting_protected_files(tmp_path, monkeypatch, protected):
    target = tmp_path / "target"
    path = target / protected
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("SYNTHETIC_PRESERVE")
    (target / "keep.txt").write_text("preserve whole mirror")
    cfg = config(tmp_path)
    cfg.local_repo_root = target
    cfg.sandbox_secret_roots = [str(target / "private-settings.json"), str(path)]

    def forbidden(*args, **kwargs):
        raise AssertionError("protected destination must fail before external work or content opens")

    monkeypatch.setattr(remote_fs, "_run", forbidden)
    monkeypatch.setattr(remote_fs.subprocess, "Popen", forbidden)
    monkeypatch.setattr(remote_fs.os, "open", forbidden)
    result = remote_fs.tar_sync_from_remote(cfg, "/synthetic/source", str(target), [])
    assert not result.ok
    assert "refusing to replace mirror" in result.stderr
    assert "SYNTHETIC_PRESERVE" not in result.stderr
    assert path.read_text() == "SYNTHETIC_PRESERVE"
    assert (target / "keep.txt").exists()


@pytest.mark.parametrize("ancestor", [False, True])
def test_explicit_secret_root_containing_source_fails_before_reads_or_sync(tmp_path, monkeypatch, ancestor):
    source = source_tree(tmp_path)
    cfg = config(tmp_path)
    cfg.local_repo_root = source
    cfg.sandbox_secret_roots = [str(source.parent if ancestor else source)]

    def forbidden(*args, **kwargs):
        raise AssertionError("source inside secret boundary must not be opened")

    monkeypatch.setattr(remote_fs, "_run", forbidden)
    monkeypatch.setattr(remote_fs.subprocess, "Popen", forbidden)
    monkeypatch.setattr(poller.os, "open", forbidden)
    with pytest.raises(ValueError, match="contains source root"):
        effective_excludes(cfg, [])
    for function in (remote_fs.tar_sync_to_remote, remote_fs.rsync_to_remote):
        assert not function(cfg, str(source), "/synthetic/target", []).ok
    for function in (remote_fs.tar_sync_from_remote, remote_fs.rsync_to_local):
        assert not function(cfg, "/synthetic/source", str(source), []).ok
    assert poller._capture_source_snapshot(source, [], cfg=cfg)["status"] == "error"
    with pytest.raises(ValueError, match="contains source root"):
        poller._dependency_fingerprint(source, [], cfg=cfg)


def test_custom_secret_roots_are_never_opened_by_source_or_lock_fingerprints(tmp_path, monkeypatch):
    source = source_tree(tmp_path)
    private = source / "private-settings.json"
    private.write_text("SYNTHETIC_PRIVATE")
    hidden_manifest = source / "internal" / "pyproject.toml"
    hidden_manifest.parent.mkdir()
    hidden_manifest.write_text("SYNTHETIC_PRIVATE_MANIFEST")
    (source / "pyproject.toml").write_text('[project]\nname = "synthetic"\n')
    cfg = config(tmp_path)
    cfg.local_repo_root = source
    cfg.sandbox_secret_roots = [str(private), str(hidden_manifest.parent)]
    actual_open = os.open
    protected = effective_excludes(cfg, [])

    def guarded_open(path, *args, **kwargs):
        assert not matches_excludes(Path(path).relative_to(source), protected)
        return actual_open(path, *args, **kwargs)

    monkeypatch.setattr(poller.os, "open", guarded_open)
    before = poller._fingerprint_tree(source, [], cfg=cfg)
    locks = poller._dependency_fingerprint(source, [], cfg=cfg)
    private.write_text("SYNTHETIC_CHANGED")
    hidden_manifest.write_text("SYNTHETIC_CHANGED_MANIFEST")
    assert poller._fingerprint_tree(source, [], cfg=cfg) == before
    assert poller._dependency_fingerprint(source, [], cfg=cfg) == locks
    assert locks[1] == 1


@pytest.mark.parametrize("name", [" private-settings.json", "private-settings.json "])
def test_exact_secret_names_keep_significant_spaces(tmp_path, local_ssh, name):
    source = tmp_path / "source"
    source.mkdir()
    (source / "service.py").write_text("ordinary")
    secret = source / name
    secret.write_text("SYNTHETIC_PRIVATE")
    cfg = config(tmp_path)
    cfg.local_repo_root = source
    cfg.sandbox_secret_roots = [str(secret)]
    assert matches_excludes(Path(name), effective_excludes(cfg, []))
    before = poller._fingerprint_tree(source, [], cfg=cfg)
    secret.write_text("SYNTHETIC_CHANGED")
    assert poller._fingerprint_tree(source, [], cfg=cfg) == before
    target = tmp_path / "target"
    cfg.local_repo_root = target
    cfg.sandbox_secret_roots = [str(target / name)]
    result = remote_fs.tar_sync_from_remote(cfg, str(source), str(target), [])
    assert result.ok, result.stderr
    assert (target / "service.py").exists()
    assert not (target / name).exists()


@pytest.mark.parametrize("method", ["tar_sync_to_remote", "rsync_to_remote"])
def test_push_is_rejected_before_any_subprocess_or_source_read(tmp_path, monkeypatch, method):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "same.py").write_text("new")
    (target / "same.py").write_text("owner content")

    def forbidden(*args, **kwargs):
        raise AssertionError("push must not start any process or read source contents")

    monkeypatch.setattr(remote_fs, "_run", forbidden)
    monkeypatch.setattr(remote_fs.subprocess, "Popen", forbidden)
    monkeypatch.setattr(remote_fs.os, "open", forbidden)
    result = getattr(remote_fs, method)(config(tmp_path), str(source), str(target), [])
    assert not result.ok
    assert "source push disabled" in result.stderr
    assert (target / "same.py").read_text() == "owner content"


@pytest.mark.parametrize("method", ["tar_sync_from_remote", "rsync_to_local"])
def test_pull_never_adopts_or_deletes_an_unowned_nonempty_mirror(tmp_path, monkeypatch, method):
    target = tmp_path / "target"
    target.mkdir()
    keep = target / "owner.txt"
    keep.write_text("owner content")

    def forbidden(*args, **kwargs):
        raise AssertionError("an unowned destination must fail before transport")

    monkeypatch.setattr(remote_fs, "_run", forbidden)
    monkeypatch.setattr(remote_fs.subprocess, "Popen", forbidden)
    result = getattr(remote_fs, method)(config(tmp_path), "/synthetic/source", str(target), [])
    assert not result.ok
    assert "not watcher-owned" in result.stderr
    assert keep.read_text() == "owner content"
    assert not list(tmp_path.glob(".harness-retained-*"))


def test_repeated_pulls_keep_all_prior_snapshots_without_deletion(tmp_path, local_ssh):
    source = tmp_path / "source"
    source.mkdir()
    (source / "service.py").write_text("first")
    (source / "removed.py").write_text("retained original")
    target = tmp_path / "target"
    cfg = config(tmp_path)
    assert remote_fs.tar_sync_from_remote(cfg, str(source), str(target), []).ok
    original_identity = target.stat().st_ino
    (source / "service.py").write_text("second")
    (source / "removed.py").unlink()
    assert remote_fs.tar_sync_from_remote(cfg, str(source), str(target), []).ok
    assert (target / "service.py").read_text() == "second"
    assert not (target / "removed.py").exists()
    archived = list(tmp_path.glob(".harness-retained-*/mirror"))
    assert len(archived) == 1
    assert archived[0].stat().st_ino == original_identity
    assert (archived[0] / "service.py").read_text() == "first"
    assert (archived[0] / "removed.py").read_text() == "retained original"


def test_failed_pull_preserves_the_current_owned_snapshot(tmp_path, local_ssh, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "service.py").write_text("known good")
    target = tmp_path / "target"
    cfg = config(tmp_path)
    assert remote_fs.tar_sync_from_remote(cfg, str(source), str(target), []).ok
    identity = target.stat().st_ino

    def fail(cfg, remote, local, exclude):
        (Path(local) / "partial.py").write_text("partial staging")
        return remote_fs.CmdResult(False, "", "source sync failed", 1, 0)

    monkeypatch.setattr(remote_fs, "_tar_into_fresh", fail)
    result = remote_fs.tar_sync_from_remote(cfg, str(source), str(target), [])
    assert not result.ok
    assert target.stat().st_ino == identity
    assert (target / "service.py").read_text() == "known good"
    assert not (target / "partial.py").exists()
    assert list(tmp_path.glob(".harness-incoming-*/partial.py"))


def test_replaced_directory_cannot_reuse_a_prior_ownership_ledger(tmp_path, local_ssh, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "service.py").write_text("first")
    target = tmp_path / "target"
    cfg = config(tmp_path)
    assert remote_fs.tar_sync_from_remote(cfg, str(source), str(target), []).ok
    target.rename(tmp_path / "saved")
    target.mkdir()
    (target / "owner.txt").write_text("owner content")

    def forbidden(*args, **kwargs):
        raise AssertionError("a replacement directory is not watcher-owned")

    monkeypatch.setattr(remote_fs, "_run", forbidden)
    result = remote_fs.tar_sync_from_remote(cfg, str(source), str(target), [])
    assert not result.ok
    assert (target / "owner.txt").read_text() == "owner content"


def test_symlinked_ownership_ledger_is_not_followed(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("SYNTHETIC_PRIVATE")
    remote_fs._mirror_ledger(target).symlink_to(outside)

    def forbidden(*args, **kwargs):
        raise AssertionError("linked ledger must not be opened or launch transport")

    monkeypatch.setattr(remote_fs.os, "open", forbidden)
    monkeypatch.setattr(remote_fs, "_run", forbidden)
    result = remote_fs.tar_sync_from_remote(config(tmp_path), "/synthetic/source", str(target), [])
    assert not result.ok
    assert outside.read_text() == "SYNTHETIC_PRIVATE"


@pytest.mark.parametrize("change", ["new_file", "changed_file", "secret_file"])
def test_local_owner_changes_revoke_mirror_refresh_permission(tmp_path, local_ssh, monkeypatch, change):
    source = tmp_path / "source"
    source.mkdir()
    (source / "service.py").write_text("first")
    target = tmp_path / "target"
    cfg = config(tmp_path)
    assert remote_fs.tar_sync_from_remote(cfg, str(source), str(target), []).ok
    path = target / {"new_file": "owner.txt", "changed_file": "service.py", "secret_file": ".env"}[change]
    path.write_text("SYNTHETIC_OWNER_CHANGE")

    def forbidden(*args, **kwargs):
        raise AssertionError("an owner's change must not be moved by a later pull")

    monkeypatch.setattr(remote_fs, "_run", forbidden)
    result = remote_fs.tar_sync_from_remote(cfg, str(source), str(target), [])
    assert not result.ok
    assert path.read_text() == "SYNTHETIC_OWNER_CHANGE"
    assert not list(tmp_path.glob(".harness-retained-*"))
