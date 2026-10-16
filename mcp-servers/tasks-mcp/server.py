#!/usr/bin/env python3
"""
MCP Server for tasks queue management.

Превращает docs/harness/tasks.json из статичного плана в живую очередь:
- claim_task / submit_task с обязательной evidence-валидацией
- record_attempt / report_blocker для stuck-detection
- Атомарная запись через временный файл + os.replace
- File lock через .lock-файл с retry

По умолчанию lifecycle хранится вне feature checkout. tasks.json остаётся
versioned definition-файлом, а статусы/claims/evidence накладываются из
out-of-band overlay. Режим tracked оставлен только для репозиториев, где
очередь сознательно ведётся отдельным coordination commit/channel.

Все операции работают на конкретной репе — путь передаётся параметром repo_path
в каждом инструменте, чтобы один MCP-сервер обслуживал несколько реп.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------- Constants ----------

TASKS_FILENAME = "docs/harness/tasks.json"
LOCK_FILENAME = "docs/harness/tasks.json.lock"
EXEC_REPORTS_DIR = "docs/harness/exec-reports"
EXEC_REQUESTS_DIR = "docs/harness/exec-requests"
QUEUE_STORAGE_MODE_ENV = "HARNESS_QUEUE_STORAGE_MODE"
STATE_DIR_ENV = "HARNESS_TASKS_STATE_DIR"
DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "harness" / "tasks-mcp"
LOCK_RETRY_COUNT = 10
LOCK_RETRY_DELAY_MS = 100
STUCK_THRESHOLD = 3  # одинаковый error_hash N раз подряд = STOP
SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

VALID_STATUSES = {"open", "in_progress", "blocked", "done"}
VALID_TYPES = {"feat", "fix", "refactor", "debt", "bug"}
VALID_PRIORITIES = {"high", "medium", "low"}
CATEGORY_ORDER = ("current_sprint", "backlog", "discovered_bugs", "tech_debt", "completed_sprint")
VALID_CATEGORIES = set(CATEGORY_ORDER)
LIFECYCLE_FIELDS = (
    "status",
    "claimed_by",
    "claimed_at",
    "attempts",
    "evidence",
    "completed_at",
    "blocker",
)

# Evidence-валидация
SHA_PATTERN = re.compile(r"^[a-f0-9]{7,64}$")
BRANCH_PATTERN = re.compile(r"^feature/[A-Z]+-\d+(-[a-z0-9-]+)?$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


# ---------- File I/O with locking ----------

def _queue_storage_mode() -> str:
    mode = os.getenv(QUEUE_STORAGE_MODE_ENV, "out_of_band").strip().lower()
    if mode not in {"out_of_band", "tracked"}:
        raise ValueError(
            f"{QUEUE_STORAGE_MODE_ENV} must be 'out_of_band' or 'tracked', got: {mode}"
        )
    return mode


def _state_dir() -> Path:
    configured = os.getenv(STATE_DIR_ENV)
    path = Path(configured).expanduser() if configured else DEFAULT_STATE_DIR
    return path.resolve()


def _state_path(repo_path: Path) -> Path:
    resolved_repo = repo_path.resolve()
    state_dir = _state_dir()
    if state_dir == resolved_repo or state_dir.is_relative_to(resolved_repo):
        raise ValueError(
            f"{STATE_DIR_ENV} must be outside the repository in out_of_band mode"
        )
    resolved = str(resolved_repo)
    digest = hashlib.sha256(resolved.encode()).hexdigest()[:20]
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", repo_path.name).strip("-") or "repo"
    return state_dir / f"{safe_name}-{digest}.json"


def _lock_path(repo_path: Path) -> Path:
    if _queue_storage_mode() == "out_of_band":
        return _state_path(repo_path).with_suffix(".lock")
    return repo_path / LOCK_FILENAME


def _acquire_lock(lock_path: Path) -> bool:
    """Простой file lock через создание файла. Возвращает True если получили лок."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(LOCK_RETRY_COUNT):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(LOCK_RETRY_DELAY_MS / 1000)
    return False


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _empty_tasks() -> dict:
    return {
        "version": "1.0",
        "last_updated": _now_iso(),
        **{category: [] for category in CATEGORY_ORDER},
    }


