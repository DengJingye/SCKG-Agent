from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.knowledge_intelligence_models import HybridRetrievalRequest
from engine.hybrid_retrieval import LocalBgeM3Encoder
from eval import retrieval_benchmark_v1_1_dev as c6


C7 = ROOT / "eval_v2/independent_retrieval_validation_v1"
OUTPUT = ROOT / "data/evaluation/scientific_kg_direct_evidence_abstention_v1"
TOP_K = 10
PROFILES = (
    ("A_bm25", True, False, False, False),
    ("B_bm25_dense", True, True, False, False),
    ("C_scikg_bm25", True, False, True, False),
    ("D_scikg_bm25_dense", True, True, True, False),
    ("E_scikg_bm25_dense_governance", True, True, True, True),
)
PROTECTED = (
    "eval_v2/independent_retrieval_validation_v1/query_set.jsonl",
    "eval_v2/independent_retrieval_validation_v1/gold.jsonl",
    "eval_v2/independent_retrieval_validation_v1/split_manifest.json",
    "data/indexes/retrieval_foundation_v1/evidence_chunks.jsonl",
    "data/indexes/retrieval_foundation_v1/evidence_index_manifest.json",
    "data/indexes/retrieval_foundation_v1/evidence_vectors.npy",
    "data/knowledge_graph_v2/manifest.json",
    "engine/capability_planner.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def load_dev_rows(path: Path, dev_ids: set[str]) -> list[dict[str, Any]]:
    """Parse only DEV records. Non-DEV lines are discarded before JSON decoding."""
    rows = []
    for raw in path.read_text().splitlines():
        match = re.search(r'"query_id"\s*:\s*"([^"]+)"', raw)
        if match and match.group(1) in dev_ids:
            rows.append(json.loads(raw))
    return rows


def evaluate(gold: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = set(gold["accepted_chunk_ids"])
    ranks = [i for i, hit in enumerate(hits[:TOP_K], 1) if hit["chunk_id"] in accepted]
    first = min(ranks) if ranks else None
    available = bool(gold["evidence_available"])
    return {
        "first_gold_rank": first,
        "hit_at_5": int(bool(first and first <= 5)) if available else None,
        "hit_at_10": int(bool(first and first <= 10)) if available else None,
        "reciprocal_rank_at_10": (round(1 / first, 8) if available and first and first <= 10 else (0.0 if available else None)),
    }


def mean(values):
    values = [float(v) for v in values if v is not None]
    return round(sum(values) / len(values), 6) if values else None


def run() -> dict[str, Any]:
    split = json.loads((C7 / "split_manifest.json").read_text())
    dev_ids = set(split["DEV_CHECK"])
    queries = load_dev_rows(C7 / "query_set.jsonl", dev_ids)
    gold_rows = load_dev_rows(C7 / "gold.jsonl", dev_ids)
    if {row["query_id"] for row in queries} != dev_ids or {row["query_id"] for row in gold_rows} != dev_ids:
        raise RuntimeError("DEV_CHECK extraction mismatch")
    gold = {row["query_id"]: row for row in gold_rows}
    protected_before = {rel: sha(ROOT / rel) for rel in PROTECTED}
    encoder = LocalBgeM3Encoder()
    service = c6._service(encoder)
    rows, paths = [], []
    try:
        for profile_id, sparse, dense, kg, governance in PROFILES:
            for query in queries:
                request = HybridRetrievalRequest(
                    query=query["query"],
                    top_k=TOP_K,
                    include_catalog=False,
                    enable_sparse=sparse,
                    enable_dense=dense,
                    nonblocking_dense=False,
                    use_kg=kg,
                    use_governance_rerank=governance,
                    use_contract_gate=False,
                    use_scientific_evidence=kg,
                )
                result = service.search(request)
                hit_rows = [hit.model_dump(mode="json") for hit in result.hits]
                assessment = evaluate(gold[query["query_id"]], hit_rows)
                row = {
                    "query_id": query["query_id"],
                    "profile_id": profile_id,
                    "evidence_available": gold[query["query_id"]]["evidence_available"],
                    "expected_abstention": gold[query["query_id"]]["expected_abstention"],
                    **assessment,
                    "answerability": result.answerability.model_dump(mode="json") if result.answerability else None,
                    "retrieved_chunk_ids": [hit["chunk_id"] for hit in hit_rows],
                }
                rows.append(row)
                if profile_id == "D_scikg_bm25_dense":
                    paths.append({
                        "query_id": query["query_id"],
                        "answerability": row["answerability"],
                        "scientific_evidence": result.scientific_evidence,
                    })
    finally:
        worker = getattr(service.dense_encoder, "_worker", None)
        if worker is not None:
            worker.close()

    by_key = {(row["profile_id"], row["query_id"]): row for row in rows}
    d_rows = [row for row in rows if row["profile_id"] == "D_scikg_bm25_dense"]
    available = [row for row in d_rows if row["evidence_available"]]
    statuses = Counter(row["answerability"]["status"] for row in d_rows)
    direct_resolution = sum(bool(row["answerability"]["direct_evidence_chunk_ids"]) for row in d_rows)
    correct_abstention = sum(
        row["expected_abstention"] and row["answerability"]["status"] != "SUPPORTED"
        for row in d_rows
    )
    false_certainty = sum(
        row["expected_abstention"] and row["answerability"]["status"] == "SUPPORTED"
        for row in d_rows
    )
    paired = Counter()
    false_filter = []
    for query_id in sorted(dev_ids):
        before = by_key["B_bm25_dense", query_id]
        after = by_key["D_scikg_bm25_dense", query_id]
        br, ar = before["first_gold_rank"], after["first_gold_rank"]
        if (br is None and ar is not None) or (br is not None and ar is not None and ar < br):
            paired["HELPED"] += 1
        elif (br is not None and ar is None) or (br is not None and ar is not None and ar > br):
            paired["HURT"] += 1
            false_filter.append({"query_id": query_id, "before_rank": br, "after_rank": ar, "reason": "paired_rank_regression"})
        else:
            paired["NEUTRAL"] += 1
    summary = {
        "schema_version": "scientific-kg-direct-evidence-abstention-v1",
        "dev_query_count": len(dev_ids),
        "statuses": {name: statuses.get(name, 0) for name in ("SUPPORTED", "INSUFFICIENT_EVIDENCE", "CLARIFICATION_REQUIRED", "UNRESOLVED")},
        "direct_graph_evidence_resolution": direct_resolution,
        "dev_correct_abstention": correct_abstention,
        "dev_false_certainty": false_certainty,
        "dev_hit_at_5": mean(row["hit_at_5"] for row in available),
        "dev_hit_at_10": mean(row["hit_at_10"] for row in available),
        "dev_mrr_at_10": mean(row["reciprocal_rank_at_10"] for row in available),
        "scikg_helped": paired["HELPED"],
        "scikg_neutral": paired["NEUTRAL"],
        "scikg_hurt": paired["HURT"],
        "false_filter_events": len(false_filter),
    }
    failure_rows = []
    path_by_id = {row["query_id"]: row for row in paths}
    for row in d_rows:
        answer = row["answerability"]
        if answer["status"] == "SUPPORTED":
            continue
        diagnostic = path_by_id[row["query_id"]]["scientific_evidence"] or {}
        failure_rows.append({
            "query_id": row["query_id"],
            "failure_class": answer["status"],
            "reason": answer["reason"],
            "fallback_reason": answer["fallback_reason"],
            "evidence_gap_id": answer["evidence_gap_id"],
            "graph_gap_reason_codes": sorted({
                gap.get("reason_code") or gap.get("reason", "")
                for gap in diagnostic.get("gaps", [])
                if gap.get("reason_code") or gap.get("reason")
            }),
        })
    protected_after = {rel: sha(ROOT / rel) for rel in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("protected frozen artifact changed")
    manifest = {
        "schema_version": "scientific-kg-direct-evidence-abstention-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dev_ids": sorted(dev_ids),
        "dev_count": len(dev_ids),
        "sealed_count": len(split["SEALED"]),
        "sealed_queries_read_for_development": False,
        "sealed_validation_rerun": False,
        "canonical_promotion": "none",
        "retrieval_snapshot_identity": c6._snapshot_identity(),
        "kg_snapshot_identity": c6._kg_identity(),
        "protected_sha256_before": protected_before,
        "protected_sha256_after": protected_after,
        "focused_test_report": "data/evaluation/scientific_kg_direct_evidence_abstention_v1/focused_tests.xml",
        "profiles": [profile[0] for profile in PROFILES],
        "top_k": TOP_K,
    }
    write_json(OUTPUT / "manifest.json", manifest)
    write_json(OUTPUT / "dev_check_results.json", {"rows": rows})
    write_json(OUTPUT / "answerability_summary.json", summary)
    write_jsonl(OUTPUT / "direct_evidence_paths.jsonl", paths)
    write_jsonl(
        OUTPUT / "failure_register.jsonl",
        [*failure_rows, *({"failure_class": "FALSE_FILTER", **row} for row in false_filter)],
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
