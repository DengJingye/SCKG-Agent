from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import eval.scientific_decision_justification_fidelity_history as history
import eval.scientific_decision_justification_fidelity_v1 as fidelity_v1
from eval.scientific_decision_justification_fidelity_history import (
    load_historical_preregistration,
    verify_historical_integrity,
)
from eval.scientific_decision_justification_fidelity_v1 import (
    PREREGISTRATION_PATH,
    SPEC_PATH,
    SPEC_SHA256,
    FrozenKnowledgeRegistry,
    JustificationVerifier,
    apply_frozen_mutation,
    build_positive_control_cases,
    mutation_changes_only_declared_dimension,
)


EXPECTED_MUTATIONS = {
    "mutation:wrong-evidence:leiden-output-for-input": "EVIDENCE_DOES_NOT_SUPPORT_DECISION_ATOM",
    "mutation:binding-mismatch:harmony-span-neighbors-claim": "CLAIM_SOURCE_BINDING_MISMATCH",
    "mutation:representation-link:valid-to-stale-record": "REPRESENTATION_LINK_WRONG",
    "mutation:epistemic:candidate-to-trusted": "EPISTEMIC_STATUS_CONFLATION",
    "mutation:scope:scrublet-capture-unknown-to-compatible": "SCOPE_SILENTLY_WIDENED",
    "mutation:scope:scrublet-capture-unknown-to-incompatible": "SCOPE_MISMATCH",
    "mutation:runtime-citation:stale-record": "OWNER_MISATTRIBUTION",
    "mutation:owner:ledger-absence-to-scientific-kg": "OWNER_MISATTRIBUTION",
}


def _atom(cases, atom_id):
    return next(atom for case in cases for atom in case["emitted_atoms"] if atom["atom_id"] == atom_id)


@pytest.fixture(autouse=True)
def _use_explicit_historical_lane(monkeypatch) -> None:
    monkeypatch.setattr(
        fidelity_v1,
        "load_frozen_preregistration",
        load_historical_preregistration,
    )


def test_frozen_spec_and_preregistration_manifest_are_integrity_verified() -> None:
    spec, manifest = load_historical_preregistration()

    assert hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest() == SPEC_SHA256
    assert manifest["expected_spec"]["sha256"] == SPEC_SHA256
    assert manifest["expected_spec"]["path"] == SPEC_PATH.relative_to(SPEC_PATH.parents[2]).as_posix()
    assert PREREGISTRATION_PATH.is_file()
    assert manifest["formal_evaluation_run"] is False


def test_exact_frozen_atom_and_mutation_sets_are_loaded() -> None:
    spec, manifest = load_historical_preregistration()

    assert len(spec["atoms"]) == manifest["counts"]["atom_count"] == 12
    assert len(spec["negative_controls"]) == manifest["counts"]["negative_control_count"] == 8
    assert {row["mutation_id"]: row["expected_first_failure"] for row in spec["negative_controls"]} == EXPECTED_MUTATIONS


def test_all_thirteen_source_artifacts_are_digest_verified() -> None:
    result = verify_historical_integrity()

    assert result["historical_source_count"] == 13
    assert result["historical_sut_paths"] == [
        "engine/scientific_kg_applicability.py"
    ]
    assert result["current_worktree_sut_checked"] is False


def test_tampered_historical_report_is_rejected(monkeypatch) -> None:
    original = history._file_hash

    def tampered(path: Path) -> str:
        if path.as_posix().endswith(
            "scientific_decision_justification_fidelity_v1/report.json"
        ):
            return "0" * 64
        return original(path)

    monkeypatch.setattr(history, "_file_hash", tampered)
    with pytest.raises(ValueError, match="historical_formal_tree_mismatch"):
        verify_historical_integrity()


