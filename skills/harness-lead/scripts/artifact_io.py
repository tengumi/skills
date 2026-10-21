"""Базовые операции с файлами Harness, снижающие риск раскрытия секретов.

Снимок включает только отслеживаемые Git или явно выбранные файлы, без полного
обхода рабочей области. Доступ идёт через дескрипторы каталогов без перехода
по символическим ссылкам. Эти проверки не заменяют права доступа ОС.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator
from uuid import uuid4

MAX_JSON_BYTES = 8 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_SECRET_DIRS = {".git", ".ssh", ".aws", ".codex"}
_EXCLUDED_DIRS = _SECRET_DIRS | {
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    ".cache",
    "outputs",
}
_SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".jks", ".keystore"}
_SECRET_NAME = re.compile(r"^(?:credentials?|secrets?|id_rsa|id_ed25519)(?:[._-]|$)")


class ToolError(Exception):
    """Сообщение без содержимого файлов и потенциально опасного текста ошибки ОС."""


class _UnsafePath(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _secret_reason(parts: tuple[str, ...]) -> str | None:
    for part in parts:
        name = part.lower()
        if name.startswith(".env") or _SECRET_NAME.match(name):
            return "sensitive-name"
        if name in _SECRET_DIRS:
            return "sensitive-directory"
        if Path(name).suffix in _SECRET_SUFFIXES:
            return "key-or-certificate"
    return None


def _io_path(path: Path) -> Path:
    try:
        path = Path(path)
        if ".." in path.parts or _secret_reason(path.parts):
            raise ToolError("Refusing a sensitive or traversing artifact path.")
        absolute = Path(os.path.abspath(path))
        if not absolute.name:
            raise ToolError("An artifact path must name a file.")
        return absolute
    except (TypeError, ValueError, OSError):
        raise ToolError("Invalid artifact path.") from None


@contextmanager
def _directory(path: Path, *, create: bool = False) -> Iterator[int]:
    """Открыть каждый родительский каталог; O_NOFOLLOW защищает от подмены ссылкой."""
    fd = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(path.anchor, flags)
        for part in path.parts[1:]:
            try:
                child_stat = os.stat(part, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    raise _UnsafePath("missing") from None
                try:
                    os.mkdir(part, mode=0o755, dir_fd=fd)
                except FileExistsError:
                    pass
                child_stat = os.stat(part, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(child_stat.st_mode):
                raise _UnsafePath("symlink")
            if not stat.S_ISDIR(child_stat.st_mode):
                raise _UnsafePath("not-directory")
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    except _UnsafePath:
        raise
    except (OSError, ValueError, NotImplementedError, AttributeError):
        raise _UnsafePath("unreadable-path") from None
    finally:
        if fd is not None:
            os.close(fd)


@contextmanager
def _reader(path: Path) -> Iterator[object]:
    with _directory(path.parent) as parent_fd:
        try:
            info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise _UnsafePath("symlink")
            if not stat.S_ISREG(info.st_mode):
                raise _UnsafePath("not-file")
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise _UnsafePath("not-file")
                yield stream
        except FileNotFoundError:
            raise _UnsafePath("missing") from None
        except (OSError, ValueError):
            raise _UnsafePath("unreadable-file") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("Non-finite JSON number")


def _finite_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("Non-finite JSON number")
    return value


def read_json(path: Path) -> object:
    """Прочитать JSON ограниченного размера, запретив дубли ключей и бесконечности."""
    path = _io_path(path)
    try:
        with _reader(path) as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ToolError("JSON artifact exceeds the 8 MiB limit.")
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except _UnsafePath as error:
        raise ToolError(f"Cannot read JSON artifact: {error.reason}.") from None
    except (UnicodeError, ValueError, RecursionError):
        raise ToolError("Invalid strict UTF-8 JSON artifact.") from None


def _write(path: Path, data: bytes, *, replace: bool) -> None:
    path = _io_path(path)
    temporary = f".harness-artifact-{uuid4().hex}.tmp"
    try:
        with _directory(path.parent, create=True) as parent_fd:
            try:
                info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                info = None
            if info is not None:
                if stat.S_ISLNK(info.st_mode):
                    raise ToolError("Refusing to replace a symlink artifact.")
                if not stat.S_ISREG(info.st_mode):
                    raise ToolError("An existing artifact must be a regular file.")
                if not replace:
                    raise ToolError("Artifact already exists; replacement was not requested.")
            try:
                fd = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if replace:
                    os.replace(temporary, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                else:
                    # В отличие от rename, link не заменит файл, созданный другим процессом.
                    os.link(
                        temporary,
                        path.name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                os.fsync(parent_fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
    except ToolError:
        raise
    except _UnsafePath as error:
        raise ToolError(f"Cannot write artifact: {error.reason}.") from None
    except (OSError, ValueError):
        raise ToolError("Cannot write artifact atomically.") from None


def write_json(path: Path, value: object, replace: bool = False) -> None:
    try:
        text = (
            json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
    except (ValueError, TypeError, RecursionError):
        raise ToolError("Cannot serialize strict JSON artifact.") from None
    write_text(path, text, replace=replace)


def write_text(path: Path, text: str, replace: bool = False) -> None:
    try:
        data = text.encode("utf-8")
    except (AttributeError, UnicodeError):
        raise ToolError("Artifact text must be valid UTF-8.") from None
    _write(path, data, replace=replace)


def _relative(raw: str) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ToolError("Snapshot paths must be non-empty relative filenames.")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or str(path) == "."
        or any(char in raw for char in "*?[]\\")
        or re.match(r"^[A-Za-z]:", raw)
    ):
        raise ToolError("Snapshot paths cannot use traversal, absolute paths or glob patterns.")
    return str(path)


def _selection(root: Path, paths: list[str] | None) -> list[str]:
    if paths is not None:
        if not isinstance(paths, list):
            raise ToolError("Explicit snapshot selection must be a list of filenames.")
        return sorted({_relative(path) for path in paths})
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        raise ToolError("Cannot list tracked files; supply an explicit file selection.") from None
    if result.returncode != 0:
        raise ToolError("Cannot list tracked files; supply an explicit file selection.")
    return sorted({_relative(os.fsdecode(path)) for path in result.stdout.split(b"\x00") if path})


def snapshot(root: Path, paths: list[str] | None = None) -> dict:
    """Вычислить суммы выбранных файлов; опасный явный путь — ошибка, неявный — пропуск."""
    root = _io_path(Path(root) / "__snapshot_root__").parent
    try:
        with _directory(root):
            pass
    except _UnsafePath as error:
        raise ToolError(f"Invalid snapshot root: {error.reason}.") from None
    selected = _selection(root, paths)
    files = {}
    skipped = {}
    for relative in selected:
        parts = PurePosixPath(relative).parts
        reason = _secret_reason(parts)
        if reason is None and any(part.lower() in _EXCLUDED_DIRS for part in parts[:-1]):
            reason = "excluded-directory"
        if reason:
            if paths is not None:
                raise ToolError(f"Explicit snapshot selection contains a forbidden path: {reason}.")
            skipped[relative] = reason
            continue
        try:
            digest = hashlib.sha256()
            with _reader(root / relative) as stream:
                while chunk := stream.read(_CHUNK_BYTES):
                    digest.update(chunk)
            files[relative] = digest.hexdigest()
        except _UnsafePath as error:
            if error.reason == "symlink" and paths is None:
                skipped[relative] = "symlink"
                continue
            raise ToolError(f"Cannot hash selected file: {error.reason}.") from None
    if not files:
        raise ToolError("Snapshot contains no safe readable files.")
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "format_version": 1,
        "algorithm": "sha256",
        "selection": "git-tracked" if paths is None else "explicit",
        "files": files,
        "content_sha256": hashlib.sha256(canonical).hexdigest(),
        "skipped": skipped,
    }
