from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import eval.scientific_decision_justification_fidelity_history as history
import eval.scientific_decision_justification_fidelity_v1 as fidelity_v1
import eval.scientific_decision_justification_fidelity_v1_1 as fidelity_v1_1
import eval.scientific_decision_justification_fidelity_v1_2 as fidelity_v1_2
from eval.scientific_decision_justification_fidelity_history import (
    load_historical_preregistration,
)
from eval.scientific_decision_justification_fidelity_v1 import ROOT
from eval.scientific_decision_justification_fidelity_v1_1 import (
    build_report,
    collect_current_cases,
)
from eval.scientific_decision_justification_fidelity_v1_2 import (
    BOUNDARY_PATH,
    EVALUATION_ID,
    EVALUATOR_SCHEMA_VERSION,
    EXPECTED_POST_FIX_SUT_SHA256,
    preflight_formal_evaluation,
    run_formal_evaluation,
    validate_digest_boundary,
    validate_version_boundary,
)


DECLARED_SUT = "engine/scientific_kg_applicability.py"


def _boundary_inputs():
    boundary = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    preregistration = json.loads(
        (
            ROOT / boundary["frozen_preregistration"]["path"]
        ).read_text(encoding="utf-8")
    )
    sources = [
        *preregistration["source_artifact_digests"],
        {
            "path": boundary["frozen_expected_spec"]["path"],
            "sha256": boundary["frozen_expected_spec"]["sha256"],
        },
    ]
    actual = {
        row["path"]: hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest()
        for row in sources
    }
    return boundary, sources, actual


def test_current_boundary_accepts_declared_cp3_sut_and_has_not_run_v1_2() -> None:
    result = validate_version_boundary(changed_production_paths={DECLARED_SUT})

    assert result["historical_formal_runs_verified"] == 2
    assert result["formal_evaluation_run"] is False
    assert result["frozen_spec_sha256"] == (
        "989bdf9b51a5e0529174a5a7b2da0bfe9735a6142fecbac9d985306cf6f61a85"
    )
    assert result["declared_production_changes"] == [DECLARED_SUT]
    assert result["sut_observations"][0]["changed"] is True
    assert (
        result["sut_observations"][0]["post_fix_sha256"]
        != result["sut_observations"][0]["pre_fix_sha256"]
    )


def test_historical_lane_does_not_silently_route_through_v1_2(monkeypatch) -> None:
    monkeypatch.setattr(
        fidelity_v1_2,
        "validate_version_boundary",
        lambda **_: (_ for _ in ()).throw(AssertionError("unexpected v1.2 route")),
    )

    result = history.verify_historical_integrity()

    assert result["historical_run_count"] == 2
    assert result["current_worktree_sut_checked"] is False


def test_v1_2_lane_does_not_reinterpret_historical_lane(monkeypatch) -> None:
    monkeypatch.setattr(
        history,
        "verify_historical_integrity",
        lambda **_: (_ for _ in ()).throw(AssertionError("unexpected history route")),
    )

    result = validate_version_boundary(changed_production_paths={DECLARED_SUT})

    assert result["historical_formal_runs_verified"] == 2
    assert result["sut_observations"][0]["changed"] is True


def test_active_v1_2_lane_measures_current_cp3_projection(monkeypatch) -> None:
    validate_version_boundary(changed_production_paths={DECLARED_SUT})
    monkeypatch.setattr(
        fidelity_v1,
        "load_frozen_preregistration",
        load_historical_preregistration,
    )
    monkeypatch.setattr(
        fidelity_v1_1,
        "load_frozen_preregistration",
        load_historical_preregistration,
    )

    report = build_report(collect_current_cases())
    evidence = report["metrics"]["evidence_fidelity"]

    assert evidence["scientific_evidence_recall"] == {
        "numerator": 5,
        "denominator": 5,
    }
    assert evidence["scientific_decision_evidence_precision"] == {
        "numerator": 5,
        "denominator": 5,
    }
    assert evidence["non_scientific_evidence_abstention"] == {
        "numerator": 7,
        "denominator": 7,
    }
    assert report["metrics"]["negative_control_first_cause_detection"] == {
        "numerator": 8,
        "denominator": 8,
    }


def test_explicit_sut_change_records_before_and_after_digest() -> None:
    boundary, sources, actual = _boundary_inputs()
    path = boundary["allowed_changed_production_files"][0]
    actual[path] = "1" * 64

    result = validate_digest_boundary(
        frozen_source_rows=sources,
        sut_rows=boundary["system_under_test_artifacts"],
        actual_digests=actual,
        changed_production_paths={path},
        allowed_changed_production_files=boundary[
            "allowed_changed_production_files"
        ],
    )

    assert result["sut_observations"] == [
        {
            "path": path,
            "pre_fix_sha256": (
                "cd4df0b5ef25679070b3eca0108aabf9a8af98575f68b32d6c21481bcb7e3eac"
            ),
            "post_fix_sha256": "1" * 64,
            "changed": True,
        }
    ]


@pytest.mark.parametrize(
    "path",
    [
        "eval/specs/scientific_decision_justification_fidelity_v1.expected.json",
        (
            "data/evidence_candidates/scientific_kg_v1_uat_decision_rules/"
            "authoritative_evidence_spans.jsonl"
        ),
    ],
)
def test_immutable_spec_or_evidence_change_is_hard_failure(path: str) -> None:
    boundary, sources, actual = _boundary_inputs()
    actual[path] = "2" * 64

    with pytest.raises(
        ValueError, match="immutable_evaluation_artifact_digest_mismatch"
    ):
        validate_digest_boundary(
            frozen_source_rows=sources,
            sut_rows=boundary["system_under_test_artifacts"],
            actual_digests=actual,
            changed_production_paths=set(),
            allowed_changed_production_files=boundary[
                "allowed_changed_production_files"
            ],
        )


