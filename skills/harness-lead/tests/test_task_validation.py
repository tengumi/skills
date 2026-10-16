"""Canonical schema and cross-task checks; no repository lifecycle mutations."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "task_validation", SKILL / "scripts/task_validation.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
validate_tasks = MODULE.validate_tasks
SCHEMA = json.loads((SKILL.parents[1] / "templates/tasks.schema.json").read_text())


def queue(*tasks):
    return {
        "version": "1.0",
        "current_sprint": list(tasks),
        "backlog": [],
        "discovered_bugs": [],
        "tech_debt": [],
        "completed_sprint": [],
    }


def task(task_id="T-001", **changes):
    result = {
        "id": task_id,
        "title": "Synthetic capability",
        "type": "feat",
        "priority": "high",
        "status": "open",
        "acceptance_criteria": ["Synthetic assertion passes."],
    }
    result.update(changes)
    return result


def b_task(task_id="T-001", **changes):
    values = {
        "plan_id": "synthetic-b",
        "stage": "B",
        "phase": "B2",
        "use_skill": "harness-production-readiness",
        "skill_mode": "adapter",
        "verification_level": "capability",
    }
    values.update(changes)
    return task(task_id, **values)


def codes(result):
    return {error["code"] for error in result["errors"]}


def test_empty_canonical_queue_passes_without_readiness_claim():
    result = validate_tasks(queue(), SCHEMA)
    assert result["valid"]
    assert result["counts"]["total"] == 0
    assert result["plans"] == []
    assert any("not the Tasks MCP lifecycle" in note for note in result["notes"])
    assert any("validity is not readiness" in note for note in result["notes"])


@pytest.mark.parametrize("value", [None, [], "secret", 1, False])
def test_non_object_queue_is_invalid_without_traceback(value):
    result = validate_tasks(value, SCHEMA)
    assert not result["valid"]
    assert "schema.type" in codes(result)


@pytest.mark.parametrize("value", [None, False, 10, "bad", [], {"id": []}, {"id": {}}])
def test_malformed_items_are_invalid_without_traceback(value):
    result = validate_tasks(queue(value), SCHEMA)
    assert not result["valid"]
    assert result["counts"]["total"] == 1


def test_malformed_sections_are_rejected():
    data = queue()
    data["backlog"] = {"secret": "do not echo"}
    result = validate_tasks(data, SCHEMA)
    assert result["errors"] == [{"code": "schema.type", "path": "$.backlog"}]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("id", "lower-001", "schema.pattern"),
        ("id", "T-abc", "schema.pattern"),
        ("plan_id", "UPPER-PLAN", "schema.pattern"),
        ("type", "test", "schema.enum"),
        ("priority", "urgent", "schema.enum"),
        ("status", "complete", "schema.enum"),
        ("verification_level", "full", "schema.enum"),
        ("skill_mode", "build", "schema.enum"),
        ("phase", "B5", "schema.pattern"),
        ("acceptance_criteria", [], "schema.minItems"),
    ],
)
def test_canonical_field_constraints(field, value, expected):
    result = validate_tasks(queue(b_task(**{field: value})), SCHEMA)
    assert not result["valid"]
    assert expected in codes(result)


def test_missing_required_field_has_exact_path_without_validator_message():
    data = task()
    del data["acceptance_criteria"]
    result = validate_tasks(queue(data), SCHEMA)
    assert {"code": "schema.required", "path": "$.current_sprint[0].acceptance_criteria"} in result[
        "errors"
    ]
    assert all(set(error) == {"code", "path"} for error in result["errors"])


@pytest.mark.parametrize("skill,mode", [("harness-eval", "stand"), ("harness-golden", "golden")])
def test_canonical_skill_mode_conditions(skill, mode):
    assert not validate_tasks(queue(task(use_skill=skill, skill_mode=mode)), SCHEMA)["valid"]


def test_eval_live_requires_c2_and_prototype_parity_requires_a():
    live = task(
        use_skill="harness-eval",
        skill_mode="live",
        plan_id="test-c",
        stage="C",
        phase="C2",
        verification_level="capability",
    )
    assert validate_tasks(queue(live), SCHEMA)["valid"]
    live["phase"] = "C1"
    assert not validate_tasks(queue(live), SCHEMA)["valid"]
    parity = task(use_skill="harness-eval", skill_mode="prototype-parity")
    assert not validate_tasks(queue(parity), SCHEMA)["valid"]
    parity.update(plan_id="test-a", stage="A", verification_level="capability")
    assert validate_tasks(queue(parity), SCHEMA)["valid"]


def test_files_hint_requires_provenance():
    data = task(files_hint=["src/app.py"])
    assert not validate_tasks(queue(data), SCHEMA)["valid"]
    data["slot_provenance"] = {"source": "synthetic-team-template"}
    assert validate_tasks(queue(data), SCHEMA)["valid"]


def test_schema_is_source_of_constraints_not_reimplemented_modes():
    schema = copy.deepcopy(SCHEMA)
    # New schema-only integer property verifies Draft 2020-12, including bool.
    schema["$defs"]["task"]["properties"]["budget"] = {"type": "integer", "minimum": 1}
    assert validate_tasks(queue(task(budget=1)), schema)["valid"]
    result = validate_tasks(queue(task(budget=True)), schema)
    assert "schema.type" in codes(result)


@pytest.mark.parametrize("section", MODULE.SECTIONS)
def test_ids_are_unique_across_all_sections(section):
    data = queue(task())
    data[section].append(task())
    result = validate_tasks(data, SCHEMA)
    assert not result["valid"]
    assert len([error for error in result["errors"] if error["code"] == "task.duplicate_id"]) == 2


def test_missing_and_self_dependencies():
    result = validate_tasks(queue(task(depends_on=["T-001", "T-404"])), SCHEMA)
    assert "task.self_dependency" in codes(result)
    assert "task.missing_dependency" in codes(result)


def test_dependency_can_reference_completed_definition():
    data = queue(task("T-002", depends_on=["T-001"]))
    data["completed_sprint"].append(task("T-001", status="done"))
    assert validate_tasks(data, SCHEMA)["valid"]


def test_dependency_cycle_is_detected_without_marking_downstream_as_cycle():
    data = queue(
        task("T-001", depends_on=["T-002"]),
        task("T-002", depends_on=["T-003"]),
        task("T-003", depends_on=["T-001"]),
        task("T-004", depends_on=["T-001"]),
    )
    result = validate_tasks(data, SCHEMA)
    cycle_errors = [
        error for error in result["errors"] if error["code"] == "task.cyclic_dependency"
    ]
    assert cycle_errors
    assert all("current_sprint[3]" not in error["path"] for error in cycle_errors)


def test_long_valid_dependency_chain_is_iterative():
    tasks = [task(f"T-{index:04d}", depends_on=[f"T-{index + 1:04d}"]) for index in range(1200)]
    tasks.append(task("T-1200"))
    assert validate_tasks(queue(*tasks), SCHEMA)["valid"]


@pytest.mark.parametrize("stage,phase", [("B", "A2"), (None, "A1"), ("A", "B1"), ("B", "C1")])
def test_stage_matches_phase_including_a(stage, phase):
    result = validate_tasks(queue(task(stage=stage, phase=phase)), SCHEMA)
    assert "task.stage_phase_mismatch" in codes(result)


@pytest.mark.parametrize("skill", ["harness-lead", "harness-pre-commit-check"])
def test_orchestration_and_commit_check_cannot_execute_tasks(skill):
    result = validate_tasks(queue(task(use_skill=skill)), SCHEMA)
    assert "task.forbidden_execution_route" in codes(result)


@pytest.mark.parametrize("level", ["runtime", "bundle"])
def test_one_owner_per_b_plan_even_across_sections(level):
    data = queue(b_task("T-001", verification_level=level))
    data["backlog"].append(b_task("T-002", verification_level=level))
    result = validate_tasks(data, SCHEMA)
    assert "task.duplicate_verification_owner" in codes(result)
    assert result["plans"][0][level + "_owners"] == 2


def test_distinct_b_plans_have_independent_owners():
    result = validate_tasks(
        queue(
            b_task("T-001", verification_level="runtime", plan_id="one"),
            b_task("T-002", verification_level="runtime", plan_id="two"),
        ),
        SCHEMA,
    )
    assert result["valid"]
    assert len(result["plans"]) == 2


def test_b_owner_rule_does_not_create_an_unrequested_a_owner_rule():
    result = validate_tasks(
        queue(
            task("T-001", plan_id="shared", stage="A", phase="A2", verification_level="runtime"),
            task("T-002", plan_id="shared", stage="A", phase="A2", verification_level="runtime"),
            b_task("T-003", plan_id="shared", verification_level="runtime"),
        ),
        SCHEMA,
    )
    assert result["valid"]
    assert len(result["plans"]) == 2


def test_missing_owners_are_not_an_applicability_decision_or_blocker():
    result = validate_tasks(queue(b_task()), SCHEMA)
    assert result["valid"]
    assert result["plans"][0]["runtime_owners"] == 0
    assert result["plans"][0]["bundle_owners"] == 0
    assert result["plans"][0]["owner_presence_check"] == "unchecked_applicability"


@pytest.mark.parametrize("level", ["runtime", "bundle"])
def test_c_does_not_repeat_runtime_or_bundle(level):
    result = validate_tasks(queue(b_task(stage="C", phase="C1", verification_level=level)), SCHEMA)
    assert "task.repeated_verification_tier" in codes(result)


@pytest.mark.parametrize(
    "ref",
    [
        "https://example.test/remote.json",
        "file:///tmp/schema.json",
        "other.json#/$defs/task",
        "#/properties/version",
        "#/$defs/missing",
        "#/$defs/",
    ],
)
def test_disallowed_or_missing_ref_fails_closed_even_when_unused(ref):
    schema = copy.deepcopy(SCHEMA)
    schema["$defs"]["unused"] = {"$ref": ref}
    result = validate_tasks(queue(), schema)
    assert not result["valid"]
    assert result["errors"] == [{"code": "schema.disallowed_reference", "path": "$"}]
    assert ref not in json.dumps(result)


@pytest.mark.parametrize("keyword", ["$dynamicRef", "$recursiveRef"])
def test_other_reference_mechanisms_are_rejected(keyword):
    schema = copy.deepcopy(SCHEMA)
    schema["$defs"]["unused"] = {keyword: "#/$defs/task"}
    assert "schema.disallowed_reference" in codes(validate_tasks(queue(), schema))


@pytest.mark.parametrize(
    "schema", [None, [], {"type": "invalid"}, {"$schema": "https://example.test/draft"}]
)
def test_invalid_or_unknown_schema_returns_diagnostic(schema):
    assert not validate_tasks(queue(), schema)["valid"]


def test_schema_resolution_never_retrieves_remote_resources(monkeypatch):
    def forbidden_retrieval(uri):
        raise AssertionError("Resource retrieval must not be attempted")

    monkeypatch.setattr(MODULE, "_no_retrieval", forbidden_retrieval)
    assert validate_tasks(queue(task()), SCHEMA)["valid"]
    schema = copy.deepcopy(SCHEMA)
    schema["$defs"]["task"]["$ref"] = "https://example.test/remote"
    assert not validate_tasks(queue(task()), schema)["valid"]


def test_nested_id_does_not_turn_local_ref_failure_into_network_or_traceback():
    schema = copy.deepcopy(SCHEMA)
    schema["$defs"]["task"]["$id"] = "https://example.test/nested"
    schema["$defs"]["task"]["properties"]["nested"] = {"$ref": "#/$defs/task"}
    result = validate_tasks(queue(task(nested={})), schema)
    assert not result["valid"]
    assert result["errors"] == [{"code": "schema.validation_unavailable", "path": "$"}]
    assert "example.test" not in json.dumps(result)


def test_no_instance_values_or_free_text_in_diagnostics_or_plan_summary():
    secret = "sensitive-sentinel-do-not-print"
    data = queue(
        b_task(
            id=secret,
            title=[secret],
            plan_id=secret,
            depends_on=[secret + "-missing"],
            acceptance_criteria=[{"private": secret}],
            notes=secret,
        )
    )
    result = validate_tasks(data, SCHEMA)
    assert not result["valid"]
    assert secret not in json.dumps(result)
    assert all(set(error) == {"code", "path"} for error in result["errors"])


def test_unknown_instance_key_is_redacted_from_locations():
    schema = {
        "type": "object",
        "additionalProperties": {"type": "integer"},
    }
    result = validate_tasks({"sensitive-key": "sensitive-value"}, schema)
    assert result["errors"] == [{"code": "schema.type", "path": "$['<redacted-field>']"}]
    assert "sensitive" not in json.dumps(result)


def test_synthetic_educational_three_a_seven_b_queue_passes():
    tasks = [
        task(
            f"T-{number:03d}",
            plan_id="educational-a",
            stage="A",
            phase="A2",
            use_skill="harness-prototype-port",
            verification_level="capability",
            depends_on=[] if number == 1 else [f"T-{number - 1:03d}"],
        )
        for number in range(1, 4)
    ]
    tasks.extend(
        b_task(
            f"T-{number:03d}",
            plan_id="educational-b",
            phase="B2" if number < 9 else "B4",
            verification_level={9: "runtime", 10: "bundle"}.get(number, "capability"),
            skill_mode="process" if number > 6 else "adapter",
            depends_on=[f"T-{number - 1:03d}"],
        )
        for number in range(4, 11)
    )
    result = validate_tasks(queue(*tasks), SCHEMA)
    assert result["valid"], result["errors"]
    assert result["counts"]["total"] == 10
    assert result["counts"]["plans"] == 2
    assert result["plans"][1]["runtime_owners"] == 1
    assert result["plans"][1]["bundle_owners"] == 1


def test_no_task_quota_is_introduced():
    assert validate_tasks(queue(*(task(f"T-{index:03d}") for index in range(50))), SCHEMA)["valid"]
