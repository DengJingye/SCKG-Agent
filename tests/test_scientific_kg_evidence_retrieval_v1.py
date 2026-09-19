"""Read-only frozen inputs, tmp-only indexes; no Seed generator or autouse import."""
import shutil
from dataclasses import replace

import pytest

from agent.research_tool_registry import ResearchToolRegistry
from core.knowledge_intelligence_models import HybridRetrievalRequest
from core.research_agent_models import ResearchToolCall, ResearchToolPlan
from engine.hybrid_retrieval import HybridRetrievalService
from engine.scientific_kg_evidence import ScientificKGEvidence, SNAPSHOT_ID, CORPUS_DIGEST, parse_scientific_query
from eval import retrieval_benchmark_v1_1_dev as prior
from eval import kg_bm25_supplement_v1 as frozen


def request(query, **kwargs):
    return HybridRetrievalRequest(query=query, include_catalog=False, enable_dense=False,
                                  use_kg=False, use_governance_rerank=False, top_k=10, **kwargs)


@pytest.fixture
def service(tmp_path):
    for name in ("evidence_chunks.jsonl", "scrna_tools_catalog_chunks.jsonl", "evidence_fts5.sqlite",
                 "evidence_index_manifest.json", "evidence_vectors.npy",
                 "evidence_vector_metadata.json"):
        shutil.copy2(prior.INDEX_DIR / name, tmp_path / name)
    return HybridRetrievalService(
        evidence_chunks_path=tmp_path / "evidence_chunks.jsonl",
        catalog_chunks_path=tmp_path / "scrna_tools_catalog_chunks.jsonl",
        fts_index_path=tmp_path / "evidence_fts5.sqlite",
        index_manifest_path=tmp_path / "evidence_index_manifest.json",
        coverage_path=tmp_path / "retrieval_coverage.json",
        dense_matrix_path=tmp_path / "evidence_vectors.npy",
        dense_metadata_path=tmp_path / "evidence_vector_metadata.json",
        scientific_evidence_enabled=True)


def lookup(service, query, adapter=None, **kwargs):
    return (adapter or ScientificKGEvidence()).query(request(query, **kwargs), service._chunks_by_id,
                                                    snapshot_id=SNAPSHOT_ID, corpus_digest=CORPUS_DIGEST)


@pytest.mark.parametrize("query,span", [
    ("Scanpy PCA input requirements", "pca.input"),
    ("Scanpy neighbors output", "neighbors.output"),
    ("Scanpy highly_variable_genes input flavor=seurat_v3", "hvg.flavor_input"),
])
def test_three_operators_real_production_search(service, query, span):
    result = service.search(request(query))
    diag = result.scientific_evidence
    assert diag["resolved_operator_revision"].endswith(":1.11.2:uat-corrected")
    assert f"scanpy-authoritative-span:{span}:1.11.2" in diag["final_graph_chunk_ids"]
    assert diag["knowledge_status"] == "candidate"
    assert not diag["execution_authorized"] and not diag["recommendation_eligible"]
    assert all(not h.recommendation_eligible for h in result.hits if h.chunk_id in diag["final_graph_chunk_ids"])


@pytest.mark.parametrize("flavor,claim", [("seurat", "hvg-dispersion-log"), ("cell_ranger", "hvg-dispersion-log"),
                                          ("seurat_v3", "hvg-count-flavors"), ("seurat_v3_paper", "hvg-count-flavors")])
def test_hvg_conditional_inputs(service, flavor, claim):
    ranked, diag = lookup(service, f"scanpy.pp.highly_variable_genes input flavor='{flavor}'")
    assert ranked
    matched = [p for p in diag["paths"] if p["status"] == "mapped"]
    assert len(matched) == 1 and claim in matched[0]["claim_revision_id"]
    assert matched[0]["scope"]["condition_status"] == "matched"
    assert matched[0]["constraint_ids"] and matched[0]["requirement_ids"]


def test_hvg_unspecified_preserves_conditions_not_compatibility(service):
    _, diag = lookup(service, "HVG input requirements")
    assert len(diag["paths"]) == 2
    assert all(p["scope"]["condition_status"] == "conditional_flavor_unspecified" for p in diag["paths"])
    assert all(not p["scope"]["data_compatibility_assessed"] for p in diag["paths"])


@pytest.mark.parametrize("query", ["Scanpy 1.10.0 PCA input", "Scanpy latest version PCA input",
                                  "Scanpy PCA input for mouse", "HVG input flavor=unregistered"])
