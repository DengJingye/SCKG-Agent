from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.scientific_knowledge_conformance_models import ConformanceBundle
from core.trace_context import load_traces
from data_pipeline import run_candidate_knowledge_deposition_pilot_v1 as pilot


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_capability_map_reuses_existing_models_and_index():
    rows = pilot.architecture_inventory()
    assert {row["disposition"] for row in rows} <= {
        "reused_as_is",
        "thin_deposition_adapter",
        "reused_with_isolated_index_paths",
        "read_only_reuse",
        "not_allowed",
    }
    assert any("AtomicClaimRevision" in row["capability"] for row in rows)
    assert any("HybridRetrievalService" in row["existing_implementation"] for row in rows)


def test_candidate_proposition_is_narrow_and_exactly_span_supported():
    _, _, span = pilot.load_cp5_evidence()
    claim, assessment = pilot.build_candidate_records()
    assert "tod" in claim.claim_text and "toc" in claim.claim_text
    assert "droplets" in claim.claim_text and "genes" in claim.claim_text
    assert assessment.stance == "supports"
    assert assessment.evidence_span_ids == [pilot.EVIDENCE_SPAN_ID]
    assert span["exact_text"].startswith("tod Table of droplets")
    lowered = claim.claim_text.casefold()
    assert not any(term in lowered for term in pilot.FORBIDDEN_BROADENING)
    assert "raw count" not in lowered
    assert "must" not in lowered


def test_candidate_records_validate_with_existing_v1_1_models():
    claim, assessment = pilot.build_candidate_records()
    entities, scope = pilot._core_identity_slice()
    bundle = ConformanceBundle(
        fixture_id="conformance-fixture:cp6-test",
        description="CP6 validation fixture",
        scopes=[scope],
        entities=entities,
        atomic_claims=[claim],
        evidence_assessments=[assessment],
        expected_semantics=["candidate only"],
    )
    assert bundle.atomic_claims[0].subject_id == pilot.SUBJECT_ID
    assert bundle.review_decisions == []
    assert bundle.derived_relations == []


def test_complete_deposition_and_second_query_reuse(tmp_path):
    report = pilot.run_pilot(output_root=tmp_path)
    assert report["status"] == "PASS"
    assert report["knowledge_status"] == "candidate_pending_review"
    assert report["candidate_kg_deposited"] is True
    assert report["rag_deposited"] is True
    assert report["second_query_reused"] is True
    assert report["external_reacquisition_count"] == 0
    assert report["derived_relation_count"] == 0
    assert report["review_decision_count"] == 0
    assert report["canonical_promotion_performed"] is False
    assert report["canonical_kg_modified"] is False
    assert report["planner_modified"] is False
    assert report["execution_authorized"] is False
    assert report["forbidden_broadening_present"] is False

    counts = report["dedup_counts"]
    assert counts == {
        "source_work_count": 1,
        "source_revision_count": 1,
        "source_artifact_count": 1,
        "evidence_span_count": 1,
        "candidate_claim_count": 1,
        "evidence_assessment_count": 1,
    }
    second = _json(tmp_path / "second_query_result.json")
    assert second["candidate_claim_reused"] is True
    assert second["evidence_span_reused"] is True
    assert second["source_artifact_reused"] is True
    assert second["external_reacquisition_count"] == 0
    assert second["candidate_knowledge_status"] == "candidate_pending_review"
    assert second["retrieved_chunk_ids"] == ["source:cp6:soupx:soupchannel-inputs:1.6.2"]
    assert second["retrieved_source_ids"] == [pilot.SOURCE_REVISION_ID]


def test_deposition_artifacts_preserve_governance_and_provenance(tmp_path):
    pilot.run_pilot(output_root=tmp_path)
    bundle = ConformanceBundle.model_validate(_json(tmp_path / "conformance_bundle.json"))
    claim = bundle.atomic_claims[0]
    assessment = bundle.evidence_assessments[0]
    risk = _jsonl(tmp_path / "risk_registry.jsonl")[0]
    graph = _json(tmp_path / "candidate_overlay_graph.json")
    provenance = _json(tmp_path / "provenance.json")
    lifecycle = _json(tmp_path / "evidence_gap_lifecycle.json")

    assert assessment.claim_revision_id == claim.claim_revision_id
    assert assessment.evidence_span_ids == [pilot.EVIDENCE_SPAN_ID]
    assert risk["review_status"] == "candidate_pending_review"
    assert risk["review_requirement"] == "qualified_human"
    assert graph["knowledge_status"] == "candidate_pending_review"
    assert graph["forbidden_derived_relations_created"] == []
    assert any(edge["relation"] == "SUPPORTS" for edge in graph["edges"])
    assert provenance["source_artifact_sha256"] == pilot.SOURCE_ARTIFACT_SHA256
    assert provenance["software_context_id"] == pilot.SUBJECT_ID
    assert claim.scope_id == "scope:cp6:soupx:soupchannel:1.6.2"
    assert lifecycle["events"] == [
        "unresolved",
        "evidence_acquired",
        "candidate_knowledge_created",
        "pending_review",
    ]
    assert lifecycle["canonical_resolution_status"] == "unresolved"


def test_trace_is_bounded_and_reconstructs_deposition(tmp_path):
    pilot.run_pilot(output_root=tmp_path)
    traces = load_traces(tmp_path / "trace.jsonl")
    assert len(traces) == 1
    stages = [span["stage"] for span in traces[0]["spans"]]
    assert stages == [
        "REQUEST",
        "STATE_INSPECTION",
        "RETRIEVAL",
        "DECISION",
        "VALIDATION",
        "DECISION",
        "RETRIEVAL",
        "RETRIEVAL",
        "VALIDATION",
    ]
    raw = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert "tod Table of droplets" not in raw
    assert str(tmp_path) not in raw
    assert pilot.SOURCE_ARTIFACT_ID in raw
    assert pilot.EVIDENCE_SPAN_ID in raw
    assert pilot.build_candidate_records()[0].claim_revision_id in raw


def test_pilot_is_write_once_and_cannot_duplicate_claim(tmp_path):
    first = pilot.run_pilot(output_root=tmp_path)
    claim_rows = _jsonl(tmp_path / "candidate_atomic_claims.jsonl")
    assert len(claim_rows) == 1
    assert claim_rows[0]["claim_revision_id"] == first["claim_revision_id"]
    with pytest.raises(FileExistsError, match="already_completed"):
        pilot.run_pilot(output_root=tmp_path)
    assert len(_jsonl(tmp_path / "candidate_atomic_claims.jsonl")) == 1


def test_existing_candidate_and_canonical_sources_are_not_mutated(tmp_path):
    core_claims = pilot.CORE_CANDIDATE_ROOT / "scientific_kg_v1_core" / "atomic_claims.jsonl"
    canonical_nodes = pilot.PROJECT_ROOT / "data" / "knowledge_graph_v2" / "nodes.jsonl"
    before = (pilot._sha_file(core_claims), pilot._sha_file(canonical_nodes))
    pilot.run_pilot(output_root=tmp_path)
    after = (pilot._sha_file(core_claims), pilot._sha_file(canonical_nodes))
    assert before == after
