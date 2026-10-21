"""Краткая сводка переданной выгрузки MCP, а не решение о готовности сервиса."""

import hashlib
import json
import re
from collections import Counter

from artifact_io import ToolError
from task_validation import validate_tasks

SECTIONS = ("current_sprint", "backlog", "discovered_bugs", "tech_debt", "completed_sprint")
LIFECYCLE_FIELDS = {
    "status",
    "claimed_by",
    "claimed_at",
    "attempts",
    "evidence",
    "completed_at",
    "blocker",
}
STATUSES = ("open", "in_progress", "blocked", "done")


def digest(value):
    """Вычислить сумму нормализованного JSON; это не сумма исходных байтов файла."""
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def make_handoff(queue, lifecycle, schema):
    if not isinstance(schema, dict) or schema.get("$id") != "tasks.schema.json":
        raise ToolError("canonical_tasks_schema_required")
    validation = validate_tasks(queue, schema)
    if not validation["valid"]:
        raise ToolError("invalid_task_definitions: run validate-tasks")
    # Защищаем отчёт даже от ошибочно переданной слишком свободной схемы:
    # произвольные объекты не должны попадать в поля задачи, этапа или маршрута.
    if not isinstance(queue, dict) or any(not isinstance(queue.get(s), list) for s in SECTIONS):
        raise ToolError("invalid_task_definitions")
    for section in SECTIONS:
        for task in queue[section]:
            if not isinstance(task, dict) or not isinstance(task.get("id"), str):
                raise ToolError("invalid_task_definitions")
            if not re.fullmatch(r"[A-Z]+-[0-9]+", task["id"]):
                raise ToolError("invalid_task_definitions")
            for field in (
                "plan_id",
                "stage",
                "phase",
                "use_skill",
                "skill_mode",
                "verification_level",
            ):
                if field in task and (
                    not isinstance(task[field], str)
                    or not re.fullmatch(r"[A-Za-z0-9._-]+", task[field])
                ):
                    raise ToolError("invalid_task_metadata")
            deps = task.get("depends_on", [])
            if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
                raise ToolError("invalid_task_dependencies")
    if not isinstance(lifecycle, dict) or lifecycle.get("status") != "ok":
        raise ToolError("invalid_mcp_export")
    if lifecycle.get("queue_storage_mode") not in ("out_of_band", "tracked"):
        raise ToolError("missing_queue_storage_mode")
    merged = lifecycle.get("all_tasks")
    if not isinstance(merged, list):
        raise ToolError("all_tasks_required: export list_open_tasks(include_all=true)")
    definitions = {task["id"]: task for section in SECTIONS for task in queue[section]}
    if len(definitions) != sum(len(queue[s]) for s in SECTIONS) or any(
        dep not in definitions for t in definitions.values() for dep in t.get("depends_on", [])
    ):
        raise ToolError("invalid_task_dependencies")
    by_id = {}
    for task in merged:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise ToolError("invalid_lifecycle_task")
        task_id = task["id"]
        if task_id not in definitions or task_id in by_id:
            raise ToolError("lifecycle_definition_ids_mismatch")
        if not isinstance(task.get("status"), str) or task["status"] not in STATUSES:
            raise ToolError("invalid_lifecycle_status")
        for key, value in definitions[task_id].items():
            if key not in LIFECYCLE_FIELDS and task.get(key) != value:
                raise ToolError("lifecycle_definition_content_mismatch: refresh MCP export")
        by_id[task_id] = task
    if set(by_id) != set(definitions):
        raise ToolError("lifecycle_definition_ids_mismatch")
    counts = {status: sum(t["status"] == status for t in merged) for status in STATUSES}
    exported_summary = lifecycle.get("summary")
    if exported_summary is not None:
        if (
            not isinstance(exported_summary, dict)
            or type(exported_summary.get("total")) is not int
            or exported_summary["total"] != len(merged)
        ):
            raise ToolError("lifecycle_summary_mismatch")
        by_status = exported_summary.get("by_status")
        if (
            not isinstance(by_status, dict)
            or by_status != counts
            or any(type(value) is not int for value in by_status.values())
        ):
            raise ToolError("lifecycle_summary_mismatch")
    items = []
    candidates = []
    stages = {}
    for task_id, definition in definitions.items():
        task = by_id[task_id]
        item = {
            key: definition[key]
            for key in (
                "id",
                "plan_id",
                "stage",
                "phase",
                "use_skill",
                "skill_mode",
                "verification_level",
            )
            if key in definition
        }
        item["status"] = task["status"]
        item["unmet_dependencies"] = [
            dependency
            for dependency in definition.get("depends_on", [])
            if by_id[dependency]["status"] != "done"
        ]
        if task["status"] == "open" and not item["unmet_dependencies"]:
            candidates.append(task_id)
        evidence = task.get("evidence")
        if isinstance(evidence, dict):
            reported = {}
            sha = evidence.get("commit_sha")
            if isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{7,64}", sha):
                reported["commit_sha"] = sha
            for field in ("tests_passed", "lint_passed"):
                if type(evidence.get(field)) is bool:
                    reported[field] = evidence[field]
            item["reported_evidence"] = reported
        items.append(item)
        stages.setdefault(definition.get("stage", "untagged"), Counter())[task["status"]] += 1
    return {
        "format_version": 1,
        "kind": "harness-handoff",
        "source": "supplied_tasks_mcp_export",
        "input_payload_sha256": {"definitions": digest(queue), "lifecycle": digest(lifecycle)},
        "counts": {"total": len(merged), "by_status": counts},
        "by_stage": {
            stage: {status: tally[status] for status in STATUSES}
            for stage, tally in sorted(stages.items())
        },
        "tasks": items,
        "dependency_only_candidates": candidates,
        "evidence_review": "REQUIRED",
        "release_readiness": "NOT_ASSESSED",
        "limitations": [
            "Snapshot of the supplied export; freshness is not independently verified.",
            "Dependency candidates are not claim authorization or stage/contract readiness.",
            "Reported evidence is not rerun, checked for ancestry, or proven current here.",
            "No claim, submit, task definition, git or approval is changed.",
        ],
    }


def render_handoff(report):
    lines = [
        "# Краткий handoff Harness",
        "",
        "Сводка переданного экспорта Tasks MCP, не заключение о готовности сервиса.",
        "",
        "| Этап | Открыто | В работе | Заблокировано | Завершено |",
        "|---|---:|---:|---:|---:|",
    ]
    for stage, counts in report["by_stage"].items():
        lines.append(f"| {stage} | " + " | ".join(str(counts[s]) for s in STATUSES) + " |")
    lines.extend(
        [
            "",
            "Кандидаты только по зависимостям: "
            + (", ".join(report["dependency_only_candidates"]) or "нет")
            + ".",
            "Перед claim проверить этап, актуальность evidence, контракты и разрешения.",
            "",
            "| Задача | Этап | Статус | Проверка | Незакрытые зависимости |",
            "|---|---|---|---|---|",
        ]
    )
    for task in report["tasks"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    task["id"],
                    task.get("stage", "untagged"),
                    task["status"],
                    task.get("verification_level", "—"),
                    ", ".join(task["unmet_dependencies"]) or "—",
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Готовность к выпуску: **не оценивалась**. Дата/свежесть экспорта,",
            "актуальность тестов, runtime, bundle и внешних проверок требуют",
            "отдельного подтверждения. Статус done сам по себе этого не доказывает.",
            "",
        ]
    )
    return "\n".join(lines)
