from __future__ import annotations

import json
import subprocess

from agent.research_tool_registry import ResearchToolRegistry
from core.knowledge_intelligence_models import HybridRetrievalRequest
from core.research_agent_models import ResearchToolCall, ResearchToolPlan
from engine.evidence_discovery_index import EvidenceChunk
from engine.hybrid_retrieval import HybridRetrievalService
from eval import retrieval_benchmark_v1_1_dev as foundation


QUERY = "For Scanpy nearest-neighbor graph construction, what input representation does it accept?"


def _request(query: str = QUERY) -> HybridRetrievalRequest:
    return HybridRetrievalRequest(
        query=query,
        tool_names=["Scanpy"],
        canonical_tasks=["neighbor_graph_construction"],
        top_k=10,
        include_catalog=False,
        enable_sparse=True,
        enable_dense=False,
        use_kg=True,
        use_governance_rerank=True,
        use_contract_gate=True,
        use_scientific_evidence=True,
    )


def _chunk(*, chunk_id: str, tool: str, task: str, text: str) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        evidence_id=chunk_id,
        source_kind="source_document",
        source_table="frozen.jsonl",
        source_record_id=chunk_id,
        source_id="source:fixed",
        source_document_id="source:fixed",
        source_span="fixed#L1-L2",
        tool_name=tool,
        tool_names=[tool],
        task=task,
        canonical_task=task,
        task_tags=[task],
        claim_type="input_requirement",
        title="Fixed evidence",
        chunk_text=text,
        source_bound=True,
        retrieval_status="retrieval_only",
    )


def _filter(chunk: EvidenceChunk, *, claim_owned: bool, task: str = "neighbor_graph_construction"):
    service = object.__new__(HybridRetrievalService)
    service._chunks_by_id = {chunk.chunk_id: chunk}
    return service._filter_ranked(
        [(chunk.chunk_id, 1.0)],
        request=_request(),
        task_ids={task},
        candidate_tools={"scanpy"},
        scientific_claim_owned_chunk_ids={chunk.chunk_id} if claim_owned else set(),
    )


def _production_result(query: str = QUERY):
    registry = ResearchToolRegistry(retrieval=foundation._service(None))
    plan = ResearchToolPlan(
        source="semantic_parser",
        answer_strategy="grounded",
        calls=[ResearchToolCall(
            call_id="neighbors-repair",
            tool_name="search_evidence",
            query=query,
            top_k=10,
        )],
    )
    return registry.execute(
        plan,
        fallback_query=query,
        fallback_task="",
        enable_dense=False,
        use_kg=True,
        use_governance_rerank=True,
        use_contract_gate=True,
    ).retrieval


def test_exact_neighbors_span_maps_to_frozen_chunk_and_is_publicly_eligible():
    result = _production_result()
    assert result.answerability.status == "SUPPORTED"
    assert result.answerability.direct_evidence_chunk_ids == [
        "scanpy-authoritative-span:neighbors.input:1.11.2"
    ]
    diagnostic = result.scientific_evidence
    assert diagnostic["mapped_chunk_ids"] == diagnostic["eligible_chunk_ids"]
    assert diagnostic["public_filter_rejected_chunk_ids"] == []
    assert diagnostic["paths"][0]["evidence"][0]["mapping_basis"] == (
        "span_identity_source_revision_locator_hash_and_exact_excerpt"
    )


def test_source_may_mention_another_method_without_changing_bound_claim_owner():
    chunk = _chunk(
        chunk_id="span:neighbors-input",
        tool="Harmony",
        task="neighbor_graph_construction",
        text="Harmony output may be supplied as a representation to the consumer.",
    )
    assert _filter(chunk, claim_owned=True) == [(chunk.chunk_id, 1.0)]


def test_producer_output_can_support_consumer_input_proposition():
    chunk = _chunk(
        chunk_id="span:producer-output-consumer-input",
        tool="PCA",
        task="neighbor_graph_construction",
        text="PCA coordinates are accepted by the downstream neighbor graph consumer.",
    )
    assert _filter(chunk, claim_owned=True) == [(chunk.chunk_id, 1.0)]


def test_genuinely_harmony_scoped_claim_remains_outside_neighbors_scope():
    result = _production_result("What input does Harmony require?")
    diagnostic = result.scientific_evidence
    assert diagnostic["subject_resolution"]["selected_operator_id"] == (
        "operator:harmony.RunHarmony"
    )
    assert all("neighbors" not in claim_id for claim_id in result.answerability.claim_ids)


def test_unbound_harmony_chunk_is_still_rejected_for_scanpy_neighbors():
    chunk = _chunk(
        chunk_id="span:unrelated-harmony",
        tool="Harmony",
        task="neighbor_graph_construction",
        text="Harmony integration details.",
    )
    assert _filter(chunk, claim_owned=False) == []


def test_neighbors_claim_does_not_inherit_unrelated_harmony_claims():
    result = _production_result()
    assert result.answerability.claim_ids == ["claim-revision:uat:neighbors-input:v1"]
    assert all(
        path["operator_revision_id"]
        == "operator-revision:scanpy.pp.neighbors:1.11.2:uat-corrected"
        for path in result.scientific_evidence["paths"]
    )
    direct_hit = next(
        hit for hit in result.hits
        if hit.chunk_id == "scanpy-authoritative-span:neighbors.input:1.11.2"
    )
    assert direct_hit.tool_name == "Scanpy"


def test_candidate_status_and_negative_controls_are_preserved():
    supported = _production_result()
    assert supported.answerability.candidate_only is True
    for query in (
        "What limitation does scanpy.pp.neighbors have in Scanpy 1.11.2?",
        "What input does Scanpy PCA version 1.10.0 accept?",
    ):
        result = _production_result(query)
        assert result.answerability.status != "SUPPORTED"


def test_single_r_behavior_matches_frozen_partial_baseline():
    baseline_path = foundation.PROJECT_ROOT / (
        "data/evaluation/scientific_kg_narrow_direct_evidence_qualification_v1/"
        "per_case_resolution.jsonl"
    )
    baseline = next(
        json.loads(line)
        for line in baseline_path.read_text().splitlines()
        if '"case_id": "qual-singler-indirect-compatibility"' in line
    )
    current = _production_result("What feature compatibility does SingleR require?")
    assert current.answerability.status == baseline["observed_answerability"]
    assert current.answerability.claim_ids == baseline["observed_claim_ids"]


def test_knowledge_corpus_index_planner_and_frozen_qualification_are_unchanged():
    paths = [
        "data/evidence_candidates/scientific_kg_v1_uat_decision_rules",
        "data/indexes/retrieval_foundation_v1",
        "data/knowledge_graph_v2",
        "engine/capability_planner.py",
        "contracts/tools",
        "capability_packs",
        "data/evaluation/scientific_kg_narrow_direct_evidence_qualification_v1",
        "docs/status/SCIENTIFIC_KG_NARROW_DIRECT_EVIDENCE_QUALIFICATION_V1.md",
    ]
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *paths], check=True)
