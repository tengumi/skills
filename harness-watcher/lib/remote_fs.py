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
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    """Переместить файл на удалённой машине."""
    cmd = [*_ssh_base(cfg), f"mv {_quote(src)} {_quote(dst)}"]
    return _run(cmd, timeout=15)


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
    """Загрузить файл с локального executor на удалённую машину."""
    remote = f"{cfg.ssh_host}:{remote_path}"
    cmd = [*_scp_base(cfg), local_path, remote]
    return _run(cmd, timeout=60)


def rsync_to_local(cfg: "Config", remote_path: str, local_path: str, exclude: list[str]) -> CmdResult:
    """Синхронизировать с удалённой машины на локальный executor.

    Сначала пробует rsync (если есть на ОБЕИХ сторонах).
    Если rsync на удалённой машине недоступен — fallback на scp -r (без exclude фильтрации
    на стороне сервера; локально потом можно почистить).
    """
    # Проверяем что rsync есть локально
    local_rsync = _run(["which", "rsync"], timeout=5)
    if not local_rsync.ok:
        return _scp_fallback_from_remote(cfg, remote_path, local_path)

    # Пробуем rsync
    excludes = []
    for ex in exclude:
        excludes.extend(["--exclude", ex])
    ssh_opt = shlex.join(["ssh", "-p", str(cfg.ssh_port), "-i", cfg.ssh_key, *_ssh_options(cfg)])
    cmd = [
        "rsync", "-az", "--delete",
        "-e", ssh_opt,
        *excludes,
        f"{cfg.ssh_host}:{remote_path.rstrip('/')}/",
        f"{local_path.rstrip('/')}/",
    ]
    r = _run(cmd, timeout=300)
    if r.ok:
        return r

    # Если rsync упал с "command not found" на сервере — fallback на scp
    if "rsync: command not found" in r.stderr or "rsync: not found" in r.stderr:
        return _scp_fallback_from_remote(cfg, remote_path, local_path)
    return r


def rsync_to_remote(cfg: "Config", local_path: str, remote_path: str, exclude: list[str]) -> CmdResult:
    """Синхронизировать с локального executor на удалённую машину с fallback на scp -r."""
    local_rsync = _run(["which", "rsync"], timeout=5)
    if not local_rsync.ok:
        return _scp_fallback_to_remote(cfg, local_path, remote_path)

    excludes = []
    for ex in exclude:
        excludes.extend(["--exclude", ex])
    ssh_opt = shlex.join(["ssh", "-p", str(cfg.ssh_port), "-i", cfg.ssh_key, *_ssh_options(cfg)])
    cmd = [
        "rsync", "-az",
        "-e", ssh_opt,
        *excludes,
        f"{local_path.rstrip('/')}/",
        f"{cfg.ssh_host}:{remote_path.rstrip('/')}/",
    ]
    r = _run(cmd, timeout=300)
    if r.ok:
        return r
    if "rsync: command not found" in r.stderr or "rsync: not found" in r.stderr:
        return _scp_fallback_to_remote(cfg, local_path, remote_path)
    return r


def _scp_fallback_from_remote(cfg: "Config", remote_path: str, local_path: str) -> CmdResult:
    """SCP -r вместо rsync: скачивает всю папку. Без exclude — фильтруем локально."""
    # Удаляем локальную папку перед загрузкой чтобы не было мусора
    cleanup = _run(["rm", "-rf", local_path], timeout=30)
    mkdir = _run(["mkdir", "-p", str(_parent(local_path))], timeout=15)
    if not mkdir.ok:
        return mkdir
    remote = f"{cfg.ssh_host}:{remote_path.rstrip('/')}"
    cmd = [*_scp_base(cfg), "-r", remote, local_path.rstrip("/")]
    return _run(cmd, timeout=600)


def _scp_fallback_to_remote(cfg: "Config", local_path: str, remote_path: str) -> CmdResult:
    """SCP -r на удалённую машину. Сначала mkdir родителя, потом копия."""
    parent = _parent(remote_path)
    mk = _run(
        [*_ssh_base(cfg), f"mkdir -p {_quote(parent)}"],
        timeout=15,
    )
    if not mk.ok:
        return mk
    remote = f"{cfg.ssh_host}:{parent}/"
    cmd = [*_scp_base(cfg), "-r", local_path.rstrip("/"), remote]
    return _run(cmd, timeout=600)