def test_unresolved_version_scope_or_condition_falls_back(service, query):
    ranked, diag = lookup(service, query)
    assert not ranked and diag["fallback_reason"]


def test_input_output_semantics_do_not_borrow(service):
    for query, expected in [("neighbors input requirements", "neighbors.input"),
                            ("neighbors output matrix stored where", "neighbors.output")]:
        ranked, diag = lookup(service, query)
        assert [r[0] for r in ranked] == [f"scanpy-authoritative-span:{expected}:1.11.2"]
        assert len(diag["parsed"]["information_needs"]) == 1
    ranked, diag = lookup(service, "Scanpy PCA output")
    assert not ranked and diag["fallback_reason"] == "information_need_not_expressed_in_graph"


def test_known_operator_no_canonical_task_still_queries(service):
    result = service.search(request("scanpy.pp.pca", claim_types=["input_requirement"]))
    assert result.scientific_evidence["final_graph_chunk_ids"]


def test_missing_binding_and_missing_chunk_are_gaps(service):
    adapter = ScientificKGEvidence()
    adapter.bindings.clear()
    ranked, diag = lookup(service, "HVG input", adapter)
    assert not ranked and {g["reason"] for g in diag["gaps"]} == {"evidence_binding_missing"}
    service._chunks_by_id = {}
    ranked, diag = lookup(service, "HVG input")
    assert not ranked and {g["reason"] for g in diag["gaps"]} == {"no_exact_chunk_in_frozen_corpus"}


def test_corrupt_binding_and_wrong_chunk_identity_fail_closed(service):
    adapter = ScientificKGEvidence()
    for row in adapter.bindings.values():
        row["claim_content_hash"] = "not-a-valid-hash"
    ranked, diag = lookup(service, "PCA input", adapter)
    assert not ranked and diag["gaps"]
    chunks = {cid: replace(chunk, source_span="wrong locator") for cid, chunk in service._chunks_by_id.items()}
    ranked, diag = ScientificKGEvidence().query(request("PCA input"), chunks, snapshot_id=SNAPSHOT_ID, corpus_digest=CORPUS_DIGEST)
    assert not ranked and diag["fallback_reason"]


@pytest.mark.parametrize("query", ["SingleR input requirements", "Seurat PCA input", "sklearn PCA input",
                                  "Scanpy PCA input for my dataset", "scanpy.tl.pca input"])
def test_unsupported_or_runtime_request_retains_baseline(service, query):
    enabled = service.search(request(query))
    service.scientific_evidence_enabled = False
    disabled = service.search(request(query))
    assert enabled.hits == disabled.hits
    assert enabled.scientific_evidence["fallback_reason"]
    assert disabled.scientific_evidence is None


def test_public_filter_uses_exact_bound_claim_ownership(service):
    result = service.search(request("Scanpy neighbors input requirements"))
    diag = result.scientific_evidence
    assert diag["public_filter_rejected_chunk_ids"] == []
    assert diag["final_graph_chunk_ids"] == [
        "scanpy-authoritative-span:neighbors.input:1.11.2"
    ]
    assert diag["public_filter_identity_basis"].startswith(
        "bound_scientific_claim_ownership"
    )
    assert result.answerability.status == "SUPPORTED"


def test_wrong_snapshot_never_injects_graph_chunks(service):
    ranked, diag = ScientificKGEvidence().query(request("HVG input"), service._chunks_by_id,
                                             snapshot_id="production_default", corpus_digest=CORPUS_DIGEST)
    assert not ranked and diag["fallback_reason"] == "snapshot_not_qualified"


def test_research_product_evidence_entry_and_frozen_integrity(service):
    before = frozen.protected_hashes()
    query = "Scanpy 1.11.2 highly_variable_genes flavor='seurat_v3' input requirements"
    registry = ResearchToolRegistry(retrieval=service)
    plan = ResearchToolPlan(source="deterministic_fallback", calls=[ResearchToolCall(
        call_id="structured-smoke", tool_name="search_evidence", query=query,
        tool_names=["Scanpy"], claim_types=["input_requirement"], top_k=10)])
    result = registry.execute(plan, fallback_query=query, fallback_task="", enable_dense=False,
                              use_kg=False, use_governance_rerank=False, use_contract_gate=False)
    assert result.observations[0].status == "completed"
    assert result.retrieval.scientific_evidence["final_graph_chunk_ids"]
    assert not result.workflow_bundles and not result.contract_context
    frozen.verify_hashes(before)


