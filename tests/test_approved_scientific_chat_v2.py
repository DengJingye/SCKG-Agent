"""Integration qualification only; immutable real package, no Agent Gain."""
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.knowledge_intelligence_models import HybridRetrievalRequest, HybridRetrievalResult
from engine.approved_scientific_kg import (
    APPROVED_SHA256, HELD_ID, SNAPSHOT_ID, ApprovedScientificKG,
    GovernedChatRetrieval, scope_result, user_scope,
)
from agent.scientific_response_context import append_caution_references, compile_answer, enrich_references, response_context


@pytest.fixture(scope="module")
def kg():
    return ApprovedScientificKG()


def search(kg, query):
    return kg.search(HybridRetrievalRequest(query=query, top_k=100))


def facts(result):
    return [p["fact"] for p in result.scientific_evidence["paths"]]


def references(kg, result):
    rows = [{"index": i, "source_span_id": h.chunk_id, "source_id": h.source_id,
             "source_span": h.source_span, "source_bound": h.source_bound,
             "authority": "source_bound", "claim_text": h.text, "claim_type": h.claim_type}
            for i, h in enumerate(result.hits, 1)]
    return enrich_references(rows, result.scientific_evidence, kg)


def test_real_manifest_exact_allowlist_and_held_absent(kg):
    assert len(kg.statements) == len(kg.allowlist) == 121
    assert HELD_ID not in kg.statements
    assert {sid for sid, _, _ in kg.fact_by_chunk.values()} == kg.allowlist
    assert kg.manifest["approved_kg_sha256"] == APPROVED_SHA256
    assert kg.manifest["held_statement_count"] == 1
    assert all(sid != HELD_ID for sid, _, _ in kg.fact_by_chunk.values())
    assert all(f["statement_id"] != HELD_ID for f in facts(search(kg, "scVelo")))


def test_hash_tamper_fails_closed(monkeypatch):
    import engine.approved_scientific_kg as mod
    original = mod.subprocess.check_output
    def tamper(args, **kwargs):
        raw = original(args, **kwargs)
        return raw + b" " if args[-1].endswith("approved_kg.json") else raw
    monkeypatch.setattr(mod.subprocess, "check_output", tamper)
    with pytest.raises(ValueError, match="hash_mismatch"):
        ApprovedScientificKG()


@pytest.mark.parametrize("status", ["unknown", "partially_known"])
def test_incomplete_scope_never_wildcard(status):
    s = {"scope_status": status, "qualifiers": {"modality": "scRNA-seq"}}
    assert scope_result(s, {})["status"] == "unknown"
    assert scope_result(s, {"modality": "scRNA-seq"})["status"] == "unknown"
    assert scope_result(s, {"modality": "scATAC-seq"})["status"] == "exclude"


@pytest.mark.parametrize("flavor,value", [("seurat", "logarithmized"), ("cell_ranger", "logarithmized"),
                                         ("seurat_v3", "counts"), ("seurat_v3_paper", "counts")])
def test_hvg_exact_conditional_input_and_no_execution_gate(kg, flavor, value):
    result = search(kg, f"Scanpy 1.11.2 HVG flavor={flavor} input requirement")
    requirements = [f for f in facts(result) if f["predicate"] == "has_requirement"]
    assert len(requirements) == 1
    fact = requirements[0]
    assert fact["constraints"][0]["required_value_states"] == [value]
    assert fact["scope"]["status"] == "applicable"
    assert fact["requirements"][0]["strength"] == "REQUIRED"
    assert not fact["execution_gate"] and not fact["execution_authorized"]
    assert fact["registered_statement"] == kg.statements[fact["statement_id"]]


def test_missing_version_and_flavor_are_unknown_not_defaults(kg):
    reqs = [f for f in facts(search(kg, "Scanpy HVG input")) if f["predicate"] == "has_requirement"]
    assert len(reqs) == 2
    assert all(f["scope"]["status"] == "unknown" for f in reqs)
    assert not search(kg, "Scanpy 9.9.9 HVG flavor=seurat_v3").hits
    assert all(f["predicate"] != "has_requirement" for f in facts(search(kg, "Scanpy 1.11.2 HVG flavor=unknown")))


@pytest.mark.parametrize("chunked,center,branch", [(True, False, "incremental"), (True, True, "incremental"),
                                                   (False, True, "nonchunked-centered"), (False, False, None)])
