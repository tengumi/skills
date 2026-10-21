"""Операции с файлами на удалённой машине через SSH/SCP.

Watcher работает в обратную сторону от remote-exec: подключается ИЗ ноутбука
на удалённый хост и читает/пишет файлы там.

Все функции возвращают (ok, data_or_error). Не бросают исключения — watcher
должен продолжать работать даже если удалённая машина временно недоступна.
"""

from __future__ import annotations

import subprocess
import shlex
import time
import os
import stat
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lib.secret_paths import effective_excludes, matches_excludes

if TYPE_CHECKING:
    from lib.config import Config


@dataclass
class CmdResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


def _ssh_options(cfg: "Config", log_level: str = "ERROR") -> list[str]:
    """Return shared SSH/SCP options with host-key verification on by default."""
    strict_value = "yes" if cfg.strict_host_key_checking else "no"
    options = [
        "-o", f"StrictHostKeyChecking={strict_value}",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=30",
        "-o", f"LogLevel={log_level}",
    ]
    if cfg.user_known_hosts_file:
        options.extend(["-o", f"UserKnownHostsFile={cfg.user_known_hosts_file}"])
    return options


def _ssh_base(cfg: "Config") -> list[str]:
    return ["ssh", "-p", str(cfg.ssh_port), "-i", cfg.ssh_key, *_ssh_options(cfg), cfg.ssh_host]


def _scp_base(cfg: "Config") -> list[str]:
    return ["scp", "-P", str(cfg.ssh_port), "-i", cfg.ssh_key, *_ssh_options(cfg)]


def _run(cmd: list[str], timeout: int) -> CmdResult:
    started = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        dur = int((time.monotonic() - started) * 1000)
        return CmdResult(
            ok=(r.returncode == 0),
            stdout=r.stdout,
            stderr=r.stderr,
            exit_code=r.returncode,
            duration_ms=dur,
        )
    except subprocess.TimeoutExpired:
        return CmdResult(ok=False, stdout="", stderr=f"timeout after {timeout}s", exit_code=-1, duration_ms=timeout * 1000)
    except FileNotFoundError as e:
        return CmdResult(ok=False, stdout="", stderr=f"command not found: {e}", exit_code=-2, duration_ms=0)
    except Exception as e:
        return CmdResult(ok=False, stdout="", stderr=f"{type(e).__name__}: {e}", exit_code=-2, duration_ms=0)


def remote_ls(cfg: "Config", remote_path: str) -> CmdResult:
    """Список файлов в удалённой папке. Возвращает CmdResult, stdout — список через \\n."""
    cmd = [*_ssh_base(cfg), f"ls -1 {_quote(remote_path)} 2>/dev/null || true"]
    return _run(cmd, timeout=15)


def remote_mkdir(cfg: "Config", remote_path: str) -> CmdResult:
    """Создать удалённую папку (mkdir -p)."""
    cmd = [*_ssh_base(cfg), f"mkdir -p {_quote(remote_path)}"]
    return _run(cmd, timeout=15)


def remote_move(cfg: "Config", src: str, dst: str) -> CmdResult:
    """Archive a protocol file without clobbering any destination entry."""
    script = _REMOTE_SAFE_PARENT + """
try:
    source_parent, source = safe_parent(sys.argv[1])
    target_parent, target = safe_parent(sys.argv[2])
    original = os.stat(source, dir_fd=source_parent, follow_symlinks=False)
    if not stat.S_ISREG(original.st_mode) or original.st_nlink != 1:
        raise ValueError('source must be an unlinked regular file')
    os.link(source, target, src_dir_fd=source_parent, dst_dir_fd=target_parent,
            follow_symlinks=False)
    linked = os.stat(target, dir_fd=target_parent, follow_symlinks=False)
    current = os.stat(source, dir_fd=source_parent, follow_symlinks=False)
    identity = (original.st_dev, original.st_ino)
    if (linked.st_dev, linked.st_ino) != identity or (current.st_dev, current.st_ino) != identity:
        raise ValueError('source changed; no source removal')
    os.unlink(source, dir_fd=source_parent)
except (OSError, ValueError):
    sys.exit(3)
"""
    result = _run([*_ssh_base(cfg), _remote_python(script, src, dst)], timeout=15)
    return _protocol_result(result, "protocol move refused or failed; existing destination preserved")


def remote_file_exists(cfg: "Config", remote_path: str) -> CmdResult:
    """Check for a regular remote file without treating absence as SSH failure."""
    cmd = [
        *_ssh_base(cfg),
        f"if test -f {_quote(remote_path)}; then echo EXISTS; else echo MISSING; fi",
    ]
    return _run(cmd, timeout=15)


