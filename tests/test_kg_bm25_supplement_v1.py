"""Evaluation-only tests. Every synthetic index/output is inside tmp_path."""
import copy
import json
from pathlib import Path

import pytest

from core.canonical_task_ontology import canonical_task
from core.kg_ontology import normalize_task, normalize_modality
from engine.evidence_discovery_index import EvidenceChunk, chunk_to_dict
from engine.hybrid_retrieval import HybridRetrievalService
from eval import kg_bm25_supplement_v1 as sut


QUERY = {"query_id": "synthetic", "query": "batch integration input", "track": sut.TRACKS[0],
         "task_family": "batch_integration", "query_type": "input_requirement"}
GOLD = {"gold_evidence_span_ids": ["gold"], "indexed_chunk_aliases": [], "source_ids": [],
        "expected_version": "", "expected_scope": ""}


def dump_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def service_fixture(tmp_path, matching_tool="AlphaTool", graph_mode="valid"):
    chunks = [EvidenceChunk(chunk_id=cid, evidence_id=cid, source_kind="source_document",
                            source_table="fixture", source_record_id=cid, tool_name=tool,
                            tool_names=[tool], source_bound=True, source_span="paragraph 1",
                            chunk_text="batch integration input matrix", title=tool,
                            content_hash=cid, retrieval_status="retrieval_only")
              for cid, tool in [("gold", "AlphaTool"), ("other", "BetaTool")]]
    dump_rows(tmp_path / "evidence.jsonl", [chunk_to_dict(c) for c in chunks])
    dump_rows(tmp_path / "catalog.jsonl", [])
    (tmp_path / "manifest.json").write_text('{"build_id":"test"}')
    graph = tmp_path / "graph"
    if graph_mode != "missing":
        graph.mkdir()
        task_id = "task:" + normalize_task(canonical_task("batch_integration").label).canonical_id
        mod_id = "modality:" + normalize_modality("scRNA-seq").canonical_id
        gov = {"layer": "retrieval_only", "source_bound": True}
        nodes = [{"node_id": task_id, "node_type": "Task", "label": "task", "governance": gov},
                 {"node_id": mod_id, "node_type": "Modality", "label": "scRNA-seq", "governance": gov},
                 {"node_id": "tool:match", "node_type": "Tool", "label": matching_tool, "governance": gov}]
        edges = [{"edge_id": "edge:task", "source_id": "tool:match", "target_id": task_id,
                  "relation": "CATALOG_ADDRESSES_TASK", "governance": gov},
                 {"edge_id": "edge:modality", "source_id": "tool:match", "target_id": mod_id,
                  "relation": "CATALOG_SUPPORTS_MODALITY", "governance": gov}]
        dump_rows(graph / "nodes.jsonl", nodes)
        dump_rows(graph / "edges.jsonl", [] if graph_mode == "no_match" else edges)
        if graph_mode == "corrupt":
            (graph / "nodes.jsonl").write_text("not-json\n")
    return HybridRetrievalService(evidence_chunks_path=tmp_path / "evidence.jsonl",
                                  catalog_chunks_path=tmp_path / "catalog.jsonl",
                                  fts_index_path=tmp_path / "fts.sqlite",
                                  index_manifest_path=tmp_path / "manifest.json",
                                  coverage_path=tmp_path / "coverage.json",
                                  dense_matrix_path=tmp_path / "unused.npy",
                                  dense_metadata_path=tmp_path / "unused.json", graph_dir=graph)


def pair(service):
    b, ob = sut.observe_search(service, sut.request_for(QUERY, False))
    k, ok = sut.observe_search(service, sut.request_for(QUERY, True))
    br = sut.prior._evaluate_hit_list(QUERY, GOLD, [h.model_dump(mode="json") for h in b.hits])
    kr = sut.prior._evaluate_hit_list(QUERY, GOLD, [h.model_dump(mode="json") for h in k.hits])
    return sut.compare(QUERY, GOLD, br, kr, ob, ok, service), ob, ok


def test_profiles_differ_only_by_kg_and_keep_original_request():
    b, k = [sut.request_for(QUERY, enabled).model_dump(mode="json") for enabled in (False, True)]
    assert {key for key in b if b[key] != k[key]} == {"use_kg"}
    assert b == sut.prior._request(QUERY, sut.prior.PROFILES[0]).model_dump(mode="json")
    assert b["top_k"] == 10 and not b["enable_dense"] and not b["use_governance_rerank"]


