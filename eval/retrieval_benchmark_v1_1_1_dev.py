from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from core.canonical_task_ontology import canonical_task_for_text
from core.knowledge_intelligence_models import HybridRetrievalRequest
from engine.hybrid_retrieval import (
    HybridRetrievalService,
    LocalBgeM3Encoder,
    _diversify_ranked_by_tool,
    _infer_claim_types,
    _rrf,
    _tool_key,
)
from eval import retrieval_benchmark_v1_1_dev as v11


PROJECT_ROOT = v11.PROJECT_ROOT
OUTPUT_DIR = PROJECT_ROOT / "eval_v2" / "retrieval_benchmark_v1_1_1_dev"
REPORT_PATH = PROJECT_ROOT / "docs" / "status" / "RETRIEVAL_BENCHMARK_V1_1_1_DEV_REPORT.md"
RUNNER_PATH = Path(__file__).resolve()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rank(rows: Sequence[Sequence[Any]], accepted: set[str]) -> int | None:
    return next((index for index, row in enumerate(rows, 1) if row[0] in accepted), None)


def _post_diversification(
    ranked: Sequence[tuple[str, float, int | None, int | None]],
    *,
    service: HybridRetrievalService,
    explicit_tools: Sequence[str],
) -> list[tuple[str, float, int | None, int | None]]:
    if explicit_tools:
        return list(ranked)
    return _diversify_ranked_by_tool(ranked, chunks_by_id=service._chunks_by_id, top_k=v11.TOP_K)


def _stage_diagnostics(
    service: HybridRetrievalService,
    query: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, Any]:
    request = HybridRetrievalRequest(
        query=query["query"],
        top_k=v11.TOP_K,
        include_catalog=query["track"] == "R2_tool_method_discovery",
    )
    inferred_tools = service._named_tools_in_query(query["query"])
    effective = request.model_copy(update={"tool_names": inferred_tools}) if inferred_tools else request
    inferred_task = canonical_task_for_text(query["query"])
    task_ids = {inferred_task.task_id} if inferred_task else set()
    claim_types = _infer_claim_types(query["query"])
    accepted = v11._accepted_ids(gold)

    bm25_raw = service._bm25_search(query["query"], limit=120)
    dense_raw, dense_status = service._dense_search(query["query"], limit=120, nonblocking=False)
    common_tools = {_tool_key(value) for value in effective.tool_names}
    bm25_common = service._filter_ranked(bm25_raw, request=effective, task_ids=task_ids, candidate_tools=common_tools)
    dense_common = service._filter_ranked(dense_raw, request=effective, task_ids=task_ids, candidate_tools=common_tools)
    r0_pre = _rrf(bm25_common, [])
    r1_pre = _rrf([], dense_common)
    r2_pre = _rrf(bm25_common, dense_common)

    kg_tools, warning = service._kg_candidates(task_ids=sorted(task_ids), explicit_tools=effective.tool_names)
    bm25_kg = service._filter_ranked(bm25_raw, request=effective, task_ids=task_ids, candidate_tools=kg_tools)
    dense_kg = service._filter_ranked(dense_raw, request=effective, task_ids=task_ids, candidate_tools=kg_tools)
    r3_pre = _rrf(bm25_kg, dense_kg)
    r4_pre = service._governance_rerank(
        r3_pre,
        request=effective,
        task_ids=task_ids,
        claim_types=claim_types,
        candidate_tools=kg_tools,
    )
    profile_rows = {
        "R0_bm25_only": (r0_pre, _post_diversification(r0_pre, service=service, explicit_tools=effective.tool_names)),
        "R1_dense_only": (r1_pre, _post_diversification(r1_pre, service=service, explicit_tools=effective.tool_names)),
        "R2_bm25_dense_rrf": (r2_pre, _post_diversification(r2_pre, service=service, explicit_tools=effective.tool_names)),
        "R3_kg_bm25_dense_rrf": (r3_pre, _post_diversification(r3_pre, service=service, explicit_tools=effective.tool_names)),
        "R4_kg_bm25_dense_rrf_governance": (r4_pre, _post_diversification(r4_pre, service=service, explicit_tools=effective.tool_names)),
    }
    return {
        "query_id": query["query_id"],
        "dense_status": dense_status,
        "inferred_tools": inferred_tools,
        "inferred_task": inferred_task.task_id if inferred_task else None,
        "inferred_claim_types": sorted(claim_types),
        "kg_candidate_tools": sorted(kg_tools),
        "kg_warning": warning,
        "stages": {
            "corpus_ids": sorted(chunk_id for chunk_id in accepted if chunk_id in service._chunks_by_id),
            "bm25_raw_rank": _rank(bm25_raw, accepted),
            "dense_raw_rank": _rank(dense_raw, accepted),
            "bm25_common_rank": _rank(bm25_common, accepted),
            "dense_common_rank": _rank(dense_common, accepted),
            "bm25_kg_rank": _rank(bm25_kg, accepted),
            "dense_kg_rank": _rank(dense_kg, accepted),
            "profiles": {
                profile_id: {
                    "pre_diversification_rank": _rank(pre, accepted),
                    "final_rank": _rank(final[: v11.TOP_K], accepted),
                }
                for profile_id, (pre, final) in profile_rows.items()
            },
        },
    }