def download_file(cfg: "Config", remote_path: str, local_path: str) -> CmdResult:
    """Скачать файл с удалённой машины на локальный executor."""
    remote = f"{cfg.ssh_host}:{remote_path}"
    cmd = [*_scp_base(cfg), remote, local_path]
    return _run(cmd, timeout=60)


def upload_file(cfg: "Config", local_path: str, remote_path: str) -> CmdResult:
    """Publish a protocol report by exclusive creation, never by SCP overwrite."""
    script = _REMOTE_SAFE_PARENT + """
temporary = None
try:
    parent, name = safe_parent(sys.argv[1])
    candidate = '.harness-report-' + os.urandom(16).hex()
    fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=parent)
    temporary = candidate
    digest = hashlib.sha256()
    received = 0
    with os.fdopen(fd, 'wb') as output:
        while True:
            chunk = sys.stdin.buffer.read(65536)
            if not chunk:
                break
            received += len(chunk)
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if received != int(sys.argv[2]) or digest.hexdigest() != sys.argv[3]:
        raise ValueError('incomplete report')
    os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
except (OSError, ValueError):
    sys.exit(3)
finally:
    if temporary is not None:
        try:
            os.unlink(temporary, dir_fd=parent)
        except OSError:
            pass
"""
    started = time.monotonic()
    try:
        fd = os.open(local_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("source must be an unlinked regular file")
            digest = hashlib.sha256()
            while chunk := source.read(65536):
                digest.update(chunk)
            source.seek(0)
            result = subprocess.run([*_ssh_base(cfg), _remote_python(script, remote_path, str(info.st_size), digest.hexdigest())],
                                    stdin=source, capture_output=True, timeout=60, check=False)
        return CmdResult(result.returncode == 0, "", "" if result.returncode == 0 else
                         "protocol upload refused or failed; existing destination preserved",
                         result.returncode, int((time.monotonic() - started) * 1000))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return CmdResult(False, "", "protocol upload refused or failed; existing destination preserved",
                         -3, int((time.monotonic() - started) * 1000))


# Isolated remote Python is required for portable POSIX exclusive creation.
# There is no shell/SCP fallback: missing primitives fail closed. Parent
# directories are held by descriptors and never traversed through symlinks.
_REMOTE_SAFE_PARENT = """
import hashlib, os, stat, sys
def safe_parent(path):
    pieces = path.split('/')
    if not pieces[-1] or '..' in pieces or '\\x00' in path:
        raise ValueError('invalid protocol path')
    parent = os.open('/' if path.startswith('/') else '.', os.O_RDONLY | os.O_DIRECTORY)
    for piece in pieces[:-1]:
        if piece in ('', '.'):
            continue
        child = os.open(piece, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        os.close(parent)
        parent = child
    if pieces[-1] == '.':
        raise ValueError('invalid protocol filename')
    return parent, pieces[-1]
"""


def _remote_python(script: str, *paths: str) -> str:
    return shlex.join(["python3", "-I", "-S", "-c", script, *paths])


def _protocol_result(result: CmdResult, error: str) -> CmdResult:
    return CmdResult(result.ok, "", "" if result.ok else error, result.exit_code, result.duration_ms)


def rsync_to_local(cfg: "Config", remote_path: str, local_path: str, exclude: list[str]) -> CmdResult:
    """Pull into a fresh snapshot, never delete or overwrite an existing tree."""
    return _pull_to_fresh_mirror(cfg, remote_path, local_path, exclude, _rsync_into_fresh)


def _rsync_into_fresh(cfg: "Config", remote_path: str, local_path: str, exclude: list[str]) -> CmdResult:
    # Проверяем что rsync есть локально
    local_rsync = _run(["which", "rsync"], timeout=5)
    if not local_rsync.ok:
        return _tar_into_fresh(cfg, remote_path, local_path, exclude)

    # Пробуем rsync
    excludes = []
    for ex in exclude:
        excludes.extend(["--exclude", ex])
    ssh_opt = shlex.join(["ssh", "-p", str(cfg.ssh_port), "-i", cfg.ssh_key, *_ssh_options(cfg)])
    cmd = [
        "rsync", "-az", "--ignore-existing",
        "-e", ssh_opt,
        *excludes,
        f"{cfg.ssh_host}:{remote_path.rstrip('/')}/",
        f"{local_path.rstrip('/')}/",
    ]
    r = _run(cmd, timeout=300)
    if r.ok:
        return _sync_result(r)

    # The fallback must preserve source-side filtering.
    if "rsync: command not found" in r.stderr or "rsync: not found" in r.stderr:
        return _tar_into_fresh(cfg, remote_path, local_path, exclude)
    return _sync_result(r)


def rsync_to_remote(cfg: "Config", local_path: str, remote_path: str, exclude: list[str]) -> CmdResult:
    """Source export is disabled: a request cannot overwrite remote inputs."""
    return _push_policy_error()


def _push_policy_error() -> CmdResult:
    return CmdResult(False, "", "source push disabled by file-preservation policy; use pull or none", -3, 0)


def _sync_result(result: CmdResult) -> CmdResult:
    """Transport diagnostics never echo remote output or source filenames."""
    return CmdResult(result.ok, "", "" if result.ok else "source sync failed", result.exit_code, result.duration_ms)


def _source_policy_error() -> CmdResult:
    return CmdResult(False, "", "source sync safety check failed: invalid secret boundary, linked or special files", -3, 0)


def _mirror_policy_error() -> CmdResult:
    return CmdResult(False, "", "refusing to replace mirror: existing files are not watcher-owned or ownership changed; use a separate empty mirror", -3, 0)


def _directory_identity(root: Path):
    try:
        info = root.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("mirror is not an unlinked directory")
    return [info.st_dev, info.st_ino]


def _mirror_ledger(root: Path) -> Path:
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:24]
    return root.parent / (".harness-mirror-" + digest + ".json")


