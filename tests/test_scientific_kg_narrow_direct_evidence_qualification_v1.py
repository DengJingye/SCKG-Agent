from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.research_tool_registry import ResearchToolRegistry
from engine.scientific_kg_evidence import ScientificKGEvidence
from eval import retrieval_benchmark_v1_1_dev as foundation
from eval.scientific_kg_narrow_direct_evidence_qualification_v1 import (
    EXPECTED_CASES_SHA256,
    OUTPUT,
    _negative_controls,
    _run_case,
    load_cases,
    protected_hashes,
    sha256,
)


@pytest.fixture(scope="module")
def qualification():
    cases = load_cases()
    service = foundation._service(None)
    registry = ResearchToolRegistry(retrieval=service)
    adapter = ScientificKGEvidence()
    rows = [_run_case(registry, adapter, case)[0] for case in cases]
    return cases, rows, service


def test_frozen_manifest_has_six_operators_and_three_cases_each():
    cases = load_cases()
    assert sha256(OUTPUT / "qualification_cases.jsonl") == EXPECTED_CASES_SHA256
    assert len(cases) == 18
    assert {case["operator"] for case in cases} == {
        "HVG", "PCA", "NEIGHBORS", "UMAP", "LEIDEN", "SINGLER",
    }
    assert all(sum(item["operator"] == operator for item in cases) == 3 for operator in {
        "HVG", "PCA", "NEIGHBORS", "UMAP", "LEIDEN", "SINGLER",
    })


def test_real_registry_path_resolves_all_expected_subjects_and_revisions(qualification):
    _, rows, _ = qualification
    assert all(row["production_entry"] == "ResearchToolRegistry.execute/search_evidence" for row in rows)
    assert all(row["production_input_fields"] == ["query"] for row in rows)
    assert all(row["gold_forwarded_to_production"] is False for row in rows)
    assert all(row["subject_resolution_correct"] for row in rows)
    assert all(row["operator_revision_correct"] for row in rows)


def test_natural_language_supported_cases_reach_exact_candidate_evidence(qualification):
    _, rows, _ = qualification
    indirect = [row for row in rows if row["case_kind"] == "indirect_supported"]
    assert len(indirect) == 6
    by_id = {row["case_id"]: row for row in indirect}
    assert all(row["candidate_only"] for row in indirect)
    assert all(row["observed_evidence_span_ids"] for row in indirect)
    assert all(row["observed_source_revision_ids"] for row in indirect)
    assert all(row["observed_answerability"] == "SUPPORTED" for row in indirect)
    assert by_id["qual-neighbors-indirect-input"]["public_filter_rejected_chunk_ids"] == []
    frozen = next(
        json.loads(line)
        for line in (OUTPUT / "per_case_resolution.jsonl").read_text().splitlines()
        if '"case_id": "qual-neighbors-indirect-input"' in line
    )
    assert frozen["observed_answerability"] == "UNRESOLVED"
    assert frozen["public_filter_rejected_chunk_ids"] == [
        "scanpy-authoritative-span:neighbors.input:1.11.2"
    ]


def test_claim_type_mismatch_and_unmapped_evidence_do_not_fabricate_support(qualification):
    _, rows, _ = qualification
    by_id = {row["case_id"]: row for row in rows}
    umap = by_id["qual-umap-unsupported-output"]
    assert umap["observed_answerability"] == "UNRESOLVED"
    assert umap["observed_claim_ids"] == []
    assert umap["observed_evidence_span_ids"] == []
    leiden = by_id["qual-leiden-unmapped-output"]
    assert leiden["observed_evidence_span_ids"] == [
        "scanpy-authoritative-span:leiden.output:1.11.2"
    ]
    assert leiden["observed_direct_evidence_chunk_ids"] == []
    assert leiden["observed_answerability"] == "UNRESOLVED"


def test_scope_version_and_ambiguity_are_preserved(qualification):
    _, rows, service = qualification
    by_id = {row["case_id"]: row for row in rows}
    assert by_id["qual-hvg-scope-mismatch"]["observed_answerability"] == "UNRESOLVED"
    assert by_id["qual-pca-version-mismatch"]["subject_resolution"]["status"] == "UNRESOLVED"
    assert by_id["qual-pca-version-mismatch"]["observed_answerability"] == "UNRESOLVED"
    assert by_id["qual-singler-version-clarification"]["observed_answerability"] == "CLARIFICATION_REQUIRED"
    controls = _negative_controls(service, rows)
    assert controls["all_passed"] is True
    assert controls["ambiguity_control"]["subject_resolution"]["status"] == "AMBIGUOUS"


def test_single_r_leakage_is_explicit_and_not_repaired(qualification):
    _, rows, _ = qualification
    row = next(item for item in rows if item["case_id"] == "qual-singler-indirect-compatibility")
    assert row["observed_answerability"] == "SUPPORTED"
    assert row["claim_type_fidelity"] is False
    assert row["failure_class"] == "CLAIM_SELECTION_ERROR"
    assert row["unrelated_claim_ids"] == [
        "claim-revision:uat:singler-query:v1",
        "claim-revision:uat:singler-reference-expression:v1",
        "claim-revision:uat:singler-reference-labels:v1",
    ]


def test_provenance_paths_include_assessment_source_chunk_and_candidate_status():
    rows = [
        json.loads(line)
        for line in (OUTPUT / "provenance_paths.jsonl").read_text().splitlines()
        if line
    ]
    assert rows
    assert all(row["operator_revision_id"] for row in rows)
    assert all(row["claim_revision_id"] for row in rows)
    assert all(row["scope_id"] for row in rows)
    assert all(row["evidence_assessment_id"] for row in rows)
    assert all(row["evidence_span_id"] for row in rows)
    assert all(row["source_revision_id"] for row in rows)
    assert all(row["knowledge_status"] == "candidate" for row in rows)
    assert any(row["rag_chunk_id"] and row["production_eligible"] for row in rows)


def test_protected_assets_and_historical_artifacts_match_integrity_record():
    integrity = json.loads((OUTPUT / "integrity.json").read_text())
    assert integrity["protected_equal"] is True
    frozen = dict(integrity["protected_after"])
    current = protected_hashes()
    # The later neighbors checkpoint intentionally repairs this one production
    # owner; every other qualification-protected artifact remains unchanged.
    frozen.pop("engine/hybrid_retrieval.py")
    current.pop("engine/hybrid_retrieval.py")
    assert frozen == current
    assert integrity["sealed_payload_accessed"] is False
    assert integrity["sealed_validation_rerun"] is False
    assert integrity["scientific_content_added"] is False
    assert integrity["corpus_changed"] is False
    assert integrity["index_rebuilt"] is False
    assert integrity["planner_changed"] is False
    assert integrity["tool_contract_changed"] is False
    assert integrity["capability_pack_changed"] is False


def test_runner_has_no_c7_loader_or_c7_artifact_dependency():
    source = Path(__file__).parents[1].joinpath(
        "eval/scientific_kg_narrow_direct_evidence_qualification_v1.py"
    ).read_text()
    assert "dev_only_c7_loader" not in source
    assert "independent_retrieval_validation_v1" not in source
    assert "eval_v2" not in source