def _baseline_first_cause(
    profile_id: str,
    diagnostic: dict[str, Any],
) -> str:
    stages = diagnostic["stages"]
    profile = stages["profiles"][profile_id]
    if profile_id == "R0_bm25_only":
        if stages["bm25_raw_rank"] is None:
            return "INITIAL_RETRIEVAL_MISS"
        if stages["bm25_common_rank"] is None:
            return "ENTITY_ASSOCIATION_OR_FILTER_MISMATCH"
        if profile["pre_diversification_rank"] is not None and profile["pre_diversification_rank"] <= v11.TOP_K and profile["final_rank"] is None:
            return "DIVERSIFICATION_RANKED_OUT"
        return "BM25_RANKING"
    if profile_id == "R1_dense_only":
        if stages["dense_raw_rank"] is None:
            return "INITIAL_RETRIEVAL_MISS"
        if stages["dense_common_rank"] is None:
            return "ENTITY_ASSOCIATION_OR_FILTER_MISMATCH"
        if profile["pre_diversification_rank"] is not None and profile["pre_diversification_rank"] <= v11.TOP_K and profile["final_rank"] is None:
            return "DIVERSIFICATION_RANKED_OUT"
        return "DENSE_RANKING"
    if stages["bm25_raw_rank"] is None and stages["dense_raw_rank"] is None:
        return "INITIAL_RETRIEVAL_MISS"
    if stages["bm25_common_rank"] is None and stages["dense_common_rank"] is None:
        return "ENTITY_ASSOCIATION_OR_FILTER_MISMATCH"
    if profile["pre_diversification_rank"] is not None and profile["pre_diversification_rank"] <= v11.TOP_K and profile["final_rank"] is None:
        return "DIVERSIFICATION_RANKED_OUT"
    return "RRF_RANKED_OUT"


def first_failure_cause(
    *,
    gold: dict[str, Any],
    profile_id: str,
    results: dict[str, dict[str, Any]],
    diagnostic: dict[str, Any],
) -> str | None:
    current = results[profile_id]
    if current["recall_at_10"]:
        return None
    if not diagnostic["stages"]["corpus_ids"]:
        return "GOLD_SOURCE_NOT_INDEXED"
    expected_tools = {_tool_key(value) for value in gold["expected_tools"]}
    inferred_tools = {_tool_key(value) for value in diagnostic["inferred_tools"]}
    if inferred_tools and expected_tools and not expected_tools.intersection(inferred_tools):
        return "TOOL_NORMALIZATION"
    if profile_id in {"R0_bm25_only", "R1_dense_only", "R2_bm25_dense_rrf"}:
        return _baseline_first_cause(profile_id, diagnostic)
    if profile_id == "R3_kg_bm25_dense_rrf":
        if results["R2_bm25_dense_rrf"]["recall_at_10"]:
            return "KG_FALSE_FILTER"
        return _baseline_first_cause("R2_bm25_dense_rrf", diagnostic)
    if profile_id == "R4_kg_bm25_dense_rrf_governance":
        if results["R3_kg_bm25_dense_rrf"]["recall_at_10"]:
            return "GOVERNANCE_RERANK"
        if results["R2_bm25_dense_rrf"]["recall_at_10"]:
            return "KG_FALSE_FILTER"
        return _baseline_first_cause("R2_bm25_dense_rrf", diagnostic)
    raise ValueError(f"unknown profile: {profile_id}")