def _parent(path: str) -> str:
    """Возвращает родительскую папку для unix-пути."""
    p = path.rstrip("/")
    if "/" not in p:
        return "."
    return p.rsplit("/", 1)[0] or "/"


def _quote(path: str) -> str:
    """Минимальное экранирование для bash."""
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./=:")
    if all(c in safe for c in path):
        return path
    return "'" + path.replace("'", "'\''") + "'"


def tar_sync_from_remote(cfg: "Config", remote_path: str, local_path: str, exclude: list[str]) -> CmdResult:
    """Синхронизировать с удалённой машины локально через tar over SSH.

    Альтернатива rsync — работает без rsync на удалённой стороне.
    Запускает 'tar czf - --exclude=... .' на удалённой машине, пайпит через ssh,
    локально 'tar xzf -' с очисткой целевой папки перед распаковкой.

    Поддерживает excludes (фильтрация на стороне источника).
    """
    # Очищаем целевую папку
    import shutil
    from pathlib import Path as _Path
    local_p = _Path(local_path)
    if local_p.exists():
        try:
            shutil.rmtree(local_p)
        except OSError as e:
            return CmdResult(False, "", f"cannot clean {local_path}: {e}", -1, 0)
    local_p.mkdir(parents=True, exist_ok=True)

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
            ["tar", "xzf", "-", "-C", local_path],
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
            stdout=tar_out.decode("utf-8", errors="replace"),
            stderr=(ssh_err.decode("utf-8", errors="replace") + tar_err.decode("utf-8", errors="replace"))[:2000],
            exit_code=tar_proc.returncode if tar_proc.returncode != 0 else ssh_proc.returncode,
            duration_ms=dur,
        )
    except subprocess.TimeoutExpired:
        return CmdResult(False, "", "tar sync timeout (>600s)", -1, 600000)
    except Exception as e:
        return CmdResult(False, "", f"{type(e).__name__}: {e}", -2, 0)


def tar_sync_to_remote(cfg: "Config", local_path: str, remote_path: str, exclude: list[str]) -> CmdResult:
    """Синхронизировать с локального executor на удалённую машину через tar over SSH.

    Обратное направление: локально 'tar czf - --exclude=... .', пайпим в ssh,
    удалённо 'tar xzf -' в remote_path.
    """
    from pathlib import Path as _Path
    if not _Path(local_path).exists():
        return CmdResult(False, "", f"local_path does not exist: {local_path}", -1, 0)

    exclude_flags = []
    for ex in exclude:
        exclude_flags.extend([f"--exclude={ex}"])

    started = time.monotonic()
    try:
        # mkdir удалённой папки
        mk = _run([*_ssh_base(cfg), f"mkdir -p {_quote(remote_path)}"], timeout=15)
        if not mk.ok:
            return mk

        tar_proc = subprocess.Popen(
            ["tar", "czf", "-", *exclude_flags, "-C", local_path, "."],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        remote_cmd = f"cd {_quote(remote_path)} && tar xzf -"
        ssh_proc = subprocess.Popen(
            [*_ssh_base(cfg), remote_cmd],
            stdin=tar_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if tar_proc.stdout:
            tar_proc.stdout.close()
        ssh_out, ssh_err = ssh_proc.communicate(timeout=600)
        tar_err = tar_proc.stderr.read() if tar_proc.stderr else b""
        tar_proc.wait(timeout=10)

        dur = int((time.monotonic() - started) * 1000)
        ok = (ssh_proc.returncode == 0 and tar_proc.returncode == 0)
        return CmdResult(
            ok=ok,
            stdout=ssh_out.decode("utf-8", errors="replace"),
            stderr=(tar_err.decode("utf-8", errors="replace") + ssh_err.decode("utf-8", errors="replace"))[:2000],
            exit_code=ssh_proc.returncode if ssh_proc.returncode != 0 else tar_proc.returncode,
            duration_ms=dur,
        )
    except subprocess.TimeoutExpired:
        return CmdResult(False, "", "tar sync timeout (>600s)", -1, 600000)
    except Exception as e:
        return CmdResult(False, "", f"{type(e).__name__}: {e}", -2, 0)