def test_pca_all_of_output_conditions(kg, chunked, center, branch):
    result = search(kg, f"Scanpy 1.11.2 PCA chunked={str(chunked).lower()} zero_center={str(center).lower()}")
    ports = {p["id"]: p for f in facts(result) for p in f["output_ports"]}
    applicable = [p for p in ports.values() if p["applicability"] == "applicable"]
    assert len(applicable) == (1 if branch else 0)
    if branch:
        assert applicable[0]["id"].endswith(":" + branch)
    else:
        assert not [f for f in facts(result) if f["predicate"] == "implements_method"]
    if branch == "nonchunked-centered":
        assert len(applicable[0]["production_conditions"]) == 2


def test_caution_not_assertion_scrublet_parent_singlet(kg):
    result = search(kg, "Scrublet parent singlet detectability caution")
    caution = result.scientific_evidence["cautions"][0]
    assert caution["caution_id"] == "evidence-gap:06b:scrublet-parent-singlet-detectability"
    assert all(caution[k] is False for k in ("scientific_assertion", "trusted", "production_retrieval_eligible", "execution_gate", "execution_authorized"))
    assert "parent" not in str([f["requirements"] for f in facts(result)]).lower()
    refs = append_caution_references(references(kg, result), result.scientific_evidence, kg)
    ref = next(r for r in refs if r.get("caution_context", {}).get("caution_id") == caution["caution_id"])
    seg = {"text": "这属于可检测性提醒，不能据此自动阻断执行。", "basis": "CAUTION_CONTEXT",
           "citations": [{"index": ref["index"], "quote": ref["claim_text"]}]}
    _, claims = compile_answer({"segments": [seg]}, refs)
    assert claims[0]["scientific_assertion"] is False
    for basis in ["KG_GROUNDED", "RETRIEVAL_GROUNDED"]:
        with pytest.raises(ValueError):
            compile_answer({"segments": [dict(seg, basis=basis)]}, refs)


def test_cellrank_putative_and_causal_caveat_survive(kg):
    result = search(kg, "CellRank scRNA-seq lineage driver causal correlation")
    driver = [f for f in facts(result) if f["registered_statement"]["object_id"] == "task:lineage-driver-gene-identification"]
    assert driver
    assert all("causal" in f["statement"] and ("not causal" in f["statement"] or "does not" in f["statement"]) for f in driver)
    assert "Causality" in result.scientific_evidence["cautions"][0]["description"]


def test_all_134_exact_source_chains(kg):
    for cid, (sid, aid, eid) in kg.fact_by_chunk.items():
        fact = kg.fact(cid, {})
        a = next(a for a in kg.assessments[sid] if a["assessment_id"] == aid)
        span = kg.spans[eid]
        assert a["statement_revision_id"] == sid and a["evidence_span_id"] == eid
        assert hashlib.sha256(span["exact_text"].encode()).hexdigest() == span["content_hash"]
        assert fact["source_revision_id"] in kg.sources
        assert kg.sources[fact["source_revision_id"]]["source_work_id"] in kg.entities
        assert span["exact_text"] == kg.chunks[cid].chunk_text
        assert not fact["original_source_file_reverified"]
        metadata = kg.source_for_span(span)
        assert metadata["source_artifact_id"] == span["source_artifact_id"]
        assert metadata["text_hash"] in span["locator"]["value"]
        assert kg.chunks[cid].title == metadata["title"]


def test_source_expansion_and_context(kg):
    result = search(kg, "Scanpy 1.11.2 HVG flavor=seurat_v3 input")
    refs = references(kg, result)
    assert all(r["exact_excerpt"] == r["claim_text"] and r["source_url"] for r in refs)
    context = response_context(conversation=[], conversation_state={}, semantic={}, references=refs,
        data_state={}, contracts=[], planner={}, diagnostic=result.scientific_evidence)
    assert context["scientific_kg"]["snapshot_id"] == SNAPSHOT_ID
    assert context["scientific_kg"]["adapter_called"]


