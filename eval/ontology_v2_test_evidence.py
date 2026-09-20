from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "sckg-local-test-result-v1"


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

    counts = {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    node_ids = sorted(
        {
            _pytest_node_id(case.attrib["classname"], case.attrib["name"])
            for suite in suites
            for case in suite.findall("testcase")
        }
    )
    if len(node_ids) != counts["tests"]:
        raise ValueError("junit_test_identity_count_mismatch")
    passed = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    status = "PASS" if passed > 0 and not counts["failures"] and not counts["errors"] else "FAIL"
    return {
        "status": status,
        "passed": passed,
        "failed": counts["failures"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "test_node_ids": node_ids,
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
        "passed": parsed["passed"],
        "failed": parsed["failed"],
        "errors": parsed["errors"],
        "skipped": parsed["skipped"],
        "command": command,
        "test_node_ids": parsed["test_node_ids"],
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
