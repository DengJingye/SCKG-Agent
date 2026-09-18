from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
from eval.retrieval_benchmark_v1_dev import PROFILES, TOP_K, Profile


OUTPUT_DIR = PROJECT_ROOT / "eval_v2" / "retrieval_benchmark_v1_1_dev"
REPORT_PATH = PROJECT_ROOT / "docs" / "status" / "RETRIEVAL_BENCHMARK_V1_1_DEV_REPORT.md"
V1_DIR = PROJECT_ROOT / "eval_v2" / "retrieval_benchmark_v1_dev"
STRENGTHENING_DIR = PROJECT_ROOT / "data" / "evaluation" / "retrieval_foundation_strengthening_v1"
INDEX_DIR = PROJECT_ROOT / "data" / "indexes" / "retrieval_foundation_v1"
KG_MANIFEST_PATH = PROJECT_ROOT / "data" / "knowledge_graph_v2" / "manifest.json"

EXPECTED_QUERY_SHA = "224384015f0df2155c55478b432941c8fb899157352b1e27d29af22aff6e3773"
EXPECTED_GOLD_SHA = "d84aff99acc9d7a4d5f0d55fb9c5c052a8eb31a9fd8d8e24797cbc3b9b14fbaa"
EXPECTED_MODEL = "BAAI/bge-m3"
EXPECTED_MODEL_REVISION = "cb1779f90b988b8deb01f9155c790ef9417d7648"
EXPECTED_CORPUS_DIGEST = "8d8990ec75f25c598f467b0da0ca2ad81ce9f0931efadff7f70acec4b7a47436"
EXPECTED_VECTOR_COUNT = 790
EXPECTED_DIMENSION = 1024
EXPECTED_BUILD_ID = "retrieval-foundation-v1-ff5b4829bc5943f4"