def _config() -> dict[str, Any]:
    config = v11._config()
    config.update({
        "schema_version": "sckg-retrieval-benchmark-v1.1.1-dev-config-v1",
        "campaign": "development_harness_repair_not_formal_midterm",
        "invalid_predecessor": {
            "path": "eval_v2/retrieval_benchmark_v1_1_dev",
            "report_sha256": _sha_file(v11.OUTPUT_DIR / "report.json"),
            "status": "INVALID_due_to_first_cause_attribution_defect",
        },
        "first_cause_policy": "a stage may own a failure only when that profile executed the stage; R3 inherits an earlier R2 failure unless KG removes an R2 top-10 hit; R4 inherits an earlier R3 failure unless governance removes an R3 top-10 hit",
        "retrieval_tuning_after_invalid_run": False,
    })
    return config


def prepare(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite v1.1.1 output: {output_dir}")
    if _sha_file(v11.V1_DIR / "queries.jsonl") != v11.EXPECTED_QUERY_SHA:
        raise RuntimeError("frozen query set drift")
    if _sha_file(v11.V1_DIR / "gold.jsonl") != v11.EXPECTED_GOLD_SHA:
        raise RuntimeError("frozen gold drift")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "queries.jsonl").write_bytes((v11.V1_DIR / "queries.jsonl").read_bytes())
    (output_dir / "gold.jsonl").write_bytes((v11.V1_DIR / "gold.jsonl").read_bytes())
    v11._write_json(output_dir / "retrieval_config.json", _config())
    v11._write_json(output_dir / "cohorts.json", v11._cohorts())
    source_paths = [
        v11.V1_DIR / "queries.jsonl", v11.V1_DIR / "gold.jsonl",
        v11.STRENGTHENING_DIR / "report.json", v11.STRENGTHENING_DIR / "source_index_gap_register.jsonl",
        v11.INDEX_DIR / "evidence_chunks.jsonl", v11.INDEX_DIR / "scrna_tools_catalog_chunks.jsonl",
        v11.INDEX_DIR / "evidence_fts5.sqlite", v11.INDEX_DIR / "evidence_index_manifest.json",
        v11.INDEX_DIR / "evidence_vector_metadata.json", v11.INDEX_DIR / "evidence_vectors.npy",
        PROJECT_ROOT / "engine" / "hybrid_retrieval.py", v11.KG_MANIFEST_PATH,
        v11.OUTPUT_DIR / "report.json", RUNNER_PATH,
    ]
    manifest = {
        "schema_version": "sckg-retrieval-benchmark-v1.1.1-dev-prerun-v1",
        "state": "prepared_not_run", "created_at": datetime.now(timezone.utc).isoformat(),
        "query_set_sha256": _sha_file(output_dir / "queries.jsonl"),
        "gold_sha256": _sha_file(output_dir / "gold.jsonl"),
        "retrieval_config_sha256": _sha_file(output_dir / "retrieval_config.json"),
        "cohorts_sha256": _sha_file(output_dir / "cohorts.json"),
        "runner_sha256": _sha_file(RUNNER_PATH),
        "source_artifact_sha256": {str(path.relative_to(PROJECT_ROOT)): _sha_file(path) for path in source_paths},
        "snapshot_identity": v11._snapshot_identity(), "kg_snapshot_identity": v11._kg_identity(),
    }
    v11._write_json(output_dir / "pre_run_manifest.json", manifest)
    return manifest