def test_gold_fields_cannot_enter_request():
    injected = {**QUERY, **GOLD, "tool_names": ["BetaTool"], "expected_tools": ["BetaTool"],
                "canonical_tasks": ["injected"], "source_types": ["injected"]}
    for kg in (False, True):
        assert sut.request_for(injected, kg) == sut.request_for(QUERY, kg)
        assert sut.request_for(injected, kg).tool_names == []


def test_disabled_kg_has_no_graph_calls_or_attribution(tmp_path):
    s = service_fixture(tmp_path)
    _, obs = sut.observe_search(s, sut.request_for(QUERY, False))
    assert not obs["graph_calls"] and "kg_call" not in obs
    assert sut.participation(obs, False) == "KG_DISABLED"
    assert s._graph_query is None


@pytest.mark.parametrize(("mode", "expected"), [("no_match", "GRAPH_LOADED_NO_MATCH"),
                          ("missing", "KG_UNAVAILABLE_FALLBACK"), ("corrupt", "KG_UNAVAILABLE_FALLBACK")])
def test_no_match_and_fallback_not_counted_as_intervention(tmp_path, mode, expected):
    p, _, _ = pair(service_fixture(tmp_path, graph_mode=mode))
    assert p["participation"] == expected
    assert not p["candidate_set_changed"]
    assert p["classification"] == "NEUTRAL"


def test_no_task_is_not_a_successful_graph_query(tmp_path):
    s = service_fixture(tmp_path)
    request = sut.request_for({**QUERY, "query": "unrelated frobnication"}, True)
    _, obs = sut.observe_search(s, request)
    assert sut.participation(obs, False) == "NO_TASK_GRAPH_NOT_QUERIED"


def test_actual_kg_gold_removal_records_correct_stage_and_denominator(tmp_path):
    p, ob, ok = pair(service_fixture(tmp_path, matching_tool="BetaTool"))
    assert p["gold_before_KG"] == ["gold"]
    assert p["gold_removed_by_KG"] == ["gold"]
    assert p["all_pre_filter_gold_lost"]
    assert p["participation"] == "GRAPH_MATCH_CANDIDATES_CHANGED"
    stats = sut.summarize([p])
    assert stats["any_available_gold_removed"]["numerator"] == 1
    assert stats["any_available_gold_removed"]["denominator"] == 1
    assert ob["raw_bm25"] == ok["raw_bm25"]
    assert any(c["matches"] for c in ok["graph_calls"])
    assert any(a["mapping"] == "incoming" and a.get("edges") for a in ok["graph_calls"][0]["accesses"])


def test_rank_only_hurt_is_not_filter_loss(tmp_path):
    s = service_fixture(tmp_path)
    b, obs = sut.observe_search(s, sut.request_for(QUERY, False))
    ko = copy.deepcopy(obs)
    ko["request"]["use_kg"] = True
    ko["kg_call"] = {"warning": "", "task_ids": ["batch_integration"], "graph_dir_exists": True, "graph_available": True}
    ko["graph_calls"] = [{"matches": [{"tool_name": "AlphaTool"}]}]
    hits = [h.model_dump(mode="json") for h in b.hits]
    before = sut.prior._evaluate_hit_list(QUERY, GOLD, sorted(hits, key=lambda h: h["chunk_id"] != "gold"))
    after = sut.prior._evaluate_hit_list(QUERY, GOLD, sorted(hits, key=lambda h: h["chunk_id"] == "gold"))
    p = sut.compare(QUERY, GOLD, before, after, obs, ko, s)
    assert p["classification"] == "HURT"
    assert not p["gold_removed_by_KG"] and not p["candidate_set_changed"]
    assert p["participation"] == "GRAPH_MATCH_NO_CANDIDATE_CHANGE"


@pytest.mark.parametrize("kg", [False, True])
def test_observer_delegation_matches_uninstrumented_real_search(tmp_path, kg):
    s = service_fixture(tmp_path)
    request = sut.request_for(QUERY, kg)
    ordinary = s.search(request)
    observed, obs = sut.observe_search(s, request)
    for field in ("hits", "pipeline", "warnings", "dense_status", "query", "mode", "index_build_id"):
        assert getattr(ordinary, field) == getattr(observed, field)
    assert obs["observed_final_matches_search"]
    assert obs["candidate_budget"] == 120


