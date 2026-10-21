#!/usr/bin/env python3
"""Проверить план, обновить статусы Tasks MCP и взять одну задачу в работу.

Утилита не исполняет команды задач, не сдаёт их и не разрешает внешние вызовы
или выпуск. Схема и сервер Tasks MCP берутся только из явно указанного kit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import selectors
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from artifact_io import ToolError, read_json  # noqa: E402

VALIDATOR = SCRIPTS / "harness_artifacts.py"
SECTIONS = ("current_sprint", "backlog", "discovered_bugs", "tech_debt", "completed_sprint")
LIFECYCLE_FIELDS = {
    "status", "claimed_by", "claimed_at", "attempts", "evidence", "completed_at", "blocker"
}
PROTOCOL = "2025-11-25"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class GuardError(Exception):
    """В вывод попадают только постоянные коды ошибок без содержимого входов."""


@dataclass(frozen=True)
class ClaimRequest:
    repo: Path
    task_id: str
    state_dir: Path
    kit: Path
    plan_id: str | None = None
    require_runtime: bool = False
    require_bundle: bool = False
    timeout: float = 15.0


def _strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def reject(_):
        raise ValueError

    def finite(raw):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError
        return value

    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw, object_pairs_hook=unique, parse_constant=reject, parse_float=finite)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise GuardError("invalid_protocol_json") from None


def _digest(queue):
    return hashlib.sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_plan(request, tasks_path):
    """Использовать общий валидатор, включая явные проверки ответственных задач."""
    command = [
        sys.executable, "-E", "-s", "-B", str(VALIDATOR), "validate-tasks",
        "--tasks", str(tasks_path), "--schema", str(request.kit / "templates/tasks.schema.json"),
    ]
    if request.plan_id is not None:
        command += ["--plan-id", request.plan_id]
    if request.require_runtime:
        command.append("--require-runtime")
    if request.require_bundle:
        command.append("--require-bundle")
    try:
        result = subprocess.run(
            command, cwd=request.kit, env={}, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=request.timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise GuardError("plan_validation_unavailable") from None
    if result.returncode != 0:
        raise GuardError("invalid_plan" if result.returncode == 1 else "plan_validation_unavailable")
    if len(result.stdout) > MAX_RESPONSE_BYTES:
        raise GuardError("invalid_validation_report")
    report = _strict_json(result.stdout)
    if not isinstance(report, dict) or report.get("valid") is not True or report.get("errors") != []:
        raise GuardError("invalid_validation_report")


class TasksClient:
    """Клиент только штатного Tasks MCP с ограниченным ожиданием и размером ответа."""

    def __init__(self, request):
        self.request = request
        self.process = None
        self.sequence = 0
        self.buffer = b""

    def __enter__(self):
        try:
            # Окружение родителя не читается и не копируется. Сервер получает
            # только две явные несекретные настройки, без dotenv и PATH.
            self.process = subprocess.Popen(
                [sys.executable, "-E", "-s", "-B", "-u", str(self.request.kit / "mcp-servers/tasks-mcp/server.py")],
                cwd=self.request.kit,
                env={
                    "HARNESS_QUEUE_STORAGE_MODE": "out_of_band",
                    "HARNESS_TASKS_STATE_DIR": str(self.request.state_dir),
                },
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
            )
            result = self._rpc("initialize", {
                "protocolVersion": PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "harness-route-runner", "version": "1.0"},
            })
            if (
                result.get("protocolVersion") != PROTOCOL
                or not isinstance(result.get("capabilities"), dict)
                or not isinstance(result["capabilities"].get("tools"), dict)
                or not isinstance(result.get("serverInfo"), dict)
                or result["serverInfo"].get("name") != "tasks-mcp"
            ):
                raise GuardError("mcp_handshake_failed")
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            return self
        except (OSError, GuardError):
            self.close()
            raise GuardError("mcp_session_unavailable") from None

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.process is None:
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=1)
        finally:
            if self.process.stdout:
                self.process.stdout.close()

    def _send(self, message):
        try:
            self.process.stdin.write((json.dumps(message) + "\n").encode())
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise GuardError("mcp_transport_failed") from None

    def _line(self):
        deadline = time.monotonic() + self.request.timeout
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise GuardError("mcp_timeout")
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise GuardError("mcp_closed")
                self.buffer += chunk
                if len(self.buffer) > MAX_RESPONSE_BYTES:
                    raise GuardError("mcp_response_too_large")
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line

    def _rpc(self, method, params):
        self.sequence += 1
        self._send({"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params})
        response = _strict_json(self._line())
        if (
            not isinstance(response, dict) or response.get("jsonrpc") != "2.0"
            or type(response.get("id")) is not int or response["id"] != self.sequence
            or "error" in response or not isinstance(response.get("result"), dict)
        ):
            raise GuardError("mcp_response_rejected")
        return response["result"]

    def call(self, name, arguments):
        if name not in {"list_open_tasks", "claim_task"}:
            raise GuardError("unsupported_operation")
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content")
        if (
            result.get("isError", False) is not False or not isinstance(content, list)
            or len(content) != 1 or not isinstance(content[0], dict)
            or content[0].get("type") != "text" or not isinstance(content[0].get("text"), str)
        ):
            raise GuardError("mcp_tool_result_rejected")
        payload = _strict_json(content[0]["text"])
        if not isinstance(payload, dict):
            raise GuardError("mcp_tool_result_rejected")
        return payload


def _fresh_state(queue, exported, task_id):
    if (
        exported.get("status") != "ok" or exported.get("queue_storage_mode") != "out_of_band"
        or not isinstance(exported.get("all_tasks"), list)
    ):
        raise GuardError("invalid_lifecycle_response")
    definitions = {t["id"]: t for section in SECTIONS for t in queue[section]}
    current = {}
    for task in exported["all_tasks"]:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise GuardError("invalid_lifecycle_response")
        identifier = task["id"]
        if identifier not in definitions or identifier in current:
            raise GuardError("lifecycle_definition_mismatch")
        expected = {k: v for k, v in definitions[identifier].items() if k not in LIFECYCLE_FIELDS}
        actual = {k: v for k, v in task.items() if k not in LIFECYCLE_FIELDS | {"_category", "acceptance"}}
        # Сервер может добавить псевдоним acceptance, но не менять определение задачи.
        if "acceptance" in expected:
            actual["acceptance"] = task.get("acceptance")
        if actual != expected or task.get("status") not in {"open", "in_progress", "blocked", "done"}:
            raise GuardError("lifecycle_definition_mismatch")
        current[identifier] = task
    if set(current) != set(definitions):
        raise GuardError("lifecycle_definition_mismatch")
    if current[task_id]["status"] != "open":
        raise GuardError("task_not_open")
    if any(current[dep]["status"] != "done" for dep in definitions[task_id].get("depends_on", [])):
        raise GuardError("dependencies_not_done")


def guarded_claim(request):
    """Остановиться до запуска MCP при неверных входах; не повторять взятие задачи."""
    if (
        not re.fullmatch(r"[A-Z]+-[0-9]+", request.task_id)
        or (request.plan_id is not None and not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", request.plan_id))
        or not math.isfinite(request.timeout) or not 0 < request.timeout <= 60
    ):
        raise GuardError("invalid_arguments")
    if (request.require_runtime or request.require_bundle) and not request.plan_id:
        raise GuardError("plan_id_required_for_explicit_gate_checks")
    # Путь kit задаётся явно: не ищем его по cwd, переменным окружения или имени.
    if not request.kit.is_absolute():
        raise GuardError("absolute_kit_path_required")
    kit = request.kit.resolve(strict=True)
    if not kit.is_dir() or not all((kit / path).is_file() for path in (
        "templates/tasks.schema.json", "mcp-servers/tasks-mcp/server.py"
    )):
        raise GuardError("kit_components_unavailable")
    # Сначала проверяем исходное написание пути безопасным читателем. resolve
    # до этой проверки позволил бы незаметно принять ссылку на секретный файл.
    tasks_path = request.repo.absolute() / "docs/harness/tasks.json"
    queue = read_json(tasks_path)
    repo = request.repo.resolve()
    state_dir = request.state_dir.resolve()
    if state_dir == repo or state_dir.is_relative_to(repo):
        raise GuardError("state_dir_must_be_outside_repository")
    request = ClaimRequest(
        repo=repo, task_id=request.task_id, state_dir=state_dir, kit=kit,
        plan_id=request.plan_id, require_runtime=request.require_runtime,
        require_bundle=request.require_bundle, timeout=request.timeout,
    )
    _validate_plan(request, tasks_path)
    if read_json(tasks_path) != queue:
        raise GuardError("plan_changed_during_validation")
    definitions = {t["id"]: t for section in SECTIONS for t in queue[section]}
    task = definitions.get(request.task_id)
    if task is None or (request.plan_id is not None and task.get("plan_id") != request.plan_id):
        raise GuardError("task_not_in_selected_plan")
    with TasksClient(request) as client:
        exported = client.call("list_open_tasks", {"repo_path": str(repo), "include_all": True})
        _fresh_state(queue, exported, request.task_id)
        if read_json(tasks_path) != queue:
            raise GuardError("plan_changed_before_claim")
        try:
            claimed = client.call("claim_task", {
                "repo_path": str(repo), "task_id": request.task_id,
                "claimed_by": "harness-route-runner",
            })
        except (GuardError, OSError):
            # Ответ может потеряться после записи статуса. Не повторяем вызов
            # и не утверждаем, что изменений не было: статусы надо обновить отдельно.
            raise GuardError("claim_outcome_unknown_refresh_lifecycle") from None
        if claimed.get("status") != "ok":
            raise GuardError("claim_rejected_refresh_lifecycle")
        if (
            claimed.get("queue_storage_mode") != "out_of_band"
            or not isinstance(claimed.get("task"), dict)
            or claimed["task"].get("id") != request.task_id
            or claimed["task"].get("status") != "in_progress"
            or claimed["task"].get("claimed_by") != "harness-route-runner"
        ):
            raise GuardError("claim_outcome_unknown_refresh_lifecycle")
    return {
        "status": "claimed", "task_id": request.task_id,
        "definitions_sha256": _digest(queue), "dependency_state": "fresh_tasks_mcp_response",
        "claim_calls": 1, "release_readiness": "NOT_ASSESSED",
    }


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise GuardError("invalid_arguments")


def main(argv=None):
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--kit", required=True, type=Path,
                            help="Абсолютный путь к полному harness-kit со схемой и Tasks MCP")
        parser.add_argument("--repo", required=True, type=Path)
        parser.add_argument("--task-id", required=True)
        parser.add_argument("--state-dir", required=True, type=Path)
        parser.add_argument("--plan-id")
        parser.add_argument("--require-runtime", action="store_true")
        parser.add_argument("--require-bundle", action="store_true")
        parser.add_argument("--timeout", type=float, default=15.0)
        result = guarded_claim(ClaimRequest(**vars(parser.parse_args(argv))))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (GuardError, ToolError, OSError, ValueError, TypeError, RecursionError) as error:
        code = str(error) if isinstance(error, GuardError) else "invalid_input_or_io_error"
        print(json.dumps({"status": "stopped", "error": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