def _read_task_definitions(repo_path: Path) -> dict:
    """Читает versioned task definitions или возвращает пустую схему."""
    tasks_path = repo_path / TASKS_FILENAME
    if not tasks_path.exists():
        return _empty_tasks()
    with open(tasks_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("tasks.json root must be an object")
    for category in CATEGORY_ORDER:
        data.setdefault(category, [])
        if not isinstance(data[category], list):
            raise ValueError(f"tasks.json field '{category}' must be a list")
    _validate_task_definitions(data)
    return data


def _validate_task_definitions(data: dict) -> None:
    """Проверяет минимальную queue-схему и глобальную уникальность id."""
    seen: set[str] = set()
    for category in CATEGORY_ORDER:
        for task in data.get(category, []):
            if not isinstance(task, dict):
                raise ValueError(f"task in category '{category}' must be an object")
            task_id = task.get("id")
            if not isinstance(task_id, str) or not task_id.strip():
                raise ValueError(f"task id in category '{category}' must be a non-empty string")
            if task_id in seen:
                raise ValueError(f"duplicate task id in tasks.json: {task_id}")
            seen.add(task_id)

            status = task.get("status", "open")
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid status for {task_id}: {status}")
            if "type" in task and task["type"] not in VALID_TYPES:
                raise ValueError(f"invalid type for {task_id}: {task['type']}")
            if "priority" in task and task["priority"] not in VALID_PRIORITIES:
                raise ValueError(f"invalid priority for {task_id}: {task['priority']}")


def _read_overlay(repo_path: Path) -> dict:
    state_path = _state_path(repo_path)
    if not state_path.exists():
        return {"version": "1.0", "repo_path": str(repo_path.resolve()), "tasks": {}}
    with open(state_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"invalid tasks-mcp overlay root: {state_path}")
    if not isinstance(data.get("tasks", {}), dict):
        raise ValueError(f"invalid tasks-mcp overlay: {state_path}")
    for task_id, state in data.get("tasks", {}).items():
        if not isinstance(task_id, str) or not isinstance(state, dict):
            raise ValueError(f"invalid task state in tasks-mcp overlay: {state_path}")
        category = state.get("category")
        if category is not None and category not in VALID_CATEGORIES:
            raise ValueError(f"invalid overlay category for {task_id}: {category}")
        status = state.get("status")
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"invalid overlay status for {task_id}: {status}")
        if "attempts" in state and not isinstance(state["attempts"], list):
            raise ValueError(f"invalid overlay attempts for {task_id}: expected list")
    return data


def _definition_index(data: dict) -> dict[str, tuple[dict, str]]:
    index: dict[str, tuple[dict, str]] = {}
    for category in CATEGORY_ORDER:
        for task in data.get(category, []):
            task_id = task.get("id")
            # _read_task_definitions has already validated id and uniqueness.
            index[task_id] = (task, category)
    return index


def _read_tasks(repo_path: Path) -> dict:
    """Читает definitions и накладывает out-of-band lifecycle state."""
    definitions = _read_task_definitions(repo_path)
    if _queue_storage_mode() == "tracked":
        return definitions

    overlay_tasks = _read_overlay(repo_path).get("tasks", {})
    merged = {key: value for key, value in definitions.items() if key not in VALID_CATEGORIES}
    merged.update({category: [] for category in CATEGORY_ORDER})
    seen: set[str] = set()

    for source_category in CATEGORY_ORDER:
        for source_task in definitions.get(source_category, []):
            task = dict(source_task)
            task_id = str(task.get("id", ""))
            if not task_id:
                raise ValueError(f"task without id in category '{source_category}'")
            if task_id in seen:
                raise ValueError(f"duplicate task id in tasks.json: {task_id}")
            seen.add(task_id)

            state = overlay_tasks.get(task_id, {})
            target_category = state.get("category", source_category)
            if target_category not in VALID_CATEGORIES:
                raise ValueError(
                    f"invalid overlay category for {task_id}: {target_category}"
                )
            for field in LIFECYCLE_FIELDS:
                if field not in state:
                    continue
                if state[field] is None:
                    task.pop(field, None)
                else:
                    task[field] = state[field]
            merged[target_category].append(task)
    return merged


