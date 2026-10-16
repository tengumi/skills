import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from artifact_io import ToolError
from handoff import make_handoff, render_handoff

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "templates/tasks.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())


def queue():
    task = {
        "id": "T-001",
        "title": "PRIVATE-TITLE",
        "type": "feat",
        "priority": "high",
        "status": "open",
        "plan_id": "b-test",
        "stage": "B",
        "phase": "B2",
        "use_skill": "harness-production-readiness",
        "skill_mode": "adapter",
        "verification_level": "capability",
        "acceptance_criteria": ["PRIVATE-CRITERIA"],
        "depends_on": [],
    }
    result = {
        name: []
        for name in (
            "current_sprint",
            "backlog",
            "discovered_bugs",
            "tech_debt",
            "completed_sprint",
        )
    }
    result.update(version="1.0", current_sprint=[task])
    return result


def lifecycle(definitions, status="done"):
    tasks = copy.deepcopy(definitions["current_sprint"])
    for task in tasks:
        task.update(
            status=status,
            evidence={"commit_sha": "a" * 40, "tests_passed": True, "notes": "PRIVATE-LOG"},
        )
    return {"status": "ok", "queue_storage_mode": "out_of_band", "all_tasks": tasks}


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "harness_artifacts.py"), *map(str, args)],
        capture_output=True,
        text=True,
    )


def inputs(tmp_path):
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps(queue()))
    merged = tmp_path / "merged.json"
    merged.write_text(json.dumps(lifecycle(queue())))
    return tasks, merged


def test_done_from_merged_not_definitions_and_not_release_approval():
    original = queue()
    report = make_handoff(original, lifecycle(original), SCHEMA)
    assert original["current_sprint"][0]["status"] == "open"
    assert report["counts"]["by_status"]["done"] == 1
    assert report["release_readiness"] == "NOT_ASSESSED"
    assert report["evidence_review"] == "REQUIRED"
    assert report["tasks"][0]["reported_evidence"]["commit_sha"] == "a" * 40
    for output in (json.dumps(report), render_handoff(report)):
        assert "PRIVATE-" not in output


@pytest.mark.parametrize("schema", [{}, True, {"$id": "tasks.schema.json"}])
def test_handoff_rejects_wrong_schema_and_partial_queue_without_traceback(schema):
    with pytest.raises(ToolError):
        make_handoff(
            {}, {"status": "ok", "queue_storage_mode": "out_of_band", "all_tasks": []}, schema
        )


def test_cli_rejects_noncanonical_schema(tmp_path):
    tasks, _ = inputs(tmp_path)
    schema = tmp_path / "wrong-schema.json"
    schema.write_text("{}")
    response = run("validate-tasks", "--tasks", tasks, "--schema", schema)
    assert response.returncode == 2
    assert "Traceback" not in response.stderr


def test_explicit_owner_checks_are_recorded_in_report(tmp_path):
    definitions = queue()
    for number, tier in ((2, "runtime"), (3, "bundle")):
        task = copy.deepcopy(definitions["current_sprint"][0])
        task.update(id=f"T-{number:03d}", verification_level=tier, skill_mode="process")
        definitions["current_sprint"].append(task)
    source = tmp_path / "tasks.json"
    source.write_text(json.dumps(definitions))
    response = run(
        "validate-tasks",
        "--tasks",
        source,
        "--schema",
        SCHEMA_PATH,
        "--plan-id",
        "b-test",
        "--require-runtime",
        "--require-bundle",
    )
    assert response.returncode == 0
    report = json.loads(response.stdout)
    assert report["requested_owner_checks"] == {
        "runtime": {"found": 1, "passed": True},
        "bundle": {"found": 1, "passed": True},
    }
    assert report["plans"][0]["owner_presence_check"] == "checked_explicit_requirements"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.pop("all_tasks"),
        lambda d: d.update(all_tasks=[]),
        lambda d: d["all_tasks"].append(copy.deepcopy(d["all_tasks"][0])),
        lambda d: d["all_tasks"][0].update(title="changed"),
        lambda d: d["all_tasks"][0].update(depends_on=["T-999"]),
        lambda d: d["all_tasks"][0].update(status="complete"),
        lambda d: d.update(queue_storage_mode=[]),
        lambda d: d.update(summary={"total": True, "by_status": {}}),
        lambda d: d.update(
            summary={
                "total": 1,
                "by_status": {"done": True, "open": 0, "in_progress": 0, "blocked": 0},
            }
        ),
    ],
)
def test_partial_stale_or_malformed_export_is_rejected(mutation):
    definitions = queue()
    merged = lifecycle(definitions)
    mutation(merged)
    with pytest.raises(ToolError):
        make_handoff(definitions, merged, SCHEMA)


