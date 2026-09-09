from __future__ import annotations

import json

import pytest

from agent.research_chat_reasoner import SemanticParseResult
from agent.research_chat_service import (
    ResearchChatIntent,
    ResearchChatService,
    _classify_intent,
    _fuse_research_route,
    _query_domain,
    _task_for_query,
)
from core.research_agent_models import AgentMode, DomainKind, ResearchAgentRequest
from core.trace_context import TraceCollector


def _semantic(
    *,
    domain: str = "SINGLE_CELL",
    intent: str = "workflow",
    task: str = "quality_control",
    needs_clarification: bool = False,
) -> SemanticParseResult:
    return SemanticParseResult(
        status="ready",
        domain=domain,
        intent=intent,
        canonical_task=task,
        needs_clarification=needs_clarification,
        confidence=0.99,
        provider="test-provider",
        model_name="test-model",
        provider_call_attempted=True,
    )


def _fuse(query: str, semantic: SemanticParseResult):
    task = _task_for_query(query)
    local_domain = _query_domain(
        query,
        explicit_task=task,
        conversation_context=[],
    )
    local_intent = _classify_intent(query)
    return _fuse_research_route(
        query=query,
        local_domain=local_domain,
        local_intent=local_intent,
        semantic_parse=semantic,
        requested_mode=None,
        explicit_task=task,
        inheritable_task=None,
        semantic_context_task=None,
    )


def _failed_semantic() -> SemanticParseResult:
    return SemanticParseResult(
        status="failed",
        error_type="provider_unavailable",
        provider_call_attempted=True,
    )


@pytest.mark.parametrize(
    ("query", "semantic_intent", "expected_intent"),
    [
        ("where is harmony2?", "tool_recommendation", ResearchChatIntent.EVIDENCE_QA),
        (
            "sc.pl.paga: TypeError: paga() got an unexpected keyword argument 'ncols'",
            "execution",
            ResearchChatIntent.EVIDENCE_QA,
        ),
        (
            "`sc.external.pp.scrublet` disables figure plot in jupyterlab",
            "caveat_comparison",
            ResearchChatIntent.EVIDENCE_QA,
        ),
        (
            "Highly Variable Genes Selection using CSC `dask`",
            "tool_recommendation",
            ResearchChatIntent.EVIDENCE_QA,
        ),
        (
            "Scrublet takes very long time to run",
            "caveat_comparison",
            ResearchChatIntent.EVIDENCE_QA,
        ),
        (
            "几个样本合起来以后还是各自聚在一起，我下一步该怎么办？",
            "workflow",
            ResearchChatIntent.TOOL_RECOMMENDATION,
        ),
        (
            "Any MLX (MPS) framework accelerate solution for scanpy？",
            "tool_recommendation",
            ResearchChatIntent.EVIDENCE_QA,
        ),
        (
            "Scanpy write compression vs os compression",
            "caveat_comparison",
            ResearchChatIntent.EVIDENCE_QA,
        ),
        (
            "Impact of scaling on clustering results and controlling minimum "
            "cluster size in Leiden clustering",
            "caveat_comparison",
            ResearchChatIntent.EVIDENCE_QA,
        ),
        (
            "Sc.tl.ingest over representing rare cell types in spatial "
            "transcriptomics data",
            "caveat_comparison",
            ResearchChatIntent.EVIDENCE_QA,
        ),
        ("Sc.pp.filter_genes how to use", "execution", ResearchChatIntent.EVIDENCE_QA),
        (
            "Confused by percent_top purpose in scanpy.pp.calculate_qc_metrics",
            "caveat_comparison",
            ResearchChatIntent.EVIDENCE_QA,
        ),
        (
            "多个患者的 PBMC 合并后 UMAP 按患者分开，应该怎样做 batch integration？",
            "workflow",
            ResearchChatIntent.TOOL_RECOMMENDATION,
        ),
        (
            "Scanorama 在基因集合不完全一致时有哪些限制？",
            "caveat_comparison",
            ResearchChatIntent.EVIDENCE_QA,
        ),
    ],
)
def test_fixed_intent_mismatches_use_query_supported_answer_shape(
    query,
    semantic_intent,
    expected_intent,
):
    decision = _fuse(query, _semantic(intent=semantic_intent))

    assert decision.domain_decision.domain == DomainKind.SINGLE_CELL
    assert decision.domain_decision.needs_clarification is False
    assert decision.intent is expected_intent
    assert decision.mode is AgentMode.ASK


def test_scanorama_title_without_query_context_remains_ambiguous():
    decision = _fuse(
        "alignment scores outpout",
        _semantic(intent="evidence_qa", task="batch_integration"),
    )

    assert decision.domain_decision.domain == DomainKind.UNCERTAIN
    assert decision.domain_decision.needs_clarification is True
    assert decision.clarification_reason == "query_ambiguity_requires_clarification"


def test_scientific_domain_enrichment_preserves_missing_context_clarification():
    decision = _fuse(
        "Can you interpret this gene expression violin plot?",
        _semantic(intent="evidence_qa", task=""),
    )

    assert decision.domain_decision.domain == DomainKind.SINGLE_CELL
    assert decision.domain_decision.needs_clarification is True
    assert decision.clarification_reason == "query_local_answer_context_incomplete"


