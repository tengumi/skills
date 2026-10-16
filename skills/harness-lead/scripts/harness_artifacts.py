#!/usr/bin/env python3
"""Local planning mechanics; does not execute tasks, tests or external calls."""

import argparse
import json
import sys
from pathlib import Path

from artifact_io import ToolError, read_json, snapshot, write_json, write_text


def same_path(first, second):
    if first.absolute() == second.absolute():
        return True
    try:
        return first.samefile(second)
    except FileNotFoundError:
        return False
    except OSError:
        raise ToolError("cannot_verify_output_identity") from None


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("validate-tasks", "handoff"):
        command = commands.add_parser(name)
        command.add_argument("--tasks", required=True, type=Path)
        command.add_argument("--schema", required=True, type=Path)
        command.add_argument("--output", type=Path)
        command.add_argument("--replace", action="store_true")
        if name == "validate-tasks":
            command.add_argument("--plan-id")
            command.add_argument("--require-runtime", action="store_true")
            command.add_argument("--require-bundle", action="store_true")
        else:
            command.add_argument("--lifecycle", required=True, type=Path)
            command.add_argument("--markdown", type=Path)
    command = commands.add_parser("manifest")
    command.add_argument("--root", required=True, type=Path)
    command.add_argument("--file", action="append", dest="files")
    command.add_argument("--output", type=Path)
    command.add_argument("--replace", action="store_true")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        inputs = {
            getattr(args, name).absolute()
            for name in ("tasks", "schema", "lifecycle")
            if getattr(args, name, None) is not None
        }
        outputs = [
            getattr(args, name).absolute()
            for name in ("output", "markdown")
            if getattr(args, name, None) is not None
        ]
        if any(same_path(out, source) for out in outputs for source in inputs) or any(
            same_path(a, b) for index, a in enumerate(outputs) for b in outputs[index + 1 :]
        ):
            raise ToolError("output_must_not_replace_input")
        # Dependencies are loaded only for schema/lifecycle commands. Manifest
        # remains usable with standard-library Python alone.
        if args.command == "manifest":
            result = snapshot(args.root, args.files)
            if args.output is not None:
                if any(
                    same_path(args.output, args.root / relative) for relative in result["files"]
                ):
                    raise ToolError("output_is_snapshot_input: select source files explicitly")
        else:
            from task_validation import validate_tasks

            queue, schema = read_json(args.tasks), read_json(args.schema)
            if not isinstance(schema, dict) or schema.get("$id") != "tasks.schema.json":
                raise ToolError("canonical_tasks_schema_required")
            if args.command == "validate-tasks":
                result = validate_tasks(queue, schema)
                if args.require_runtime or args.require_bundle:
                    if not args.plan_id:
                        raise ToolError("plan_id_required_for_explicit_gate_checks")
                    tasks = (
                        [
                            task
                            for section in (
                                "current_sprint",
                                "backlog",
                                "discovered_bugs",
                                "tech_debt",
                                "completed_sprint",
                            )
                            for task in queue.get(section, [])
                            if isinstance(task, dict)
                        ]
                        if result["valid"]
                        else []
                    )
                    selected = [
                        t
                        for t in tasks
                        if t.get("plan_id") == args.plan_id and t.get("stage") == "B"
                    ]
                    result["requested_owner_checks"] = {}
                    result["notes"][1] = (
                        "Applicability is supplied by the caller, not inferred. "
                        "Requested owner counts are reported separately; other plans are unchecked."
                    )
                    selected_paths = (
                        {
                            f"$.{section}[{index}].plan_id"
                            for section in (
                                "current_sprint",
                                "backlog",
                                "discovered_bugs",
                                "tech_debt",
                                "completed_sprint",
                            )
                            for index, task in enumerate(queue.get(section, []))
                            if isinstance(task, dict) and task in selected
                        }
                        if isinstance(queue, dict) and tasks
                        else set()
                    )
                    for plan in result["plans"]:
                        if plan["plan_path"] in selected_paths:
                            plan["owner_presence_check"] = "checked_explicit_requirements"
                    for tier, required in (
                        ("runtime", args.require_runtime),
                        ("bundle", args.require_bundle),
                    ):
                        if not required:
                            continue
                        found = sum(t.get("verification_level") == tier for t in selected)
                        result["requested_owner_checks"][tier] = {
                            "found": found,
                            "passed": found == 1,
                        }
                        if found != 1:
                            result["errors"].append(
                                {"code": "required_" + tier + "_owner", "path": "$"}
                            )
                            result["valid"] = False
            else:
                from handoff import make_handoff, render_handoff

                lifecycle = read_json(args.lifecycle)
                result = make_handoff(queue, lifecycle, schema)
                if args.markdown:
                    if args.output and args.output.absolute() == args.markdown.absolute():
                        raise ToolError("distinct_output_paths_required")
                    write_text(args.markdown, render_handoff(result), replace=args.replace)
        if args.output:
            write_json(args.output, result, replace=args.replace)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 1 if args.command == "validate-tasks" and not result["valid"] else 0
    except ImportError:
        print(
            json.dumps({"error": "missing_dependency: install scripts/requirements.txt"}),
            file=sys.stderr,
        )
        return 2
    except (ToolError, OSError, ValueError, RecursionError):
        # Never include third-party parser diagnostics or input values.
        error = sys.exc_info()[1]
        code = str(error) if isinstance(error, ToolError) else "invalid_input_or_io_error"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