def test_undeclared_production_change_is_hard_failure() -> None:
    boundary, sources, actual = _boundary_inputs()
    path = "engine/capability_planner.py"
    actual[path] = "3" * 64

    with pytest.raises(ValueError, match="undeclared_production_change"):
        validate_digest_boundary(
            frozen_source_rows=sources,
            sut_rows=boundary["system_under_test_artifacts"],
            actual_digests=actual,
            changed_production_paths={path},
            allowed_changed_production_files=boundary[
                "allowed_changed_production_files"
            ],
        )


def test_sut_digest_change_must_be_declared() -> None:
    boundary, sources, actual = _boundary_inputs()
    path = boundary["allowed_changed_production_files"][0]
    actual[path] = "4" * 64

    with pytest.raises(
        ValueError, match="undeclared_system_under_test_digest_change"
    ):
        validate_digest_boundary(
            frozen_source_rows=sources,
            sut_rows=boundary["system_under_test_artifacts"],
            actual_digests=actual,
            changed_production_paths=set(),
            allowed_changed_production_files=boundary[
                "allowed_changed_production_files"
            ],
        )


@pytest.fixture(scope="module")
def completed_v1_2_run(tmp_path_factory):
    output = tmp_path_factory.mktemp("v1-2-formal") / "formal"
    historical_before = {
        row["path"]: history._tree_hash(ROOT / row["path"])
        for row in json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))[
            "historical_formal_runs"
        ]
    }

    report = run_formal_evaluation(output)

    historical_after = {
        path: history._tree_hash(ROOT / path) for path in historical_before
    }
    assert historical_after == historical_before
    return output, report


def test_v1_2_formal_runner_emits_only_v1_2_identity(completed_v1_2_run) -> None:
    output, report = completed_v1_2_run
    started = json.loads(
        (output / "formal_run_started.json").read_text(encoding="utf-8")
    )
    completed = json.loads(
        (output / "formal_run_completed.json").read_text(encoding="utf-8")
    )

    assert started["schema_version"] == EVALUATOR_SCHEMA_VERSION
    assert started["evaluation_id"] == EVALUATION_ID
    assert completed["schema_version"] == EVALUATOR_SCHEMA_VERSION
    assert completed["evaluation_id"] == EVALUATION_ID
    assert report["schema_version"] == EVALUATOR_SCHEMA_VERSION
    assert report["evaluation_id"] == EVALUATION_ID
    assert EXPECTED_POST_FIX_SUT_SHA256 == started["declared_sut_sha256"]
    assert (output / "evidence_reference_checks.json").is_file()
    assert (output / "negative_controls.json").is_file()
    assert not (ROOT / "data/evaluation/scientific_decision_justification_fidelity_v1_2").exists()


def test_v1_2_formal_runner_reuses_frozen_semantics_unchanged(
    completed_v1_2_run,
) -> None:
    output, report = completed_v1_2_run
    boundary = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    spec_path = ROOT / boundary["frozen_expected_spec"]["path"]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    assert hashlib.sha256(spec_path.read_bytes()).hexdigest() == (
        boundary["frozen_expected_spec"]["sha256"]
    )
    assert len(spec["atoms"]) == len(report["atom_results"]) == 12
    assert len(spec["negative_controls"]) == len(
        report["negative_control_results"]
    ) == 8
    assert set(report["metrics"]) == {
        "evidence_fidelity",
        "scope_fidelity",
        "representation_linkage_fidelity",
        "epistemic_state_fidelity",
        "ownership_fidelity",
        "behavior_digest_invariance",
        "negative_control_first_cause_detection",
    }
    assert json.loads(
        (output / "negative_controls.json").read_text(encoding="utf-8")
    )["results"] == report["negative_control_results"]


def test_v1_2_preflight_rejects_sut_digest_drift(tmp_path) -> None:
    with pytest.raises(ValueError, match="declared_v1_2_sut_digest_mismatch"):
        preflight_formal_evaluation(
            tmp_path / "formal",
            expected_sut_sha256="0" * 64,
        )


def test_v1_2_write_once_guards_started_and_completed_runs(
    tmp_path,
    completed_v1_2_run,
) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / "formal_run_started.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="incomplete_run_exists"):
        preflight_formal_evaluation(incomplete)

    completed, _ = completed_v1_2_run
    with pytest.raises(FileExistsError, match="completed_run_exists"):
        run_formal_evaluation(completed)


def test_v1_2_failure_after_start_remains_auditable_and_non_rerunnable(
    tmp_path,
) -> None:
    output = tmp_path / "failed-after-start"

    def fail_collection():
        raise RuntimeError("injected_collection_failure")

    with pytest.raises(RuntimeError, match="injected_collection_failure"):
        run_formal_evaluation(output, case_collector=fail_collection)

    assert (output / "formal_run_started.json").is_file()
    assert not (output / "formal_run_completed.json").exists()
    with pytest.raises(RuntimeError, match="incomplete_run_exists"):
        run_formal_evaluation(output)


def test_v1_2_rejects_historical_output_paths() -> None:
    for name in (
        "scientific_decision_justification_fidelity_v1",
        "scientific_decision_justification_fidelity_v1_1",
    ):
        with pytest.raises(ValueError, match="historical_formal_output_path_forbidden"):
            preflight_formal_evaluation(ROOT / "data/evaluation" / name)
