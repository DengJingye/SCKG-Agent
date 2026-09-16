"""Read-only integrity verification for historical fidelity evaluations.

Historical verification answers whether a recorded formal run and its frozen
inputs are still intact.  It deliberately resolves the historical System
Under Test from the recorded Git baseline rather than comparing that digest
with today's worktree implementation.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from eval.scientific_decision_justification_fidelity_v1 import ROOT


BOUNDARY_PATH = (
    ROOT
    / "eval/specs/scientific_decision_justification_fidelity_v1_2.boundary.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(path: Path) -> tuple[int, str]:
    rows = [
        {
            "path": item.relative_to(path).as_posix(),
            "sha256": _file_hash(item),
        }
        for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
    ]
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return len(rows), digest


def _git_blob_hash(root: Path, revision: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def _git_contains_blob(root: Path, path: str, expected_sha256: str) -> bool:
    revisions = subprocess.run(
        ["git", "log", "--all", "--format=%H", "--", path],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return any(
        _git_blob_hash(root, revision, path) == expected_sha256
        for revision in revisions
    )


def load_historical_preregistration(
    *, root: Path = ROOT
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load frozen semantics after verifying their historical identity lane."""

    verify_historical_integrity(root=root)
    boundary = _read_json(root / BOUNDARY_PATH.relative_to(ROOT))
    return (
        _read_json(root / boundary["frozen_expected_spec"]["path"]),
        _read_json(root / boundary["frozen_preregistration"]["path"]),
    )


def verify_historical_integrity(*, root: Path = ROOT) -> dict[str, Any]:
    """Verify v1/v1.1 artifacts without requiring the current SUT to be old."""

    boundary = _read_json(root / BOUNDARY_PATH.relative_to(ROOT))
    spec_row = boundary["frozen_expected_spec"]
    prereg_row = boundary["frozen_preregistration"]
    spec_path = root / spec_row["path"]
    prereg_path = root / prereg_row["path"]
    if _file_hash(spec_path) != spec_row["sha256"]:
        raise ValueError("historical_frozen_spec_digest_mismatch")
    if _file_hash(prereg_path) != prereg_row["sha256"]:
        raise ValueError("historical_preregistration_digest_mismatch")

    spec = _read_json(spec_path)
    preregistration = _read_json(prereg_path)
    if preregistration["expected_spec"]["sha256"] != spec_row["sha256"]:
        raise ValueError("historical_spec_identity_mismatch")
    if len(spec["atoms"]) != preregistration["counts"]["atom_count"]:
        raise ValueError("historical_atom_count_mismatch")
    if (
        len(spec["negative_controls"])
        != preregistration["counts"]["negative_control_count"]
    ):
        raise ValueError("historical_mutation_count_mismatch")

    sut_rows = {
        row["path"]: row
        for row in boundary["system_under_test_artifacts"]
    }
    source_rows = preregistration["source_artifact_digests"]
    for row in source_rows:
        path = row["path"]
        if path in sut_rows:
            archived = _git_blob_hash(root, boundary["baseline_commit"], path)
            expected = sut_rows[path]["pre_fix_sha256"]
            if row["sha256"] != expected or archived != expected:
                raise ValueError(f"historical_recorded_sut_digest_mismatch:{path}")
            continue
        artifact = root / path
        if not artifact.is_file() or _file_hash(artifact) != row["sha256"]:
            raise ValueError(f"historical_source_artifact_digest_mismatch:{path}")

    for row in boundary["historical_formal_runs"]:
        count, digest = _tree_hash(root / row["path"])
        if count != row["file_count"] or digest != row["tree_sha256"]:
            raise ValueError(f"historical_formal_tree_mismatch:{row['path']}")

    v1_root = root / "data/evaluation/scientific_decision_justification_fidelity_v1"
    v1_started = _read_json(v1_root / "formal_run_started.json")
    v1_completed = _read_json(v1_root / "formal_run_completed.json")
    if (
        v1_started["preregistration_sha256"] != prereg_row["sha256"]
        or v1_started["frozen_spec_sha256"] != spec_row["sha256"]
        or v1_started["baseline_commit"] != boundary["baseline_commit"]
    ):
        raise ValueError("historical_v1_run_identity_mismatch")
    if _file_hash(v1_root / "report.json") != v1_completed["report_sha256"]:
        raise ValueError("historical_v1_report_digest_mismatch")
    if _file_hash(v1_root / "SUMMARY.md") != v1_completed["summary_sha256"]:
        raise ValueError("historical_v1_summary_digest_mismatch")

    v1_1_root = root / "data/evaluation/scientific_decision_justification_fidelity_v1_1"
    v1_1_started = _read_json(v1_1_root / "formal_run_started.json")
    v1_1_completed = _read_json(v1_1_root / "formal_run_completed.json")
    v1_1_report = _read_json(v1_1_root / "report.json")
    if (
        v1_1_started["spec_sha256"] != spec_row["sha256"]
        or v1_1_started["head"] != boundary["baseline_commit"]
        or v1_1_started["input_sha256"] != v1_1_report["input_sha256"]
    ):
        raise ValueError("historical_v1_1_run_identity_mismatch")
    if _file_hash(v1_1_root / "report.json") != v1_1_completed["report_sha256"]:
        raise ValueError("historical_v1_1_report_digest_mismatch")
    evaluator_path = "eval/scientific_decision_justification_fidelity_v1_1.py"
    if not _git_contains_blob(root, evaluator_path, v1_1_started["evaluator_sha256"]):
        raise ValueError("historical_v1_1_evaluator_not_archived")

    return {
        "historical_run_count": len(boundary["historical_formal_runs"]),
        "historical_source_count": len(source_rows),
        "historical_sut_paths": sorted(sut_rows),
        "frozen_spec_sha256": spec_row["sha256"],
        "current_worktree_sut_checked": False,
    }
