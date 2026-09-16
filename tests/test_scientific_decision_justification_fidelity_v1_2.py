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