def _write_tasks_atomic(repo_path: Path, data: dict) -> None:
    """Пишет tracked queue или атомарный out-of-band lifecycle overlay."""
    if _queue_storage_mode() == "out_of_band":
        definitions = _read_task_definitions(repo_path)
        base_index = _definition_index(definitions)
        overlay_tasks: dict[str, dict] = {}
        seen: set[str] = set()

        for category in CATEGORY_ORDER:
            for task in data.get(category, []):
                task_id = str(task.get("id", ""))
                if not task_id or task_id in seen:
                    raise ValueError(f"missing or duplicate task id while writing overlay: {task_id}")
                seen.add(task_id)
                if task_id not in base_index:
                    raise ValueError(f"task {task_id} is absent from versioned tasks.json")
                base_task, base_category = base_index[task_id]
                state: dict[str, Any] = {}
                if category != base_category:
                    state["category"] = category
                for field in LIFECYCLE_FIELDS:
                    current = task.get(field)
                    baseline = base_task.get(field)
                    if current != baseline:
                        state[field] = current
                if state:
                    overlay_tasks[task_id] = state

        state_path = _state_path(repo_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".json.tmp")
        payload = {
            "version": "1.0",
            "repo_path": str(repo_path.resolve()),
            "updated_at": _now_iso(),
            "tasks": overlay_tasks,
        }
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, state_path)
        return

    tasks_path = repo_path / TASKS_FILENAME
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = tasks_path.with_suffix(".json.tmp")
    data["last_updated"] = _now_iso()
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, tasks_path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- Task lookup helpers ----------

def _find_task(data: dict, task_id: str) -> tuple[dict | None, str | None]:
    """Ищет задачу во всех категориях. Возвращает (task, category)."""
    for category in CATEGORY_ORDER:
        for task in data.get(category, []):
            if task.get("id") == task_id:
                return task, category
    return None, None


def _move_task(data: dict, task_id: str, target_category: str) -> bool:
    """Перемещает задачу в другую категорию. Возвращает True если перемещена."""
    task, source_category = _find_task(data, task_id)
    if task is None or source_category is None:
        return False
    if source_category == target_category:
        return True
    data[source_category] = [t for t in data[source_category] if t.get("id") != task_id]
    data[target_category].append(task)
    return True


# ---------- Tool implementations ----------

def tool_list_open_tasks(repo_path: Path, include_all: bool = False) -> dict:
    """Возвращает open subset; опционально — полное merged lifecycle-состояние."""
    if not isinstance(include_all, bool):
        raise ValueError("include_all must be a boolean")
    data = _read_tasks(repo_path)
    open_tasks = []
    for category in ("current_sprint", "backlog", "discovered_bugs"):
        for task in data.get(category, []):
            status = task.get("status", "open")
            if status == "open":
                open_tasks.append({**_task_for_response(task), "_category": category})
    result = {
        "status": "ok",
        "queue_storage_mode": _queue_storage_mode(),
        "count": len(open_tasks),
        "tasks": open_tasks,
    }
    if include_all:
        all_tasks = []
        by_status = {status: 0 for status in sorted(VALID_STATUSES)}
        by_category = {category: 0 for category in CATEGORY_ORDER}
        for category in CATEGORY_ORDER:
            for task in data.get(category, []):
                all_tasks.append({**_task_for_response(task), "_category": category})
                by_category[category] += 1
                by_status[task.get("status", "open")] += 1
        result["all_tasks"] = all_tasks
        result["summary"] = {
            "total": len(all_tasks),
            "by_status": by_status,
            "by_category": by_category,
        }
    return result


