from __future__ import annotations

import hashlib
import json

import pytest

import eval.scientific_decision_justification_fidelity_v1 as fidelity_v1
import eval.scientific_decision_justification_fidelity_v1_1 as fidelity_v1_1
from eval.scientific_decision_justification_fidelity_history import (
    load_historical_preregistration,
)
from eval.scientific_decision_justification_fidelity_v1 import (
    ROOT,
    SPEC_PATH,
    SPEC_SHA256,
    JustificationVerifier,
    apply_frozen_mutation,
    build_positive_control_cases,
)
from eval.scientific_decision_justification_fidelity_v1_1 import (
    build_report,
    representation_linkage_metrics,
)


@pytest.fixture(autouse=True)
def _use_explicit_historical_lane(monkeypatch) -> None:
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


def _historical_cases() -> list[dict]:
    root = (
        ROOT
        / "data/evaluation/scientific_decision_justification_fidelity_v1_1"
    )
    return [
        json.loads((root / f"{scenario_id}.json").read_text(encoding="utf-8"))
        for scenario_id in (
            "valid-neighbor-graph-to-leiden",
            "stale-or-misaligned-graph",
            "harmony-embedding-to-neighbors",
            "scrublet-rejects-transformed-expression",
        )
    ]


def test_frozen_spec_and_source_digests_remain_unchanged() -> None:
    spec, manifest = load_historical_preregistration()

    assert hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest() == SPEC_SHA256
    assert len(spec["atoms"]) == 12
    assert len(spec["negative_controls"]) == 8
    assert len(manifest["source_artifact_digests"]) == 13


def test_behavior_invariant_compares_unmutated_and_single_fault_outputs() -> None:
    positive = build_positive_control_cases()
    for mutation in load_historical_preregistration()[0]["negative_controls"]:
        mutated = apply_frozen_mutation(positive, mutation["mutation_id"])
        assert [row["behavior_digest"] for row in mutated] == [
            row["behavior_digest"] for row in positive
        ]


def test_historical_collector_preserved_behavior_invariant() -> None:
    cases = _historical_cases()

    assert len(cases) == 4
    assert all(
        case["behavior_digest"] == case["expected_behavior_digest"]
        for case in cases
    )


def test_harmony_producer_scope_is_not_evaluated_as_neighbors_consumer() -> None:
    cases = _historical_cases()
    harmony = next(
        atom
        for case in cases
        for atom in case["emitted_atoms"]
        if atom["atom_id"] == "atom:harmony:corrected-embedding-output"
    )
    neighbors = next(
        atom
        for case in cases
        for atom in case["emitted_atoms"]
        if atom["atom_id"] == "atom:harmony:neighbors-named-representation-input"
    )

    assert harmony["scope"]["version"]["state"] == "compatible"
    assert harmony["scope"]["task"]["state"] == "compatible"
    assert harmony["scope"]["interface"] == {
        "state": "unknown",
        "evaluation": "not_evaluated",
    }
    assert neighbors["scope"]["version"]["state"] == "compatible"
    assert neighbors["scope"]["task"]["state"] == "compatible"


def test_representation_aggregate_separates_records_and_absence() -> None:
    assert representation_linkage_metrics(build_positive_control_cases()) == {
        "concrete_records": {"numerator": 6, "denominator": 6},
        "explicit_absence": {"numerator": 1, "denominator": 1},
    }


def test_v1_1_report_preserves_negative_control_first_causes() -> None:
    report = build_report(build_positive_control_cases())

    assert report["metrics"]["negative_control_first_cause_detection"] == {
        "numerator": 8,
        "denominator": 8,
    }
    assert report["metrics"]["representation_linkage_fidelity"] == {
        "concrete_records": {"numerator": 6, "denominator": 6},
        "explicit_absence": {"numerator": 1, "denominator": 1},
    }
    assert JustificationVerifier().verify(build_positive_control_cases()).passed


def test_historical_report_preserves_scenario_local_evidence_denominators() -> None:
    report = json.loads(
        (
            ROOT
            / "data/evaluation/scientific_decision_justification_fidelity_v1_1/report.json"
        ).read_text(encoding="utf-8")
    )

    evidence = report["metrics"]["evidence_fidelity"]
    assert evidence["scientific_evidence_recall"] == {
        "numerator": 5,
        "denominator": 5,
    }
    assert evidence["evidence_object_and_binding_resolvability"] == {
        "numerator": 17,
        "denominator": 17,
    }
    assert evidence["scientific_decision_evidence_precision"] == {
        "numerator": 5,
        "denominator": 17,
    }