def _validate_prepared(output_dir: Path) -> dict[str, Any]:
    manifest = json.loads((output_dir / "pre_run_manifest.json").read_text(encoding="utf-8"))
    for field, path in {
        "query_set_sha256": output_dir / "queries.jsonl",
        "gold_sha256": output_dir / "gold.jsonl",
        "retrieval_config_sha256": output_dir / "retrieval_config.json",
        "cohorts_sha256": output_dir / "cohorts.json",
        "runner_sha256": RUNNER_PATH,
    }.items():
        if manifest[field] != _sha_file(path):
            raise RuntimeError(f"v1.1.1 pre-run drift: {field}")
    if manifest["query_set_sha256"] != v11.EXPECTED_QUERY_SHA or manifest["gold_sha256"] != v11.EXPECTED_GOLD_SHA:
        raise RuntimeError("v1.1.1 query/gold mismatch")
    for rel, digest in manifest["source_artifact_sha256"].items():
        if _sha_file(PROJECT_ROOT / rel) != digest:
            raise RuntimeError(f"source artifact drift: {rel}")
    if manifest["snapshot_identity"] != v11._snapshot_identity() or manifest["kg_snapshot_identity"] != v11._kg_identity():
        raise RuntimeError("retrieval or KG identity drift")
    return manifest


def _ranking_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "query_id", "track", "task_family", "query_type", "recall_at_5",
            "recall_at_10", "reciprocal_rank", "ndcg_at_10", "first_gold_rank",
            "authoritative_source_hit", "correct_version_hit", "correct_scope_hit",
            "irrelevant_context_rate", "retrieved", "profile_id", "dense_status",
            "pipeline", "warnings",
        )
    }