def test_tampered_historical_manifest_is_rejected(monkeypatch) -> None:
    original = history._file_hash

    def tampered(path: Path) -> str:
        if path == PREREGISTRATION_PATH:
            return "0" * 64
        return original(path)

    monkeypatch.setattr(history, "_file_hash", tampered)
    with pytest.raises(ValueError, match="historical_preregistration_digest_mismatch"):
        verify_historical_integrity()


def test_historical_recorded_sut_digest_mismatch_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(history, "_git_blob_hash", lambda *_: "0" * 64)

    with pytest.raises(ValueError, match="historical_recorded_sut_digest_mismatch"):
        verify_historical_integrity()


def test_positive_controls_cover_all_atoms_and_pass() -> None:
    cases = build_positive_control_cases()
    result = JustificationVerifier().verify(cases)

    assert result.passed is True
    assert result.first_failure is None
    assert result.atom_count == 12


def test_positive_runtime_atoms_resolve_real_ledger_records_and_absence() -> None:
    cases = build_positive_control_cases()

    assert _atom(cases, "atom:valid-graph:record-state")["representation_record_id"] == "rep:demo:neighbor-graph:valid"
    assert _atom(cases, "atom:invalid-graph:stale-record-state")["representation_record_id"] == "rep:demo:neighbor-graph:stale"
    assert _atom(cases, "atom:invalid-graph:misaligned-record-state")["representation_record_id"] == "rep:demo:neighbor-graph:misaligned"
    assert _atom(cases, "atom:scrublet:raw-umi-absence")["representation_absence"] == {
        "representation_type_id": "representation-type:raw_umi_counts",
        "matching_record_count": 0,
    }


def test_positive_scientific_and_runtime_ownership_is_separate() -> None:
    cases = build_positive_control_cases()
    atoms = [atom for case in cases for atom in case["emitted_atoms"]]

    scientific = [atom for atom in atoms if atom["primary_owner"] == "SCIENTIFIC_KG"]
    runtime = [atom for atom in atoms if atom["primary_owner"] == "REPRESENTATION_LEDGER_PROFILER"]
    assert len(scientific) == 5 and all(atom["scientific_evidence_bindings"] for atom in scientific)
    assert len(runtime) == 7 and all(not atom["scientific_evidence_bindings"] for atom in runtime)


def test_scope_unknown_dimensions_remain_unknown_and_not_evaluated() -> None:
    cases = build_positive_control_cases()

    harmony = _atom(cases, "atom:harmony:corrected-embedding-output")
    scrublet = _atom(cases, "atom:scrublet:raw-umi-input")
    assert harmony["scope"]["interface"] == {"state": "unknown", "evaluation": "not_evaluated"}
    assert scrublet["scope"]["capture_or_sample_unit"] == {"state": "unknown", "evaluation": "not_evaluated"}
    assert scrublet["scope"]["droplet_umi_study_design"] == {"state": "unknown", "evaluation": "not_evaluated"}


def test_evidence_registry_checks_object_resolution_before_binding() -> None:
    registry = FrozenKnowledgeRegistry.load()
    cases = build_positive_control_cases()
    reference = _atom(cases, "atom:harmony:corrected-embedding-output")["scientific_evidence_bindings"][0]

    assert registry.resolution_failure(reference) is None
    assert registry.binding_valid(reference) is True
    missing = {**reference, "evidence_span_id": "missing:evidence-span"}
    assert registry.resolution_failure(missing) == "missing_claim_hash_or_span_object"


def test_individually_valid_objects_with_invalid_relationship_are_binding_mismatch() -> None:
    cases = build_positive_control_cases()
    atom = _atom(cases, "atom:harmony:corrected-embedding-output")
    atom["scientific_evidence_bindings"][0]["claim_revision_id"] = "claim-revision:uat:neighbors-input:v1"
    case = next(case for case in cases if case["scenario_id"] == atom["scenario_id"])
    case["scenario_scientific_references"] = copy.deepcopy(atom["scientific_evidence_bindings"])

    result = JustificationVerifier().verify(cases)
    assert result.first_failure == "CLAIM_SOURCE_BINDING_MISMATCH"