def test_dependency_candidates_are_not_claims():
    definitions = queue()
    second = copy.deepcopy(definitions["current_sprint"][0])
    second.update(id="T-002", depends_on=["T-001"])
    definitions["current_sprint"].append(second)
    merged = lifecycle(definitions, "open")
    report = make_handoff(definitions, merged, SCHEMA)
    assert report["dependency_only_candidates"] == ["T-001"]
    assert report["tasks"][1]["unmet_dependencies"] == ["T-001"]
    merged["all_tasks"][0]["status"] = "done"
    assert make_handoff(definitions, merged, SCHEMA)["dependency_only_candidates"] == ["T-002"]


def test_validation_cli_and_explicit_applicability(tmp_path):
    tasks, _ = inputs(tmp_path)
    args = ("validate-tasks", "--tasks", tasks, "--schema", SCHEMA_PATH)
    assert run(*args).returncode == 0
    response = run(*args, "--plan-id", "b-test", "--require-runtime", "--require-bundle")
    assert response.returncode == 1
    assert {error["code"] for error in json.loads(response.stdout)["errors"]} == {
        "required_runtime_owner",
        "required_bundle_owner",
    }
    assert run(*args, "--require-runtime").returncode == 2


def test_handoff_cli_outputs_and_no_rewrites(tmp_path):
    tasks, merged = inputs(tmp_path)
    original = tasks.read_bytes()
    output, markdown = tmp_path / "handoff.json", tmp_path / "handoff.md"
    args = (
        "handoff",
        "--tasks",
        tasks,
        "--schema",
        SCHEMA_PATH,
        "--lifecycle",
        merged,
        "--output",
        output,
        "--markdown",
        markdown,
    )
    assert run(*args).returncode == 0
    assert json.loads(output.read_text())["counts"]["by_status"]["done"] == 1
    assert "T-001" in markdown.read_text()
    assert run(*args).returncode == 2
    assert run(*args, "--replace").returncode == 0
    assert tasks.read_bytes() == original


@pytest.mark.parametrize("which", ["tasks", "schema", "lifecycle"])
def test_replace_cannot_target_an_input(tmp_path, which):
    tasks, merged = inputs(tmp_path)
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(SCHEMA))
    selected = {"tasks": tasks, "schema": schema, "lifecycle": merged}[which]
    before = selected.read_bytes()
    response = run(
        "handoff",
        "--tasks",
        tasks,
        "--schema",
        schema,
        "--lifecycle",
        merged,
        "--output",
        selected,
        "--replace",
    )
    assert response.returncode == 2
    assert selected.read_bytes() == before


def test_cli_malformed_json_never_echoes_payload(tmp_path):
    tasks = tmp_path / "tasks.json"
    tasks.write_text('{"private": "SENTINEL-PRIVATE-TEXT",')
    response = run("validate-tasks", "--tasks", tasks, "--schema", SCHEMA_PATH)
    assert response.returncode == 2
    assert "SENTINEL" not in response.stdout + response.stderr
    assert "Traceback" not in response.stderr


def test_manifest_cli_and_self_reference(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "app.py").write_text("pass\n")
    output = tmp_path / "source-manifest.json"
    response = run("manifest", "--root", root, "--file", "app.py", "--output", output)
    assert response.returncode == 0
    assert list(json.loads(output.read_text())["files"]) == ["app.py"]
    response = run(
        "manifest", "--root", root, "--file", "app.py", "--output", root / "app.py", "--replace"
    )
    assert response.returncode == 2
    assert (root / "app.py").read_text() == "pass\n"


def test_input_alias_by_file_identity_is_not_overwritten(tmp_path):
    tasks, merged = inputs(tmp_path)
    alias = tmp_path / "alias.json"
    os.link(tasks, alias)
    before = tasks.read_bytes()
    response = run(
        "validate-tasks", "--tasks", tasks, "--schema", SCHEMA_PATH, "--output", alias, "--replace"
    )
    assert response.returncode == 2
    assert tasks.read_bytes() == alias.read_bytes() == before


def test_manifest_source_alias_by_file_identity_is_not_overwritten(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original\n")
    alias = tmp_path / "alias.txt"
    os.link(source, alias)
    response = run(
        "manifest", "--root", tmp_path, "--file", source.name, "--output", alias, "--replace"
    )
    assert response.returncode == 2
    assert source.read_text() == alias.read_text() == "original\n"


def test_case_insensitive_alias_not_overwritten(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original\n")
    alias = tmp_path / "SOURCE.TXT"
    if not alias.exists():
        pytest.skip("Filesystem is case-sensitive; identity protection covered by hardlink test")
    response = run(
        "manifest", "--root", tmp_path, "--file", source.name, "--output", alias, "--replace"
    )
    assert response.returncode == 2
    assert source.read_text() == "original\n"
