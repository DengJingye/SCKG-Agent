from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "sckg-local-test-result-v2"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_relative(path: Path, repository_root: Path) -> str:
    return str(path.resolve().relative_to(repository_root.resolve()))


def _pytest_node_id(classname: str, name: str) -> str:
    module_path = classname.replace(".", "/") + ".py"
    return f"{module_path}::{name}"


def parse_junit(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("junit_has_no_test_suites")

    outcomes: list[dict[str, str]] = []
    computed = {key: 0 for key in ("tests", "passed", "failed", "errors", "skipped")}
    header_keys = {
        "tests": "tests",
        "failures": "failed",
        "errors": "errors",
        "skipped": "skipped",
    }
    for suite in suites:
        suite_counts = {key: 0 for key in computed}
        cases = list(suite.findall("testcase"))
        for case in cases:
            node_id = _pytest_node_id(case.attrib["classname"], case.attrib["name"])
            outcome_elements = [
                outcome
                for outcome in ("failure", "error", "skipped")
                if case.find(outcome) is not None
            ]
            if len(outcome_elements) > 1:
                raise ValueError("junit_testcase_has_multiple_outcomes")
            outcome = {
                "failure": "FAILED",
                "error": "ERROR",
                "skipped": "SKIPPED",
            }.get(outcome_elements[0] if outcome_elements else "", "PASSED")
            outcomes.append({"node_id": node_id, "outcome": outcome})
            suite_counts["tests"] += 1
            suite_counts[
                {
                    "PASSED": "passed",
                    "FAILED": "failed",
                    "ERROR": "errors",
                    "SKIPPED": "skipped",
                }[outcome]
            ] += 1
        for header_key, computed_key in header_keys.items():
            if header_key in suite.attrib and int(suite.attrib[header_key]) != suite_counts[computed_key]:
                raise ValueError(f"junit_{header_key}_header_mismatch")
        for key, value in suite_counts.items():
            computed[key] += value

    node_ids = sorted(item["node_id"] for item in outcomes)
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("junit_duplicate_test_identity")
    if root.tag == "testsuites":
        for header_key, computed_key in header_keys.items():
            if header_key in root.attrib and int(root.attrib[header_key]) != computed[computed_key]:
                raise ValueError(f"junit_root_{header_key}_header_mismatch")
    verified_node_ids = sorted(
        item["node_id"] for item in outcomes if item["outcome"] == "PASSED"
    )
    outcomes.sort(key=lambda item: item["node_id"])
    status = (
        "PASS"
        if computed["passed"] > 0 and not computed["failed"] and not computed["errors"]
        else "FAIL"
    )
    return {
        "status": status,
        **computed,
        "test_node_ids": node_ids,
        "verified_node_ids": verified_node_ids,
        "testcase_outcomes": outcomes,
    }


def record_junit_result(
    *,
    junit_path: Path,
    output_path: Path,
    repository_root: Path,
    suite_id: str,
    tested_revision: str,
    command: list[str],
) -> dict[str, Any]:
    junit_path = junit_path.resolve()
    output_path = output_path.resolve()
    repository_root = repository_root.resolve()
    parsed = parse_junit(junit_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "suite_id": suite_id,
        "tested_revision": tested_revision,
        "status": parsed["status"],
        "tests": parsed["tests"],
        "passed": parsed["passed"],
        "failed": parsed["failed"],
        "errors": parsed["errors"],
        "skipped": parsed["skipped"],
        "command": command,
        "test_node_ids": parsed["test_node_ids"],
        "verified_node_ids": parsed["verified_node_ids"],
        "testcase_outcomes": parsed["testcase_outcomes"],
        "junit_artifact": _repository_relative(junit_path, repository_root),
        "junit_artifact_sha256": sha256_file(junit_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--suite-id", required=True)
    parser.add_argument("--tested-revision", required=True)
    parser.add_argument("--command", action="append", required=True)
    args = parser.parse_args()
    record_junit_result(
        junit_path=args.junit,
        output_path=args.output,
        repository_root=args.repository_root,
        suite_id=args.suite_id,
        tested_revision=args.tested_revision,
        command=args.command,
    )


if __name__ == "__main__":
    main()
