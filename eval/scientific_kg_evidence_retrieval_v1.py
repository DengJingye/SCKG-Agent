"""Write-once development comparison. Real production search, no diagnostic ranking clone.

Gold is available only to the post-search scorer. Production sees the same public
request whitelist as the frozen supplement, with a service-level graph switch.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np

from agent.research_tool_registry import ResearchToolRegistry
from core.research_agent_models import ResearchToolCall, ResearchToolPlan
from engine.hybrid_retrieval import HybridRetrievalService
from engine.scientific_kg_evidence import ScientificKGEvidence, parse_scientific_query, PREDICATES
from eval import kg_bm25_supplement_v1 as frozen
from eval import retrieval_benchmark_v1_1_dev as prior

ROOT = prior.PROJECT_ROOT
OUTPUT = ROOT / "eval_v2/scientific_kg_evidence_retrieval_v1_dev"
REPORT = ROOT / "docs/status/SCIENTIFIC_KG_EVIDENCE_RETRIEVAL_INTEGRATION_V1.md"
OLD = ROOT / "eval_v2/kg_bm25_supplement_v1"
PRODUCTION = ["engine/scientific_kg_evidence.py", "engine/hybrid_retrieval.py",
              "core/knowledge_intelligence_models.py", "agent/research_tool_registry.py"]
NEW_FILES = [*PRODUCTION, "eval/scientific_kg_evidence_retrieval_v1.py",
             "tests/test_scientific_kg_evidence_retrieval_v1.py"]
PROFILES = ("A_BM25", "B_LEGACY_KG_BM25", "C_SCIENTIFIC_KG_BM25")
MERGE_POLICY = {"channels": "BM25 plus scientific evidence (no legacy KG in C)",
                "rrf_k": 60, "channel_weights": "equal", "scientific_max_chunks": 12,
                "scientific_order": "unique chunk IDs ascending", "bm25_budget": 120,
                "top_k": 10, "diversification": "unchanged production behavior",
                "fallback": "original BM25; no corpus/index mutation"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    frozen.write(path, value)


def request_for(query, profile):
    if profile not in PROFILES:
        raise ValueError("unknown_profile")
    return frozen.request_for({"query": query["query"], "track": query["track"]}, profile == PROFILES[1])


def scope_partition(queries):
    """Frozen before results, based only on operator/API resolution, never gold."""
    return {q["query_id"]: {"operator": parse_scientific_query(q["query"])["operator"],
                           "supported_operator_scope": q["track"] == frozen.TRACKS[0] and
                           parse_scientific_query(q["query"])["operator"] is not None and
                           parse_scientific_query(q["query"])["fallback_reason"] not in {
                               "non_scanpy_package", "unsupported_or_historical_operator_api"}}
            for q in queries}


def metrics(rows):
    return {"query_count": len(rows),
            "hit_at_5": {"numerator": sum(r["recall_at_5"] for r in rows), "denominator": len(rows)},
            "hit_at_10": {"numerator": sum(r["recall_at_10"] for r in rows), "denominator": len(rows)},
            "mrr": prior._mean(r["reciprocal_rank"] for r in rows)}


def classify(a, c):
    delta = c["reciprocal_rank"] - a["reciprocal_rank"]
    return "HELPED" if delta > 0 else "HURT" if delta < 0 else "NEUTRAL"


def verify_baseline(hits, old, query_id, profile):
    if hits != old:
        first = next((i for i, (a, b) in enumerate(zip(hits, old), 1) if a != b), min(len(hits), len(old)) + 1)
        raise RuntimeError(f"baseline_output_divergence:{profile}:{query_id}:rank={first}")


def preflight():
    historical = json.loads((OLD / "pre_run_manifest.json").read_text())
    frozen.verify_hashes({p: h for p, h in historical["protected_sha256"].items() if p not in PRODUCTION})
    artifact = json.loads((OLD / "artifact_manifest.json").read_text())
    for name, digest in artifact["files"].items():
        if sha(OLD / name) != digest:
            raise RuntimeError(f"historical_supplement_drift:{name}")
    for name, digest in [("queries.jsonl", prior.EXPECTED_QUERY_SHA), ("gold.jsonl", prior.EXPECTED_GOLD_SHA)]:
        if sha(prior.V1_DIR / name) != digest:
            raise RuntimeError(f"frozen_query_or_gold_drift:{name}")
    snapshot = prior._snapshot_identity()
    if snapshot != historical["snapshot"]:
        raise RuntimeError("frozen_snapshot_drift")
    matrix = np.load(prior.INDEX_DIR / "evidence_vectors.npy", mmap_mode="r")
    if matrix.shape != (790, 1024):
        raise RuntimeError("dense_shape_drift")
    meta = json.loads((prior.INDEX_DIR / "evidence_vector_metadata.json").read_text())
    ids = set(meta["chunk_ids"])
    chunks = prior._json_rows(prior.INDEX_DIR / "evidence_chunks.jsonl")
    digest = hashlib.sha256()
    eligible = sorted((r for r in chunks if r["chunk_id"] in ids), key=lambda r: r["chunk_id"])
    for r in eligible:
        digest.update((r["chunk_id"] + "\0" + r["content_hash"] + "\n").encode())
    if len(eligible) != 790 or digest.hexdigest() != prior.EXPECTED_CORPUS_DIGEST:
        raise RuntimeError("actual_corpus_digest_drift")
    with sqlite3.connect((prior.INDEX_DIR / "evidence_fts5.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("SELECT value FROM index_metadata WHERE key='build_id'").fetchone() != (prior.EXPECTED_BUILD_ID,):
            raise RuntimeError("fts_rebuild_would_be_required")
    queries = prior._json_rows(prior.V1_DIR / "queries.jsonl")
    if Counter(q["track"] for q in queries) != Counter({frozen.TRACKS[0]: 45, frozen.TRACKS[1]: 12}):
        raise RuntimeError("query_population_drift")
    protected = frozen.protected_hashes()
    # Preserve known local audit/development files too; never include their content.
    for subdir in ("data/development", "data/evaluation"):
        for path in (ROOT / subdir).rglob("*"):
            if path.is_file():
                protected[str(path.relative_to(ROOT))] = sha(path)
    return queries, {"head": frozen.git("rev-parse", "HEAD"), "status_before": frozen.git("status", "--short"),
                     "query_set_sha256": prior.EXPECTED_QUERY_SHA, "gold_sha256": prior.EXPECTED_GOLD_SHA,
                     "snapshot": snapshot, "corpus_digest_recomputed": digest.hexdigest(),
                     "scientific_graph": ScientificKGEvidence().identity, "legacy_graph": prior._kg_identity(),
                     "source_sha256": {p: sha(ROOT / p) for p in NEW_FILES}, "protected_sha256": protected,
                     "scope_partition": scope_partition(queries), "merge_policy": MERGE_POLICY,
                     "development_only": True, "production_default_changed": False}


def product_smoke(service):
    query = "Scanpy 1.11.2 highly_variable_genes flavor='seurat_v3' input requirements"
    plan = ResearchToolPlan(source="deterministic_fallback", answer_strategy="grounded", calls=[ResearchToolCall(
        call_id="scientific-evidence-structured-smoke", tool_name="search_evidence", query=query,
        tool_names=["Scanpy"], claim_types=["input_requirement"], top_k=10)])
    result = ResearchToolRegistry(retrieval=service).execute(plan, fallback_query=query, fallback_task="",
             enable_dense=False, use_kg=False, use_governance_rerank=False, use_contract_gate=False)
    retrieval = result.retrieval
    if not retrieval or not retrieval.scientific_evidence or not retrieval.scientific_evidence["final_graph_chunk_ids"]:
        raise RuntimeError("structured_research_entry_did_not_return_graph_evidence")
    return {"kind": "structured_product_interface_smoke_not_LLM_QA", "external_llm_calls": 0,
            "entrypoint": "ResearchToolRegistry.execute -> _search -> HybridRetrievalService.search -> ScientificKGEvidence.query",
            "canonical_trace_claimed": False, "execution_authorized": False,
            "observations": [o.model_dump(mode="json") for o in result.observations],
            "retrieval": retrieval.model_dump(mode="json")}


def evidence_checks(diag):
    checks = []
    final = set(diag.get("final_graph_chunk_ids", []))
    for path in diag.get("paths", []):
        for ev in path["evidence"]:
            for cid in set(ev["chunk_ids"]) & final:
                checks.append({"chunk_id": cid, "claim_id": path["claim_revision_id"],
                               "predicate": path["predicate"], "scope": path["scope"],
                               "binding_verified": ev["binding_verified"],
                               "candidate_not_trusted": ev["knowledge_status"] == "candidate",
                               "registered_support_only_not_independent_human_adjudication": True,
                               "information_need_matches": path["predicate"] in set().union(*(
                                   PREDICATES[n] for n in diag["parsed"]["information_needs"])),
                               "scope_not_asserted_compatible_with_user_data": not path["scope"]["data_compatibility_assessed"]})
    return checks


def render(report, rows):
    lines = ["# Scientific KG Evidence Retrieval Integration v1", "",
             "开发对照；不是 formal holdout，不是独立泛化验证。问题级 Hit@5/10，不是全相关文档召回率。", "",
             f"Integration: {report['integration']}；DEV: {report['status']}；observed benefit: {report['benefit']}。", "",
             "## 完整结果", "", "| Panel | Profile | Hit@5 | Hit@10 | MRR |", "|---|---|---:|---:|---:|"]
    for panel, profiles in report["metrics"].items():
        for profile, m in profiles.items():
            lines.append(f"| {panel} | {profile} | {m['hit_at_5']['numerator']}/{m['query_count']} | {m['hit_at_10']['numerator']}/{m['query_count']} | {m['mrr']} |")
    lines += ["", "## 因果与语义边界", "",
              "A/B 所有114份 hit 列表（含排名、score和来源字段）与冻结补充实验完全一致；只新增 C。",
              "C 不使用 legacy KG hard filter；科学图通道与 A 的 BM25 候选合并，等权 RRF k=60、图预算12、稳定chunk-ID次序，公共过滤/多样化不变。默认关闭。",
              "实际遍历 OperatorRevision → subject-matched AtomicClaim/Requirement/Constraint → scope/version/flavor → exact binding → EvidenceSpan/SourceRevision → 已有chunk。",
              "candidate 仍是 candidate，supports assessment不等于人工审阅；没有执行授权，没有伪造Ledger。",
              "证据支持检查仅验证已登记的predicate/scope/binding，不是对全部top-k内容的独立科学正确性认证；未命中gold不自动意味着科学错误。",
              "未指定版本仅返回1.11.2范围内证据；未指定HVG flavor保留条件化分支。版本/范围不支持则不向图通道注入。",
              "PCA output在当前图切片无对应claim；pca.mask、neighbors.metadata span未进入冻结corpus。neighbors.input在corpus标记Harmony，显式Scanpy过滤可能拒绝。均保留EvidenceGap/回退，不修图或corpus。", "",
              "## 图参与度", "", "```json", json.dumps(report["participation"], ensure_ascii=False, indent=2), "```", "",
              "## 逐题 first-gold rank", "", "| Query | A | B | C | C vs A | C vs B |", "|---|---:|---:|---:|---|---|"]
    for r in report["paired"]:
        lines.append(f"| {r['query_id']} | {r['A']} | {r['B']} | {r['C']} | {r['C_vs_A']} | {r['C_vs_B']} |")
    lines += ["", "## 验证与失败归因", "",
              f"Focused validation: {report['tests']}；未运行full pytest。", "",
              "预实验EDD：系统python缺pytest（环境）；测试夹具误复制不存在的可选retrieval_coverage.json（测试层，去除复制）；测试给frozen EvidenceChunk赋值（测试层，改用dataclasses.replace临时副本）；HVG flavor被已有工具识别附带识别为Seurat（新adapter上下文层，区分已解析flavor，不改公共工具识别）。均在实验前修复并回归。",
              "额外历史回归检查：62 passed / 1 failed。唯一失败为旧supplement preflight锁定旧hybrid_retrieval.py SHA，当前经授权新增生产入口必然不相等；属于历史SUT身份门槛，不声称旧实验可在新SUT上重跑。未修改旧测试/runner。当前focused门槛使用新adapter/harness+HybridRetrieval+Research入口；新preflight验证旧资产，A/B精确hit等价另行验证行为。",
              "ResearchToolRegistry真实search_evidence入口smoke返回图证据，未调用LLM；不冒充完整问答或canonical执行Trace。新增诊断只包含登记知识标识/约束，无用户数据状态、主机绝对路径、凭证或执行授权。",
              "数据、图、Seed、Planner/Contract/Policy和历史实验摘要前后保持一致，详见pre_run_manifest和integrity_after。测试只写临时目录。",
              "下一步若要覆盖更多谓词、operator或当前数据适用性，需要另行确认知识/映射/产品调用边界；本轮未实施。", "",
              "## 产物", "",
              "`eval_v2/scientific_kg_evidence_retrieval_v1_dev/`：pre_run_manifest、raw_search、per_query_results、graph_paths、evidence_checks、product_smoke、report、integrity_after和write-once markers。",
              "新增实现/测试/结果未commit或push；仅上一轮补充实验已独立冻结。"]
    return "\n".join(lines) + "\n"


def run(output=OUTPUT, report_path=REPORT, *, test_report):
    if output.exists() or report_path.exists():
        raise FileExistsError("refuse_overwrite_existing_campaign_or_report")
    test_root = ET.parse(test_report).getroot()
    suites = list(test_root.iter("testsuite"))
    tests = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    if not tests["tests"] or tests["errors"] or tests["failures"] or tests["skipped"]:
        raise RuntimeError("focused_tests_not_all_passed")
    queries, manifest = preflight()
    manifest["tests"] = {**tests, "junit_sha256": sha(test_report)}
    manifest["configuration_sha256"] = frozen.digest({"merge": MERGE_POLICY, "scope": manifest["scope_partition"],
                                                     "requests": {p: [request_for(q, p).model_dump(mode="json") for q in queries] for p in PROFILES}})
    output.mkdir(parents=True, exist_ok=False)
    write(output / "pre_run_manifest.json", manifest)
    write(output / "run_started.json", {"timestamp": datetime.now(timezone.utc).isoformat(), "campaign": "development", "run_count": 1})
    rows, diagnostics = [], []
    try:
        gold = {r["query_id"]: r for r in prior._json_rows(prior.V1_DIR / "gold.jsonl")}
        previous = {(r["profile_id"], r["query_id"]): r for r in json.loads((OLD / "per_query_results.json").read_text())}
        with patch.object(HybridRetrievalService, "_build_fts_index", side_effect=RuntimeError("index_rebuild_forbidden")):
            service = prior._service(None)
            with (output / "raw_search.jsonl").open("x") as raw:
                for profile in PROFILES:
                    service.scientific_evidence_enabled = profile == PROFILES[2]
                    for query in queries:
                        req = request_for(query, profile)
                        response = service.search(req)
                        raw.write(json.dumps({"profile_id": profile, "query_id": query["query_id"],
                                              "request": req.model_dump(mode="json"), "response": response.model_dump(mode="json")}, ensure_ascii=False) + "\n")
                        raw.flush()
                        hits = [h.model_dump(mode="json") for h in response.hits]
                        if profile in PROFILES[:2]:
                            old_profile = "BM25" if profile == PROFILES[0] else "KG_BM25"
                            verify_baseline(hits, previous[old_profile, query["query_id"]]["retrieved"], query["query_id"], profile)
                        row = {**prior._evaluate_hit_list(query, gold[query["query_id"]], hits), "profile_id": profile}
                        rows.append(row)
                        if profile == PROFILES[2]:
                            diagnostics.append({"query_id": query["query_id"], "diagnostic": response.scientific_evidence})
                    if profile == PROFILES[1]:
                        write(output / "baseline_equivalence.json", {"A": "57/57", "B": "57/57", "exact_hit_objects": True})
            smoke = product_smoke(service)
        write(output / "per_query_results.json", rows)
        write(output / "graph_paths.json", diagnostics)
        write(output / "product_smoke.json", smoke)
        checks = [{"query_id": d["query_id"], "checks": evidence_checks(d["diagnostic"])} for d in diagnostics]
        write(output / "evidence_checks.json", checks)
        indexed = {(r["profile_id"], r["query_id"]): r for r in rows}
        paired = []
        for q in queries:
            a, b, c = [indexed[p, q["query_id"]] for p in PROFILES]
            paired.append({"query_id": q["query_id"], "track": q["track"],
                           "supported_operator_scope": manifest["scope_partition"][q["query_id"]]["supported_operator_scope"],
                           "A": a["first_gold_rank"], "B": b["first_gold_rank"], "C": c["first_gold_rank"],
                           "C_vs_A": classify(a, c), "C_vs_B": classify(b, c),
                           "C_hits_equal_A": c["retrieved"] == a["retrieved"]})
        panels = {"scientific_all45": {q["query_id"] for q in queries if q["track"] == frozen.TRACKS[0]},
                  "supported_operator_scope": {k for k, v in manifest["scope_partition"].items() if v["supported_operator_scope"]},
                  "tool_discovery12": {q["query_id"] for q in queries if q["track"] == frozen.TRACKS[1]}}
        panels["unsupported_scientific_scope"] = panels["scientific_all45"] - panels["supported_operator_scope"]
        grouped = {panel: {p: metrics([r for r in rows if r["profile_id"] == p and r["query_id"] in ids]) for p in PROFILES} for panel, ids in panels.items()}
        counts = Counter(r["C_vs_A"] for r in paired)
        benefit = "MIXED" if counts["HELPED"] and counts["HURT"] else "IMPROVED" if counts["HELPED"] else "REGRESSED" if counts["HURT"] else "NONE"
        report = {"status": "COMPLETE", "integration": "PASS", "benefit": benefit, "metrics": grouped,
                  "paired": paired, "tests": manifest["tests"], "baseline_equivalence": {"A": "57/57", "B": "57/57"},
                  "participation": {"query_count": len(diagnostics),
                       "resolved_operator": sum(bool(d["diagnostic"].get("resolved_operator_revision")) for d in diagnostics),
                       "mapped_graph_evidence": sum(bool(d["diagnostic"].get("mapped_chunk_ids")) for d in diagnostics),
                       "passed_public_filter": sum(bool(d["diagnostic"].get("eligible_chunk_ids")) for d in diagnostics),
                       "graph_evidence_in_final_topk": sum(bool(d["diagnostic"].get("final_graph_chunk_ids")) for d in diagnostics),
                       "fallback_reasons": dict(Counter(d["diagnostic"].get("fallback_reason") or "no_fallback" for d in diagnostics)),
                       "C_vs_A": dict(counts), "C_vs_B": dict(Counter(r["C_vs_B"] for r in paired))},
                  "scientific_graph": manifest["scientific_graph"], "frozen_artifacts_changed": False,
                  "production_changed": True, "production_default_changed": False, "external_llm_calls": 0,
                  "semantic_validation": "registered source-bound support and conditions only; no independent expert certification of all returned content"}
        # Caller-facing verdicts never treat no improvement as integration failure.
        frozen.verify_hashes(manifest["protected_sha256"])
        for p, h in manifest["source_sha256"].items():
            if sha(ROOT / p) != h:
                raise RuntimeError(f"sut_changed_during_run:{p}")
        write(output / "integrity_after.json", {"protected_files_verified": len(manifest["protected_sha256"]),
                                               "all_match": True, "source_sha256": manifest["source_sha256"]})
        write(output / "report.json", report)
        with report_path.open("x") as handle:
            handle.write(render(report, rows))
        write(output / "run_completed.json", {"status": "COMPLETE", "run_count": 1, "timestamp": datetime.now(timezone.utc).isoformat()})
        write(output / "artifact_manifest.json", {"files": {p.name: sha(p) for p in output.iterdir() if p.is_file()}, "human_report_sha256": sha(report_path)})
        return report
    except Exception as exc:
        write(output / "run_failed.json", {"status": "INVALID", "first_failure": str(exc), "run_count": 1,
                                          "partial_result_count": len(rows), "rerun_authorized": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-report", type=Path, required=True)
    args = parser.parse_args()
    result = run(test_report=args.test_report)
    print(json.dumps({k: result[k] for k in ("status", "integration", "benefit", "metrics", "participation")}, ensure_ascii=False, indent=2))
