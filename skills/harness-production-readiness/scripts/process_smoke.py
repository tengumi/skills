"""Ограниченная проверка локального процесса; не запуск службы и не сетевая изоляция."""

from __future__ import annotations

import argparse
import errno
import http.client
import ipaddress
import json
import math
import os
import select
import signal
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Probe:
    url: str
    expected_status: int = 200


@dataclass(frozen=True)
class ShutdownPolicy:
    # Политика обязательна для конкретного процесса; SIGTERM или код 0 не принимаются неявно.
    exit_codes: tuple[int, ...]
    stdout_markers: tuple[str, ...] = ()
    forbidden_stdout_markers: tuple[str, ...] = ()


def _endpoint(probe: Probe) -> tuple[str, int, str]:
    url = urlsplit(probe.url)
    address = ipaddress.ip_address(url.hostname or "")
    if (
        url.scheme != "http" or not address.is_loopback or url.port is None
        or url.username is not None or url.password is not None or url.query or url.fragment
        or any(ord(char) < 32 or ord(char) == 127 for char in probe.url)
        or len(probe.url) > 2048 or not 100 <= probe.expected_status <= 599
    ):
        raise ValueError("invalid_loopback_probe")
    return str(address), url.port, url.path or "/"


def _probe(endpoint: tuple[str, int, str], status: int, timeout: float) -> bool:
    # Без DNS-имён, прокси, перенаправлений, тела запроса и записи тела ответа.
    connection = http.client.HTTPConnection(endpoint[0], endpoint[1], timeout=timeout)
    try:
        connection.request("GET", endpoint[2])
        response = connection.getresponse()
        return response.status == status
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def _port_closed(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return False
    except OSError as error:
        # Таймаут и отказ в доступе означают неопределённость, а не закрытый порт.
        return error.errno == errno.ECONNREFUSED


class _MarkerReader:
    """Храним только признаки маркеров; весь вывод, включая запуск, отбрасываем."""

    def __init__(self, stream, policy: ShutdownPolicy):
        self.stream = stream
        self.required = tuple(marker.encode() for marker in policy.stdout_markers)
        self.forbidden = tuple(marker.encode() for marker in policy.forbidden_stdout_markers)
        self.found: set[int] = set()
        self.bad = False
        self.armed = threading.Event()
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.tail = b""
        os.set_blocking(stream.fileno(), False)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def arm(self) -> None:
        # Отбрасываем и буферизованный вывод запуска, а не только уже обработанный.
        with self.lock:
            for _ in range(256):
                try:
                    if not os.read(self.stream.fileno(), 4096):
                        self.bad = True
                        break
                except BlockingIOError:
                    break
            else:
                self.bad = True  # Never wait forever for a noisy startup stream.
            self.tail = b""
            self.armed.set()

    def _read(self) -> None:
        max_length = max((len(marker) for marker in (*self.required, *self.forbidden)), default=1)
        try:
            while not self.closed.is_set():
                if not select.select([self.stream.fileno()], [], [], 0.05)[0]:
                    continue
                with self.lock:
                    try:
                        chunk = os.read(self.stream.fileno(), 4096)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        break
                    if not self.armed.is_set():
                        continue
                    content = self.tail + chunk
                    self.found.update(index for index, marker in enumerate(self.required) if marker in content)
                    self.bad = self.bad or any(marker in content for marker in self.forbidden)
                    self.tail = content[-(max_length - 1):] if max_length > 1 else b""
        except (OSError, ValueError):
            self.bad = True

    def finish(self) -> bool:
        self.thread.join(timeout=1)
        if self.thread.is_alive():
            self.closed.set()
            self.stream.close()
            return False
        self.stream.close()
        return not self.bad and len(self.found) == len(self.required)


def _group_exists(process: subprocess.Popen) -> bool:
    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Отказ в доступе не доказывает отсутствие процесса; повторяем в пределах срока.
        return True


def _signal_owned(process: subprocess.Popen, sig: int) -> None:
    try:
        # Сессию и группу создал Popen; другие PID не ищем и сигналы им не отправляем.
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Ограничения среды могут запретить сигнал группе. Проверяем прямой дочерний процесс;
        # неизвестное состояние группы по-прежнему не проходит проверку завершения.
        if process.poll() is None:
            try:
                process.send_signal(sig)
            except (ProcessLookupError, PermissionError):
                pass


def _stop_owned(process: subprocess.Popen, timeout: float) -> dict:
    stopped_before_request = process.poll() is not None
    _signal_owned(process, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process.poll()  # Reap our direct child before checking its process group.
        if not _group_exists(process):
            break
        time.sleep(0.02)
    forced = _group_exists(process)
    if forced:
        _signal_owned(process, signal.SIGKILL)
    try:
        code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        code = None
    return {
        "exit_code": code, "forced_kill": forced,
        "stopped_before_request": stopped_before_request,
        "owned_group_stopped": not _group_exists(process),
    }


def _validate(argv, cwd, probes, policy, startup_timeout, stop_timeout, poll_interval):
    if os.name != "posix":
        raise ValueError("posix_required")
    if (
        not isinstance(argv, (list, tuple)) or not argv
        or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
        or not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file()
        or not Path(cwd).is_dir() or not probes
    ):
        raise ValueError("invalid_command_or_cwd")
    if any(not math.isfinite(value) or not 0 < value <= 300 for value in (startup_timeout, stop_timeout, poll_interval)):
        raise ValueError("invalid_timeout")
    if not policy.exit_codes or any(type(code) is not int for code in policy.exit_codes):
        raise ValueError("explicit_exit_policy_required")
    markers = (*policy.stdout_markers, *policy.forbidden_stdout_markers)
    if len(markers) > 32 or any(not isinstance(marker, str) or not marker or len(marker.encode()) > 256 for marker in markers):
        raise ValueError("invalid_markers")
    return [_endpoint(probe) for probe in probes]


def run_smoke(
    argv: list[str], *, cwd: Path, probes: tuple[Probe, ...], shutdown_policy: ShutdownPolicy,
    startup_timeout: float = 10, stop_timeout: float = 10, poll_interval: float = 0.05,
) -> dict:
    """Запускаем доверенный явный argv в указанном cwd без наследования окружения.

    Останавливаем только собственную новую группу POSIX-процессов. Команда не должна
    уходить в фон или покидать группу; её сеть должна быть настроена на локальный адрес.
    Утилита ограничивает свои проверочные запросы, но не произвольный дочерний исполняемый файл.
    """
    result = {"success": False, "probes_passed": False, "errors": []}
    try:
        endpoints = _validate(argv, cwd, probes, shutdown_policy, startup_timeout, stop_timeout, poll_interval)
    except (ValueError, TypeError, OSError, AttributeError):
        result["errors"].append({"code": "invalid_configuration"})
        return result
    ports = sorted({endpoint[:2] for endpoint in endpoints})
    if not all(_port_closed(*port, timeout=0.2) for port in ports):
        result["errors"].append({"code": "probe_port_already_open_or_unknown"})
        return result
    process, reader = None, None
    try:
        with_markers = bool(shutdown_policy.stdout_markers or shutdown_policy.forbidden_stdout_markers)
        process = subprocess.Popen(
            argv, cwd=cwd, env={}, shell=False, start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if with_markers else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if with_markers:
            reader = _MarkerReader(process.stdout, shutdown_policy)
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                result["errors"].append({"code": "process_exited_during_startup"})
                break
            remaining = max(0.001, deadline - time.monotonic())
            if all(_probe(endpoint, probe.expected_status, min(0.2, remaining / len(probes))) for endpoint, probe in zip(endpoints, probes)):
                result["probes_passed"] = True
                break
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        if not result["probes_passed"] and not result["errors"]:
            result["errors"].append({"code": "startup_deadline_exceeded"})
    except (OSError, ValueError, RuntimeError):
        result["errors"].append({"code": "process_check_failed"})
    finally:
        if process is not None:
            if reader is not None:
                try:
                    reader.arm()
                except (OSError, ValueError):
                    reader.bad = True
            result["shutdown"] = _stop_owned(process, stop_timeout)
            markers_passed = reader.finish() if reader is not None else True
            result["shutdown"]["stdout_markers_passed"] = markers_passed
            result["shutdown"]["policy_passed"] = (
                result["shutdown"]["exit_code"] in shutdown_policy.exit_codes
                and not result["shutdown"]["forced_kill"]
                and not result["shutdown"]["stopped_before_request"]
                and result["shutdown"]["owned_group_stopped"] and markers_passed
            )
            result["ports_closed"] = all(_port_closed(*port, timeout=0.2) for port in ports)
            if not result["shutdown"]["policy_passed"]:
                result["errors"].append({"code": "shutdown_policy_failed"})
            if not result["ports_closed"]:
                result["errors"].append({"code": "probe_port_not_closed"})
    result["success"] = result["probes_passed"] and not result["errors"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", type=Path, help="Явно заданный рабочий каталог; иначе используется одноразовый временный каталог")
    parser.add_argument("--health-url", required=True)
    parser.add_argument("--ready-url", required=True)
    parser.add_argument("--success-exit-code", type=int, action="append", required=True)
    parser.add_argument("--shutdown-stdout-marker", action="append", default=[])
    parser.add_argument("--forbidden-stdout-marker", action="append", default=[])
    parser.add_argument("--startup-timeout", type=float, default=10)
    parser.add_argument("--stop-timeout", type=float, default=10)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    with tempfile.TemporaryDirectory(prefix="harness-smoke-") as directory:
        cwd = args.cwd if args.cwd is not None else Path(directory)
        argv = [arg.replace("{workdir}", str(cwd.resolve())) for arg in argv]
        result = run_smoke(
            argv, cwd=cwd, probes=(Probe(args.health_url), Probe(args.ready_url)),
            shutdown_policy=ShutdownPolicy(tuple(args.success_exit_code), tuple(args.shutdown_stdout_marker), tuple(args.forbidden_stdout_marker)),
            startup_timeout=args.startup_timeout, stop_timeout=args.stop_timeout,
        )
    print(json.dumps(result, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
