"""Version boundary and write-once runner for the post-fix evaluation.

The v1.2 boundary keeps scientific inputs, gold semantics, and historical
formal outputs immutable while treating the explicitly declared production
adapter as the System Under Test.  The formal runner reuses the frozen v1.1
evaluation semantics while giving the post-fix run its own identity and
write-once artifact lifecycle.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from eval.scientific_decision_justification_fidelity_v1 import ROOT


BOUNDARY_PATH = (
    ROOT
    / "eval/specs/scientific_decision_justification_fidelity_v1_2.boundary.json"
)
EVALUATION_ID = "scientific-decision-justification-fidelity-v1.2"
EVALUATOR_SCHEMA_VERSION = (
    "sckg-scientific-decision-justification-fidelity-v1.2"
)
DEFAULT_OUTPUT_ROOT = (
    ROOT / "data/evaluation/scientific_decision_justification_fidelity_v1_2"
)
DECLARED_SUT_PATH = "engine/scientific_kg_applicability.py"
EXPECTED_POST_FIX_SUT_SHA256 = (
    "9d40f3ef06c3eff8653ebf8afc6d7a2995cd25aae76fa1d44bd6e6de45307722"
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


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _canonical_request_digest() -> tuple[int, str]:
    from eval.scientific_kg_contribution_v1 import frozen_requests, load_spec

    requests = frozen_requests(load_spec())
    return len(requests), _digest(requests)


@contextlib.contextmanager
def _active_frozen_contract() -> Iterator[None]:
    """Route reused verifier semantics through the immutable historical lane.

    The active v1.2 boundary validates the declared current SUT separately.
    The temporary loader binding prevents the historical source manifest from
    mistaking that declared SUT change for frozen-input drift.
    """

    import eval.scientific_decision_justification_fidelity_v1 as fidelity_v1
    import eval.scientific_decision_justification_fidelity_v1_1 as fidelity_v1_1
    from eval.scientific_decision_justification_fidelity_history import (
        load_historical_preregistration,
    )

    old_v1 = fidelity_v1.load_frozen_preregistration
    old_v1_1 = fidelity_v1_1.load_frozen_preregistration
    fidelity_v1.load_frozen_preregistration = load_historical_preregistration
    fidelity_v1_1.load_frozen_preregistration = load_historical_preregistration
    try:
        yield
    finally:
        fidelity_v1.load_frozen_preregistration = old_v1
        fidelity_v1_1.load_frozen_preregistration = old_v1_1


def _collect_current_cases() -> list[dict[str, Any]]:
    from eval.scientific_decision_justification_fidelity_v1_1 import (
        collect_current_cases,
    )

    with _active_frozen_contract():
        return collect_current_cases()


def _build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    from eval.scientific_decision_justification_fidelity_v1_1 import build_report

    with _active_frozen_contract():
        report = build_report(cases)
    boundary = _read_json(BOUNDARY_PATH)
    report["schema_version"] = EVALUATOR_SCHEMA_VERSION
    report["evaluation_id"] = EVALUATION_ID
    report["frozen_identity"].update(
        {
            "boundary_sha256": _file_hash(BOUNDARY_PATH),
            "preregistration_sha256": boundary["frozen_preregistration"][
                "sha256"
            ],
            "decision_atom_count": boundary["reused_frozen_semantics"][
                "decision_atom_count"
            ],
            "negative_control_count": boundary["reused_frozen_semantics"][
                "negative_control_count"
            ],
            "declared_sut_path": DECLARED_SUT_PATH,
            "declared_sut_sha256": _file_hash(ROOT / DECLARED_SUT_PATH),
        }
    )
    return report


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


def preflight_formal_evaluation(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    root: Path = ROOT,
    expected_sut_sha256: str = EXPECTED_POST_FIX_SUT_SHA256,
) -> dict[str, Any]:
    """Fail closed before consuming the single v1.2 formal-run ordinal."""

    output_root = output_root.resolve()
    protected = {
        (
            root
            / "data/evaluation/scientific_decision_justification_fidelity_v1"
        ).resolve(),
        (
            root
            / "data/evaluation/scientific_decision_justification_fidelity_v1_1"
        ).resolve(),
    }
    if output_root in protected:
        raise ValueError("historical_formal_output_path_forbidden")
    completed = output_root / "formal_run_completed.json"
    started = output_root / "formal_run_started.json"
    if completed.exists():
        raise FileExistsError("formal_v1_2_completed_run_exists")
    if started.exists():
        raise RuntimeError("formal_v1_2_incomplete_run_exists")
    if output_root.exists():
        raise FileExistsError("formal_v1_2_output_already_exists")

    boundary_result = validate_version_boundary(
        root=root,
        changed_production_paths={DECLARED_SUT_PATH},
    )
    sut_path = root / DECLARED_SUT_PATH
    actual_sut_sha256 = _file_hash(sut_path)
    if actual_sut_sha256 != expected_sut_sha256:
        raise ValueError("declared_v1_2_sut_digest_mismatch")
    boundary = _read_json(root / BOUNDARY_PATH.relative_to(ROOT))
    if boundary["evaluation_id"] != EVALUATION_ID:
        raise ValueError("v1_2_evaluation_identity_mismatch")
    if boundary["formal_evaluation_run"] is not False:
        raise ValueError("v1_2_boundary_already_records_formal_run")
    request_count, request_digest = _canonical_request_digest()
    source_rows = _read_json(
        root / boundary["frozen_preregistration"]["path"]
    )["source_artifact_digests"]
    return {
        **boundary_result,
        "head": _head(root),
        "output_root": str(output_root),
        "boundary_sha256": _file_hash(
            root / BOUNDARY_PATH.relative_to(ROOT)
        ),
        "preregistration_sha256": boundary["frozen_preregistration"][
            "sha256"
        ],
        "declared_sut_path": DECLARED_SUT_PATH,
        "declared_sut_sha256": actual_sut_sha256,
        "canonical_request_count": request_count,
        "canonical_request_sha256": request_digest,
        "source_artifact_digest_count": len(source_rows),
        "source_artifact_manifest_sha256": _digest(source_rows),
        "eligible": True,
    }


def run_formal_evaluation(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    root: Path = ROOT,
    expected_sut_sha256: str = EXPECTED_POST_FIX_SUT_SHA256,
    case_collector: Callable[[], list[dict[str, Any]]] = _collect_current_cases,
    report_builder: Callable[[list[dict[str, Any]]], dict[str, Any]] = _build_report,
) -> dict[str, Any]:
    """Execute the single write-once v1.2 formal evaluation.

    Tests must pass a temporary ``output_root``.  The production default is
    reserved for the separately authorized formal-run checkpoint.
    """

    preflight = preflight_formal_evaluation(
        output_root,
        root=root,
        expected_sut_sha256=expected_sut_sha256,
    )
    output_root.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(timezone.utc).isoformat()
    runner_path = root / Path(__file__).resolve().relative_to(ROOT)
    semantics_path = (
        root / "eval/scientific_decision_justification_fidelity_v1_1.py"
    )
    _write_json(
        output_root / "formal_run_started.json",
        {
            "schema_version": EVALUATOR_SCHEMA_VERSION,
            "evaluation_id": EVALUATION_ID,
            "formal_run_ordinal": 1,
            "started_at": started_at,
            "head": preflight["head"],
            "frozen_spec_sha256": preflight["frozen_spec_sha256"],
            "preregistration_sha256": preflight["preregistration_sha256"],
            "boundary_sha256": preflight["boundary_sha256"],
            "runner_sha256": _file_hash(runner_path),
            "frozen_semantics_evaluator_sha256": _file_hash(semantics_path),
            "declared_sut_path": preflight["declared_sut_path"],
            "declared_sut_sha256": preflight["declared_sut_sha256"],
            "canonical_request_count": preflight["canonical_request_count"],
            "canonical_request_sha256": preflight[
                "canonical_request_sha256"
            ],
            "source_artifact_digest_count": preflight[
                "source_artifact_digest_count"
            ],
            "source_artifact_manifest_sha256": preflight[
                "source_artifact_manifest_sha256"
            ],
        },
    )

    cases = case_collector()
    input_sha256 = _digest(cases)
    report = report_builder(cases)
    report.update(
        {
            "schema_version": EVALUATOR_SCHEMA_VERSION,
            "evaluation_id": EVALUATION_ID,
            "formal_run_ordinal": 1,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "input_sha256": input_sha256,
        }
    )
    for case in cases:
        _write_json(output_root / f"{case['scenario_id']}.json", case)
    _write_json(
        output_root / "evidence_reference_checks.json",
        {
            "schema_version": EVALUATOR_SCHEMA_VERSION,
            "evaluation_id": EVALUATION_ID,
            "evidence_fidelity": report["metrics"]["evidence_fidelity"],
            "atom_results": report["atom_results"],
            "evidence_failures": [
                row
                for row in report["failures"]
                if row["code"]
                in {
                    "EXPECTED_ATOM_MISSING",
                    "EVIDENCE_UNRESOLVABLE",
                    "CLAIM_SOURCE_BINDING_MISMATCH",
                    "EVIDENCE_DOES_NOT_SUPPORT_DECISION_ATOM",
                    "EXTRA_NON_DECISION_EVIDENCE",
                }
            ],
        },
    )
    _write_json(
        output_root / "negative_controls.json",
        {
            "schema_version": EVALUATOR_SCHEMA_VERSION,
            "evaluation_id": EVALUATION_ID,
            "results": report["negative_control_results"],
        },
    )
    _write_json(output_root / "report.json", report)
    summary_path = output_root / "SUMMARY.md"
    summary_path.write_text(
        "# Scientific Decision Justification Fidelity v1.2\n\n"
        f"- Status: **{report['status']}**\n"
        f"- Frozen spec SHA-256: `{preflight['frozen_spec_sha256']}`\n"
        f"- Declared SUT SHA-256: `{preflight['declared_sut_sha256']}`\n"
        f"- First failure: `{report['first_failure']}`\n"
        "- Historical v1 and v1.1 formal runs remain unchanged.\n",
        encoding="utf-8",
    )
    _write_json(
        output_root / "formal_run_completed.json",
        {
            "schema_version": EVALUATOR_SCHEMA_VERSION,
            "evaluation_id": EVALUATION_ID,
            "formal_run_ordinal": 1,
            "completed_at": report["finished_at"],
            "status": report["status"],
            "report_sha256": _file_hash(output_root / "report.json"),
            "summary_sha256": _file_hash(summary_path),
        },
    )
    return report


if __name__ == "__main__":
    run_formal_evaluation()