def test_clarification_does_not_block_query_local_domain_enrichment():
    local_task = _task_for_query("Can you interpret this gene expression violin plot?")
    assert local_task is None

    decision = _fuse(
        "Can you interpret this gene expression violin plot?",
        _failed_semantic(),
    )

    assert decision.domain_decision.domain == DomainKind.SINGLE_CELL
    assert decision.domain_decision.source == "local_rule"
    assert decision.domain_decision.needs_clarification is True


def test_provider_failure_does_not_prevent_complete_local_domain_proposition():
    decision = _fuse(
        "Interpret gene expression violin plots",
        _failed_semantic(),
    )

    assert decision.domain_decision.domain == DomainKind.SINGLE_CELL
    assert decision.domain_decision.source == "local_rule"
    assert decision.domain_decision.needs_clarification is False
    assert decision.clarification_reason == "query_local_answer_context_complete"


def test_route_regression_query_uses_generic_scientific_proposition():
    decision = _fuse(
        "Interpretting differential gene expression dotplot",
        _failed_semantic(),
    )

    assert decision.domain_decision.domain == DomainKind.SINGLE_CELL
    assert decision.domain_decision.needs_clarification is False
    assert decision.intent is ResearchChatIntent.EVIDENCE_QA


def test_vague_query_without_scientific_domain_evidence_remains_uncertain():
    decision = _fuse("Can i obtain my original data shape?", _failed_semantic())

    assert decision.domain_decision.domain == DomainKind.UNCERTAIN
    assert decision.domain_decision.needs_clarification is True


@pytest.mark.parametrize(
    ("query", "semantic_intent", "semantic_task"),
    [
        ("Reg negative and positive TF activity values", "evidence_qa", "quality_control"),
        ("Can i obtain my original data shape?", "execution", "quality_control"),
        (
            "Draw_graph results in a cloud or nice PAGA-like structure depending "
            "on dataset?",
            "caveat_comparison",
            "trajectory_inference",
        ),
        (
            "Investigate our neighbors algorithm choice",
            "tool_recommendation",
            "clustering",
        ),
        (
            "Different results on 2 different machines despite using the same "
            "docker image",
            "caveat_comparison",
            "batch_integration",
        ),
    ],
)
def test_llm_cannot_remove_query_local_clarification(
    query,
    semantic_intent,
    semantic_task,
):
    decision = _fuse(
        query,
        _semantic(intent=semantic_intent, task=semantic_task),
    )

    assert decision.domain_decision.domain == DomainKind.UNCERTAIN
    assert decision.domain_decision.needs_clarification is True
    assert decision.mode is AgentMode.ASK
    assert decision.fusion_reason.startswith("ambiguity_guard_")


def test_deterministic_intent_gaps_are_disjoint():
    assert _classify_intent(
        "Confused by percent_top purpose in scanpy.pp.calculate_qc_metrics"
    ) is ResearchChatIntent.EVIDENCE_QA
    assert _classify_intent(
        "多个患者的 PBMC 合并后 UMAP 按患者分开，应该如何做 batch integration？"
    ) is ResearchChatIntent.TOOL_RECOMMENDATION
    assert _classify_intent(
        "多个患者的 PBMC 合并后 UMAP 按患者分开，应该怎样做 batch integration？"
    ) is ResearchChatIntent.TOOL_RECOMMENDATION
    assert _classify_intent(
        "Sc.pp.filter_genes how to use"
    ) is ResearchChatIntent.EVIDENCE_QA
    assert _classify_intent(
        "Scanorama 在基因集合不完全一致时有哪些限制？"
    ) is ResearchChatIntent.EVIDENCE_QA
    assert _classify_intent(
        "Harmony 和 Scanorama 的限制分别是什么？"
    ) is ResearchChatIntent.CAVEAT_COMPARISON


class _OverconfidentWorkflowReasoner:
    def parse(self, **_kwargs):
        return _semantic(intent="workflow", task="quality_control")


def test_trace_records_local_semantic_and_fused_route_without_raw_query(tmp_path):
    trace_path = tmp_path / "route-fusion-traces.jsonl"
    service = ResearchChatService(
        dense_default_enabled=False,
        trace_collector=TraceCollector(trace_path),
    )
    service._reasoner = _OverconfidentWorkflowReasoner()
    query = "Sc.pp.filter_genes how to use"

    response = service.run_request(
        ResearchAgentRequest(request_id="route-fusion-trace", query=query),
        user_runtime_config={"privacy_authorized": True},
    )

    row = json.loads(trace_path.read_text(encoding="utf-8").strip())
    routing = next(span for span in row["spans"] if span["stage"] == "ROUTING")
    decisions = {
        item["decision_type"]: item for item in routing["decision_evidence"]
    }
    assert response.state.intent == ResearchChatIntent.EVIDENCE_QA.value
    assert {
        "route_local_decision",
        "route_llm_proposal",
        "route_clarification_signal",
        "route_fusion_decision",
    }.issubset(decisions)
    assert decisions["route_local_decision"]["outcome"] == "single_cell_evidence_qa_ask"
    assert decisions["route_llm_proposal"]["outcome"] == (
        "single_cell_workflow_resolved"
    )
    assert decisions["route_fusion_decision"]["outcome"] == "single_cell_evidence_qa_ask"
    assert decisions["route_clarification_signal"]["outcome"] == "not_required"
    assert query not in trace_path.read_text(encoding="utf-8")