def _task_for_response(task: dict) -> dict:
    """Добавляет runtime alias acceptance, не меняя source schema tasks.json."""
    result = dict(task)
    if "acceptance" not in result and "acceptance_criteria" in result:
        result["acceptance"] = result["acceptance_criteria"]
    return result


def tool_claim_task(repo_path: Path, task_id: str, claimed_by: str = "agent") -> dict:
    """Помечает задачу in_progress, возвращает полный контекст."""
    lock_path = _lock_path(repo_path)
    if not _acquire_lock(lock_path):
        return {"status": "error", "message": "could not acquire lock"}
    try:
        data = _read_tasks(repo_path)
        task, category = _find_task(data, task_id)
        if task is None:
            return {"status": "error", "message": f"task {task_id} not found"}
        if task.get("status") == "in_progress":
            return {"status": "error", "message": f"task {task_id} already in_progress (claimed by {task.get('claimed_by')})"}
        if task.get("status") == "done":
            return {"status": "error", "message": f"task {task_id} already done"}
        task["status"] = "in_progress"
        task["claimed_by"] = claimed_by
        task["claimed_at"] = _now_iso()
        task.setdefault("attempts", [])
        _write_tasks_atomic(repo_path, data)
        return {
            "status": "ok",
            "queue_storage_mode": _queue_storage_mode(),
            "task": _task_for_response(task),
            "category": category,
        }
    finally:
        _release_lock(lock_path)


def tool_submit_task(repo_path: Path, task_id: str, evidence: dict) -> dict:
    """Помечает задачу done. Evidence обязателен и валидируется."""
    # Валидация evidence ДО блокировки — быстро, не нужен лок
    validation_errors = _validate_evidence(evidence)
    if validation_errors:
        return {"status": "reject", "errors": validation_errors}

    lock_path = _lock_path(repo_path)
    if not _acquire_lock(lock_path):
        return {"status": "error", "message": "could not acquire lock"}
    try:
        data = _read_tasks(repo_path)
        task, category = _find_task(data, task_id)
        if task is None:
            return {"status": "error", "message": f"task {task_id} not found"}
        if task.get("status") != "in_progress":
            return {"status": "error", "message": f"task {task_id} not in_progress (current: {task.get('status')})"}
        task["status"] = "done"
        task["evidence"] = evidence
        task["completed_at"] = _now_iso()
        _move_task(data, task_id, "completed_sprint")
        _write_tasks_atomic(repo_path, data)
        return {
            "status": "ok",
            "queue_storage_mode": _queue_storage_mode(),
            "task": _task_for_response(task),
        }
    finally:
        _release_lock(lock_path)


def _validate_evidence(evidence: dict) -> list[str]:
    """Возвращает список ошибок. Пустой = валидно."""
    errors = []
    if not isinstance(evidence, dict):
        return ["evidence must be a dict"]

    commit_sha = evidence.get("commit_sha")
    if not commit_sha:
        errors.append("commit_sha is required")
    elif not SHA_PATTERN.match(str(commit_sha)):
        errors.append(f"commit_sha must be 7-64 hex chars, got: {commit_sha}")

    tests_passed = evidence.get("tests_passed")
    if tests_passed is not True:
        errors.append(f"tests_passed must be true, got: {tests_passed}")

    branch = evidence.get("branch")
    if not branch:
        errors.append("branch is required")
    elif branch in ("main", "master", "develop") or str(branch).startswith("release/"):
        errors.append(f"branch '{branch}' is protected — use feature/TICKET")
    elif not BRANCH_PATTERN.match(str(branch)):
        errors.append(f"branch must match feature/TICKET-NUM[-short-description], got: {branch}")

    artifacts = evidence.get("artifacts")
    if artifacts is not None:
        if not isinstance(artifacts, list) or not all(
            isinstance(path, str) and path.strip() for path in artifacts
        ):
            errors.append("artifacts must be a list of non-empty repo-relative paths")
        else:
            unsafe = [
                path for path in artifacts
                if Path(path).is_absolute() or ".." in Path(path).parts
            ]
            if unsafe:
                errors.append("artifacts paths must stay inside the repository")

    return errors


