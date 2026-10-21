"""Named, isolated watcher projects; no SSH or installation is performed here."""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from lib.config import Config, ConfigError
from lib.sandbox import validate_sandbox


DEFAULT_PROFILES_DIR = Path.home() / ".config" / "harness-watcher" / "profiles"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_STORAGE_ID = re.compile(r"[0-9a-f]{32}\Z")
_HOST = re.compile(
    r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?"
    r"(?:[A-Za-z0-9][A-Za-z0-9._-]*|\[[A-Fa-f0-9:]+\])\Z"
)
_MARKER = ".harness-watcher-project.json"
_MAX_DOCUMENT_BYTES = 64 * 1024
_EXCLUDES = [
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".ruff_cache", "*.pyc", ".DS_Store", "dist", "build",
    "*.egg-info", ".env", ".env*", "certs", "keys", "*.key", "*.pem",
    ".aws", ".ssh",
]


def _name(value: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ConfigError("profile name must contain 1–64 ASCII letters, digits, '_' or '-' and start with a letter or digit")
    return value


def validate_profile_name(value: str) -> str:
    return _name(value)


def _no_controls(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError(f"{field} must be a non-empty string without control characters")
    return value


def _absolute(path: Path) -> Path:
    """Keep the spelling to detect symlinks rather than silently following them."""
    _no_controls(str(path), "managed path")
    raw = Path(path).expanduser()
    if ".." in raw.parts:
        raise ConfigError("managed paths must not contain '..'")
    return raw.absolute()


def _assert_no_symlinks(path: Path) -> None:
    for part in reversed((path, *path.parents)):
        if part.is_symlink():
            raise ConfigError(f"managed path must not be a symlink: {part}")


def _private_directory(path: Path) -> None:
    _assert_no_symlinks(path)
    missing = []
    part = path
    while not part.exists():
        missing.append(part)
        part = part.parent
    if not part.is_dir():
        raise ConfigError(f"managed parent is not a directory: {part}")
    for part in reversed(missing):
        try:
            part.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _assert_no_symlinks(part)
        if not part.is_dir():
            raise ConfigError(f"managed path is not a directory: {part}")


def _regular_metadata(path: Path) -> None:
    _assert_no_symlinks(path)
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ConfigError(f"metadata must be an unlinked regular file: {path}")


def _write_new_json(path: Path, value: dict) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > _MAX_DOCUMENT_BYTES:
        raise ConfigError("profile metadata is too large")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # link is an atomic create-if-absent, unlike replace/rename. The
            # temporary hardlink is removed before metadata can be loaded.
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise ConfigError(f"profile already exists: {path.stem}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _read_json(path: Path) -> dict:
    _regular_metadata(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_DOCUMENT_BYTES:
                raise ConfigError(f"invalid metadata file: {path}")
            payload = stream.read(_MAX_DOCUMENT_BYTES + 1)
        if len(payload) > _MAX_DOCUMENT_BYTES:
            raise ConfigError(f"metadata too large: {path}")
        value = json.loads(payload, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        return value
    except (OSError, ValueError, UnicodeError) as exc:
        # Parser exceptions can include source text; never expose their contents.
        raise ConfigError(f"cannot read valid project metadata: {path}") from exc


def _remote(*, ssh_host, ssh_key, remote_repo_root, ssh_port=22) -> dict:
    _no_controls(ssh_host, "ssh_host")
    if not _HOST.fullmatch(ssh_host):
        raise ConfigError("ssh_host must be an SSH alias or [user@]hostname, not options or a command")
    if isinstance(ssh_port, bool) or not isinstance(ssh_port, int) or not 1 <= ssh_port <= 65535:
        raise ConfigError("ssh_port must be an integer between 1 and 65535")
    if not isinstance(ssh_key, (str, os.PathLike)):
        raise ConfigError("ssh_key must be a file path")
    key = Path(_no_controls(str(ssh_key), "ssh_key")).expanduser().absolute()
    if not key.is_file():
        raise ConfigError(f"ssh_key not found or not a file: {key}")
    root = PurePosixPath(_no_controls(remote_repo_root, "remote_repo_root"))
    if not root.is_absolute() or str(root) in ("/", "//") or ".." in root.parts:
        raise ConfigError("remote_repo_root must be an absolute repository path, not '/' or a parent traversal")
    return {
        "ssh_host": ssh_host,
        "ssh_port": ssh_port,
        "ssh_key": str(key),
        "remote_repo_root": str(root),
    }


def _document(path: Path, name: str) -> dict:
    data = _read_json(path)
    fields = set(data)
    if fields - {"schema", "name", "storage_id", "remote", "environment", "sandbox"} or not {"schema", "name", "storage_id", "remote", "environment"} <= fields:
        raise ConfigError("invalid profile fields; local paths are managed automatically")
    if type(data["schema"]) is not int or data["schema"] != 1 or data["name"] != name:
        raise ConfigError("profile schema or name does not match")
    if not isinstance(data["storage_id"], str) or not _STORAGE_ID.fullmatch(data["storage_id"]):
        raise ConfigError("invalid profile storage identity")
    remote = data["remote"]
    if not isinstance(remote, dict) or set(remote) != {"ssh_host", "ssh_port", "ssh_key", "remote_repo_root"}:
        raise ConfigError("invalid remote connection fields")
    validated = _remote(**remote)
    if validated != remote:
        raise ConfigError("remote connection paths must be normalized")
    if not isinstance(data["environment"], dict):
        raise ConfigError("environment recipe must be an object")
    validate_sandbox(data.get("sandbox"))
    return data


def _marker(data: dict) -> dict:
    return {key: data[key] for key in ("schema", "name", "storage_id", "remote")}


def _config(data: dict, path: Path) -> Config:
    root = path.parent.parent / "projects" / data["storage_id"]
    sandbox = validate_sandbox(data.get("sandbox"))
    return Config(
        **data["remote"],
        local_repo_root=root / "repo",
        audit_log_path=root / "audit.log",
        state_path=root / "state.json",
        rsync_exclude=list(_EXCLUDES),
        config_path=path,
        profile_name=data["name"],
        managed_root=root,
        environment=data["environment"],
        execution_sandbox=sandbox["mode"],
        sandbox_binary=sandbox["binary"],
        sandbox_read_roots=sandbox["read_roots"],
        sandbox_secret_roots=sandbox["secret_roots"],
        sandbox_install_network=sandbox["install_network"],
    )


def create_profile(
    name: str, *, ssh_host: str, ssh_key: str, remote_repo_root: str,
    ssh_port: int = 22, environment: dict | None = None,
    sandbox: dict | None = None,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> Config:
    """Save a project without overwriting any profile or touching its remote."""
    name = _name(name)
    base = _absolute(profiles_dir)
    _assert_no_symlinks(base)
    path = base / f"{name}.json"
    if path.exists() or path.is_symlink():
        raise ConfigError(f"profile already exists: {name}")
    remote = _remote(ssh_host=ssh_host, ssh_key=ssh_key, remote_repo_root=remote_repo_root, ssh_port=ssh_port)
    # One workstation consumer per exact queue. Different aliases/machines
    # still require owner coordination; this is not a distributed queue lock.
    for existing in list_profiles(profiles_dir=base):
        saved = _document(base / f"{existing}.json", existing)["remote"]
        if all(saved[field] == remote[field] for field in ("ssh_host", "ssh_port", "remote_repo_root")):
            raise ConfigError(f"this remote repository already has profile {existing}; use start {existing}")
    if environment is None:
        environment = {"mode": "none"}
    if not isinstance(environment, dict):
        raise ConfigError("environment recipe must be an object")
    try:
        # Isolate the saved recipe from caller mutations and reject non-JSON values.
        recipe = json.loads(json.dumps(environment, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ConfigError("environment recipe must be JSON serializable") from exc
    sandbox = validate_sandbox(sandbox)
    if sandbox["install_network"]:
        raise ConfigError("new profiles require install_network=false for offline dependency installation")
    data = {"schema": 1, "name": name, "storage_id": uuid.uuid4().hex, "remote": remote,
            "environment": recipe, "sandbox": sandbox}
    if len(json.dumps(data).encode("utf-8")) > _MAX_DOCUMENT_BYTES - 4096:
        raise ConfigError("profile metadata is too large")
    root = base.parent / "projects" / data["storage_id"]
    _private_directory(base)
    _private_directory(root.parent)
    _assert_no_symlinks(root)
    try:
        root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ConfigError("project storage identity already exists; try again") from exc
    try:
        _write_new_json(root / _MARKER, _marker(data))
        (root / "repo").mkdir(mode=0o700)
        _write_new_json(path, data)
    except Exception:
        # Only remove files just created here; never recursively delete storage.
        if (root / "repo").is_dir():
            (root / "repo").rmdir()
        (root / _MARKER).unlink(missing_ok=True)
        root.rmdir()
        raise
    return load_profile(name, profiles_dir=base)


def load_profile(name: str, profiles_dir: Path = DEFAULT_PROFILES_DIR) -> Config:
    name = _name(name)
    path = _absolute(profiles_dir) / f"{name}.json"
    data = _document(path, name)
    cfg = _config(data, path)
    validate_managed_paths(cfg)
    return cfg


def list_profiles(profiles_dir: Path = DEFAULT_PROFILES_DIR) -> list[str]:
    base = _absolute(profiles_dir)
    _assert_no_symlinks(base)
    if not base.exists():
        return []
    if not base.is_dir():
        raise ConfigError("profiles path is not a directory")
    names = []
    for path in base.glob("*.json"):
        _regular_metadata(path)
        names.append(_name(path.stem))
    return sorted(names)


def validate_managed_paths(cfg: Config) -> None:
    """Fail before mirror deletion/env writes if project ownership has changed."""
    name = getattr(cfg, "profile_name", None)
    root = getattr(cfg, "managed_root", None)
    if name is None and root is None:
        return  # Legacy diagnostics may load; runtime/transport enforce ownership.
    if name is None or root is None or cfg.config_path is None:
        raise ConfigError("incomplete managed profile identity")
    name = _name(name)
    path = _absolute(cfg.config_path)
    if path.name != f"{name}.json":
        raise ConfigError("profile filename does not match project identity")
    data = _document(path, name)
    expected = _config(data, path)
    for field in ("managed_root", "local_repo_root", "state_path", "audit_log_path"):
        actual = _absolute(getattr(cfg, field))
        if actual != getattr(expected, field):
            raise ConfigError(f"managed {field} does not match project storage")
        _assert_no_symlinks(actual)
    for field, value in data["remote"].items():
        if getattr(cfg, field) != value:
            raise ConfigError("remote connection does not match saved project")
    root = expected.managed_root
    if not root.is_dir() or _read_json(root / _MARKER) != _marker(data):
        raise ConfigError("project storage marker is missing or mismatched")
    for directory in (root / "repo", root / "venv", root / ".harness-watcher-tmp"):
        _assert_no_symlinks(directory)
        if directory.exists() and not directory.is_dir():
            raise ConfigError(f"managed directory is not a directory: {directory}")
    for filename in ("state.json", "audit.log", "environment.json", "environment.json.tmp", ".watcher.lock"):
        _regular_metadata(root / filename)


@contextmanager
def profile_lock(cfg: Config):
    """Prevent two watcher processes from sharing a profile's mirror and queue."""
    if getattr(cfg, "managed_root", None) is None and getattr(cfg, "profile_name", None) is None:
        yield
        return
    validate_managed_paths(cfg)
    try:
        import fcntl
    except ImportError as exc:
        raise ConfigError("named project locking requires macOS/Linux (fcntl)") from exc
    path = cfg.managed_root / ".watcher.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ConfigError("invalid project lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConfigError(f"watcher is already running for project {cfg.profile_name}") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