FAILURE_CLASSES = {
    "GOLD_SOURCE_NOT_INDEXED",
    "RRF_RANKED_OUT",
    "DIVERSIFICATION_RANKED_OUT",
    "ENTITY_ASSOCIATION_OR_FILTER_MISMATCH",
    "INITIAL_RETRIEVAL_MISS",
    "BM25_RANKING",
    "DENSE_RANKING",
    "TOOL_NORMALIZATION",
    "GOVERNANCE_RERANK",
    "VERSION_SCOPE",
    "KG_FALSE_FILTER",
    "OTHER",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()


def _kg_identity() -> dict[str, Any]:
    manifest = json.loads(KG_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "path": str(KG_MANIFEST_PATH.relative_to(PROJECT_ROOT)),
        "sha256": _sha_file(KG_MANIFEST_PATH),
        "build_id": manifest.get("build_id", manifest.get("graph_version", "")),
    }


def _dense_identity() -> dict[str, Any]:
    metadata_path = INDEX_DIR / "evidence_vector_metadata.json"
    matrix_path = INDEX_DIR / "evidence_vectors.npy"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    identity = {
        "model": metadata.get("model"),
        "model_revision": metadata.get("model_revision"),
        "source_digest": metadata.get("source_digest"),
        "vector_count": len(metadata.get("chunk_ids", [])),
        "dimension": EXPECTED_DIMENSION,
        "build_id": metadata.get("build_id"),
        "metadata_sha256": _sha_file(metadata_path),
        "matrix_sha256": _sha_file(matrix_path),
    }
    actual = (
        identity["model"], identity["model_revision"], identity["source_digest"],
        identity["vector_count"], identity["dimension"], identity["build_id"],
    )
    expected = (
        EXPECTED_MODEL, EXPECTED_MODEL_REVISION, EXPECTED_CORPUS_DIGEST,
        EXPECTED_VECTOR_COUNT, EXPECTED_DIMENSION, EXPECTED_BUILD_ID,
    )
    if actual != expected:
        raise RuntimeError(f"strengthened dense foundation drift: expected={expected!r}; actual={actual!r}")
    return identity


def _snapshot_identity() -> dict[str, Any]:
    manifest_path = INDEX_DIR / "evidence_index_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("build_id") != EXPECTED_BUILD_ID:
        raise RuntimeError("strengthened retrieval build identity drift")
    return {
        "build_id": manifest["build_id"],
        "corpus_digest": EXPECTED_CORPUS_DIGEST,
        "index_manifest_sha256": _sha_file(manifest_path),
        "evidence_chunks_sha256": _sha_file(INDEX_DIR / "evidence_chunks.jsonl"),
        "catalog_chunks_sha256": _sha_file(INDEX_DIR / "scrna_tools_catalog_chunks.jsonl"),
        "fts_sha256": _sha_file(INDEX_DIR / "evidence_fts5.sqlite"),
        "dense": _dense_identity(),
    }


def _cohorts() -> dict[str, list[str]]:
    gap_rows = _json_rows(STRENGTHENING_DIR / "source_index_gap_register.jsonl")
    affected = {query_id for row in gap_rows for query_id in row["affected_query_ids"]}
    repaired = {
        query_id
        for row in gap_rows
        if row["repair_status"] == "eligible_for_retrieval_only_indexing"
        for query_id in row["affected_query_ids"]
    }
    blocked = {
        query_id
        for row in gap_rows
        if row["repair_status"] == "untouched_gap"
        for query_id in row["affected_query_ids"]
    }
    queries = _json_rows(V1_DIR / "queries.jsonl")
    unaffected_r1 = {
        row["query_id"] for row in queries
        if row["track"] == "R1_scientific_evidence" and row["query_id"] not in affected
    }
    v1_governance = _json_rows(V1_DIR / "governance_diagnostics.jsonl")
    hurt = {row["query_id"] for row in v1_governance if row["classification"] == "HURT"}
    return {
        "previous_gold_source_not_indexed": sorted(affected),
        "repaired": sorted(repaired),
        "still_blocked": sorted(blocked),
        "unaffected_r1": sorted(unaffected_r1),
        "original_governance_hurt": sorted(hurt),
    }


def _config() -> dict[str, Any]:
    return {
        "schema_version": "sckg-retrieval-benchmark-v1.1-dev-config-v1",
        "campaign": "development_not_formal_midterm",
        "parent_campaign": "Retrieval Benchmark v1 DEV",
        "query_gold_policy": "byte-identical copies of frozen v1 queries and gold",
        "gold_resolution_policy": "gold_evidence_span_ids OR indexed_chunk_aliases; identity is accepted only when present in the frozen strengthened index",
        "top_k": TOP_K,
        "profiles": [asdict(profile) for profile in PROFILES],
        "eligibility_boundary": "identical to v1; R1 excludes catalog and R2 permits catalog discovery",
        "metric_policy": "same v1 query-level metrics; raw numerators and denominators added without changing metric semantics",
        "primary_sampling_unit": "retrieval_query_scientific_information_need",
        "strengthened_foundation": _snapshot_identity(),
        "governance_sut": {
            "path": "engine/hybrid_retrieval.py",
            "sha256": _sha_file(PROJECT_ROOT / "engine" / "hybrid_retrieval.py"),
        },
        "kg_snapshot_identity": _kg_identity(),
    }


def prepare(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite v1.1 output: {output_dir}")
    if _sha_file(V1_DIR / "queries.jsonl") != EXPECTED_QUERY_SHA:
        raise RuntimeError("frozen v1 query set drift")
    if _sha_file(V1_DIR / "gold.jsonl") != EXPECTED_GOLD_SHA:
        raise RuntimeError("frozen v1 gold drift")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "queries.jsonl").write_bytes((V1_DIR / "queries.jsonl").read_bytes())
    (output_dir / "gold.jsonl").write_bytes((V1_DIR / "gold.jsonl").read_bytes())
    _write_json(output_dir / "retrieval_config.json", _config())
    _write_json(output_dir / "cohorts.json", _cohorts())
    source_paths = [
        V1_DIR / "queries.jsonl", V1_DIR / "gold.jsonl", V1_DIR / "report.json",
        STRENGTHENING_DIR / "report.json", STRENGTHENING_DIR / "source_index_gap_register.jsonl",
        INDEX_DIR / "evidence_chunks.jsonl", INDEX_DIR / "scrna_tools_catalog_chunks.jsonl",
        INDEX_DIR / "evidence_fts5.sqlite", INDEX_DIR / "evidence_index_manifest.json",
        INDEX_DIR / "evidence_vector_metadata.json", INDEX_DIR / "evidence_vectors.npy",
        PROJECT_ROOT / "engine" / "hybrid_retrieval.py", KG_MANIFEST_PATH,
    ]
    manifest = {
        "schema_version": "sckg-retrieval-benchmark-v1.1-dev-prerun-v1",
        "state": "prepared_not_run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "head": _git_head(),
        "query_set_sha256": _sha_file(output_dir / "queries.jsonl"),
        "gold_sha256": _sha_file(output_dir / "gold.jsonl"),
        "retrieval_config_sha256": _sha_file(output_dir / "retrieval_config.json"),
        "cohorts_sha256": _sha_file(output_dir / "cohorts.json"),
        "source_artifact_sha256": {str(path.relative_to(PROJECT_ROOT)): _sha_file(path) for path in source_paths},
        "snapshot_identity": _snapshot_identity(),
        "kg_snapshot_identity": _kg_identity(),
    }
    _write_json(output_dir / "pre_run_manifest.json", manifest)
    return manifest


def _validate_prepared(output_dir: Path) -> dict[str, Any]:
    manifest = json.loads((output_dir / "pre_run_manifest.json").read_text(encoding="utf-8"))
    checks = {
        "query_set_sha256": _sha_file(output_dir / "queries.jsonl"),
        "gold_sha256": _sha_file(output_dir / "gold.jsonl"),
        "retrieval_config_sha256": _sha_file(output_dir / "retrieval_config.json"),
        "cohorts_sha256": _sha_file(output_dir / "cohorts.json"),
    }
    for field, value in checks.items():
        if manifest[field] != value:
            raise RuntimeError(f"prepared v1.1 drift: {field}")
    if manifest["query_set_sha256"] != EXPECTED_QUERY_SHA or manifest["gold_sha256"] != EXPECTED_GOLD_SHA:
        raise RuntimeError("v1.1 query/gold identity does not match frozen v1")
    for rel, digest in manifest["source_artifact_sha256"].items():
        if _sha_file(PROJECT_ROOT / rel) != digest:
            raise RuntimeError(f"source artifact drift: {rel}")
    if manifest["snapshot_identity"] != _snapshot_identity():
        raise RuntimeError("strengthened snapshot identity drift")
    if manifest["kg_snapshot_identity"] != _kg_identity():
        raise RuntimeError("KG snapshot identity drift")
    return manifest


def _service(encoder: LocalBgeM3Encoder) -> HybridRetrievalService:
    return HybridRetrievalService(
        evidence_chunks_path=INDEX_DIR / "evidence_chunks.jsonl",
        catalog_chunks_path=INDEX_DIR / "scrna_tools_catalog_chunks.jsonl",
        fts_index_path=INDEX_DIR / "evidence_fts5.sqlite",
        index_manifest_path=INDEX_DIR / "evidence_index_manifest.json",
        coverage_path=INDEX_DIR / "retrieval_coverage.json",
        dense_matrix_path=INDEX_DIR / "evidence_vectors.npy",
        dense_metadata_path=INDEX_DIR / "evidence_vector_metadata.json",
        dense_encoder=encoder,
    )


def _request(query: dict[str, Any], profile: Profile) -> HybridRetrievalRequest:
    return HybridRetrievalRequest(
        query=query["query"], top_k=TOP_K,
        include_catalog=query["track"] == "R2_tool_method_discovery",
        enable_sparse=profile.sparse, enable_dense=profile.dense,
        nonblocking_dense=False, use_kg=profile.kg,
        use_governance_rerank=profile.governance, use_contract_gate=False,
    )


def _accepted_ids(gold: dict[str, Any]) -> set[str]:
    return set(gold["gold_evidence_span_ids"]) | set(gold["indexed_chunk_aliases"])


def _evaluate_hit_list(query: dict[str, Any], gold: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = _accepted_ids(gold)
    ranks = [rank for rank, hit in enumerate(hits, 1) if hit["chunk_id"] in accepted]
    first = min(ranks) if ranks else None
    ideal = min(len(accepted), 10)
    dcg = sum(1.0 / math.log2(rank + 1) for rank in ranks if rank <= 10)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal + 1)) if ideal else 0.0
    source_ids = set(gold["source_ids"])
    returned = hits[:10]
    return {
        "query_id": query["query_id"], "track": query["track"],
        "task_family": query["task_family"], "query_type": query["query_type"],
        "recall_at_5": int(bool(first and first <= 5)),
        "recall_at_10": int(bool(first and first <= 10)),
        "reciprocal_rank": 1.0 / first if first else 0.0,
        "ndcg_at_10": dcg / idcg if idcg else 0.0,
        "first_gold_rank": first,
        "authoritative_source_hit": int(any(hit["chunk_id"] in accepted or hit.get("source_id") in source_ids for hit in returned)),
        "correct_version_hit": int(bool(first and first <= 10)) if gold["expected_version"] else None,
        "correct_scope_hit": int(bool(first and first <= 10)) if gold["expected_scope"] else None,
        "irrelevant_context_rate": sum(hit["chunk_id"] not in accepted for hit in returned) / len(returned) if returned else 0.0,
        "retrieved": hits,
    }