def tool_record_attempt(repo_path: Path, task_id: str, command: str, exit_code: int, error_output: str = "") -> dict:
    """
    Записывает попытку выполнения команды. Если 3 раза подряд один error_hash —
    возвращает action=stop, остальное — action=continue.
    """
    error_hash = hashlib.sha256(f"{command}|{exit_code}|{error_output[:500]}".encode()).hexdigest()[:12]

    lock_path = _lock_path(repo_path)
    if not _acquire_lock(lock_path):
        return {"status": "error", "message": "could not acquire lock"}
    try:
        data = _read_tasks(repo_path)
        task, _ = _find_task(data, task_id)
        if task is None:
            return {"status": "error", "message": f"task {task_id} not found"}

        attempts = task.setdefault("attempts", [])
        attempts.append({
            "at": _now_iso(),
            "command": command,
            "exit_code": exit_code,
            "error_hash": error_hash,
            "error_preview": error_output[:200],
        })

        # Stuck detection: N последних попыток с одинаковым error_hash и ненулевым exit
        recent = attempts[-STUCK_THRESHOLD:]
        if len(recent) >= STUCK_THRESHOLD:
            same_hash = all(a["error_hash"] == error_hash for a in recent)
            all_failed = all(a["exit_code"] != 0 for a in recent)
            if same_hash and all_failed:
                _write_tasks_atomic(repo_path, data)
                return {
                    "status": "ok",
                    "action": "stop",
                    "reason": f"command failed {STUCK_THRESHOLD} times with identical error",
                    "error_hash": error_hash,
                    "attempts": len(attempts),
                    "guidance": "call report_blocker with this reason and stop trying — escalate to human",
                }

        _write_tasks_atomic(repo_path, data)
        return {"status": "ok", "action": "continue", "attempts": len(attempts)}
    finally:
        _release_lock(lock_path)


def tool_report_blocker(repo_path: Path, task_id: str, reason: str, attempts: int | None = None) -> dict:
    """Помечает задачу blocked, эскалирует человеку."""
    lock_path = _lock_path(repo_path)
    if not _acquire_lock(lock_path):
        return {"status": "error", "message": "could not acquire lock"}
    try:
        data = _read_tasks(repo_path)
        task, _ = _find_task(data, task_id)
        if task is None:
            return {"status": "error", "message": f"task {task_id} not found"}
        task["status"] = "blocked"
        task["blocker"] = {
            "at": _now_iso(),
            "reason": reason,
            "attempts": attempts if attempts is not None else len(task.get("attempts", [])),
        }
        _write_tasks_atomic(repo_path, data)
        return {"status": "ok", "task_id": task_id, "message": "task marked blocked, human needed"}
    finally:
        _release_lock(lock_path)


