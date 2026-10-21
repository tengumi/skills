"""Проверка описаний задач без чтения файлов, загрузки URL и учёта рабочих статусов.

Ограничения полей, режимов и уровней проверки определяет JSON Schema.
Дополнительные проверки касаются связей между корректно описанными задачами.
Диагностика содержит только коды и пути полей, но не значения и не сообщения
jsonschema, которые могут включать все проверяемые данные.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable

SECTIONS = (
    "current_sprint",
    "backlog",
    "discovered_bugs",
    "tech_debt",
    "completed_sprint",
)
FORBIDDEN_EXECUTION_SKILLS = {"harness-lead", "harness-pre-commit-check"}
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def _no_retrieval(uri: str) -> Any:
    """Запретить загрузку любых внешних ресурсов, включая ссылки file:."""
    raise NoSuchResource(ref=uri)


def _path(parts: tuple[Any, ...] | list[Any], allowed_fields: set[str]) -> str:
    result = "$"
    for part in parts:
        if isinstance(part, int) and not isinstance(part, bool):
            result += f"[{part}]"
        elif isinstance(part, str) and part in allowed_fields:
            result += "." + part
        else:
            # Произвольные имена полей сами могут содержать секретные данные.
            result += "['<redacted-field>']"
    return result


def _field_names(schema: Any) -> set[str]:
    """В диагностике допустимы только имена полей, объявленные в схеме задач."""
    result = set(SECTIONS)
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            result.update(key for key in properties if isinstance(key, str))
        definitions = schema.get("$defs")
        if isinstance(definitions, dict):
            task = definitions.get("task")
            if isinstance(task, dict) and isinstance(task.get("properties"), dict):
                result.update(task["properties"])
    return result


def _pointer_exists(schema: Any, ref: str) -> bool:
    current = schema
    for escaped in ref[2:].split("/"):
        part = escaped.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return isinstance(current, (dict, bool))


def _schema_preflight(schema: Any) -> list[dict[str, str]]:
    if not isinstance(schema, (dict, bool)):
        return [{"code": "schema.invalid", "path": "$"}]
    if isinstance(schema, dict) and schema.get("$schema", DRAFT_2020_12) != DRAFT_2020_12:
        return [{"code": "schema.unsupported_draft", "path": "$"}]

    stack = [schema]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if not isinstance(node, (dict, list)):
            continue
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, list):
            stack.extend(node)
            continue
        for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
            if keyword not in node:
                continue
            ref = node[keyword]
            if (
                keyword != "$ref"
                or not isinstance(ref, str)
                or not ref.startswith("#/$defs/")
                or not _pointer_exists(schema, ref)
            ):
                return [{"code": "schema.disallowed_reference", "path": "$"}]
        stack.extend(node.values())
    try:
        Draft202012Validator.check_schema(schema)
    except (SchemaError, TypeError, ValueError, RecursionError):
        return [{"code": "schema.invalid", "path": "$"}]
    return []


def validate_tasks(queue: Any, schema: Any) -> dict[str, Any]:
    """Вернуть JSON-совместимый отчёт об описании очереди, а не о выполнении задач.

    Пустая очередь допустима. Отсутствие задач проверки запуска или сборки само
    по себе не ошибка: их применимость определяется требованиями проекта.
    Успех проверки не доказывает готовность, завершение работ или наличие разрешения.
    """
    allowed_fields = _field_names(schema)
    errors: list[dict[str, str]] = _schema_preflight(schema)
    counts = {section: 0 for section in SECTIONS}
    plans: list[dict[str, Any]] = []

    def add(code: str, parts: tuple[Any, ...]) -> None:
        error = {"code": code, "path": _path(parts, allowed_fields)}
        if error not in errors:
            errors.append(error)

    def report() -> dict[str, Any]:
        return {
            "valid": not errors,
            "errors": sorted(errors, key=lambda item: (item["path"], item["code"])),
            "counts": {"total": sum(counts.values()), "sections": counts, "plans": len(plans)},
            "plans": plans,
            "notes": [
                "Task definitions are not the Tasks MCP lifecycle or evidence of completion.",
                "Runtime/bundle applicability and missing owners are unchecked; validity is not readiness.",
                "Plan locations identify definitions without echoing titles, IDs, or free-text payloads.",
            ],
        }

    if errors:
        return report()
    try:
        validator = Draft202012Validator(schema, registry=Registry(retrieve=_no_retrieval))
        for error in validator.iter_errors(queue):
            location = tuple(error.absolute_path)
            if error.validator == "required" and isinstance(error.instance, dict):
                for field in error.validator_value:
                    if field not in error.instance:
                        add("schema.required", location + (field,))
            else:
                # Имена проверок — фиксированные слова Draft 2020-12, а не данные задачи.
                add("schema." + str(error.validator), location)
    except (Unresolvable, RecursionError, TypeError, ValueError, KeyError):
        add("schema.validation_unavailable", ())
        return report()

    if not isinstance(queue, dict):
        return report()
    tasks: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    by_id: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]] = defaultdict(list)
    by_plan: dict[tuple[str, str], list[tuple[tuple[Any, ...], dict[str, Any]]]] = defaultdict(list)
    for section in SECTIONS:
        items = queue.get(section)
        if not isinstance(items, list):
            continue
        counts[section] = len(items)
        for index, task in enumerate(items):
            if not isinstance(task, dict):
                continue
            location = (section, index)
            tasks.append((location, task))
            task_id = task.get("id")
            if isinstance(task_id, str):
                by_id[task_id].append((location, task))
            plan_id, stage = task.get("plan_id"), task.get("stage")
            if (
                isinstance(plan_id, str)
                and isinstance(stage, str)
                and stage in {"A", "B", "C", "general"}
            ):
                by_plan[(plan_id, stage)].append((location, task))

    for instances in by_id.values():
        if len(instances) > 1:
            for location, _ in instances:
                add("task.duplicate_id", location + ("id",))

    edges: dict[str, list[tuple[str, tuple[Any, ...]]]] = {task_id: [] for task_id in by_id}
    for location, task in tasks:
        skill = task.get("use_skill")
        if isinstance(skill, str) and skill in FORBIDDEN_EXECUTION_SKILLS:
            add("task.forbidden_execution_route", location + ("use_skill",))
        phase, stage = task.get("phase"), task.get("stage")
        if isinstance(phase, str) and phase[:1] in {"A", "B", "C"} and stage != phase[0]:
            add("task.stage_phase_mismatch", location + ("phase",))
        if stage == "C" and task.get("verification_level") in ("runtime", "bundle"):
            add("task.repeated_verification_tier", location + ("verification_level",))
        dependencies = task.get("depends_on")
        if not isinstance(dependencies, list):
            continue
        task_id = task.get("id")
        for index, dependency in enumerate(dependencies):
            if not isinstance(dependency, str):
                continue
            dep_location = location + ("depends_on", index)
            if dependency == task_id:
                add("task.self_dependency", dep_location)
            elif dependency not in by_id:
                add("task.missing_dependency", dep_location)
            elif isinstance(task_id, str):
                edges[task_id].append((dependency, dep_location))

    # Обход в глубину без рекурсии не упирается в её предел на больших очередях.
    colors: dict[str, int] = {}
    for start in edges:
        if colors.get(start):
            continue
        colors[start] = 1
        stack: list[tuple[str, Iterator[tuple[str, tuple[Any, ...]]]]] = [
            (start, iter(edges[start]))
        ]
        while stack:
            node, adjacent = stack[-1]
            edge = next(adjacent, None)
            if edge is None:
                colors[node] = 2
                stack.pop()
                continue
            destination, dep_location = edge
            if colors.get(destination) == 1:
                add("task.cyclic_dependency", dep_location)
            elif not colors.get(destination):
                colors[destination] = 1
                stack.append((destination, iter(edges[destination])))

    for (_, stage), instances in by_plan.items():
        owners = {
            level: [
                location for location, task in instances if task.get("verification_level") == level
            ]
            for level in ("runtime", "bundle")
        }
        if stage == "B":
            for locations in owners.values():
                if len(locations) > 1:
                    for location in locations:
                        add("task.duplicate_verification_owner", location + ("verification_level",))
        plans.append(
            {
                "plan_path": _path(instances[0][0] + ("plan_id",), allowed_fields),
                "stage": stage,
                "tasks": len(instances),
                "runtime_owners": len(owners["runtime"]),
                "bundle_owners": len(owners["bundle"]),
                "owner_presence_check": "unchecked_applicability",
            }
        )
    return report()