def _mirror_inventory(root: Path) -> str:
    """Metadata-only ownership proof: locally added/changed files revoke it."""
    entries = []

    def fail(error):
        raise error

    for current, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        for name in sorted([*dirs, *files]):
            path = Path(current) / name
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                raise ValueError("mirror contains linked or special files")
            entries.append([str(path.relative_to(root)), info.st_dev, info.st_ino,
                            info.st_mode, info.st_size, info.st_mtime_ns])
    return hashlib.sha256(json.dumps(sorted(entries), separators=(",", ":")).encode()).hexdigest()


def _read_mirror_ledger(ledger: Path):
    try:
        info = ledger.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
        raise ValueError("invalid ownership ledger")
    fd = os.open(ledger, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("ownership ledger changed")
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("schema") != "harness-watcher-mirror-v1":
        raise ValueError("unrecognized ownership ledger")
    return data


def _write_mirror_ledger(root: Path, ledger: Path):
    data = {"schema": "harness-watcher-mirror-v1", "root": str(root),
            "identity": _directory_identity(root), "inventory": _mirror_inventory(root)}
    # The sidecar is outside the repository granted to request commands.
    # Exclusive temporary creation avoids following a pre-existing alias.
    fd, temporary = tempfile.mkstemp(prefix=".harness-mirror-ledger-", dir=root.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, ledger)


def _pull_to_fresh_mirror(cfg, remote_path: str, local_path: str, exclude: list[str], transfer) -> CmdResult:
    """Keep every old tree; promote only a completed watcher-created snapshot.

    A sidecar inode record allows subsequent pulls at a stable repository path.
    Unowned nonempty directories are never adopted, moved or deleted. Old owned
    snapshots and failed staging trees are retained for owner-controlled cleanup.
    """
    root = Path(local_path).absolute()
    try:
        if root == root.parent or root.resolve() != root:
            return _mirror_policy_error()
        exclude = effective_excludes(cfg, exclude, root=root)
        root.parent.mkdir(parents=True, exist_ok=True)
        if root.parent.resolve() != root.parent:
            return _mirror_policy_error()
        identity = _directory_identity(root)
        ledger = _mirror_ledger(root)
        record = _read_mirror_ledger(ledger)
        inventory = _mirror_inventory(root) if identity is not None else None
        owned = (record is not None and record.get("root") == str(root)
                 and record.get("identity") == identity and record.get("inventory") == inventory)
        if identity is not None and not owned and any(root.iterdir()):
            return _mirror_policy_error()
        if record is not None and not owned:
            return _mirror_policy_error()
    except (OSError, ValueError, RuntimeError):
        return _mirror_policy_error()

    safe = _remote_source_preflight(cfg, remote_path, exclude)
    if not safe.ok:
        return safe
    try:
        staging = Path(tempfile.mkdtemp(prefix=".harness-incoming-", dir=root.parent))
        result = transfer(cfg, remote_path, str(staging), exclude)
        if not result.ok:
            return result
        # The transport may not smuggle links or special files into the mirror.
        safe = _local_source_preflight(str(staging), [])
        if not safe.ok:
            return safe
        if _directory_identity(root) != identity or _read_mirror_ledger(ledger) != record:
            return _mirror_policy_error()
        if identity is not None and _mirror_inventory(root) != inventory:
            return _mirror_policy_error()
        if identity is not None and not owned and any(root.iterdir()):
            return _mirror_policy_error()
        if identity is not None:
            archive = Path(tempfile.mkdtemp(prefix=".harness-retained-", dir=root.parent))
            root.rename(archive / "mirror")
        # Neither source input files nor prior snapshots are deleted. If an
        # unexpected directory appears here, refuse rather than replace it.
        if root.exists() or root.is_symlink():
            return _mirror_policy_error()
        staging.rename(root)
        _write_mirror_ledger(root, ledger)
        return result
    except (OSError, ValueError, RuntimeError):
        return CmdResult(False, "", "source sync failed; existing and staged snapshots retained", -3, 0)


def _local_source_preflight(local_path: str, exclude: list[str]) -> CmdResult:
    """Inspect metadata only; never open linked aliases of excluded secrets."""
    root = Path(local_path)
    try:
        if root.is_symlink() or not root.is_dir():
            return _source_policy_error()
        def fail(error):
            raise error

        for current, dirs, files in os.walk(root, followlinks=False, onerror=fail):
            kept = []
            for name in [*dirs, *files]:
                path = Path(current) / name
                if matches_excludes(path.relative_to(root), exclude):
                    continue
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    kept.append(name)
                elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    return _source_policy_error()
            dirs[:] = kept
    except OSError:
        return _source_policy_error()
    return CmdResult(True, "", "", 0, 0)


def _source_preflight_command(exclude: list[str]) -> str:
    # POSIX find -exec ... {} + propagates a failed utility exit status. Do not
    # print paths: a source filename may itself contain confidential data.
    clauses = []
    for raw in exclude:
        pattern = raw.strip("/")
        if pattern:
            clauses.extend(["-name " + _quote(pattern), "-path " + _quote("./" + pattern),
                            "-path " + _quote("*/" + pattern)])
    prune = "\\( " + " -o ".join(clauses) + " \\) -prune -o " if clauses else ""
    unsafe = "\\( -type l -o \\( -type f -links +1 \\) -o \\( ! -type f ! -type d \\) \\)"
    return "find . " + prune + unsafe + " -exec false {} + >/dev/null 2>&1"


def _remote_source_preflight(cfg: "Config", remote_path: str, exclude: list[str]) -> CmdResult:
    command = f"test ! -L {_quote(remote_path)} && cd {_quote(remote_path)} && {_source_preflight_command(exclude)}"
    result = _run([*_ssh_base(cfg), command], timeout=60)
    return CmdResult(True, "", "", 0, result.duration_ms) if result.ok else _source_policy_error()


def _parent(path: str) -> str:
    """Возвращает родительскую папку для unix-пути."""
    p = path.rstrip("/")
    if "/" not in p:
        return "."
    return p.rsplit("/", 1)[0] or "/"


def _quote(path: str) -> str:
    """Quote one literal shell argument, including apostrophes in paths."""
    return shlex.quote(path)


def tar_sync_from_remote(cfg: "Config", remote_path: str, local_path: str, exclude: list[str]) -> CmdResult:
    """Filtered tar pull with non-destructive snapshot publication."""
    return _pull_to_fresh_mirror(cfg, remote_path, local_path, exclude, _tar_into_fresh)


def _tar_into_fresh(cfg: "Config", remote_path: str, local_path: str, exclude: list[str]) -> CmdResult:
    """Extract into the newly created staging directory only."""

    # Формируем exclude-флаги для tar
    exclude_flags = " ".join(f"--exclude={_quote(ex)}" for ex in exclude)

    # Удалённая команда: cd → tar
    remote_cmd = f"cd {_quote(remote_path)} && tar czf - {exclude_flags} ."

    # Пайплайн: ssh remote_cmd | tar xzf - -C local_path
    started = time.monotonic()
    try:
        ssh_proc = subprocess.Popen(
            [*_ssh_base(cfg), remote_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        tar_proc = subprocess.Popen(
            ["tar", "xzf", "-", "--keep-old-files", "-C", local_path],
            stdin=ssh_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Закрываем stdout у ssh чтобы tar получил SIGPIPE если ssh умрёт
        if ssh_proc.stdout:
            ssh_proc.stdout.close()
        tar_out, tar_err = tar_proc.communicate(timeout=600)
        ssh_err = ssh_proc.stderr.read() if ssh_proc.stderr else b""
        ssh_proc.wait(timeout=10)

        dur = int((time.monotonic() - started) * 1000)
        ok = (tar_proc.returncode == 0 and ssh_proc.returncode == 0)
        return CmdResult(
            ok=ok,
            stdout="",
            stderr="" if ok else "source sync failed",
            exit_code=tar_proc.returncode if tar_proc.returncode != 0 else ssh_proc.returncode,
            duration_ms=dur,
        )
    except subprocess.TimeoutExpired:
        return CmdResult(False, "", "tar sync timeout (>600s)", -1, 600000)
    except Exception:
        return CmdResult(False, "", "source sync failed", -2, 0)


def tar_sync_to_remote(cfg: "Config", local_path: str, remote_path: str, exclude: list[str]) -> CmdResult:
    """No tar fallback may bypass the source-export prohibition."""
    return _push_policy_error()