def test_missing_evidence_object_is_not_misclassified_as_binding_mismatch() -> None:
    cases = build_positive_control_cases()
    atom = _atom(cases, "atom:harmony:corrected-embedding-output")
    atom["scientific_evidence_bindings"][0]["evidence_span_id"] = "missing:evidence-span"
    case = next(case for case in cases if case["scenario_id"] == atom["scenario_id"])
    case["scenario_scientific_references"] = copy.deepcopy(atom["scientific_evidence_bindings"])

    result = JustificationVerifier().verify(cases)
    assert result.first_failure == "EVIDENCE_UNRESOLVABLE"


def test_behavior_digest_is_the_first_failure_and_is_independent_of_atoms() -> None:
    cases = build_positive_control_cases()
    cases[0]["behavior_digest"] = "f" * 64

    result = JustificationVerifier().verify(cases)
    assert result.first_failure == "BEHAVIOR_MUTATED"


def test_scientific_evidence_cannot_prove_a_runtime_fact() -> None:
    cases = build_positive_control_cases()
    runtime_atom = _atom(cases, "atom:invalid-graph:stale-record-state")
    runtime_atom["scientific_evidence_bindings"] = copy.deepcopy(
        _atom(cases, "atom:valid-graph:leiden-input")["scientific_evidence_bindings"]
    )

    result = JustificationVerifier().verify(cases)
    assert result.first_failure == "OWNER_MISATTRIBUTION"


def test_candidate_status_is_distinct_from_trusted() -> None:
    cases = build_positive_control_cases()
    _atom(cases, "atom:harmony:corrected-embedding-output")["knowledge_status"] = "trusted"

    result = JustificationVerifier().verify(cases)
    assert result.first_failure == "EPISTEMIC_STATUS_CONFLATION"


@pytest.mark.parametrize(("mutation_id", "expected_failure"), EXPECTED_MUTATIONS.items())
def test_each_frozen_mutation_changes_one_dimension_and_has_unique_first_failure(
    mutation_id: str, expected_failure: str
) -> None:
    positive = build_positive_control_cases()
    mutated = apply_frozen_mutation(positive, mutation_id)

    assert [case["behavior_digest"] for case in mutated] == [case["behavior_digest"] for case in positive]
    assert mutation_changes_only_declared_dimension(positive, mutated, mutation_id)
    result = JustificationVerifier().verify(mutated)
    assert result.passed is False
    assert result.first_failure == expected_failure


def test_valid_nondecision_reference_is_kept_in_precision_denominator_and_rejected() -> None:
    cases = build_positive_control_cases()
    atom = _atom(cases, "atom:valid-graph:leiden-input")
    registry = FrozenKnowledgeRegistry.load()
    extra = registry.enrich_reference(
        {
            "claim_revision_id": "claim-revision:uat:leiden-output:v1",
            "evidence_span_id": "scanpy-authoritative-span:leiden.output:1.11.2",
            "source_revision_id": "source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa",
            "locator": "src/scanpy/tools/_leiden.py#L108-L118",
            "content_hash": "c1259b85e010c20046cc5b7d8418a5e937307ea0207bef28ee6e35873f14bd06",
        }
    )
    case = next(case for case in cases if case["scenario_id"] == atom["scenario_id"])
    case["scenario_scientific_references"].append(extra)

    result = JustificationVerifier().verify(cases)
    assert result.first_failure == "EXTRA_NON_DECISION_EVIDENCE"


def test_spec_files_are_json_and_are_not_modified_by_verification() -> None:
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (SPEC_PATH, PREREGISTRATION_PATH)}
    JustificationVerifier().verify(build_positive_control_cases())
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (SPEC_PATH, PREREGISTRATION_PATH)}

    assert before == after
    assert before[SPEC_PATH] == SPEC_SHA256
