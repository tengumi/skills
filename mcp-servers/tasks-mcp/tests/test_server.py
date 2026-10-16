from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "server.py"
SPEC = importlib.util.spec_from_file_location("harness_tasks_mcp_server", MODULE_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def _task(task_id: str, **overrides: object) -> dict:
    task = {
        "id": task_id,
        "title": f"Task {task_id}",
        "type": "feat",
        "priority": "high",
        "status": "open",
        "acceptance_criteria": ["observable result"],
    }
    task.update(overrides)
    return task


def _queue(*, current: list[dict] | None = None, backlog: list[dict] | None = None) -> dict:
    return {
        "version": "1.0",
        "last_updated": "2026-01-01T00:00:00+00:00",
        "current_sprint": current or [],
        "backlog": backlog or [],
        "discovered_bugs": [],
        "tech_debt": [],
        "completed_sprint": [],
    }


def _write_queue(repo: Path, data: dict) -> Path:
    path = repo / "docs" / "harness" / "tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _repo_snapshot(repo: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(repo)): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }


class TasksMcpTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.state = root / "state"
        env_patch = mock.patch.dict(
            os.environ,
            {server.STATE_DIR_ENV: str(self.state)},
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop(server.QUEUE_STORAGE_MODE_ENV, None)

    def test_default_claim_submit_is_out_of_band_and_returns_acceptance_alias(self) -> None:
        tasks_path = _write_queue(self.repo, _queue(current=[_task("T-001")]))
        before = _repo_snapshot(self.repo)

        claimed = server.tool_claim_task(self.repo, "T-001", "codex")
        self.assertEqual(claimed["status"], "ok")
        self.assertEqual(claimed["queue_storage_mode"], "out_of_band")
        self.assertEqual(claimed["task"]["acceptance"], ["observable result"])
        self.assertEqual(claimed["task"]["acceptance_criteria"], ["observable result"])
        self.assertEqual(_repo_snapshot(self.repo), before)

        submitted = server.tool_submit_task(
            self.repo,
            "T-001",
            {
                "commit_sha": "abcdef1",
                "tests_passed": True,
                "branch": "feature/T-001",
            },
        )
        self.assertEqual(submitted["status"], "ok")
        self.assertEqual(submitted["task"]["status"], "done")
        self.assertEqual(_repo_snapshot(self.repo), before)
        self.assertEqual(tasks_path.read_bytes(), before["docs/harness/tasks.json"])
        self.assertTrue(list(self.state.glob("*.json")))
        self.assertEqual(server.tool_list_open_tasks(self.repo)["tasks"], [])
        full_queue = server.tool_list_open_tasks(self.repo, include_all=True)
        self.assertEqual(full_queue["tasks"], [])
        self.assertEqual(full_queue["all_tasks"][0]["id"], "T-001")
        self.assertEqual(full_queue["all_tasks"][0]["status"], "done")
        self.assertEqual(full_queue["all_tasks"][0]["_category"], "completed_sprint")
        self.assertEqual(full_queue["summary"]["total"], 1)
        self.assertEqual(full_queue["summary"]["by_status"]["done"], 1)
        self.assertEqual(full_queue["summary"]["by_category"]["completed_sprint"], 1)

    def test_overlay_persists_and_new_definitions_merge(self) -> None:
        tasks_path = _write_queue(self.repo, _queue(current=[_task("T-001")]))
        self.assertEqual(server.tool_claim_task(self.repo, "T-001")["status"], "ok")

        persisted, category = server._find_task(server._read_tasks(self.repo), "T-001")
        self.assertEqual(category, "current_sprint")
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["status"], "in_progress")

        definitions = json.loads(tasks_path.read_text(encoding="utf-8"))
        definitions["backlog"].append(_task("T-002", priority="medium"))
        tasks_path.write_text(json.dumps(definitions, ensure_ascii=False, indent=2), encoding="utf-8")

        merged = server._read_tasks(self.repo)
        first, _ = server._find_task(merged, "T-001")
        second, second_category = server._find_task(merged, "T-002")
        self.assertEqual(first["status"], "in_progress")
        self.assertEqual(second["status"], "open")
        self.assertEqual(second_category, "backlog")
        self.assertEqual(
            [task["id"] for task in server.tool_list_open_tasks(self.repo)["tasks"]],
            ["T-002"],
        )

    def test_duplicate_ids_are_rejected_in_every_storage_mode(self) -> None:
        for mode in ("out_of_band", "tracked"):
            with self.subTest(mode=mode):
                os.environ[server.QUEUE_STORAGE_MODE_ENV] = mode
                _write_queue(
                    self.repo,
                    _queue(current=[_task("T-001")], backlog=[_task("T-001")]),
                )
                with self.assertRaisesRegex(ValueError, "duplicate task id"):
                    server.tool_list_open_tasks(self.repo)

    def test_stuck_detection_stops_after_three_identical_failures(self) -> None:
        _write_queue(self.repo, _queue(current=[_task("T-003")]))
        self.assertEqual(server.tool_claim_task(self.repo, "T-003")["status"], "ok")

        results = [
            server.tool_record_attempt(self.repo, "T-003", "make verify", 1, "same failure")
            for _ in range(3)
        ]
        self.assertEqual(
            [result["action"] for result in results],
            ["continue", "continue", "stop"],
        )
        self.assertEqual(results[-1]["attempts"], 3)

        blocked = server.tool_report_blocker(self.repo, "T-003", results[-1]["reason"])
        self.assertEqual(blocked["status"], "ok")
        task, _ = server._find_task(server._read_tasks(self.repo), "T-003")
        self.assertEqual(task["status"], "blocked")
        self.assertEqual(task["blocker"]["attempts"], 3)
        full_queue = server.tool_list_open_tasks(self.repo, include_all=True)
        self.assertEqual(full_queue["summary"]["by_status"]["blocked"], 1)

    def test_tracked_mode_is_explicit_and_updates_tasks_json(self) -> None:
        os.environ[server.QUEUE_STORAGE_MODE_ENV] = "tracked"
        tasks_path = _write_queue(self.repo, _queue(current=[_task("T-004")]))
        before = tasks_path.read_bytes()

        claimed = server.tool_claim_task(self.repo, "T-004", "agent")
        self.assertEqual(claimed["queue_storage_mode"], "tracked")
        self.assertNotEqual(tasks_path.read_bytes(), before)
        tracked = json.loads(tasks_path.read_text(encoding="utf-8"))
        self.assertEqual(tracked["current_sprint"][0]["status"], "in_progress")
        self.assertFalse(self.state.exists())

        submitted = server.tool_submit_task(
            self.repo,
            "T-004",
            {
                "commit_sha": "1234567",
                "tests_passed": True,
                "branch": "feature/T-004",
            },
        )
        self.assertEqual(submitted["status"], "ok")
        tracked = json.loads(tasks_path.read_text(encoding="utf-8"))
        self.assertEqual(tracked["current_sprint"], [])
        self.assertEqual(tracked["completed_sprint"][0]["id"], "T-004")

    def test_evidence_artifacts_are_repo_relative_paths(self) -> None:
        base = {
            "commit_sha": "abcdef1",
            "tests_passed": True,
            "branch": "feature/T-005",
        }
        self.assertEqual(
            server._validate_evidence(
                {**base, "artifacts": ["docs/harness/evals/prototype-parity.md"]}
            ),
            [],
        )
        self.assertIn(
            "artifacts paths must stay inside the repository",
            server._validate_evidence({**base, "artifacts": ["../outside.json"]}),
        )
        self.assertIn(
            "artifacts must be a list of non-empty repo-relative paths",
            server._validate_evidence({**base, "artifacts": "report.json"}),
        )

    def test_only_feature_ticket_branches_are_accepted(self) -> None:
        base = {
            "commit_sha": "abcdef1",
            "tests_passed": True,
        }
        self.assertEqual(
            server._validate_evidence(
                {**base, "branch": "feature/ABC-123-short-name"}
            ),
            [],
        )
        for branch in (
            "agent/ABC-123",
            "codex/ABC-123",
            "fix/ABC-123",
            "hotfix/ABC-123",
            "feature/no-ticket",
        ):
            with self.subTest(branch=branch):
                errors = server._validate_evidence({**base, "branch": branch})
                self.assertTrue(any("feature/TICKET" in error for error in errors))

    def test_concurrent_claim_has_one_winner_and_preserves_overlay(self) -> None:
        _write_queue(self.repo, _queue(current=[_task("T-006")]))

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda claimer: server.tool_claim_task(self.repo, "T-006", claimer),
                    ("agent-a", "agent-b"),
                )
            )

        self.assertEqual([result["status"] for result in results].count("ok"), 1)
        self.assertEqual([result["status"] for result in results].count("error"), 1)
        task, _ = server._find_task(server._read_tasks(self.repo), "T-006")
        self.assertEqual(task["status"], "in_progress")
        self.assertIn(task["claimed_by"], {"agent-a", "agent-b"})

    def test_json_rpc_initialize_tool_list_and_argument_validation(self) -> None:
        initialized = server.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        self.assertEqual(
            initialized["result"]["serverInfo"],
            {"name": "tasks-mcp", "version": "0.3.0"},
        )
        self.assertEqual(
            initialized["result"]["protocolVersion"],
            server.LATEST_PROTOCOL_VERSION,
        )
        self.assertEqual(initialized["result"]["capabilities"], {"tools": {}})

        legacy = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
        self.assertEqual(legacy["result"]["protocolVersion"], "2024-11-05")

        listed = server.handle_request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        names = [tool["name"] for tool in listed["result"]["tools"]]
        self.assertEqual(
            names,
            [
                "list_open_tasks",
                "claim_task",
                "submit_task",
                "record_attempt",
                "report_blocker",
                "wait_for_report",
            ],
        )
        list_schema = listed["result"]["tools"][0]["inputSchema"]
        self.assertEqual(list_schema["properties"]["include_all"]["type"], "boolean")

        _write_queue(self.repo, _queue(backlog=[_task("T-007")]))
        full_call = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "list_open_tasks",
                    "arguments": {
                        "repo_path": str(self.repo),
                        "include_all": True,
                    },
                },
            }
        )
        full_payload = json.loads(full_call["result"]["content"][0]["text"])
        self.assertEqual(full_payload["all_tasks"][0]["id"], "T-007")
        self.assertEqual(full_payload["summary"]["total"], 1)
        self.assertIsNone(
            server.handle_request(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            )
        )

        invalid = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_open_tasks", "arguments": {}},
            }
        )
        self.assertEqual(invalid["error"]["code"], -32602)
        self.assertIn("repo_path is required", invalid["error"]["message"])

        invalid_root = server.handle_request([])
        self.assertEqual(invalid_root["error"]["code"], -32600)
        invalid_params = server.handle_request(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": []}
        )
        self.assertEqual(invalid_params["error"]["code"], -32602)
        invalid_include_all = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "list_open_tasks",
                    "arguments": {"repo_path": str(self.repo), "include_all": "yes"},
                },
            }
        )
        self.assertEqual(invalid_include_all["error"]["code"], -32602)

    def test_out_of_band_state_directory_must_be_outside_repo(self) -> None:
        _write_queue(self.repo, _queue(current=[_task("T-005")]))
        os.environ[server.STATE_DIR_ENV] = str(self.repo / ".state")
        with self.assertRaisesRegex(ValueError, "must be outside"):
            server.tool_claim_task(self.repo, "T-005")


if __name__ == "__main__":
    unittest.main()