def test_scientific_lane_never_calls_legacy_and_followup_scope_updates(kg):
    calls = []
    def legacy_search(request):
        calls.append(request)
        return HybridRetrievalResult(query=request.query, mode="bm25", latency_ms=0)
    wrapped = GovernedChatRetrieval(SimpleNamespace(_chunks_by_id={}, search=legacy_search), kg)
    q = "Scanpy 1.11.2 HVG flavor=seurat_v3 输入是什么？"
    wrapped.begin_turn(q, [])
    first = wrapped.search(HybridRetrievalRequest(query=q))
    wrapped.begin_turn("那改成 flavor=seurat 呢？", [{"role": "user", "content": q},
                     {"role": "assistant", "content": "Scanpy 9.9.9 flavor=cell_ranger"}])
    # A hallucinated model retrieval rewrite cannot override actual user scope.
    second = wrapped.search(HybridRetrievalRequest(query="Scanpy 9.9.9 HVG flavor=seurat_v3 input"))
    assert first.scientific_evidence["scope_context"]["flavor"] == "seurat_v3"
    assert second.scientific_evidence["scope_context"]["flavor"] == "seurat"
    assert second.scientific_evidence["scope_context"]["software_version"] == "1.11.2"
    assert not calls
    assert not ({f["statement_id"] for f in facts(first) if f["predicate"] == "has_requirement"}
                & {f["statement_id"] for f in facts(second) if f["predicate"] == "has_requirement"})
    for profile in ["generic_rag", "legacy_kg"]:
        wrapped.configure_profile(profile)
        wrapped.search(HybridRetrievalRequest(query=q, use_scientific_evidence=True))
        assert calls[-1].use_kg == (profile == "legacy_kg")
        assert calls[-1].use_scientific_evidence is (profile == "legacy_kg")


def test_actual_legacy_scientific_baseline_is_distinct_from_approved(tmp_path):
    from agent.research_runtime import build_chat_retrieval
    wrapper = build_chat_retrieval(tmp_path)
    wrapper.configure_profile("legacy_kg")
    count = wrapper.approved.query_count
    result = wrapper.search(HybridRetrievalRequest(query="Scanpy 1.11.2 HVG input flavor=seurat_v3",
                            include_catalog=False, enable_dense=False))
    assert wrapper.approved.query_count == count
    assert "1651" in result.scientific_evidence["baseline_identity"]
    assert result.scientific_evidence["final_graph_chunk_ids"]
    refs = references(wrapper._scientific_evidence_adapter, result)
    candidates = [f for r in refs for f in r.get("kg_statements", [])]
    assert candidates and all(f["knowledge_status"] == "candidate" for f in candidates)
    assert not {f["statement_id"] for f in candidates}.intersection(wrapper.approved.allowlist)


def test_outside_kg_does_not_borrow_previous_subject_or_assistant_context(kg):
    wrapped = GovernedChatRetrieval(SimpleNamespace(_chunks_by_id={}), kg)
    wrapped.begin_turn("解释量子引力。", [{"role": "user", "content": "Scanpy 1.11.2 HVG"}])
    result = wrapped.search(HybridRetrievalRequest(query="quantum gravity"))
    assert not result.hits and not result.scientific_evidence["cautions"]
    assert result.scientific_evidence["legacy_kg_consulted"] is False


def test_user_alternatives_not_guessed():
    assert user_scope("Scanpy 1.11.2 HVG seurat / cell_ranger / seurat_v3 / seurat_v3_paper")["flavor"] is None
    assert user_scope("flavor='seurat_v3'输入")["flavor"] == "seurat_v3"


def test_consumer_rejects_unqualified_pca_svd_sentence(kg):
    result = search(kg, "Scanpy 1.11.2 PCA chunked=false zero_center=false")
    refs = append_caution_references(references(kg, result), result.scientific_evidence, kg)
    ref = next(r for r in refs if r.get("caution_context", {}).get("caution_id") == "evidence-gap:6a1028f08b7c9ead1bdce01d")
    segment = {"text": "提醒：zero_center=false 时执行截断 SVD。", "basis": "CAUTION_CONTEXT",
               "citations": [{"index": ref["index"], "quote": ref["claim_text"]}]}
    with pytest.raises(ValueError, match="full_conjunction"):
        compile_answer({"segments": [segment]}, refs)
    segment["text"] = "提醒：截断 SVD 分支需同时考虑 chunked=false 且 zero_center=false。"
    assert compile_answer({"segments": [segment]}, refs)[1][0]["scientific_assertion"] is False