def tool_wait_for_report(repo_path: Path, request_id: str, timeout_seconds: int = 300) -> dict:
    """Ждёт появления exec-report.json от watcher'а.

    Поллит локальный файл docs/harness/exec-reports/{request_id}.json
    каждые ~500ms. Возвращает содержимое report как только файл появится
    и будет успешно распарсен.

    Если за timeout_seconds report не появился — возвращает status=timeout.
    Это значит либо watcher не работает, либо команда зависла.
    """
    if not REQUEST_ID_PATTERN.fullmatch(request_id):
        return {
            "status": "error",
            "message": "request_id must contain only letters, digits, '.', '_' or '-' (max 128 chars)",
        }
    if timeout_seconds < 0:
        return {"status": "error", "message": "timeout_seconds must be non-negative"}

    report_path = repo_path / EXEC_REPORTS_DIR / f"{request_id}.json"
    request_path = repo_path / EXEC_REQUESTS_DIR / f"{request_id}.json"

    # Проверка что request реально существует — иначе вечно будем ждать
    if not request_path.exists() and not (repo_path / "docs/harness/exec-processed" / f"{request_id}.json").exists():
        return {
            "status": "error",
            "message": f"request {request_id} not found in exec-requests/ or exec-processed/. Did you forget to write it?",
        }

    poll_interval = 0.5  # секунды
    deadline = time.monotonic() + timeout_seconds
    polls = 0

    while time.monotonic() < deadline:
        polls += 1
        if report_path.exists():
            try:
                # Файл может ещё писаться — пробуем распарсить, если не получится — ждём
                with open(report_path, "r", encoding="utf-8") as f:
                    report = json.load(f)
                return {
                    "status": "ok",
                    "request_id": request_id,
                    "polls": polls,
                    "report": report,
                }
            except (json.JSONDecodeError, OSError):
                # Файл в процессе записи — ждём ещё чуть-чуть
                time.sleep(poll_interval)
                continue
        time.sleep(poll_interval)

    return {
        "status": "timeout",
        "request_id": request_id,
        "polls": polls,
        "elapsed_seconds": timeout_seconds,
        "message": (
            f"report not received within {timeout_seconds}s. "
            f"Check that harness-watcher is running on workstation and "
            f"that exec-request was uploaded correctly."
        ),
    }


# ---------- MCP JSON-RPC ----------

TOOLS_SCHEMA = [
    {
        "name": "list_open_tasks",
        "description": "List open task definitions with lifecycle state applied. Set include_all=true to also return the complete merged queue and status/category summary for resume. Returns queue_storage_mode for work-session coordination checks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to repository root"},
                "include_all": {"type": "boolean", "default": False, "description": "Also return all_tasks and summary, including done and blocked lifecycle"},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "claim_task",
        "description": "Claim a task for work. Sets status=in_progress, records claimed_by/claimed_at. Returns full task context including acceptance criteria and files_hint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "task_id": {"type": "string", "description": "Task id like T-001 or S-001"},
                "claimed_by": {"type": "string", "description": "Optional claimer identifier, default 'agent'"},
            },
            "required": ["repo_path", "task_id"],
        },
    },
    {
        "name": "submit_task",
        "description": "Submit completed task with evidence. REJECTS if evidence is invalid. Required: commit_sha, tests_passed=true, and branch feature/TICKET-NUM[-short-description] (for example feature/T-001).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "task_id": {"type": "string"},
                "evidence": {
                    "type": "object",
                    "properties": {
                        "commit_sha": {"type": "string"},
                        "tests_passed": {"type": "boolean"},
                        "branch": {"type": "string"},
                        "lint_passed": {"type": "boolean"},
                        "notes": {"type": "string"},
                        "artifacts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional repo-relative evidence/report paths"
                        },
                    },
                    "required": ["commit_sha", "tests_passed", "branch"],
                },
            },
            "required": ["repo_path", "task_id", "evidence"],
        },
    },
    {
        "name": "record_attempt",
        "description": f"Record a command attempt. If same error repeats {STUCK_THRESHOLD} times in a row, returns action=stop with guidance to call report_blocker. Otherwise returns action=continue.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "task_id": {"type": "string"},
                "command": {"type": "string", "description": "Command that was run, e.g. 'make verify'"},
                "exit_code": {"type": "integer"},
                "error_output": {"type": "string", "description": "Error stderr/stdout (first 500 chars used for hashing)"},
            },
            "required": ["repo_path", "task_id", "command", "exit_code"],
        },
    },
    {
        "name": "report_blocker",
        "description": "Mark task as blocked. Use when stuck-detector says stop, or when task is underspecified, or when external dependency is broken.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "task_id": {"type": "string"},
                "reason": {"type": "string"},
                "attempts": {"type": "integer"},
            },
            "required": ["repo_path", "task_id", "reason"],
        },
    },
    {
        "name": "wait_for_report",
        "description": (
            "Block until exec-report.json from harness-watcher appears for given request_id, "
            "or until timeout. Use after writing an exec-request to docs/harness/exec-requests/. "
            "Polls local file system (no network calls). Returns parsed report content as 'report' field on success. "
            "If timeout — likely watcher is not running or command hung."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "request_id": {"type": "string", "description": "ID used as filename for exec-request and exec-report"},
                "timeout_seconds": {"type": "integer", "description": "Max seconds to wait, default 300"},
            },
            "required": ["repo_path", "request_id"],
        },
    },
]


