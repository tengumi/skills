"""Behavioral tests using only disposable synthetic files and local Git."""

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "artifact_io.py"
SPEC = importlib.util.spec_from_file_location("artifact_io", MODULE_PATH)
io = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(io)


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def make_file(root, name, content="safe"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.example",
        ".env.local",
        "x.pem",
        "x.key",
        "x.p12",
        "x.pfx",
        "x.crt",
        "x.cer",
        "x.jks",
        "x.keystore",
        "credentials.json",
        "secret",
        "secrets.yaml",
        "id_rsa",
        "id_ed25519.pub",
        ".ssh/file",
        ".aws/file",
        ".codex/file",
        "node_modules/file",
        "build/file",
        "dist/file",
        "outputs/file",
    ],
)
def test_forbidden_explicit_never_opens_file(tmp_path, monkeypatch, name):
    path = make_file(tmp_path, name, "SENTINEL-NOT-TO-BE-READ")
    original = io.os.open

    def guarded(file, flags, *args, **kwargs):
        if str(file) == path.name:
            pytest.fail("A forbidden file was opened")
        return original(file, flags, *args, **kwargs)

    monkeypatch.setattr(io.os, "open", guarded)
    with pytest.raises(io.ToolError, match="forbidden"):
        io.snapshot(tmp_path, [name])