def _mean(values: Iterable[float | int | None]) -> float | None:
    kept = [float(value) for value in values if value is not None]
    return round(sum(kept) / len(kept), 6) if kept else None


def _rate_count(rows: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [int(row[field]) for row in rows if row[field] is not None]
    return {"numerator": sum(values), "denominator": len(values), "rate": round(sum(values) / len(values), 6) if values else None}


def _aggregate(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "query_count": len(rows),
        "recall_at_5": _rate_count(rows, "recall_at_5"),
        "recall_at_10": _rate_count(rows, "recall_at_10"),
        "mrr": _mean(row["reciprocal_rank"] for row in rows),
        "ndcg_at_10": _mean(row["ndcg_at_10"] for row in rows),
        "authoritative_source_hit_rate": _rate_count(rows, "authoritative_source_hit"),
        "correct_version_hit_rate": _rate_count(rows, "correct_version_hit"),
        "correct_scope_hit_rate": _rate_count(rows, "correct_scope_hit"),
        "irrelevant_context_rate": _mean(row["irrelevant_context_rate"] for row in rows),
    }


def _rank(rows: Sequence[Sequence[Any]], accepted: set[str]) -> int | None:
    return next((index for index, row in enumerate(rows, 1) if row[0] in accepted), None)


def _stage_diagnostics(service: HybridRetrievalService, query: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    request = HybridRetrievalRequest(query=query["query"], top_k=TOP_K, include_catalog=query["track"] == "R2_tool_method_discovery")
    inferred_tools = service._named_tools_in_query(query["query"])
    effective = request.model_copy(update={"tool_names": inferred_tools}) if inferred_tools else request
    inferred_task = canonical_task_for_text(query["query"])
    task_ids = {inferred_task.task_id} if inferred_task else set()
    claim_types = _infer_claim_types(query["query"])
    bm25_raw = service._bm25_search(query["query"], limit=120)
    dense_raw, dense_status = service._dense_search(query["query"], limit=120, nonblocking=False)
    common_tools = {_tool_key(value) for value in effective.tool_names}
    bm25_common = service._filter_ranked(bm25_raw, request=effective, task_ids=task_ids, candidate_tools=common_tools)
    dense_common = service._filter_ranked(dense_raw, request=effective, task_ids=task_ids, candidate_tools=common_tools)
    fused_before = _rrf(bm25_common, dense_common)
    kg_tools, warning = service._kg_candidates(task_ids=sorted(task_ids), explicit_tools=effective.tool_names)
    bm25_kg = service._filter_ranked(bm25_raw, request=effective, task_ids=task_ids, candidate_tools=kg_tools)
    dense_kg = service._filter_ranked(dense_raw, request=effective, task_ids=task_ids, candidate_tools=kg_tools)
    fused_after = _rrf(bm25_kg, dense_kg)
    governed = service._governance_rerank(fused_after, request=effective, task_ids=task_ids, claim_types=claim_types, candidate_tools=kg_tools)
    final_governed = governed if effective.tool_names else _diversify_ranked_by_tool(governed, chunks_by_id=service._chunks_by_id, top_k=TOP_K)
    accepted = _accepted_ids(gold)
    stages = {
        "corpus_ids": sorted(chunk_id for chunk_id in accepted if chunk_id in service._chunks_by_id),
        "bm25_raw_rank": _rank(bm25_raw, accepted), "dense_raw_rank": _rank(dense_raw, accepted),
        "common_filter_rank": min((value for value in (_rank(bm25_common, accepted), _rank(dense_common, accepted)) if value is not None), default=None),
        "fusion_before_kg_rank": _rank(fused_before, accepted),
        "kg_filter_rank": min((value for value in (_rank(bm25_kg, accepted), _rank(dense_kg, accepted)) if value is not None), default=None),
        "fusion_after_kg_rank": _rank(fused_after, accepted),
        "governance_rank": _rank(governed, accepted),
        "post_diversification_rank": _rank(final_governed[:TOP_K], accepted),
    }
    return {
        "query_id": query["query_id"], "dense_status": dense_status,
        "inferred_tools": inferred_tools, "inferred_task": inferred_task.task_id if inferred_task else None,
        "inferred_claim_types": sorted(claim_types), "kg_candidate_tools": sorted(kg_tools), "kg_warning": warning,
        "gold_present_before_kg_filtering": stages["fusion_before_kg_rank"] is not None,
        "gold_survives_kg_filtering": stages["fusion_after_kg_rank"] is not None,
        "gold_rank_before_kg": stages["fusion_before_kg_rank"], "gold_rank_after_kg": stages["fusion_after_kg_rank"],
        "stages": stages,
    }


def _paired(before: dict[str, Any], after: dict[str, Any]) -> str:
    before_hit, after_hit = bool(before["recall_at_10"]), bool(after["recall_at_10"])
    before_rank, after_rank = before["first_gold_rank"] or 10**9, after["first_gold_rank"] or 10**9
    if (not before_hit and after_hit) or (before_hit == after_hit and after_rank < before_rank):
        return "HELPED"
    if (before_hit and not after_hit) or (before_hit == after_hit and after_rank > before_rank):
        return "HURT"
    return "NEUTRAL"


def _failure_cause(
    gold: dict[str, Any], profile_id: str, result: dict[str, Any], diagnostic: dict[str, Any],
    r2: dict[str, Any], r3: dict[str, Any],
) -> str | None:
    if result["recall_at_10"]:
        return None
    stages = diagnostic["stages"]
    if not stages["corpus_ids"]:
        return "GOLD_SOURCE_NOT_INDEXED"
    expected_tools = {_tool_key(value) for value in gold["expected_tools"]}
    inferred_tools = {_tool_key(value) for value in diagnostic["inferred_tools"]}
    if inferred_tools and expected_tools and not expected_tools.intersection(inferred_tools):
        return "TOOL_NORMALIZATION"
    if stages["bm25_raw_rank"] is None and stages["dense_raw_rank"] is None:
        return "INITIAL_RETRIEVAL_MISS"
    if stages["common_filter_rank"] is None:
        return "ENTITY_ASSOCIATION_OR_FILTER_MISMATCH"
    if profile_id == "R0_bm25_only":
        return "BM25_RANKING"
    if profile_id == "R1_dense_only":
        return "DENSE_RANKING"
    if profile_id == "R3_kg_bm25_dense_rrf" and r2["recall_at_10"]:
        return "KG_FALSE_FILTER"
    if profile_id == "R4_kg_bm25_dense_rrf_governance" and r3["recall_at_10"]:
        return "GOVERNANCE_RERANK"
    if stages["fusion_after_kg_rank"] is not None and stages["governance_rank"] is not None and stages["governance_rank"] > TOP_K:
        return "GOVERNANCE_RERANK"
    if stages["governance_rank"] is not None and stages["post_diversification_rank"] is None:
        return "DIVERSIFICATION_RANKED_OUT"
    if stages["fusion_before_kg_rank"] is not None and stages["fusion_before_kg_rank"] > TOP_K:
        return "RRF_RANKED_OUT"
    if gold["expected_version"] or gold["expected_scope"]:
        return "VERSION_SCOPE"
    return "RRF_RANKED_OUT" if stages["fusion_before_kg_rank"] is not None else "OTHER"


def _metric_delta(v1: dict[str, Any], v11: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in ("recall_at_5", "recall_at_10", "authoritative_source_hit_rate"):
        old = v1[field]
        new = v11[field]
        result[field] = {"v1_rate": old, "v1_1": new, "rate_delta": None if old is None or new["rate"] is None else round(new["rate"] - old, 6)}
    for field in ("mrr", "ndcg_at_10", "irrelevant_context_rate"):
        result[field] = {"v1": v1[field], "v1_1": v11[field], "delta": round(v11[field] - v1[field], 6)}
    return result


def run(output_dir: Path = OUTPUT_DIR, report_path: Path = REPORT_PATH) -> dict[str, Any]:
    if (output_dir / "run_started.json").exists() or (output_dir / "report.json").exists():
        raise FileExistsError("v1.1 development run is write-once")
    pre = _validate_prepared(output_dir)
    queries = _json_rows(output_dir / "queries.jsonl")
    gold_rows = _json_rows(output_dir / "gold.jsonl")
    gold_by_id = {row["query_id"]: row for row in gold_rows}
    cohorts = json.loads((output_dir / "cohorts.json").read_text(encoding="utf-8"))
    _write_json(output_dir / "run_started.json", {
        "schema_version": "sckg-retrieval-benchmark-v1.1-dev-marker-v1",
        "started_at": datetime.now(timezone.utc).isoformat(), "run_count": 1,
        "pre_run_manifest_sha256": _sha_file(output_dir / "pre_run_manifest.json"),
    })
    encoder = LocalBgeM3Encoder()
    if encoder.model_revision != EXPECTED_MODEL_REVISION:
        raise RuntimeError("loaded dense encoder revision differs from frozen revision")
    service = _service(encoder)
    diagnostics = {row["query_id"]: _stage_diagnostics(service, row, gold_by_id[row["query_id"]]) for row in queries}
    all_results: list[dict[str, Any]] = []
    by_profile: dict[str, dict[str, dict[str, Any]]] = {}
    for profile in PROFILES:
        by_profile[profile.profile_id] = {}
        for query in queries:
            response = service.search(_request(query, profile))
            evaluated = _evaluate_hit_list(query, gold_by_id[query["query_id"]], [hit.model_dump(mode="json") for hit in response.hits])
            evaluated.update({"profile_id": profile.profile_id, "dense_status": response.dense_status, "pipeline": response.pipeline, "warnings": response.warnings})
            all_results.append(evaluated)
            by_profile[profile.profile_id][query["query_id"]] = evaluated

    kg_rows: list[dict[str, Any]] = []
    governance_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for query in queries:
        qid = query["query_id"]
        r2, r3, r4 = (by_profile[key][qid] for key in ("R2_bm25_dense_rrf", "R3_kg_bm25_dense_rrf", "R4_kg_bm25_dense_rrf_governance"))
        kg_rows.append({**diagnostics[qid], "paired_classification": _paired(r2, r3)})
        governance_rows.append({"query_id": qid, "classification": _paired(r3, r4), "r3_first_gold_rank": r3["first_gold_rank"], "r4_first_gold_rank": r4["first_gold_rank"], "r3_recall_at_10": r3["recall_at_10"], "r4_recall_at_10": r4["recall_at_10"]})
        for profile in PROFILES:
            result = by_profile[profile.profile_id][qid]
            cause = _failure_cause(gold_by_id[qid], profile.profile_id, result, diagnostics[qid], r2, r3)
            if cause:
                if cause not in FAILURE_CLASSES:
                    raise AssertionError(f"unregistered failure class: {cause}")
                failures.append({"query_id": qid, "track": query["track"], "profile_id": profile.profile_id, "first_cause": cause, "stage_ranks": diagnostics[qid]["stages"]})

    aggregates: dict[str, Any] = {}
    stratified: dict[str, Any] = {}
    for profile in PROFILES:
        rows = [row for row in all_results if row["profile_id"] == profile.profile_id]
        aggregates[profile.profile_id] = {track: _aggregate([row for row in rows if row["track"] == track]) for track in ("R1_scientific_evidence", "R2_tool_method_discovery")}
        stratified[profile.profile_id] = {}
        for dimension in ("task_family", "query_type"):
            stratified[profile.profile_id][dimension] = {value: _aggregate([row for row in rows if row[dimension] == value]) for value in sorted({row[dimension] for row in rows})}

    v1_aggregates = json.loads((V1_DIR / "aggregate_metrics.json").read_text(encoding="utf-8"))
    comparison = {profile.profile_id: {track: _metric_delta(v1_aggregates[profile.profile_id][track], aggregates[profile.profile_id][track]) for track in ("R1_scientific_evidence", "R2_tool_method_discovery")} for profile in PROFILES}
    cohort_results: dict[str, Any] = {}
    for name, ids in cohorts.items():
        cohort_results[name] = {
            "query_count": len(ids),
            "profiles": {profile.profile_id: _aggregate([by_profile[profile.profile_id][qid] for qid in ids]) for profile in PROFILES},
        }
    original_hurt = set(cohorts["original_governance_hurt"])
    cohort_results["original_governance_hurt"]["v1_1_governance_classification"] = dict(Counter(row["classification"] for row in governance_rows if row["query_id"] in original_hurt))
    kg_counts = Counter(row["paired_classification"] for row in kg_rows)
    governance_counts = Counter(row["classification"] for row in governance_rows)
    failure_counts = dict(sorted(Counter(row["first_cause"] for row in failures).items()))
    causal_gains = {
        "corpus_coverage": {"repaired_query_count": len(cohorts["repaired"]), "still_blocked_query_count": len(cohorts["still_blocked"])},
        "ranking": {"failure_records": sum(failure_counts.get(key, 0) for key in ("BM25_RANKING", "DENSE_RANKING", "RRF_RANKED_OUT", "DIVERSIFICATION_RANKED_OUT", "INITIAL_RETRIEVAL_MISS"))},
        "kg_filtering": dict(kg_counts),
        "governance_reranking": dict(governance_counts),
    }
    _write_jsonl(output_dir / "per_query_results.jsonl", all_results)
    _write_json(output_dir / "aggregate_metrics.json", aggregates)
    _write_json(output_dir / "stratified_metrics.json", stratified)
    _write_jsonl(output_dir / "kg_diagnostics.jsonl", kg_rows)
    _write_jsonl(output_dir / "governance_diagnostics.jsonl", governance_rows)
    _write_jsonl(output_dir / "failure_register.jsonl", failures)
    _write_json(output_dir / "v1_to_v1_1_comparison.json", comparison)
    _write_json(output_dir / "cohort_analysis.json", cohort_results)
    _write_json(output_dir / "causal_gain_analysis.json", causal_gains)
    report = {
        "schema_version": "sckg-retrieval-benchmark-v1.1-dev-report-v1",
        "status": "COMPLETE",
        "interpretation_boundary": "COMPLETE means the frozen development comparison executed faithfully; it does not assert superiority",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "query_set_sha256": pre["query_set_sha256"], "gold_sha256": pre["gold_sha256"],
        "retrieval_config_sha256": pre["retrieval_config_sha256"],
        "snapshot_identity": pre["snapshot_identity"], "kg_snapshot_identity": pre["kg_snapshot_identity"],
        "query_counts": {"R1_scientific_evidence": sum(row["track"] == "R1_scientific_evidence" for row in queries), "R2_tool_method_discovery": sum(row["track"] == "R2_tool_method_discovery" for row in queries)},
        "aggregate_metrics": aggregates, "v1_to_v1_1": comparison,
        "cohort_analysis": cohort_results, "kg_analysis": dict(kg_counts),
        "governance_analysis": dict(governance_counts), "failure_counts": failure_counts,
        "other_failure_count": failure_counts.get("OTHER", 0), "causal_gain_analysis": causal_gains,
        "boundaries": {"corpus_mutated_during_run": False, "kg_mutated_during_run": False, "gold_changed": False, "query_set_changed": False, "formal_holdout_run": False, "seed_v1_started": False, "repairs_after_results": False},
    }
    _write_json(output_dir / "report.json", report)
    _write_json(output_dir / "run_completed.json", {"schema_version": "sckg-retrieval-benchmark-v1.1-dev-marker-v1", "completed_at": report["completed_at"], "run_count": 1, "report_sha256": _sha_file(output_dir / "report.json")})
    _write_report(report_path, report)
    _write_json(output_dir / "manifest.json", {"schema_version": "sckg-retrieval-benchmark-v1.1-dev-artifact-manifest-v1", "artifacts": {path.name: _sha_file(path) for path in sorted(output_dir.iterdir()) if path.is_file()}})
    return report


def _fmt_rate(value: dict[str, Any]) -> str:
    return f"{value['numerator']}/{value['denominator']} ({value['rate']:.3f})" if value["rate"] is not None else "not_applicable"


def _write_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Retrieval Benchmark v1.1 — Development Campaign", "",
        "Status: **COMPLETE**. This is a frozen development comparison, not the formal Midterm holdout.", "",
        f"- Query-set SHA-256: `{report['query_set_sha256']}`", f"- Gold SHA-256: `{report['gold_sha256']}`",
        f"- Strengthened corpus digest: `{report['snapshot_identity']['corpus_digest']}`",
        f"- Dense build: `{report['snapshot_identity']['dense']['build_id']}`", "",
        "## v1.1 metrics", "",
        "| Profile | Track | Recall@5 | Recall@10 | MRR | nDCG@10 | Authoritative hit | Irrelevant context |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for profile, tracks in report["aggregate_metrics"].items():
        for track, metric in tracks.items():
            lines.append(f"| {profile} | {track} | {_fmt_rate(metric['recall_at_5'])} | {_fmt_rate(metric['recall_at_10'])} | {metric['mrr']:.3f} | {metric['ndcg_at_10']:.3f} | {_fmt_rate(metric['authoritative_source_hit_rate'])} | {metric['irrelevant_context_rate']:.3f} |")
    lines.extend(["", "## Frozen cohort results", ""])
    for name, value in report["cohort_analysis"].items():
        lines.append(f"- **{name}**: {value['query_count']} queries")
        if "v1_1_governance_classification" in value:
            lines.append(f"  - v1.1 governance: `{value['v1_1_governance_classification']}`")
    lines.extend([
        "", "## Causal diagnostics", "",
        f"- KG R2→R3: `{report['kg_analysis']}`",
        f"- Governance R3→R4: `{report['governance_analysis']}`",
        f"- Failure first causes: `{report['failure_counts']}`",
        f"- OTHER: {report['other_failure_count']}", "",
        "No corpus, gold, queries, KG, Planner, thresholds, or ranking configuration was changed after observing the v1.1 result.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval Benchmark v1.1 development comparison")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    result = prepare(args.output) if args.prepare else run(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
