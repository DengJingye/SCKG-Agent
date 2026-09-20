from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.scientific_response_context import (
    audit_answer, compile_answer, compact_conversation, decision_local_projection, enrich_references,
    recover_prose_payload,
    bind_source_quotes,
)
from agent.research_chat_reasoner import ExternalReasoningResult, SemanticParseResult, _user_reported_facts
from core.research_agent_models import ResearchToolCall
from tests.test_research_chat_service import _service


def refs():
    return [{"index": 1, "tool_name": "Scrublet", "source_span_id": "span:1",
             "source_id": "source:1", "source_span": "README:2", "source_bound": True,
             "authority": "source_bound",
             "claim_type": "input_requirement", "claim_text": "Scrublet requires raw count matrices."}]


def payload(text="Scrublet 需要原始计数矩阵。", basis="RETRIEVAL_GROUNDED"):
    return {"segments": [{"text": text, "basis": basis,
             "citations": [{"index": 1, "quote": "Scrublet requires raw count matrices."}]}]}


def test_natural_chinese_preserves_source_without_verbatim_copy():
    answer, claims = compile_answer(payload(), refs())
    assert answer == "Scrublet 需要原始计数矩阵。[1]"
    assert audit_answer(claims, refs())["passed"]
    assert not audit_answer(claims, refs())["semantic_claim_correctness"]


def test_plain_provider_prose_still_requires_the_same_grounding_contract():
    recovered = recover_prose_payload("Scrublet 需要原始计数矩阵。[1]", refs())
    answer, claims = compile_answer(recovered, refs())
    assert audit_answer(claims, refs())["passed"]
    with pytest.raises(ValueError):
        recover_prose_payload("Scrublet 有更高性能。[99]", refs())
    with pytest.raises(ValueError):
        recover_prose_payload('{"segments": malformed', refs())


def test_miscopied_quote_is_discarded_and_only_registered_source_reaches_check():
    p = payload()
    p["segments"][0]["citations"][0]["quote"] = "Fabricated quote"
    bound, count = bind_source_quotes(p, refs())
    assert count == 1
    assert bound["segments"][0]["citations"][0]["quote"] == refs()[0]["claim_text"]
    assert "Fabricated" not in json.dumps(bound)
    p["segments"][0]["citations"][0]["index"] = 99
    with pytest.raises(ValueError):
        bind_source_quotes(p, refs())


@pytest.mark.parametrize("mutation", ["quote", "reference", "kg", "model"])
def test_citation_authority_and_exact_quote_fail_closed(mutation):
    p = payload()
    if mutation == "quote":
        p["segments"][0]["citations"][0]["quote"] = "Invented excellent scientific evidence."
    elif mutation == "reference":
        p["segments"][0]["citations"][0]["index"] = 99
    else:
        p["segments"][0]["basis"] = "KG_GROUNDED" if mutation == "kg" else "MODEL_KNOWLEDGE"
    with pytest.raises(ValueError):
        compile_answer(p, refs())


def test_numeric_or_cross_method_claim_still_fails_existing_audit():
    for text in ["Scrublet 的阈值必须是 99%。", "Harmony requires raw count matrices."]:
        _, claims = compile_answer(payload(text), refs())
        assert not audit_answer(claims, refs())["passed"]


def test_missing_kg_is_model_knowledge_without_borrowed_citations():
    p = {"segments": [{"text": "可以先确认研究目标。", "basis": "MODEL_KNOWLEDGE", "citations": []}]}
    answer, claims = compile_answer(p, [])
    assert "尚未核验" in answer
    projection = decision_local_projection(answer, refs(), claims)
    assert projection["references"] == []
    assert not projection["scientific_kg_used"]
    assert projection["knowledge_sources"] == ["MODEL_KNOWLEDGE"]


def test_unused_sources_do_not_appear_in_decision_local_evidence():
    answer, claims = compile_answer(payload(), refs())
    projection = decision_local_projection(answer, refs() + [dict(refs()[0], index=2)], claims)
    assert [r["index"] for r in projection["references"]] == [1]


def test_user_facts_cannot_be_taken_from_assistant_advice():
    rows = [{"role": "assistant", "content": "请保留原始计数"}, {"role": "user", "content": "四个病人"}]
    facts = _user_reported_facts({"raw_counts": {"value": "available", "user_quote": "请保留原始计数"},
                               "sample_count": {"value": "4", "user_quote": "四个病人"}}, "已经merge", rows)
    assert "raw_counts" not in facts
    assert facts["sample_count"].startswith("4")
    assert all(row["authority"] == "conversation_only_not_evidence" for row in compact_conversation(rows))


class ConversationReasoner:
    supports_response_context = True

    def __init__(self, dependency="none", intent="evidence_qa"):
        self.inputs = []
        self.dependency, self.intent = dependency, intent
        self.parse_count = 0

    def parse(self, **kwargs):
        self.parse_count += 1
        return SemanticParseResult(status="ready", domain="SINGLE_CELL", canonical_task="doublet_detection",
            intent=self.intent, confidence=.95, data_dependency=self.dependency,
            retrieval_query=kwargs["query"] + " Scrublet input requirements",
            tool_calls=[ResearchToolCall(call_id="evidence", tool_name="search_evidence",
                query=kwargs["query"] + " Scrublet input requirements", tool_names=["Scrublet"],
                canonical_task="doublet_detection", claim_types=["input_requirement"])])

    def synthesize(self, **kwargs):
        self.inputs.append(kwargs)
        ref = kwargs["references"][0]
        p = {"segments": [{"text": "Scrublet requires raw count matrices.", "basis": "RETRIEVAL_GROUNDED",
            "citations": [{"index": ref["index"], "quote": ref["claim_text"]}]}],
            "clarifying_question": "这些是独立捕获的样本吗？"}
        answer, claims = compile_answer(p, kwargs["references"])
        return ExternalReasoningResult(status="ready", content=answer, answer_claims=claims)