def test_git_selects_only_tracked_and_reports_exclusions(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    make_file(tmp_path, "source/env.py", "migration code")
    make_file(tmp_path, ".env.example", "SENTINEL")
    make_file(tmp_path, "outputs/report.json", "SENTINEL")
    make_file(tmp_path, "untracked.txt", "not selected")
    git(tmp_path, "add", "source/env.py", ".env.example", "outputs/report.json")
    (tmp_path / "link.py").symlink_to(tmp_path / "source/env.py")
    git(tmp_path, "add", "link.py")
    original = io.os.open

    def guarded(file, flags, *args, **kwargs):
        if str(file) in {".env.example", "report.json", "untracked.txt", "link.py"}:
            pytest.fail("An excluded or untracked file was opened")
        return original(file, flags, *args, **kwargs)

    monkeypatch.setattr(io.os, "open", guarded)
    result = io.snapshot(tmp_path)
    assert result["selection"] == "git-tracked"
    assert list(result["files"]) == ["source/env.py"]
    assert result["skipped"] == {
        ".env.example": "sensitive-name",
        "link.py": "symlink",
        "outputs/report.json": "excluded-directory",
    }


def test_hash_deterministic_and_tracks_bytes_not_metadata(tmp_path):
    first = make_file(tmp_path, "a.py", "A")
    make_file(tmp_path, "b.py", "B")
    a = io.snapshot(tmp_path, ["b.py", "a.py"])
    os.utime(first, (0, 0))
    b = io.snapshot(tmp_path, ["a.py", "b.py", "a.py"])
    assert a == b
    canonical = json.dumps(a["files"], sort_keys=True, separators=(",", ":")).encode()
    assert a["content_sha256"] == hashlib.sha256(canonical).hexdigest()
    first.write_text("different")
    assert io.snapshot(tmp_path, ["a.py", "b.py"])["content_sha256"] != a["content_sha256"]


@pytest.mark.parametrize(
    "path",
    [
        "../elsewhere",
        "/absolute",
        "x/../../outside",
        "*.py",
        "x?.py",
        "[ab].py",
        "C:\\file",
        "",
        ".",
    ],
)
def test_explicit_path_validation(tmp_path, path):
    with pytest.raises(io.ToolError):
        io.snapshot(tmp_path, [path])


@pytest.mark.parametrize("operation", ["snapshot", "read", "write"])
def test_symlink_ancestor_is_never_followed(tmp_path, operation):
    outside = tmp_path / "outside"
    outside.mkdir()
    make_file(outside, "input.json", '{"sentinel":"do not read"}')
    root = tmp_path / "root"
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(io.ToolError, match="symlink"):
        if operation == "snapshot":
            io.snapshot(root, ["linked/input.json"])
        elif operation == "read":
            io.read_json(root / "linked/input.json")
        else:
            io.write_json(root / "linked/output.json", {})
    assert not (outside / "output.json").exists()


def test_missing_tracked_file_is_error_not_silent_skip(tmp_path):
    git(tmp_path, "init", "-q")
    path = make_file(tmp_path, "tracked.py")
    make_file(tmp_path, "other.py")
    git(tmp_path, "add", "tracked.py", "other.py")
    path.unlink()
    with pytest.raises(io.ToolError, match="missing"):
        io.snapshot(tmp_path)


def test_empty_and_missing_explicit_selection_fail(tmp_path):
    with pytest.raises(io.ToolError, match="no safe"):
        io.snapshot(tmp_path, [])
    with pytest.raises(io.ToolError, match="missing"):
        io.snapshot(tmp_path, ["missing"])


@pytest.mark.parametrize(
    "content",
    [
        '{"SENSITIVE":1,"SENSITIVE":2}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":-Infinity}',
        '{"x":1e999}',
        '{"SENSITIVE":"unterminated}',
        '{"x":{"a":1,"a":2}}',
    ],
)
def test_invalid_json_error_never_echoes_values(tmp_path, content):
    path = make_file(tmp_path, "input.json", content)
    with pytest.raises(io.ToolError) as caught:
        io.read_json(path)
    assert "SENSITIVE" not in str(caught.value)
    assert content not in str(caught.value)


def test_json_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(io, "MAX_JSON_BYTES", 8)
    path = make_file(tmp_path, "input.json", '{"value":123}')
    with pytest.raises(io.ToolError, match="limit"):
        io.read_json(path)


@pytest.mark.parametrize(
    "name", [".env.example", "keys/service.pem", "secrets.json", ".aws/file.json"]
)
def test_json_io_denies_sensitive_paths_before_open(tmp_path, monkeypatch, name):
    path = make_file(tmp_path, name, "SENTINEL")
    monkeypatch.setattr(io.os, "open", lambda *args, **kwargs: pytest.fail("Opened sensitive path"))
    with pytest.raises(io.ToolError):
        io.read_json(path)
    with pytest.raises(io.ToolError):
        io.write_json(path, {}, replace=True)


def test_write_no_overwrite_and_replace_without_reading_old_file(tmp_path, monkeypatch):
    path = tmp_path / "outputs" / "nested" / "result.json"
    io.write_json(path, {"z": 1, "a": "текст"})
    assert io.read_json(path) == {"a": "текст", "z": 1}
    before = path.read_bytes()
    with pytest.raises(io.ToolError, match="already exists"):
        io.write_text(path, "replacement")
    assert path.read_bytes() == before
    original = io.os.open

    def guarded(file, flags, *args, **kwargs):
        if str(file) == "result.json":
            pytest.fail("Replacement read the old file")
        return original(file, flags, *args, **kwargs)

    monkeypatch.setattr(io.os, "open", guarded)
    io.write_json(path, {"new": True}, replace=True)
    assert path.read_text() == '{\n  "new": true\n}\n'
    assert not list(path.parent.glob(".harness-artifact-*.tmp"))


def test_existing_symlink_output_rejected(tmp_path):
    original = make_file(tmp_path, "real.json", "unchanged")
    (tmp_path / "link.json").symlink_to(original)
    with pytest.raises(io.ToolError, match="symlink"):
        io.write_json(tmp_path / "link.json", {}, replace=True)
    assert original.read_text() == "unchanged"


def test_failed_atomic_publication_preserves_original_and_cleans_temporary(tmp_path, monkeypatch):
    original = make_file(tmp_path, "result.json", "original")
    monkeypatch.setattr(
        io.os, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("SENSITIVE"))
    )
    with pytest.raises(io.ToolError) as caught:
        io.write_json(original, {}, replace=True)
    assert "SENSITIVE" not in str(caught.value)
    assert original.read_text() == "original"
    assert not list(tmp_path.glob(".harness-artifact-*.tmp"))


def test_competing_writer_is_not_overwritten(tmp_path, monkeypatch):
    target = tmp_path / "result.json"
    original_link = io.os.link

    def concurrent_link(*args, **kwargs):
        target.write_text("other writer")
        return original_link(*args, **kwargs)

    monkeypatch.setattr(io.os, "link", concurrent_link)
    with pytest.raises(io.ToolError):
        io.write_json(target, {"ours": True})
    assert target.read_text() == "other writer"
    assert not list(tmp_path.glob(".harness-artifact-*.tmp"))
