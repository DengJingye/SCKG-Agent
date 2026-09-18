"""Write-once development supplement. Observers delegate to the real search methods.

No dense encoder, new retrieval algorithm, graph construction or gold-to-request path.
Candidate snapshots are actual method outputs, not canonical product Trace records.
"""
from __future__ import annotations

import argparse
from collections import Counter, UserDict
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any
from unittest.mock import patch

import numpy as np

from engine import hybrid_retrieval as hr
from engine.evidence_graph_query import EvidenceGraphQuery
from eval import retrieval_benchmark_v1_1_dev as prior

ROOT = prior.PROJECT_ROOT
BASELINE = "fd3e528c7c85683382242f22da30e4c9a33dcf94"
CAMPAIGN_COMMIT = "52d1d1d8ee54dc035e88c3f855cee59a35023607"
HISTORICAL = ROOT / "eval_v2/retrieval_benchmark_v1_1_1_dev"
OUTPUT = ROOT / "eval_v2/kg_bm25_supplement_v1"
REPORT = ROOT / "docs/status/KG_BM25_SUPPLEMENT_V1.md"
TRACKS = ("R1_scientific_evidence", "R2_tool_method_discovery")
PROFILES = (prior.Profile("BM25", True, False, False, False),
            prior.Profile("KG_BM25", True, False, True, False))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(prior._canonical_json(value).encode()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def write(path: Path, value: Any) -> None:
    """Never overwrite any audit record, including failed-run records."""
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def protected_hashes() -> dict[str, str]:
    paths = git("ls-files", "--", "agent", "core", "engine", "execution", "data",
                "eval_v2", "eval/specs", "tool_contracts", "capability_packs").splitlines()
    return {p: sha(ROOT / p) for p in paths}


def verify_hashes(expected: dict[str, str]) -> None:
    for rel, expected_sha in expected.items():
        if not (ROOT / rel).is_file() or sha(ROOT / rel) != expected_sha:
            raise RuntimeError(f"protected_artifact_drift:{rel}")


def preflight() -> dict[str, Any]:
    old = json.loads((HISTORICAL / "pre_run_manifest.json").read_text())
    verify_hashes(old["source_artifact_sha256"])
    q, g = prior.V1_DIR / "queries.jsonl", prior.V1_DIR / "gold.jsonl"
    if sha(q) != prior.EXPECTED_QUERY_SHA or sha(g) != prior.EXPECTED_GOLD_SHA:
        raise RuntimeError("query_or_gold_drift")
    sut_paths = ["engine/hybrid_retrieval.py", "engine/evidence_graph_query.py",
                 "engine/evidence_discovery_index.py", "engine/knowledge_foundation_safety.py",
                 "core/canonical_task_ontology.py", "core/kg_ontology.py",
                 "core/knowledge_intelligence_models.py", "core/knowledge_graph_models.py"]
    graph_paths = git("ls-files", "--", "data/knowledge_graph_v2").splitlines()
    for rel in sut_paths + graph_paths:
        original = subprocess.check_output(["git", "show", f"{CAMPAIGN_COMMIT}:{rel}"], cwd=ROOT)
        if hashlib.sha256(original).hexdigest() != sha(ROOT / rel):
            raise RuntimeError(f"campaign_sut_or_graph_drift:{rel}")
    snapshot = prior._snapshot_identity()
    if snapshot != old["snapshot_identity"]:
        raise RuntimeError("snapshot_identity_drift")
    matrix = np.load(prior.INDEX_DIR / "evidence_vectors.npy", mmap_mode="r")
    if matrix.shape != (790, 1024):
        raise RuntimeError("actual_dense_shape_mismatch")
    meta = json.loads((prior.INDEX_DIR / "evidence_vector_metadata.json").read_text())
    ids = set(meta["chunk_ids"])
    chunks = prior._json_rows(prior.INDEX_DIR / "evidence_chunks.jsonl")
    corpus = hashlib.sha256()
    eligible = sorted((r for r in chunks if r["chunk_id"] in ids), key=lambda r: r["chunk_id"])
    for row in eligible:
        corpus.update((row["chunk_id"] + "\0" + row["content_hash"] + "\n").encode())
    if len(eligible) != 790 or corpus.hexdigest() != prior.EXPECTED_CORPUS_DIGEST:
        raise RuntimeError("actual_corpus_digest_mismatch")
    with sqlite3.connect((prior.INDEX_DIR / "evidence_fts5.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        build = db.execute("SELECT value FROM index_metadata WHERE key='build_id'").fetchone()
    if build != (prior.EXPECTED_BUILD_ID,):
        raise RuntimeError("fts_would_require_rebuild")
    queries = prior._json_rows(q)
    if Counter(r["track"] for r in queries) != Counter({TRACKS[0]: 45, TRACKS[1]: 12}):
        raise RuntimeError("query_population_mismatch")
    return {"head": git("rev-parse", "HEAD"), "baseline": BASELINE,
            "branch": git("branch", "--show-current"), "status_before": git("status", "--short"),
            "query_sha256": sha(q), "gold_sha256": sha(g), "snapshot": snapshot,
            "corpus_digest_recomputed": corpus.hexdigest(),
            "actual_dense_shape": list(matrix.shape), "campaign_comparison_commit": CAMPAIGN_COMMIT,
            "sut_sha256": {p: sha(ROOT / p) for p in sut_paths},
            "graph": {"path": "data/knowledge_graph_v2", "sha256": {p: sha(ROOT / p) for p in graph_paths}},
            "protected_sha256": protected_hashes()}


def request_for(query: dict[str, Any], kg: bool):
    # Explicit whitelist: never accept expected_tools, source/span IDs or gold.
    public = {"query": query["query"], "track": query["track"]}
    return prior._request(public, PROFILES[int(kg)])


class AccessLog(UserDict):
    """Read-only observation of dictionary lookups inside actual rank_tools()."""
    def __init__(self, original, events, kind):
        super().__init__()
        self.data = original
        self.events, self.kind = events, kind

    def __getitem__(self, key):
        value = self.data[key]
        self._record(key, value)
        return value

    def get(self, key, default=None):
        value = self.data.get(key, default)
        self._record(key, value)
        return value

    def __contains__(self, key):
        exists = key in self.data
        self.events.append({"mapping": self.kind, "key": key, "operation": "contains", "exists": exists})
        return exists

    def _record(self, key, value):
        event = {"mapping": self.kind, "key": key, "operation": "read"}
        if self.kind == "nodes":
            event["node"] = None if value is None else {"node_id": value.node_id, "node_type": value.node_type, "label": value.label}
        else:
            event["edges"] = [{"edge_id": e.edge_id, "source_id": e.source_id,
                               "relation": e.relation, "target_id": e.target_id,
                               "governance_layer": e.governance.layer} for e in (value or [])]
        self.events.append(event)


def verify_observed_output(observation: dict, response) -> None:
    final = observation.get("diversified", observation.get("fused", []))
    if hr._unsupported_operation_request(response.query):
        final = []
    expected = [[r[0], round(r[1], 8), r[2], r[3]] for r in final[:observation["request"]["top_k"]]]
    actual = [[h.chunk_id, h.score, h.sparse_rank, h.dense_rank] for h in response.hits]
    if expected != actual:
        raise RuntimeError(f"observer_search_divergence:expected={expected!r};actual={actual!r}")


def observe_search(service, request):
    """One actual search; wrappers return the original objects without changes."""
    obs = {"origin": "evaluation_observer_actual_method_calls_not_canonical_Trace",
           "request": request.model_dump(mode="json"), "graph_calls": [], "filter_calls": []}
    bm25, filt, kg = service._bm25_search, service._filter_ranked, service._kg_candidates
    rank_tools, rrf, diversify = EvidenceGraphQuery.rank_tools, hr._rrf, hr._diversify_ranked_by_tool

    def sparse(*args, **kwargs):
        rows = bm25(*args, **kwargs)
        obs["candidate_budget"] = kwargs["limit"]
        obs["raw_bm25"] = [list(r) for r in rows]
        return rows

    def filtered(rows, **kwargs):
        result = filt(rows, **kwargs)
        obs["filter_calls"].append({"input": [list(r) for r in rows], "output": [list(r) for r in result],
                                    "task_ids": sorted(kwargs["task_ids"]),
                                    "candidate_tools": sorted(kwargs["candidate_tools"]),
                                    "effective_request": kwargs["request"].model_dump(mode="json")})
        return result

    def candidates(**kwargs):
        result = kg(**kwargs)
        obs["kg_call"] = {**kwargs, "candidate_tools": sorted(result[0]), "warning": result[1],
                          "graph_dir_exists": service.graph_dir.is_dir(),
                          "graph_loaded": service._graph_query is not None,
                          "graph_available": bool(service._graph_query and service._graph_query.available)}
        return result

    def ranking(graph, **kwargs):
        call = {"entrypoint": "EvidenceGraphQuery.rank_tools", "arguments": kwargs,
                "graph_path": str(graph.graph_dir.relative_to(ROOT)) if graph.graph_dir.is_relative_to(ROOT) else "temporary_test_graph",
                "accesses": []}
        obs["graph_calls"].append(call)
        with ExitStack() as stack:
            for name in ("nodes", "incoming", "outgoing"):
                stack.enter_context(patch.object(graph, name, AccessLog(getattr(graph, name), call["accesses"], name)))
            matches = rank_tools(graph, **kwargs)
        call["matches"] = [m.model_dump(mode="json") for m in matches]
        return matches

    def fusion(*args, **kwargs):
        result = rrf(*args, **kwargs)
        obs["fused"] = [list(r) for r in result]
        return result

    def diversity(*args, **kwargs):
        result = diversify(*args, **kwargs)
        obs["diversified"] = [list(r) for r in result]
        return result

    with ExitStack() as stack:
        for obj, name, wrapper in [(service, "_bm25_search", sparse), (service, "_filter_ranked", filtered),
                                   (service, "_kg_candidates", candidates), (EvidenceGraphQuery, "rank_tools", ranking),
                                   (hr, "_rrf", fusion), (hr, "_diversify_ranked_by_tool", diversity)]:
            stack.enter_context(patch.object(obj, name, wrapper))
        response = service.search(request)
    if len(obs["filter_calls"]) != 1 or (not request.use_kg and (obs["graph_calls"] or "kg_call" in obs)):
        raise RuntimeError("unexpected_search_stage_count")
    verify_observed_output(obs, response)
    obs["observed_final_matches_search"] = True
    return response, obs


def candidate_summary(rows):
    ids = [r[0] for r in rows]
    return {"count": len(ids), "chunk_ids_in_order": ids,
            "set_digest": digest(sorted(set(ids))), "ordered_digest": digest(ids)}


def participation(obs: dict, changed: bool) -> str:
    if not obs["request"]["use_kg"]:
        return "KG_DISABLED"
    k = obs["kg_call"]
    if k["warning"] or not k["graph_dir_exists"] or (k["task_ids"] and not k["graph_available"]):
        return "KG_UNAVAILABLE_FALLBACK"
    if not obs["graph_calls"]:
        return "NO_TASK_GRAPH_NOT_QUERIED"
    if not any(c.get("matches") for c in obs["graph_calls"]):
        return "GRAPH_LOADED_NO_MATCH"
    return "GRAPH_MATCH_CANDIDATES_CHANGED" if changed else "GRAPH_MATCH_NO_CANDIDATE_CHANGE"


def compare(query, gold, before, after, baseline_obs, kg_obs, service):
    if baseline_obs["raw_bm25"] != kg_obs["raw_bm25"]:
        raise RuntimeError("initial_bm25_candidates_differ")
    bfilter, kfilter = baseline_obs["filter_calls"][0], kg_obs["filter_calls"][0]
    common, kgrows = bfilter["output"], kfilter["output"]
    bset, kset = {r[0] for r in common}, {r[0] for r in kgrows}
    removed, added = bset-kset, kset-bset
    accepted = prior._accepted_ids(gold)
    reasons = []
    for cid in sorted(removed):
        chunk = service._chunks_by_id[cid]
        tools = {hr._tool_key(t) for t in (chunk.tool_names or [chunk.tool_name]) if t}
        if not tools or not kfilter["candidate_tools"] or tools & set(kfilter["candidate_tools"]):
            raise RuntimeError(f"unexplained_candidate_removal:{cid}")
        reasons.append({"chunk_id": cid, "reason": "chunk_tool_membership_disjoint_from_KG_candidate_tools",
                        "chunk_tools": sorted(tools)})
    return {"query_id": query["query_id"], "query": query["query"], "track": query["track"],
            "classification": prior._paired(before, after),
            "participation": participation(kg_obs, bset != kset),
            "candidate_set_changed": bset != kset,
            "common_filter_before_KG": candidate_summary(common), "KG_filtered": candidate_summary(kgrows),
            "stage_interpretation": "Paired actual filter outputs. Production uses one combined filter, not a sequential common-then-KG stage. Common includes unchanged explicit-tool and task safeguards; KG may also widen candidate tools.",
            "removed": reasons, "added_chunk_ids": sorted(added),
            "gold_in_corpus": sorted(accepted & service._chunks_by_id.keys()),
            "gold_in_raw_bm25": sorted(accepted & {r[0] for r in baseline_obs["raw_bm25"]}),
            "gold_before_KG": sorted(accepted & bset), "gold_after_KG": sorted(accepted & kset),
            "gold_removed_by_KG": sorted(accepted & removed),
            "all_pre_filter_gold_lost": bool(accepted & bset) and not bool(accepted & kset),
            "BM25_first_gold_rank": before["first_gold_rank"], "KG_BM25_first_gold_rank": after["first_gold_rank"],
            "BM25_top_k": [h["chunk_id"] for h in before["retrieved"]],
            "KG_BM25_top_k": [h["chunk_id"] for h in after["retrieved"]],
            "top5_degradation": bool(before["recall_at_5"] and not after["recall_at_5"]),
            "top10_degradation": bool(before["recall_at_10"] and not after["recall_at_10"])}


def fraction(n, d):
    return {"numerator": n, "denominator": d, "rate": n/d if d else None,
            "status": "applicable" if d else "not_applicable"}


def summarize(rows):
    available = [r for r in rows if r["gold_before_KG"]]
    return {"query_count": len(rows), "helped_neutral_hurt": dict(Counter(r["classification"] for r in rows)),
            "participation": dict(Counter(r["participation"] for r in rows)),
            "candidate_set_changed": sum(r["candidate_set_changed"] for r in rows),
            "final_top_k_changed": sum(r["BM25_top_k"] != r["KG_BM25_top_k"] for r in rows),
            "first_gold_rank_changed": sum(r["BM25_first_gold_rank"] != r["KG_BM25_first_gold_rank"] for r in rows),
            "any_available_gold_removed": fraction(sum(bool(r["gold_removed_by_KG"]) for r in available), len(available)),
            "all_available_gold_lost": fraction(sum(r["all_pre_filter_gold_lost"] for r in available), len(available)),
            "baseline_hit5_lost": fraction(sum(r["top5_degradation"] for r in rows), sum(r["BM25_first_gold_rank"] is not None and r["BM25_first_gold_rank"] <= 5 for r in rows)),
            "baseline_hit10_lost": fraction(sum(r["top10_degradation"] for r in rows), sum(r["BM25_first_gold_rank"] is not None for r in rows))}


def graph_summary(observations):
    calls = [call for obs in observations.values() for call in obs["graph_calls"]]
    accessed_edges, nodes, selected_edges = {}, {}, {}
    for call in calls:
        for access in call["accesses"]:
            if access.get("node"):
                nodes[access["node"]["node_id"]] = access["node"]
            for edge in access.get("edges", []):
                accessed_edges[edge["edge_id"]] = edge
        for match in call.get("matches", []):
            for edge in match["paths"]:
                selected_edges[edge["edge_id"]] = edge
    return {"rank_tools_call_count": len(calls), "graph_read_node_types": dict(Counter(n["node_type"] for n in nodes.values())),
            "unique_nodes_read": len(nodes), "unique_edges_read": len(accessed_edges),
            "adjacency_read_relation_types": dict(Counter(e["relation"] for e in accessed_edges.values())),
            "selected_task_modality_path_relation_types": dict(Counter(e["relation"] for e in selected_edges.values())),
            "read_vs_use_boundary": "Adjacency lists can contain unrelated edges; read does not prove semantic evaluation. Selected match paths directly control candidate-tool eligibility. Outgoing contract/pilot/chunk checks only affect tool rank before limit=200.",
            "entrypoints": {name: {"path": str(Path(inspect.getfile(fn)).relative_to(ROOT)), "line": inspect.getsourcelines(fn)[1]}
                            for name, fn in [("search", hr.HybridRetrievalService.search),
                                             ("kg_candidates", hr.HybridRetrievalService._kg_candidates),
                                             ("rank_tools", EvidenceGraphQuery.rank_tools),
                                             ("tool_edges", EvidenceGraphQuery._tool_edges_for_targets),
                                             ("filter_ranked", hr.HybridRetrievalService._filter_ranked)]}}


def render_report(report):
    lines = ["# KG＋BM25 补充对照与实际参与度 v1", "", f"状态：{report['status']}。开发补充实验，不是 formal holdout。", "",
             "## 比较表", "", "Hit@5 / Hit@10 均为问题级至少命中一个 gold，不是完整相关文档召回率。历史 recall_at_5 / recall_at_10 字段未改写。", "",
             "| 来源 | Profile | Track | 问题级 Hit@5 | 问题级 Hit@10 | MRR |", "|---|---|---|---:|---:|---:|"]
    for origin, profiles in [("冻结 v1.1.1", report["historical_metrics"]), ("本次补充", report["metrics"])]:
        for profile, tracks in profiles.items():
            for track, m in tracks.items():
                h5, h10 = m["recall_at_5"], m["recall_at_10"]
                lines.append(f"| {origin} | {profile} | {track} | {h5['numerator']}/{h5['denominator']} | {h10['numerator']}/{h10['denominator']} | {m['mrr']:.6f} |")
    lines += ["", "版本/scope/authority 历史指标只是 gold/source 命中代理，不能独立验证所有返回内容的科学正确性。", "",
              "## 实际参与度与逐问题对照", "", f"BM25 冻结排序复现：{report['baseline_equivalence']}/57；观测输出与真实 search 最终排序校验：114/114。", "",
              "HELPED/HURT 按首个 gold 的 reciprocal rank 提升/降低；未命中记为 0。候选集合变化与最终排名变化分别记录。", ""]
    for track, stats in report["participation"].items():
        lines += [f"### {track}", "", "```json", json.dumps(stats, indent=2, ensure_ascii=False), "```", ""]
    lines += ["过滤损失分母：公共过滤后至少存在一个 gold 的 query；top-k 退化分母：BM25 原本命中的 query。HURT 不是 false-filter rate。", "",
              "| Query | Track | BM25 gold rank | KG＋BM25 gold rank | 结果 | 候选数 before→after | 参与类型 |", "|---|---|---:|---:|---|---|---|"]
    for p in report["pairs"]:
        lines.append(f"| {p['query_id']} | {p['track']} | {p['BM25_first_gold_rank']} | {p['KG_BM25_first_gold_rank']} | {p['classification']} | {p['common_filter_before_KG']['count']}→{p['KG_filtered']['count']} | {p['participation']} |")
    lines += ["", "## 实际图调用边界", "", "```json", json.dumps(report["graph_usage"], ensure_ascii=False, indent=2), "```", "",
              "真实调用：HybridRetrievalService.search → _kg_candidates → EvidenceGraphQuery.rank_tools；图文件为 data/knowledge_graph_v2/{nodes,edges,manifest}.json[l]。",
              "rank_tools 按 Task/Modality 查询工具，可能展开 IS_SUBTASK_OF，并用 contract/pilot/source-chunk 元数据为工具候选评分；分数本身不加入 BM25/RRF 排名。候选集合最多 200 个工具，再以 chunk 原有工具 membership 过滤。", "",
              "graph_access.jsonl 保存每次真实图查询的节点/边读取、匹配路径、候选工具和 warning。读取某类边不等于执行了该边的科学含义；例如读取 HAS_TOOL_CONTRACT 只检查存在性与治理层，不验证 contract 输入。", "",
              "production search 内只有一次综合 _filter_ranked。before/after 是两个配对 profile 的实际过滤输出，不伪称 production 先后执行两次 filter，也不是 canonical Trace。", "",
              "- legacy Tool/Task/Modality：EXERCISED（实际调用证据见 graph_access.jsonl）。",
              "- Scientific KG OperatorRevision：NOT_EXERCISED。",
              "- Scientific requirement / ApplicabilityScope / version 条件：NOT_EXERCISED。",
              "- AtomicClaim → EvidenceSpan 科学决策证据遍历：NOT_EXERCISED。",
              "新 Scientific KG 的适用性语义在 planner applicability 路径，不在此检索候选接口。本次不能证明新图改善科学检索。若后续要测，需要单独定义并实现从 retrieval scientific claim request 到受治理 OperatorRevision/requirement/scope/version/AtomicClaim→EvidenceSpan 的生产查询边界；本轮未接入。", "",
              "## 冻结与执行记录", "", f"输入/SUT/graph/test SHA 见 pre_run_manifest.json；结果摘要见 artifact_manifest.json。测试记录：{report['test_record']}。",
              "BM25 与 KG＋BM25 各执行 57 次 search，无 dense encode；不修改原有工具识别、归一化、top-k、候选预算或多样化规则。所有 gold 仅在响应产生后评分，未传入 request。",
              "输出中的 candidate_pending_review、catalog metadata 不能因命中升级为 trusted。历史结果与 Seed 保持原字节；未调参、未提交、未 push。", ""]
    return "\n".join(lines)


def run(output: Path, report_path: Path, test_record: str) -> dict:
    if output.exists() or report_path.exists():
        raise FileExistsError("write-once supplement output/report already exists")
    pre = preflight()
    pre.update({"runner_sha256": sha(Path(__file__)),
                "test_sha256": sha(ROOT / "tests/test_kg_bm25_supplement_v1.py"),
                "test_record": test_record,
                "profiles": [request_for({"query": "<query>", "track": TRACKS[0]}, p.kg).model_dump(mode="json") for p in PROFILES],
                "metric_policy": "query-level Hit@5/10; historical recall field aliases unchanged; HELPED/HURT by reciprocal rank; no composite score"})
    pre["configuration_sha256"] = digest(pre["profiles"])
    output.mkdir(parents=True, exist_ok=False)
    write(output / "pre_run_manifest.json", pre)
    write(output / "run_started.json", {"started_at": datetime.now(timezone.utc).isoformat(), "run_count": 1})
    active = {"stage": "service_initialization"}
    results, observations, pairs = [], {}, []
    try:
        # Abort instead of allowing the constructor to rebuild an index.
        with patch.object(hr.HybridRetrievalService, "_build_fts_index", side_effect=RuntimeError("index_rebuild_forbidden")):
            service = prior._service(None)
        queries = prior._json_rows(prior.V1_DIR / "queries.jsonl")
        golds = {r["query_id"]: r for r in prior._json_rows(prior.V1_DIR / "gold.jsonl")}
        frozen = {r["query_id"]: r for r in prior._json_rows(HISTORICAL / "per_query_results.jsonl") if r["profile_id"] == "R0_bm25_only"}
        # Gate the complete new BM25 baseline BEFORE any KG-enabled experiment.
        with (output / "raw_search.jsonl").open("x") as raw, (output / "observations.jsonl").open("x") as obsfile, (output / "graph_access.jsonl").open("x") as graphfile:
            for profile in PROFILES:
                for query in queries:
                    qid = query["query_id"]
                    active = {"stage": "search", "profile": profile.profile_id, "query_id": qid, "query": query["query"]}
                    response, obs = observe_search(service, request_for(query, profile.kg))
                    raw.write(prior._canonical_json({**active, "response": response.model_dump(mode="json")}) + "\n"); raw.flush()
                    obsfile.write(prior._canonical_json({**active, "observation": obs}) + "\n"); obsfile.flush()
                    graphfile.write(prior._canonical_json({"query_id": qid, "profile": profile.profile_id, "graph_identity": pre["graph"], "calls": obs["graph_calls"], "kg_call": obs.get("kg_call")}) + "\n"); graphfile.flush()
                    hits = [h.model_dump(mode="json") for h in response.hits]
                    if not profile.kg and hits != frozen[qid]["retrieved"]:
                        active.update({"earliest_divergence": "frozen_BM25_returned_hits", "expected": frozen[qid]["retrieved"], "actual": hits})
                        raise RuntimeError(f"BM25_frozen_ranking_mismatch:{qid}")
                    result = prior._evaluate_hit_list(query, golds[qid], hits)
                    result["profile_id"] = profile.profile_id
                    results.append(result)
                    observations[(profile.profile_id, qid)] = obs
                    if profile.kg:
                        before = next(r for r in results if r["profile_id"] == "BM25" and r["query_id"] == qid)
                        pairs.append(compare(query, golds[qid], before, result, observations[("BM25", qid)], obs, service))
        verify_hashes(pre["protected_sha256"])
        metrics = {p.profile_id: {t: prior._aggregate([r for r in results if r["profile_id"] == p.profile_id and r["track"] == t]) for t in TRACKS} for p in PROFILES}
        report = {"status": "COMPLETE", "development_only": True, "head": pre["head"],
                  "baseline_equivalence": len(queries), "search_calls": len(results), "metrics": metrics,
                  "graph_usage": graph_summary(observations),
                  "historical_metrics": json.loads((HISTORICAL / "report.json").read_text())["aggregate_metrics"],
                  "participation": {t: summarize([r for r in pairs if r["track"] == t]) for t in (*TRACKS, "ALL")},
                  "pairs": pairs, "test_record": test_record,
                  "production_changed": False, "frozen_artifacts_changed": False}
        report["participation"]["ALL"] = summarize(pairs)
        write(output / "per_query_results.json", results)
        write(output / "report.json", report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("x") as stream:
            stream.write(render_report(report))
        write(output / "run_completed.json", {"completed_at": datetime.now(timezone.utc).isoformat(), "run_count": 1, "report_sha256": sha(output / "report.json")})
        write(output / "artifact_manifest.json", {"files": {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()}, "human_report_sha256": sha(report_path)})
        return report
    except Exception as exc:
        failure = {"status": "INVALID", "exception_type": type(exc).__name__, "message": str(exc),
                   "reproduction": active, "owner": "evaluation_or_frozen_SUT_equivalence_requires_read_only_attribution",
                   "impact": "No KG gain conclusion authorized; partial artifacts preserved; do not overwrite."}
        write(output / "failure.json", failure)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--test-record", default="")
    args = parser.parse_args()
    if args.preflight == args.run:
        parser.error("select exactly one of --preflight or --run")
    if args.run and not args.test_record:
        parser.error("--test-record required after focused tests")
    value = preflight() if args.preflight else run(args.output, args.report, args.test_record)
    print(json.dumps(value if args.preflight else {k: value[k] for k in ("status", "baseline_equivalence", "metrics", "participation")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
