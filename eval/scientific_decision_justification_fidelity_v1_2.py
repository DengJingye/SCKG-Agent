"""Version-boundary guard for the post-fix fidelity evaluation.

The v1.2 boundary keeps scientific inputs, gold semantics, and historical
formal outputs immutable while treating the explicitly declared production
adapter as the System Under Test.  It does not execute a formal evaluation.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from eval.scientific_decision_justification_fidelity_v1 import ROOT


BOUNDARY_PATH = (
    ROOT
    / "eval/specs/scientific_decision_justification_fidelity_v1_2.boundary.json"
)
PRODUCTION_PREFIXES = (
    "agent/",
    "core/",
    "engine/",
    "execution/",
    "orchestration/",
    "retrieval/",
    "runtime/",
    "validation/",
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


def _production_changes(root: Path) -> set[str]:
    output = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.decode()
    changed: set[str] = set()
    for row in output.split("\0"):
        if not row:
            continue
        path = row[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith(PRODUCTION_PREFIXES):
            changed.add(path)
    return changed


def validate_digest_boundary(
    *,
    frozen_source_rows: Iterable[dict[str, str]],
    sut_rows: Iterable[dict[str, str]],
    actual_digests: Mapping[str, str | None],
    changed_production_paths: Iterable[str],
    allowed_changed_production_files: Iterable[str],
) -> dict[str, Any]:
    """Validate immutable artifacts and explicit SUT changes separately."""

    sut_by_path = {row["path"]: row for row in sut_rows}
    allowed = set(allowed_changed_production_files)
    if allowed != set(sut_by_path):
        raise ValueError("sut_allowlist_manifest_mismatch")
    changed = set(changed_production_paths)
    undeclared = changed - allowed
    if undeclared:
        raise ValueError(
            "undeclared_production_change:" + ",".join(sorted(undeclared))
        )
    for row in frozen_source_rows:
        path = row["path"]
        if path in allowed:
            continue
        if actual_digests.get(path) != row["sha256"]:
            raise ValueError(f"immutable_evaluation_artifact_digest_mismatch:{path}")
    observations: list[dict[str, Any]] = []
    for path, row in sorted(sut_by_path.items()):
        current = actual_digests.get(path)
        if current is None:
            raise ValueError(f"system_under_test_missing:{path}")
        changed_digest = current != row["pre_fix_sha256"]
        if changed_digest and path not in changed:
            raise ValueError(f"undeclared_system_under_test_digest_change:{path}")
        observations.append(
            {
                "path": path,
                "pre_fix_sha256": row["pre_fix_sha256"],
                "post_fix_sha256": current,
                "changed": changed_digest,
            }
        )
    return {
        "immutable_artifact_count": sum(
            row["path"] not in allowed for row in frozen_source_rows
        ),
        "sut_observations": observations,
        "declared_production_changes": sorted(changed),
    }


def validate_version_boundary(
    *,
    root: Path = ROOT,
    changed_production_paths: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Validate the v1.2 boundary without running the formal evaluation."""

    boundary = _read_json(
        root
        / BOUNDARY_PATH.relative_to(ROOT)
    )
    preregistration_path = root / boundary["frozen_preregistration"]["path"]
    expected_path = root / boundary["frozen_expected_spec"]["path"]
    if _file_hash(preregistration_path) != boundary["frozen_preregistration"]["sha256"]:
        raise ValueError("frozen_preregistration_digest_mismatch")
    if _file_hash(expected_path) != boundary["frozen_expected_spec"]["sha256"]:
        raise ValueError("frozen_expected_spec_digest_mismatch")
    preregistration = _read_json(preregistration_path)
    if preregistration["expected_spec"]["sha256"] != boundary["frozen_expected_spec"]["sha256"]:
        raise ValueError("frozen_spec_identity_mismatch")
    if (
        preregistration["counts"]["atom_count"]
        != boundary["reused_frozen_semantics"]["decision_atom_count"]
        or preregistration["counts"]["negative_control_count"]
        != boundary["reused_frozen_semantics"]["negative_control_count"]
    ):
        raise ValueError("frozen_semantic_count_mismatch")
    for historical in boundary["historical_formal_runs"]:
        count, digest = _tree_hash(root / historical["path"])
        if count != historical["file_count"] or digest != historical["tree_sha256"]:
            raise ValueError(
                f"historical_formal_artifact_digest_mismatch:{historical['path']}"
            )
    source_rows = preregistration["source_artifact_digests"]
    sut_rows = boundary["system_under_test_artifacts"]
    paths = {row["path"] for row in source_rows}
    paths.update(row["path"] for row in sut_rows)
    actual = {
        path: _file_hash(root / path) if (root / path).is_file() else None
        for path in paths
    }
    observed_changes = (
        _production_changes(root)
        if changed_production_paths is None
        else set(changed_production_paths)
    )
    result = validate_digest_boundary(
        frozen_source_rows=source_rows,
        sut_rows=sut_rows,
        actual_digests=actual,
        changed_production_paths=observed_changes,
        allowed_changed_production_files=boundary[
            "allowed_changed_production_files"
        ],
    )
    result.update(
        {
            "evaluation_id": boundary["evaluation_id"],
            "formal_evaluation_run": boundary["formal_evaluation_run"],
            "historical_formal_runs_verified": len(
                boundary["historical_formal_runs"]
            ),
            "frozen_spec_sha256": boundary["frozen_expected_spec"]["sha256"],
        }
    )
    return result