def run(output_dir: Path = OUTPUT_DIR, report_path: Path = REPORT_PATH) -> dict[str, Any]:
    if (output_dir / "run_started.json").exists() or (output_dir / "report.json").exists():
        raise FileExistsError("v1.1.1 development run is write-once")
    pre = _validate_prepared(output_dir)
    queries = v11._json_rows(output_dir / "queries.jsonl")
    gold_rows = v11._json_rows(output_dir / "gold.jsonl")
    gold_by_id = {row["query_id"]: row for row in gold_rows}
    cohorts = json.loads((output_dir / "cohorts.json").read_text(encoding="utf-8"))
    v11._write_json(output_dir / "run_started.json", {
        "schema_version": "sckg-retrieval-benchmark-v1.1.1-dev-marker-v1",
        "started_at": datetime.now(timezone.utc).isoformat(), "run_count": 1,
        "pre_run_manifest_sha256": _sha_file(output_dir / "pre_run_manifest.json"),
    })
    encoder = LocalBgeM3Encoder()
    if encoder.model_revision != v11.EXPECTED_MODEL_REVISION:
        raise RuntimeError("dense encoder revision drift")
    service = v11._service(encoder)
    diagnostics = {row["query_id"]: _stage_diagnostics(service, row, gold_by_id[row["query_id"]]) for row in queries}
    all_results: list[dict[str, Any]] = []
    by_profile: dict[str, dict[str, dict[str, Any]]] = {}
    for profile in v11.PROFILES:
        by_profile[profile.profile_id] = {}
        for query in queries:
            response = service.search(v11._request(query, profile))
            result = v11._evaluate_hit_list(query, gold_by_id[query["query_id"]], [hit.model_dump(mode="json") for hit in response.hits])
            result.update({"profile_id": profile.profile_id, "dense_status": response.dense_status, "pipeline": response.pipeline, "warnings": response.warnings})
            all_results.append(result)
            by_profile[profile.profile_id][query["query_id"]] = result

    invalid_results = v11._json_rows(v11.OUTPUT_DIR / "per_query_results.jsonl")
    old_projection = [_ranking_projection(row) for row in invalid_results]
    new_projection = [_ranking_projection(row) for row in all_results]
    if old_projection != new_projection:
        raise RuntimeError("retrieval ranking changed between invalid v1.1 and harness-only v1.1.1")

    failures: list[dict[str, Any]] = []
    kg_rows: list[dict[str, Any]] = []
    governance_rows: list[dict[str, Any]] = []
    for query in queries:
        qid = query["query_id"]
        results = {profile.profile_id: by_profile[profile.profile_id][qid] for profile in v11.PROFILES}
        r2, r3, r4 = (results[key] for key in ("R2_bm25_dense_rrf", "R3_kg_bm25_dense_rrf", "R4_kg_bm25_dense_rrf_governance"))
        kg_rows.append({"query_id": qid, "classification": v11._paired(r2, r3), "diagnostic": diagnostics[qid]})
        governance_rows.append({"query_id": qid, "classification": v11._paired(r3, r4), "r3_first_gold_rank": r3["first_gold_rank"], "r4_first_gold_rank": r4["first_gold_rank"]})
        for profile in v11.PROFILES:
            cause = first_failure_cause(gold=gold_by_id[qid], profile_id=profile.profile_id, results=results, diagnostic=diagnostics[qid])
            if cause:
                failures.append({"query_id": qid, "track": query["track"], "profile_id": profile.profile_id, "first_cause": cause, "stage_ranks": diagnostics[qid]["stages"]})

    prohibited = {
        "R0_bm25_only": {"DENSE_RANKING", "KG_FALSE_FILTER", "GOVERNANCE_RERANK"},
        "R1_dense_only": {"BM25_RANKING", "KG_FALSE_FILTER", "GOVERNANCE_RERANK"},
        "R2_bm25_dense_rrf": {"KG_FALSE_FILTER", "GOVERNANCE_RERANK"},
        "R3_kg_bm25_dense_rrf": {"GOVERNANCE_RERANK"},
        "R4_kg_bm25_dense_rrf_governance": set(),
    }
    violations = [row for row in failures if row["first_cause"] in prohibited[row["profile_id"]]]
    if violations:
        raise RuntimeError(f"profile-stage attribution invariant violated: {violations[:1]}")

    aggregates: dict[str, Any] = {}
    stratified: dict[str, Any] = {}
    for profile in v11.PROFILES:
        rows = [row for row in all_results if row["profile_id"] == profile.profile_id]
        aggregates[profile.profile_id] = {track: v11._aggregate([row for row in rows if row["track"] == track]) for track in ("R1_scientific_evidence", "R2_tool_method_discovery")}
        stratified[profile.profile_id] = {
            dimension: {value: v11._aggregate([row for row in rows if row[dimension] == value]) for value in sorted({row[dimension] for row in rows})}
            for dimension in ("task_family", "query_type")
        }
    v1_aggregates = json.loads((v11.V1_DIR / "aggregate_metrics.json").read_text(encoding="utf-8"))
    comparison = {profile.profile_id: {track: v11._metric_delta(v1_aggregates[profile.profile_id][track], aggregates[profile.profile_id][track]) for track in ("R1_scientific_evidence", "R2_tool_method_discovery")} for profile in v11.PROFILES}
    cohort_results = {
        name: {"query_count": len(ids), "profiles": {profile.profile_id: v11._aggregate([by_profile[profile.profile_id][qid] for qid in ids]) for profile in v11.PROFILES}}
        for name, ids in cohorts.items()
    }
    original_hurt = set(cohorts["original_governance_hurt"])
    cohort_results["original_governance_hurt"]["v1_1_1_governance_classification"] = dict(Counter(row["classification"] for row in governance_rows if row["query_id"] in original_hurt))
    kg_counts = Counter(row["classification"] for row in kg_rows)
    governance_counts = Counter(row["classification"] for row in governance_rows)
    failure_counts = dict(sorted(Counter(row["first_cause"] for row in failures).items()))
    v11._write_jsonl(output_dir / "per_query_results.jsonl", all_results)
    v11._write_json(output_dir / "aggregate_metrics.json", aggregates)
    v11._write_json(output_dir / "stratified_metrics.json", stratified)
    v11._write_jsonl(output_dir / "kg_diagnostics.jsonl", kg_rows)
    v11._write_jsonl(output_dir / "governance_diagnostics.jsonl", governance_rows)
    v11._write_jsonl(output_dir / "failure_register.jsonl", failures)
    v11._write_json(output_dir / "v1_to_v1_1_1_comparison.json", comparison)
    v11._write_json(output_dir / "cohort_analysis.json", cohort_results)
    report = {
        "schema_version": "sckg-retrieval-benchmark-v1.1.1-dev-report-v1",
        "status": "COMPLETE",
        "interpretation_boundary": "COMPLETE means faithful development execution, not superiority or formal holdout qualification",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "query_set_sha256": pre["query_set_sha256"], "gold_sha256": pre["gold_sha256"],
        "retrieval_config_sha256": pre["retrieval_config_sha256"], "runner_sha256": pre["runner_sha256"],
        "snapshot_identity": pre["snapshot_identity"], "kg_snapshot_identity": pre["kg_snapshot_identity"],
        "query_counts": {"R1_scientific_evidence": 45, "R2_tool_method_discovery": 12},
        "aggregate_metrics": aggregates, "v1_to_v1_1_1": comparison, "cohort_analysis": cohort_results,
        "kg_analysis": dict(kg_counts), "kg_false_filter_rate": round(kg_counts.get("HURT", 0) / len(queries), 6),
        "governance_analysis": dict(governance_counts), "failure_counts": failure_counts,
        "profile_stage_attribution_violations": 0,
        "ranking_equivalent_to_invalid_v1_1": True,
        "invalid_v1_1_used_to_tune_retrieval": False,
        "boundaries": {"corpus_changed": False, "dense_index_changed": False, "kg_changed": False, "governance_changed": False, "queries_changed": False, "gold_changed": False, "formal_holdout_run": False, "seed_v1_started": False},
    }
    v11._write_json(output_dir / "report.json", report)
    v11._write_json(output_dir / "run_completed.json", {"schema_version": "sckg-retrieval-benchmark-v1.1.1-dev-marker-v1", "completed_at": report["completed_at"], "run_count": 1, "report_sha256": _sha_file(output_dir / "report.json")})
    _write_report(report_path, report)
    v11._write_json(output_dir / "manifest.json", {"schema_version": "sckg-retrieval-benchmark-v1.1.1-dev-artifact-manifest-v1", "artifacts": {path.name: _sha_file(path) for path in sorted(output_dir.iterdir()) if path.is_file()}})
    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Retrieval Benchmark v1.1.1 — Development Campaign", "",
        "Status: **COMPLETE**. The evaluation-only attribution repair was frozen before this single run. This is not a formal holdout.", "",
        f"- Query SHA: `{report['query_set_sha256']}`", f"- Gold SHA: `{report['gold_sha256']}`",
        f"- Runner SHA: `{report['runner_sha256']}`", f"- Snapshot: `{report['snapshot_identity']['build_id']}`", "",
        "## Primary results", "",
        "| Profile | Track | Recall@5 | Recall@10 | MRR | nDCG@10 | Authoritative hit | Irrelevant context |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for profile, tracks in report["aggregate_metrics"].items():
        for track, metric in tracks.items():
            lines.append(f"| {profile} | {track} | {v11._fmt_rate(metric['recall_at_5'])} | {v11._fmt_rate(metric['recall_at_10'])} | {metric['mrr']:.3f} | {metric['ndcg_at_10']:.3f} | {v11._fmt_rate(metric['authoritative_source_hit_rate'])} | {metric['irrelevant_context_rate']:.3f} |")
    lines.extend([
        "", "## Cohorts and causal diagnostics", "",
        f"- Repaired cohort: {report['cohort_analysis']['repaired']['query_count']} queries",
        f"- Still-blocked cohort: {report['cohort_analysis']['still_blocked']['query_count']} queries",
        f"- Unaffected R1 cohort: {report['cohort_analysis']['unaffected_r1']['query_count']} queries",
        f"- KG R2→R3: `{report['kg_analysis']}`; false-filter rate `{report['kg_false_filter_rate']}`",
        f"- Governance R3→R4: `{report['governance_analysis']}`",
        f"- Valid first-cause register: `{report['failure_counts']}`",
        f"- Profile/stage attribution violations: {report['profile_stage_attribution_violations']}", "",
        "The top-k outputs are byte/semantic-equivalent to the preserved invalid v1.1 campaign. Only evaluation attribution changed; invalid v1.1 observations were not used to tune retrieval behavior.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval Benchmark v1.1.1 development campaign")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    result = prepare(args.output) if args.prepare else run(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