def test_multiturn_retrieves_again_and_synthesis_sees_all_user_conditions(tmp_path):
    service = _service(tmp_path)
    reasoner = ConversationReasoner()
    service._reasoner = reasoner
    history = []
    for query in ["我有10x PBMC，怎么检测doublet？", "四个病人的样本呢？", "我已经merge过了怎么办？"]:
        result = service.run(query, conversation_context=history, user_runtime_config={"privacy_authorized": True})
        assert result["runtime_mode"] == "external_reasoning_with_deterministic_governance"
        assert result["extracted_constraints"]["canonical_task"] == "doublet_detection"
        history += [{"role": "user", "content": query}, {"role": "assistant", "content": result["final_report"],
            "conversation_state": result["context_pack"]["conversation_state"]}]
    ctx = reasoner.inputs[-1]["response_context"]
    assert "四个病人" in json.dumps(ctx, ensure_ascii=False)
    assert reasoner.parse_count == 3
    assert "我已经merge" in result["context_pack"]["research_tool_plan"]["calls"][0]["query"]
    assert result["execution_handoff"]["execution_request_count"] == 0


def test_stale_binding_does_not_block_unrelated_ask(tmp_path):
    service = _service(tmp_path); service._reasoner = ConversationReasoner()
    result = service.run("Scrublet需要什么输入？", user_runtime_config={"privacy_authorized": True, "input_binding_status": "stale"})
    assert result["runtime_mode"] == "external_reasoning_with_deterministic_governance"
    assert result["context_pack"]["response_context"]["data_state"]["status"] == "stale"


def test_data_dependent_ask_requires_rebind_without_fabricated_analysis(tmp_path):
    service = _service(tmp_path); service._reasoner = ConversationReasoner("analysis")
    result = service.run("我的数据有多少doublet？", user_runtime_config={"privacy_authorized": True, "input_binding_status": "stale"})
    assert result["runtime_mode"] == "clarification_required"
    assert "重新选择" in result["final_report"]
    assert not service._reasoner.inputs
    assert result["execution_handoff"]["execution_request_count"] == 0


def test_stale_run_is_blocked_before_provider(tmp_path):
    service = _service(tmp_path); service._reasoner = ConversationReasoner(intent="execution")
    result = service.run("现在运行Scrublet", mode="RUN", user_runtime_config={"privacy_authorized": True, "input_binding_status": "stale"})
    assert "尚未执行" in result["final_report"]
    assert service._reasoner.parse_count == 0
    assert result["execution_handoff"]["execution_request_count"] == 0


def test_actual_kg_statement_assessment_span_source_chain_and_candidate_status(tmp_path):
    from agent.research_runtime import build_chat_retrieval
    from core.knowledge_intelligence_models import HybridRetrievalRequest
    # The historical candidate adapter remains a baseline, not production v2.
    retrieval = build_chat_retrieval(tmp_path).legacy
    result = retrieval.search(HybridRetrievalRequest(query="Scanpy 1.11.2 HVG input flavor=seurat_v3",
        include_catalog=False, enable_dense=False, use_scientific_evidence=True, use_kg=False))
    ids = result.scientific_evidence["final_graph_chunk_ids"]
    assert ids
    hit = next(h for h in result.hits if h.chunk_id in ids)
    reference = dict(index=1, source_span_id=hit.chunk_id, source_id=hit.source_id,
        source_span=hit.source_span, claim_text=hit.text, source_bound=True, tool_name=hit.tool_name)
    row = enrich_references([reference], result.scientific_evidence, retrieval._scientific_evidence_adapter)[0]
    assert row["knowledge_source"] == "KG_GROUNDED"
    fact = row["kg_statements"][0]
    assert fact["assessment_ids"] and fact["evidence_span_id"] and fact["source_revision_id"]
    assert fact["knowledge_status"] == "candidate" and not fact["recommendation_eligible"]
    assert row["exact_excerpt"] == hit.text
    assert "1.11.2" in json.dumps(fact["scope"])


@pytest.mark.parametrize("profile,uses_scientific", [("llm_only", False), ("generic_rag", False), ("legacy_kg", False), ("scientific_kg", True)])
def test_ablation_profiles_do_not_leak_scientific_kg(profile, uses_scientific, tmp_path):
    from agent.research_chat_service import ResearchChatService, _retrieval_options
    from core.knowledge_intelligence_models import AdaptiveRetrievalDecision
    from core.trace_context import TraceCollector
    service = ResearchChatService(evaluation_retrieval_profile=profile, dense_default_enabled=False,
                                 trace_collector=TraceCollector(tmp_path / "trace"))
    assert service._research_tools.scientific_evidence_enabled is uses_scientific
    opts = _retrieval_options(AdaptiveRetrievalDecision(route="kg_bm25", enable_dense=False, reason="test"), evaluation_profile=profile)
    assert not opts["enable_dense"]
    assert opts["use_kg"] is (profile in {"legacy_kg", "scientific_kg"})