def handle_request(request: dict) -> dict | None:
    """Синхронный обработчик JSON-RPC. Использован в тестах напрямую.

    Возвращает None для notifications (без id) — их не надо отправлять обратно.
    """
    if not isinstance(request, dict):
        return _err(None, -32600, "invalid request: JSON-RPC message must be an object")

    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})
    if not isinstance(params, dict):
        return _err(req_id, -32602, "params must be an object")

    try:
        # MCP protocol handshake для совместимых stdio-клиентов.
        if method == "initialize":
            requested_version = params.get("protocolVersion")
            negotiated_version = (
                requested_version
                if requested_version in SUPPORTED_PROTOCOL_VERSIONS
                else LATEST_PROTOCOL_VERSION
            )
            return _ok(req_id, {
                "protocolVersion": negotiated_version,
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "tasks-mcp",
                    "version": "0.3.0",
                },
            })

        # Уведомления (notifications) — без id, не требуют ответа
        if method in ("notifications/initialized", "initialized"):
            return None  # notification — нет ответа

        if method == "ping":
            return _ok(req_id, {})

        if method == "tools/list":
            return _ok(req_id, {"tools": TOOLS_SCHEMA})

        if method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            if not isinstance(args, dict):
                return _err(req_id, -32602, "arguments must be an object")
            raw_repo_path = args.get("repo_path")
            if not isinstance(raw_repo_path, str) or not raw_repo_path.strip():
                return _err(req_id, -32602, "repo_path is required and must be a non-empty string")
            repo_path = Path(raw_repo_path).expanduser().resolve()
            if not repo_path.is_dir():
                return _err(req_id, -32602, f"repo_path is not an existing directory: {repo_path}")

            if tool_name == "list_open_tasks":
                include_all = args.get("include_all", False)
                if not isinstance(include_all, bool):
                    return _err(req_id, -32602, "include_all must be a boolean")
                result = tool_list_open_tasks(repo_path, include_all)
            elif tool_name == "claim_task":
                result = tool_claim_task(repo_path, args["task_id"], args.get("claimed_by", "agent"))
            elif tool_name == "submit_task":
                result = tool_submit_task(repo_path, args["task_id"], args["evidence"])
            elif tool_name == "record_attempt":
                result = tool_record_attempt(
                    repo_path,
                    args["task_id"],
                    args["command"],
                    args["exit_code"],
                    args.get("error_output", ""),
                )
            elif tool_name == "report_blocker":
                result = tool_report_blocker(
                    repo_path,
                    args["task_id"],
                    args["reason"],
                    args.get("attempts"),
                )
            elif tool_name == "wait_for_report":
                result = tool_wait_for_report(
                    repo_path,
                    args["request_id"],
                    int(args.get("timeout_seconds", 300)),
                )
            else:
                return _err(req_id, -32601, f"unknown tool: {tool_name}")

            return _ok(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})

        return _err(req_id, -32601, f"method not found: {method}")
    except KeyError as e:
        return _err(req_id, -32602, f"missing required argument: {e}")
    except Exception as e:
        return _err(req_id, -32000, f"{type(e).__name__}: {e}")


def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ---------- stdio loop ----------

async def main() -> None:
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps(_err(None, -32700, f"parse error: {e}")), flush=True)
            continue
        response = handle_request(request)
        # notifications не требуют ответа — handle_request возвращает None
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


def run() -> None:
    """Console-script entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