def test_off_is_original_baseline_and_adapter_not_loaded(service):
    service.scientific_evidence_enabled = False
    assert service._scientific_evidence_adapter is None
    result = service.search(request("Scanpy PCA input requirements"))
    assert service._scientific_evidence_adapter is None and result.scientific_evidence is None


def test_gold_never_parsed_or_forwarded():
    q = {"query": "PCA input", "track": "R1_scientific_evidence"}
    polluted = {**q, "expected_tools": ["Scanpy"], "gold_evidence_span_ids": ["secret"], "query_id": "secret"}
    assert frozen.request_for(q, False) == frozen.request_for(polluted, False)
    assert "eval" not in ScientificKGEvidence.__module__


def test_harness_requests_only_differ_in_declared_switch():
    from eval import scientific_kg_evidence_retrieval_v1 as harness
    query = {"query": "Scanpy PCA input", "track": frozen.TRACKS[0]}
    a, b, c = [harness.request_for(query, p).model_dump(mode="json") for p in harness.PROFILES]
    assert a == c
    assert {k for k in a if a[k] != b[k]} == {"use_kg"}
    assert not a["enable_dense"] and not a["use_governance_rerank"] and a["top_k"] == 10
    assert harness.request_for({**query, "expected_tools": ["secret"], "gold_evidence_span_ids": ["secret"]}, harness.PROFILES[2]).model_dump(mode="json") == c


def test_harness_comparison_does_not_normalize_away_rank_or_score():
    from eval import scientific_kg_evidence_retrieval_v1 as harness
    original = [{"chunk_id": "x", "score": .1}, {"chunk_id": "y", "score": .2}]
    harness.verify_baseline(original, original, "fixture", "A")
    for changed in (list(reversed(original)), [{"chunk_id": "x", "score": .2}, original[1]], original[:1]):
        with pytest.raises(RuntimeError, match="baseline_output_divergence"):
            harness.verify_baseline(changed, original, "fixture", "A")


def test_scope_partition_operator_not_gold_or_representation_mention():
    from eval import scientific_kg_evidence_retrieval_v1 as harness
    rows = [{"query_id": str(i), "track": frozen.TRACKS[0], "query": q, "expected_tools": ["Scanpy"]}
            for i, q in enumerate(["PCA output", "Leiden consumes neighbor graph", "scanpy.tl.umap uses neighbors", "HVG parameters"]) ]
    assert [v["supported_operator_scope"] for v in harness.scope_partition(rows).values()] == [True, False, False, True]


def test_new_campaign_write_once_tmp_only(tmp_path):
    from eval import scientific_kg_evidence_retrieval_v1 as harness
    p = tmp_path / "report.json"
    harness.write(p, {"status": "INVALID"})
    with pytest.raises(FileExistsError):
        harness.write(p, {"status": "COMPLETE"})


def test_can_use_is_input_not_operator_wide_evidence(service):
    ranked, diag = lookup(service, "Can scanpy.pp.neighbors use an embedding?")
    assert [r[0] for r in ranked] == ["scanpy-authoritative-span:neighbors.input:1.11.2"]
    assert diag["paths"][0]["predicate"] == "accepts_representation"


def test_unregistered_scope_and_graph_load_failure_retain_baseline(service, monkeypatch):
    adapter = ScientificKGEvidence()
    scope = next(c.scope_id for c in adapter.bundle.atomic_claims if c.claim_revision_id == "claim-revision:uat:pca-expression:v1")
    adapter.scopes[scope] = adapter.scopes[scope].model_copy(update={"scope_status": "unknown"})
    ranked, diag = lookup(service, "PCA input", adapter)
    assert not ranked and any(g["reason"] == "scope_unknown" for g in diag["gaps"])
    monkeypatch.setattr("engine.scientific_kg_evidence.ScientificKGEvidence", lambda: (_ for _ in ()).throw(ValueError("bad hash")))
    enabled = service.search(request("PCA input"))
    service.scientific_evidence_enabled = False
    baseline = service.search(request("PCA input"))
    assert enabled.hits == baseline.hits
    assert enabled.scientific_evidence["fallback_reason"] == "scientific_graph_binding_unavailable"


def test_new_preflight_preserves_all_frozen_assets_without_old_sut_lock():
    from eval import scientific_kg_evidence_retrieval_v1 as harness
    queries, manifest = harness.preflight()
    assert len(queries) == 57
    assert manifest["corpus_digest_recomputed"] == CORPUS_DIGEST
    assert manifest["production_default_changed"] is False
    frozen.verify_hashes(manifest["protected_sha256"])