def test_diagnostic_rank_drift_is_fatal(tmp_path):
    s = service_fixture(tmp_path)
    response, obs = sut.observe_search(s, sut.request_for(QUERY, False))
    obs.get("diversified", obs["fused"])[0][0] = "wrong-id"
    with pytest.raises(RuntimeError, match="observer_search_divergence"):
        sut.verify_observed_output(obs, response)


def test_undefined_opportunities_are_not_applicable():
    stats = sut.summarize([])
    for key in ("any_available_gold_removed", "all_available_gold_lost", "baseline_hit5_lost", "baseline_hit10_lost"):
        assert stats[key] == {"numerator": 0, "denominator": 0, "rate": None, "status": "not_applicable"}


def test_write_once_artifacts(tmp_path):
    path = tmp_path / "marker.json"
    sut.write(path, {"status": "INVALID"})
    with pytest.raises(FileExistsError):
        sut.write(path, {"status": "COMPLETE"})
    assert json.loads(path.read_text())["status"] == "INVALID"


def test_frozen_assets_and_seed_are_unchanged_by_temp_search(tmp_path):
    before = sut.protected_hashes()
    pair(service_fixture(tmp_path))
    sut.verify_hashes(before)
    for rel in ("eval_v2/manifests/midterm_core_seed_v0.json", "eval_v2/manifests/midterm_core_seed_v0.freeze.json"):
        committed = sut.subprocess.check_output(["git", "show", f"{sut.BASELINE}:{rel}"], cwd=sut.ROOT)
        assert (sut.ROOT / rel).read_bytes() == committed


def test_frozen_input_preflight_is_read_only_and_matches_real_assets():
    before = sut.protected_hashes()
    pre = sut.preflight()
    sut.verify_hashes(before)
    assert pre["query_sha256"] == sut.prior.EXPECTED_QUERY_SHA
    assert pre["gold_sha256"] == sut.prior.EXPECTED_GOLD_SHA
    assert pre["corpus_digest_recomputed"] == sut.prior.EXPECTED_CORPUS_DIGEST
    assert pre["actual_dense_shape"] == [790, 1024]


def test_baseline_drift_stops_before_kg_and_preserves_failed_run(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    dump_rows(inputs / "queries.jsonl", [QUERY])
    dump_rows(inputs / "gold.jsonl", [{"query_id": QUERY["query_id"], **GOLD}])
    dump_rows(inputs / "per_query_results.jsonl", [{"profile_id": "R0_bm25_only", "query_id": QUERY["query_id"], "retrieved": []}])
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    s = service_fixture(fixture_dir)
    monkeypatch.setattr(sut, "preflight", lambda: {"head": "synthetic", "protected_sha256": {}, "graph": {}})
    monkeypatch.setattr(sut.prior, "V1_DIR", inputs)
    monkeypatch.setattr(sut, "HISTORICAL", inputs)
    monkeypatch.setattr(sut.prior, "_service", lambda _: s)
    out, doc = tmp_path / "failed", tmp_path / "report.md"
    with pytest.raises(RuntimeError, match="BM25_frozen_ranking_mismatch"):
        sut.run(out, doc, "synthetic negative control")
    assert s._graph_query is None
    assert (out / "run_started.json").exists()
    assert not (out / "run_completed.json").exists()
    assert json.loads((out / "failure.json").read_text())["reproduction"]["earliest_divergence"] == "frozen_BM25_returned_hits"
    preserved = {p.name: sut.sha(p) for p in out.iterdir()}
    with pytest.raises(FileExistsError):
        sut.run(out, doc, "must not overwrite")
    assert preserved == {p.name: sut.sha(p) for p in out.iterdir()}


def test_graph_read_relations_are_distinct_from_selected_match_paths(tmp_path):
    _, _, obs = pair(service_fixture(tmp_path))
    summary = sut.graph_summary({"query": obs})
    assert summary["rank_tools_call_count"] == 1
    assert summary["selected_task_modality_path_relation_types"] == {"CATALOG_ADDRESSES_TASK": 1, "CATALOG_SUPPORTS_MODALITY": 1}
    assert "OperatorRevision" not in summary["graph_read_node_types"]
