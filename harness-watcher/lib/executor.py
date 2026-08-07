"""Локальное выполнение команд на ноутбуке.

Получает exec-request (распарсенный JSON), выполняет команды последовательно
в local_repo_root, возвращает результат каждой команды.

Если stop_on_failure=true — после первой не-нулевой команды останавливается.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.config import Config


@dataclass
class CommandResult:
    cmd: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


@dataclass
class ExecResult:
    request_id: str
    task_id: str | None
    started_at: str
    completed_at: str
    duration_ms: int
    overall_status: str  # success | failure | timeout | error
    results: list[CommandResult] = field(default_factory=list)
    error: str | None = None  # если overall_status=error — что не так


def execute_request(cfg: "Config", request: dict, on_progress=None) -> ExecResult:
    """Выполнить exec-request локально.

    request — словарь из распарсенного JSON-файла exec-request.
    Поля которые читаем: request_id, task_id, commands (list of {cmd, cwd}),
    timeout_seconds, stop_on_failure.

    on_progress — optional callback(event: str, **fields) для realtime-прогресса.
    Если None — выполнение тихое. События:
      - cmd_start: cmd, idx, total, cwd
      - cmd_output: line (одна строка stdout/stderr команды)
      - cmd_done: cmd, idx, total, exit_code, duration_ms
    """
    if on_progress is None:
        on_progress = lambda *a, **kw: None  # noop
    started = time.monotonic()
    started_iso = _now()

    request_id = request.get("request_id", "unknown")
    task_id = request.get("task_id")
    commands = request.get("commands") or []
    timeout = int(request.get("timeout_seconds", cfg.default_timeout_seconds))
    stop_on_failure = bool(request.get("stop_on_failure", True))

    results: list[CommandResult] = []
    overall_status = "success"
    error_message: str | None = None

    if not commands:
        return ExecResult(
            request_id=request_id,
            task_id=task_id,
            started_at=started_iso,
            completed_at=_now(),
            duration_ms=0,
            overall_status="error",
            results=[],
            error="no commands to execute",
        )

    # Бюджет времени на всю сессию
    remaining = timeout

    for idx, cmd_spec in enumerate(commands, start=1):
        cmd_str = cmd_spec.get("cmd")
        cwd_rel = cmd_spec.get("cwd", ".")
        if not cmd_str:
            continue

        # Абсолютный cwd внутри local_repo_root
        cwd_abs = (cfg.local_repo_root / cwd_rel).resolve()
        # Защита: cwd должен оставаться внутри local_repo_root
        try:
            cwd_abs.relative_to(cfg.local_repo_root.resolve())
        except ValueError:
            results.append(CommandResult(
                cmd=cmd_str, cwd=cwd_rel,
                exit_code=-3,
                stdout="", stderr=f"cwd '{cwd_rel}' escapes local_repo_root",
                duration_ms=0,
            ))
            overall_status = "error"
            error_message = "cwd escape attempt"
            break

        if not cwd_abs.exists():
            cwd_abs.mkdir(parents=True, exist_ok=True)

        cmd_started = time.monotonic()
        cmd_timeout = min(remaining, cfg.default_timeout_seconds) if remaining > 0 else 1

        if cfg.pre_exec_hook:
            full_cmd = f"set -e\n{cfg.pre_exec_hook}\n{cmd_str}"
        else:
            full_cmd = cmd_str

        on_progress("cmd_start", cmd=cmd_str, idx=idx, total=len(commands), cwd=cwd_rel)

        cmd_result = _run_streaming(
            full_cmd=full_cmd,
            cwd=str(cwd_abs),
            cmd_str=cmd_str,
            cwd_rel=cwd_rel,
            timeout=cmd_timeout,
            stdout_max=cfg.stdout_max_chars,
            stderr_max=cfg.stderr_max_chars,
            cmd_started=cmd_started,
            on_progress=on_progress,
        )

        if cmd_result.timed_out:
            overall_status = "timeout"
        elif cmd_result.exit_code == -2:
            overall_status = "error"
            error_message = f"executor exception in cmd {idx}"

        on_progress(
            "cmd_done",
            cmd=cmd_str, idx=idx, total=len(commands),
            exit_code=cmd_result.exit_code,
            duration_ms=cmd_result.duration_ms,
            timed_out=cmd_result.timed_out,
        )

        results.append(cmd_result)
        remaining -= int((time.monotonic() - cmd_started))

        # Останавливаемся при ошибке если stop_on_failure
        if cmd_result.exit_code != 0:
            if overall_status == "success":
                overall_status = "failure"
            if stop_on_failure:
                break
        if remaining <= 0:
            if overall_status == "success":
                overall_status = "timeout"
            break

    return ExecResult(
        request_id=request_id,
        task_id=task_id,
        started_at=started_iso,
        completed_at=_now(),
        duration_ms=int((time.monotonic() - started) * 1000),
        overall_status=overall_status,
        results=results,
        error=error_message,
    )


def _run_streaming(
    full_cmd: str,
    cwd: str,
    cmd_str: str,
    cwd_rel: str,
    timeout: float,
    stdout_max: int,
    stderr_max: int,
    cmd_started: float,
    on_progress,
) -> CommandResult:
    """Запустить команду через Popen, стримить stdout/stderr построчно.

    Каждую строку отдаём в on_progress("cmd_output", line=..., stream="stdout|stderr").
    Накапливаем для финального CommandResult.
    Контролируем timeout — если превышен, kill процесса.
    """
    import threading

    stdout_buf: list[str] = []
    stderr_buf: list[str] = []

    try:
        proc = subprocess.Popen(
            ["bash", "-lc", full_cmd],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
            # A command may start workers or other children.  Give the whole
            # command tree its own process group so timeout cleanup cannot
            # leave descendants running after the report says "timeout".
            start_new_session=True,
        )
    except Exception as e:
        return CommandResult(
            cmd=cmd_str, cwd=cwd_rel,
            exit_code=-2,
            stdout="", stderr=f"{type(e).__name__}: {e}",
            duration_ms=int((time.monotonic() - cmd_started) * 1000),
        )

    def reader(stream, buf, stream_name):
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                buf.append(line)
                on_progress("cmd_output", line=line.rstrip("\n"), stream=stream_name)
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    t_out = threading.Thread(target=reader, args=(proc.stdout, stdout_buf, "stdout"), daemon=True)
    t_err = threading.Thread(target=reader, args=(proc.stderr, stderr_buf, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        # SIGTERM/SIGKILL are sent to the process group, not only to the
        # outer `bash -lc`.  Otherwise a timed-out test can leave a server,
        # worker or subprocess alive on the workstation.
        _terminate_process_group(proc)

    # ждём readers ещё пару секунд чтобы они подобрали остатки
    t_out.join(timeout=2)
    t_err.join(timeout=2)

    cmd_dur = int((time.monotonic() - cmd_started) * 1000)
    stdout = "".join(stdout_buf)
    stderr = "".join(stderr_buf)
    if timed_out:
        stderr += f"\n[command timed out after {int(timeout)}s]"

    return CommandResult(
        cmd=cmd_str,
        cwd=cwd_rel,
        exit_code=(-1 if timed_out else (proc.returncode if proc.returncode is not None else -2)),
        stdout=_truncate(stdout, stdout_max),
        stderr=_truncate(stderr, stderr_max),
        duration_ms=cmd_dur,
        timed_out=timed_out,
    )


def _terminate_process_group(proc: subprocess.Popen, grace_seconds: float = 5.0) -> None:
    """Terminate a command and all of its descendants created in the group."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except (AttributeError, PermissionError, OSError):
        # Defensive fallback for an unusual executor platform.  The watcher
        # normally runs on POSIX because it requires bash/ssh/tar.
        try:
            proc.terminate()
        except OSError:
            return

    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass

    # The group leader may have exited while a child is still alive.  Always
    # attempt the group SIGKILL; ESRCH simply means TERM already cleaned it up.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except (AttributeError, PermissionError, OSError):
        try:
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _truncate(s: str, max_chars: int) -> str:
    """Обрезает строку оставляя конец (для логов важнее последние строки)."""
    if not s:
        return ""
    if len(s) <= max_chars:
        return s
    return f"[...{len(s) - max_chars} chars truncated...]\n" + s[-max_chars:]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def exec_result_to_dict(r: ExecResult, hostname: str = "", version: str = "0.1.0") -> dict:
    """Сериализация ExecResult в dict для записи в exec-report.json."""
    return {
        "request_id": r.request_id,
        "task_id": r.task_id,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "duration_ms": r.duration_ms,
        "overall_status": r.overall_status,
        "error": r.error,
        "results": [
            {
                "cmd": cr.cmd,
                "cwd": cr.cwd,
                "exit_code": cr.exit_code,
                "stdout": cr.stdout,
                "stderr": cr.stderr,
                "duration_ms": cr.duration_ms,
                "timed_out": cr.timed_out,
            }
            for cr in r.results
        ],
        "watcher_version": version,
        "hostname": hostname,
    }
