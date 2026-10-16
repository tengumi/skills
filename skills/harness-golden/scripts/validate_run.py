#!/usr/bin/env python3
"""Check compact package structure/bindings. This is NOT a semantic oracle."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def input_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def read_jsonl(path):
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = parse(line)
            if not isinstance(row, dict):
                raise ValueError("record must be an object")
            rows.append(row)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path.name}:{line_no}: {exc}") from exc
    return rows


def validate_compact_layout(root, run, selected, files, errors):
    """Check delivery layout, not the semantic content of human exports."""
    allowed = {"run.json", "cases.jsonl", "audit.jsonl", "results"}
    for child in root.iterdir():
        if child.name not in allowed:
            errors.append(f"unexpected package entry: {child.name}")
    for path in root.rglob("*"):
        if path.is_symlink():
            errors.append(f"symlink not allowed in compact-v2: {path.relative_to(root)}")
    results = root / "results"
    if not results.is_dir():
        errors.append("results directory missing")
    summary = run.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be an object with outcome and limitations")
    else:
        if not isinstance(summary.get("outcome"), str) or not summary["outcome"].strip():
            errors.append("summary.outcome must be nonempty text")
        limitations = summary.get("limitations")
        if not isinstance(limitations, list) or any(not isinstance(x, str) for x in limitations):
            errors.append("summary.limitations must be an array of strings")
    if "selected_case_ids" not in run:
        errors.append("compact-v2 requires explicit selected_case_ids")
    declared = set()
    selected_ids = set(selected)
    represented_ids = set()
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue  # The shared file/binding validation reports malformed entries.
        name = entry["path"]
        path = Path(name)
        if (path.is_absolute() or len(path.parts) < 2 or path.parts[0] != "results"
                or ".." in path.parts or path.as_posix() != name):
            errors.append(f"result path must be canonical and inside results/: {name}")
            continue
        if name in declared:
            errors.append(f"duplicate result path: {name}")
        declared.add(name)
        ids = entry.get("case_ids")
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
            errors.append(f"result case_ids must be an array of strings: {name}")
        elif len(set(ids)) != len(ids) or not set(ids) <= selected_ids:
            errors.append(f"result case_ids contain duplicates or non-selected cases: {name}")
        else:
            represented_ids.update(ids)
    actual = {p.relative_to(root).as_posix() for p in results.rglob("*") if p.is_file()}
    for name in sorted(actual - declared):
        errors.append(f"undeclared result file: {name}")
    if represented_ids != selected_ids:
        errors.append("result manifest does not cover all selected cases")
    if not selected and actual:
        errors.append("results must be empty when no cases are selected")
    entrypoint = run.get("results_entrypoint")
    if selected or entrypoint is not None:
        if not isinstance(entrypoint, str) or entrypoint not in declared:
            errors.append("results_entrypoint must name a declared result file")
        else:
            path = root / entrypoint
            try:
                if not path.is_file() or path.stat().st_size == 0:
                    errors.append("results_entrypoint must be a nonempty file")
            except OSError as exc:
                errors.append(str(exc))


def validate(root):
    root = Path(root).resolve()
    errors, warnings = [], []
    try:
        run = parse((root / "run.json").read_text(encoding="utf-8"))
        cases = read_jsonl(root / "cases.jsonl")
        audit = read_jsonl(root / "audit.jsonl")
        if not isinstance(run, dict):
            raise ValueError("run.json must be an object")
    except (OSError, ValueError, TypeError) as exc:
        return {"passed": False, "errors": [str(exc)], "warnings": [],
                "scope": "structure_and_binding_only"}

    layout = run.get("package_layout")
    if "package_layout" not in run:
        if not (root / "report.md").is_file():
            errors.append("report.md missing")
    elif layout != "compact-v2":
        errors.append("unknown package_layout")
    mode = run.get("mode")
    evaluation = run.get("evaluation")
    if not isinstance(evaluation, dict) or not evaluation:
        errors.append("evaluation must contain the current truth and contract profile")
    evaluation_sha256 = input_hash(evaluation)
    if not isinstance(mode, str) or mode not in {"business_review_draft", "benchmark_release"}:
        errors.append("unknown or missing mode")
    if mode == "business_review_draft" and run.get("scoring_ready") is True:
        errors.append("draft cannot be scoring_ready")
    if mode == "benchmark_release" and not run.get("verification_policy"):
        errors.append("release requires explicit verification_policy")
    if run.get("external_review_required") is True and run.get("scoring_ready") is True:
        if run.get("external_review_status") != "accepted":
            errors.append("required external review not accepted")

    by_id = {}
    for index, case in enumerate(cases, 1):
        cid = case.get("case_id")
        if not isinstance(cid, str) or not cid.strip():
            errors.append(f"case {index}: case_id missing")
            continue
        if cid in by_id:
            errors.append(f"{cid}: duplicate case_id")
        by_id[cid] = case
        if "input" not in case:
            errors.append(f"{cid}: input missing")
        elif case.get("input_sha256") != input_hash(case["input"]):
            errors.append(f"{cid}: input hash mismatch")
        if not isinstance(case.get("status"), str) or case["status"] not in {"ready", "quarantined", "pending"}:
            errors.append(f"{cid}: unknown or missing status")
        if case.get("status") == "ready" and "expected" not in case:
            errors.append(f"{cid}: ready case lacks expected")

    verified = set()
    for index, record in enumerate(audit, 1):
        if not isinstance(record.get("type"), str):
            errors.append(f"audit {index}: type missing")
        if record.get("type") != "verification":
            continue
        cid = record.get("case_id")
        case = by_id.get(cid) if isinstance(cid, str) else None
        if case is None:
            errors.append(f"audit {index}: unknown case_id")
            continue
        # Prior revisions may be kept in the journal, but cannot attest the current one.
        current = (record.get("input_sha256") == case.get("input_sha256")
                   and record.get("evaluation_sha256") == evaluation_sha256
                   and "expected" in case
                   and record.get("expected_sha256") == input_hash(case["expected"]))
        if record.get("superseded") is True:
            continue
        if not current:
            errors.append(f"audit {index}: verification binding mismatch")
        method = record.get("method")
        if not isinstance(method, str) or method not in {"fresh_context", "deterministic", "self_check"}:
            errors.append(f"audit {index}: unknown verification method")
            continue
        if not record.get("evidence"):
            errors.append(f"audit {index}: verification evidence missing")
        identity = record.get("worker_id") if record.get("method") == "fresh_context" else record.get("tool_version")
        if record.get("method") in {"fresh_context", "deterministic"} and not identity:
            errors.append(f"audit {index}: worker_id/tool_version missing")
        if (current and identity and record.get("result") == "pass"
                and record.get("method") in {"fresh_context", "deterministic"}
                and record.get("evidence")):
            verified.add(cid)

    ready = {cid for cid, case in by_id.items() if case.get("status") == "ready"}
    for cid in sorted(ready - verified):
        errors.append(f"{cid}: no current independent/executable verification record")
    selected = run.get("selected_case_ids", sorted(ready))
    if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
        errors.append("selected_case_ids must be an array of strings")
        selected = []
    if len(set(selected)) != len(selected) or not set(selected) <= ready:
        errors.append("selection contains duplicates or non-ready cases")
    counts = {"case_count": len(cases), "ready_count": len(ready),
              "selected_count": len(selected)}
    for name, actual in counts.items():
        if name in run and (type(run[name]) is not int or run[name] != actual):
            errors.append(f"{name}: declared {run[name]}, actual {actual}")

    files = run.get("files", [])
    if not isinstance(files, list):
        errors.append("files must be an array")
        files = []
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("files entry requires path and sha256")
            continue
        path = (root / entry["path"]).resolve()
        if Path(entry["path"]).is_absolute() or not path.is_relative_to(root):
            errors.append(f"external fixture outside run: {entry['path']}")
            continue
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
                errors.append(f"file hash mismatch: {entry['path']}")
        except OSError as exc:
            errors.append(str(exc))

    actual_files = [p for p in root.rglob("*") if p.is_file()]
    if layout == "compact-v2":
        validate_compact_layout(root, run, selected, files, errors)
    else:
        recommended = 4 + len(files)
        if len(actual_files) > recommended:
            warnings.append(f"{len(actual_files)} files; compact baseline is {recommended} plus requested exports")
    if not cases:
        warnings.append("no cases; this may be a truthful blocked/partial run, not a ready dataset")
    warnings.append("Semantic truth, realism, real isolation and release-policy fulfilment need separate evidence.")
    return {"passed": not errors, "errors": errors, "warnings": warnings,
            "counts": counts, "file_count": len(actual_files),
            "scope": "structure_and_binding_only"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = validate(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
