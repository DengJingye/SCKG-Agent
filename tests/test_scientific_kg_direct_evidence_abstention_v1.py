"""Focused DEV fixtures for direct Scientific KG evidence and abstention."""
from __future__ import annotations

import shutil

import pytest

from agent.research_tool_registry import ResearchToolRegistry
from core.knowledge_intelligence_models import HybridRetrievalRequest
from core.research_agent_models import ResearchToolCall, ResearchToolPlan
from engine.hybrid_retrieval import HybridRetrievalService
from engine.scientific_kg_evidence import parse_scientific_query
from eval import retrieval_benchmark_v1_1_dev as prior


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("direct-evidence-index")
    for name in (
        "evidence_chunks.jsonl",
        "scrna_tools_catalog_chunks.jsonl",
        "evidence_fts5.sqlite",
        "evidence_index_manifest.json",
        "evidence_vectors.npy",
        "evidence_vector_metadata.json",
    ):
        shutil.copy2(prior.INDEX_DIR / name, tmp_path / name)
    return HybridRetrievalService(
        evidence_chunks_path=tmp_path / "evidence_chunks.jsonl",
        catalog_chunks_path=tmp_path / "scrna_tools_catalog_chunks.jsonl",
        fts_index_path=tmp_path / "evidence_fts5.sqlite",
        index_manifest_path=tmp_path / "evidence_index_manifest.json",
        coverage_path=tmp_path / "retrieval_coverage.json",
        dense_matrix_path=tmp_path / "evidence_vectors.npy",
        dense_metadata_path=tmp_path / "evidence_vector_metadata.json",
        scientific_evidence_enabled=False,
    )


def request(query: str, **updates):
    return HybridRetrievalRequest(
        query=query,
        include_catalog=False,
        enable_dense=False,
        use_kg=False,
        use_governance_rerank=False,
        use_scientific_evidence=True,
        top_k=10,
        **updates,
    )


@pytest.mark.parametrize(
    "query,expected_need",
    [
        ("How should sample identity be supplied?", "input_requirement"),
        ("Contrast the data products written by two methods.", "output"),
        ("Which threshold and seed should be adjusted?", "parameter"),
        ("Which methodological sensitivities reduce reliability?", "limitation"),
        ("Which benchmark artifact supports this claim?", "reference_artifact"),
        ("Which evidence-backed method fits this task?", "method_type"),
        ("When is it scientifically defensible to run this method?", "scope"),
    ],
)
def test_generic_information_need_normalization(query, expected_need):
    parsed = parse_scientific_query(query, extended=True)
    assert expected_need in parsed["information_needs"]


@pytest.mark.parametrize(
    "query,status",
    [
        ("Scanpy PCA input requirements", "SUPPORTED"),
        ("Scanpy neighbors output", "SUPPORTED"),
        ("Scanpy highly_variable_genes input flavor=seurat_v3", "SUPPORTED"),
        ("Scanpy highly_variable_genes output", "SUPPORTED"),
        ("Scanpy Leiden input requirements", "SUPPORTED"),
        ("Scanpy UMAP input requirements", "SUPPORTED"),
        ("SingleR input requirements", "SUPPORTED"),
        ("SingleR reference compatibility", "SUPPORTED"),
        ("Harmony limitations", "INSUFFICIENT_EVIDENCE"),
        ("CellRank limitations", "INSUFFICIENT_EVIDENCE"),
        ("scVelo input requirements", "INSUFFICIENT_EVIDENCE"),
        ("CellTypist reference model compatibility", "INSUFFICIENT_EVIDENCE"),
        ("PCA and neighbors input requirements", "CLARIFICATION_REQUIRED"),
        ("Scanpy PCA input latest version", "CLARIFICATION_REQUIRED"),
        ("Leiden output version 1.11.2 and version 1.10.0", "CLARIFICATION_REQUIRED"),
        ("SingleR which reference should be used", "CLARIFICATION_REQUIRED"),
        ("Scanpy PCA input for my dataset", "UNRESOLVED"),
        ("UnknownTool output", "UNRESOLVED"),
    ],
)
def test_four_state_answerability(service, query, status):
    result = service.search(request(query))
    assert result.answerability is not None
    assert result.answerability.status == status


def test_supported_metadata_is_source_bound_and_candidate_only(service):
    answer = service.search(request("SingleR reference compatibility")).answerability
    assert answer.scientific_kg_used
    assert answer.operator_revision_id
    assert answer.claim_ids and answer.evidence_span_ids and answer.source_revision_ids
    assert answer.direct_evidence_chunk_ids
    assert answer.candidate_only


def test_graph_evidence_not_in_corpus_is_unresolved(service):
    original_chunks = service._chunks_by_id
    service._chunks_by_id = {}
    try:
        result = service.search(request("Scanpy PCA input requirements"))
    finally:
        service._chunks_by_id = original_chunks
    assert result.answerability.status == "UNRESOLVED"
    assert any(
        gap.get("reason_code") == "GRAPH_EVIDENCE_NOT_IN_CORPUS"
        for gap in result.scientific_evidence["gaps"]
    )


def test_search_evidence_activates_direct_path_and_surfaces_observation(service):
    plan = ResearchToolPlan(
        source="deterministic_fallback",
        answer_strategy="grounded",
        calls=[
            ResearchToolCall(
                call_id="direct-evidence",
                tool_name="search_evidence",
                query="Scanpy PCA input requirements",
                claim_types=["input_requirement"],
                top_k=10,
            )
        ],
    )
    execution = ResearchToolRegistry(retrieval=service).execute(
        plan,
        fallback_query="",
        fallback_task="",
        enable_dense=False,
        use_kg=False,
        use_governance_rerank=False,
        use_contract_gate=False,
    )
    assert execution.retrieval.answerability.status == "SUPPORTED"
    payload = execution.observations[0].payload
    assert payload["answerability"]["status"] == "SUPPORTED"
    assert payload["answerability_status"] == "SUPPORTED"
    assert payload["scientific_kg_used"] is True
    assert payload["operator_revision_id"]
    assert payload["claim_ids"] and payload["evidence_span_ids"]
    assert payload["source_revision_ids"]
    assert execution.retrieval.scientific_evidence["execution_authorized"] is False


def test_search_catalog_does_not_activate_direct_path(service):
    plan = ResearchToolPlan(
        source="deterministic_fallback",
        answer_strategy="grounded",
        calls=[
            ResearchToolCall(
                call_id="catalog",
                tool_name="search_catalog",
                query="Scanpy PCA",
                top_k=5,
            )
        ],
    )
    execution = ResearchToolRegistry(retrieval=service).execute(
        plan,
        fallback_query="",
        fallback_task="",
        enable_dense=False,
        use_kg=False,
        use_governance_rerank=False,
        use_contract_gate=False,
    )
    assert execution.retrieval.answerability is None
    assert execution.retrieval.scientific_evidence is None


def test_generic_retrieval_default_is_unchanged(service):
    result = service.search(
        HybridRetrievalRequest(
            query="Scanpy PCA input requirements",
            include_catalog=False,
            enable_dense=False,
            use_kg=False,
        )
    )
    assert result.answerability is None
    assert "scientific_kg_evidence_lookup" not in result.pipeline


def test_no_execution_authority_or_request_is_created(service):
    result = service.search(request("Scanpy PCA input requirements"))
    assert result.scientific_evidence["execution_authorized"] is False
    assert not hasattr(result, "execution_request")
