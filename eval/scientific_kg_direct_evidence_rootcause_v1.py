from __future__ import annotations

import argparse
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
from engine.scientific_kg_evidence import ScientificKGEvidence
from eval import retrieval_benchmark_v1_1_dev as c6
from eval.dev_only_c7_loader import load_dev_pair


C7 = ROOT / "eval_v2/independent_retrieval_validation_v1"
BLOCKED = ROOT / "data/evaluation/scientific_kg_direct_evidence_abstention_v1"
OUTPUT = ROOT / "data/evaluation/scientific_kg_direct_evidence_rootcause_v1"
PROTECTED = (
    C7,
    BLOCKED,
    ROOT / "data/indexes/retrieval_foundation_v1",
    ROOT / "data/knowledge_graph_v2",
    ROOT / "engine/capability_planner.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    if path.is_file():
        return sha(path)
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(bytes.fromhex(sha(item)))
    return digest.hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def subject_vocabulary(adapter: ScientificKGEvidence) -> set[str]:
    values = {
        str(gap.get("ecosystem", ""))
        for gap in adapter.evidence_gaps
        if gap.get("ecosystem")
    }
    values.update(
        operator.operator_id.split(":", 1)[-1].split(".", 1)[0]
        for operator in adapter.operators
    )
    return {normalize(value) for value in values if normalize(value)}


def earliest_failure(
    trace: dict[str, Any],
    diagnostic: dict[str, Any],
) -> tuple[str, list[str]]:
    parsed = diagnostic.get("parsed", {})
    fallback = diagnostic.get("fallback_reason", "")
    paths = diagnostic.get("paths", [])
    secondary: list[str] = []
    if not parsed.get("information_needs"):
        return "INFORMATION_NEED_PARSE_FAILED", secondary
    if fallback in {"ambiguous_operator", "multiple_conditions_require_clause_resolution"}:
        return "MULTIPLE_OPERATOR_AMBIGUITY", secondary
    if not parsed.get("operator_id"):
        if trace["registry_subject_candidates"]:
            return "IMPLEMENTATION_WIRING_ERROR", secondary
        if parsed.get("ecosystem"):
            return "OPERATOR_REVISION_NOT_FOUND", secondary
        return "SUBJECT_RESOLUTION_FAILED", secondary
    if not trace["candidate_operator_revisions"]:
        return "OPERATOR_REVISION_NOT_FOUND", secondary
    if fallback == "information_need_not_expressed_in_graph":
        return "CLAIM_TYPE_NOT_EXPRESSED", secondary
    if not paths:
        return "CLAIM_NOT_FOUND", secondary
    gap_reasons = {
        gap.get("reason_code") or gap.get("reason", "")
        for gap in diagnostic.get("gaps", [])
    }
    if "version_not_supported_by_scope" in gap_reasons:
        return "VERSION_UNRESOLVED", secondary
    if "flavor_condition_mismatch" in gap_reasons:
        return "FLAVOR_UNRESOLVED", secondary
    if gap_reasons & {
        "scope_unknown",
        "explicit_biological_scope_not_resolved",
        "unhandled_scope_condition",
    }:
        return "SCOPE_UNRESOLVED", secondary
    if "evidence_binding_missing" in gap_reasons:
        return "EVIDENCE_BINDING_NOT_FOUND", secondary
    if gap_reasons & {
        "claim_binding_integrity_failure",
        "binding_not_supported_candidate",
        "assessment_binding_missing",
        "evidence_span_unresolvable",
        "span_binding_integrity_failure",
        "source_revision_unresolvable",
        "source_version_mismatch",
    }:
        return "EVIDENCE_SPAN_NOT_RESOLVABLE", secondary
    if "GRAPH_EVIDENCE_NOT_IN_CORPUS" in gap_reasons:
        return "EVIDENCE_NOT_IN_FROZEN_CORPUS", secondary
    if fallback == "public_eligibility_filter_rejected_graph_evidence":
        return "PUBLIC_ELIGIBILITY_REJECTED", secondary
    if diagnostic.get("final_graph_chunk_ids"):
        return "RESOLVED", secondary
    return "OTHER_EXPLICIT", [fallback] if fallback else []


def collect_traces(
    queries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    service = c6._service(None)
    adapter = ScientificKGEvidence()
    vocabulary = subject_vocabulary(adapter)
    traces: list[dict[str, Any]] = []
    attribution: list[dict[str, Any]] = []
    for query in queries:
        registry_candidates = [
            tool
            for tool in service._named_tools_in_query(query["query"])
            if normalize(tool) in vocabulary
        ]
        request = HybridRetrievalRequest(
            query=query["query"],
            top_k=10,
            include_catalog=False,
            enable_sparse=True,
            enable_dense=False,
            use_kg=True,
            use_governance_rerank=False,
            use_scientific_evidence=True,
        )
        result = service.search(request)
        diagnostic = result.scientific_evidence or {}
        parsed = diagnostic.get("parsed", {})
        candidate_revisions = [
            operator.entity_id
            for operator in adapter.operators
            if operator.operator_id == parsed.get("operator_id")
        ]
        paths = diagnostic.get("paths", [])
        trace = {
            "query_id": query["query_id"],
            "natural_query": query["query"],
            "parsed_information_need": parsed.get("information_needs", []),
            "parsed_scientific_subject": parsed.get("ecosystem", ""),
            "parsed_operator_id": parsed.get("operator_id", ""),
            "registry_subject_candidates": registry_candidates,
            "candidate_operator_revisions": candidate_revisions,
            "selected_operator_revision": diagnostic.get("resolved_operator_revision", ""),
            "claim_type_requested": parsed.get("information_needs", []),
            "claim_candidates": [path.get("claim_revision_id", "") for path in paths],
            "scope_version_flavor_evaluation": [path.get("scope", {}) for path in paths],
            "evidence_binding_candidates": [
                evidence.get("evidence_span_id", "")
                for path in paths
                for evidence in path.get("evidence", [])
            ],
            "evidence_span_resolution": [
                {
                    "evidence_span_id": evidence.get("evidence_span_id", ""),
                    "source_revision_id": evidence.get("source_revision_id", ""),
                    "binding_verified": evidence.get("binding_verified", False),
                }
                for path in paths
                for evidence in path.get("evidence", [])
            ],
            "rag_chunk_mapping": diagnostic.get("mapped_chunk_ids", []),
            "final_direct_chunk_ids": diagnostic.get("final_graph_chunk_ids", []),
            "answerability_state": (
                result.answerability.model_dump(mode="json")
                if result.answerability is not None
                else None
            ),
            "fallback_reason": diagnostic.get("fallback_reason", ""),
            "secondary_diagnostics": diagnostic.get("gaps", []),
        }
        cause, secondary = earliest_failure(trace, diagnostic)
        trace["earliest_failure"] = cause
        trace["secondary_failure_classes"] = secondary
        traces.append(trace)
        attribution.append({
            "query_id": query["query_id"],
            "earliest_failure": cause,
            "secondary_diagnostics": secondary,
        })
    return traces, attribution


def capture_before() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError("rootcause output already exists")
    queries, _gold, loader_audit = load_dev_pair(
        C7 / "query_set.jsonl",
        C7 / "gold.jsonl",
        C7 / "split_manifest.json",
    )
    protected_before = {str(path.relative_to(ROOT)): tree_hash(path) for path in PROTECTED}
    traces, attribution = collect_traces(queries)
    counts = Counter(row["earliest_failure"] for row in attribution)
    primary = counts.most_common(1)[0]
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_jsonl(OUTPUT / "failure_attribution.before.jsonl", attribution)
    write_jsonl(OUTPUT / "dev_resolution_paths.before.jsonl", traces)
    manifest = {
        "schema_version": "scientific-kg-direct-evidence-rootcause-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dev_query_count": len(queries),
        "loader_audit": loader_audit,
        "sealed_payload_accessed": False,
        "sealed_validation_rerun": False,
        "quarantined_after_disclosure": loader_audit["quarantine"],
        "protected_before": protected_before,
        "before_failure_counts": dict(sorted(counts.items())),
        "primary_earliest_divergence": primary[0],
        "primary_count": primary[1],
    }
    write_json(OUTPUT / "manifest.json", manifest)
    return {
        "counts": dict(sorted(counts.items())),
        "primary": primary,
        "sealed_payload_accessed": False,
    }


PROFILES = (
    ("A_bm25", True, False, False, False),
    ("B_bm25_dense", True, True, False, False),
    ("C_scikg_bm25", True, False, True, False),
    ("D_scikg_bm25_dense", True, True, True, False),
    ("E_scikg_bm25_dense_governance", True, True, True, True),
)


def evaluate_hits(gold: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = set(gold["accepted_chunk_ids"])
    ranks = [i for i, hit in enumerate(hits[:10], 1) if hit["chunk_id"] in accepted]
    first = min(ranks) if ranks else None
    available = bool(gold["evidence_available"])
    return {
        "first_gold_rank": first,
        "hit_at_5": int(bool(first and first <= 5)) if available else None,
        "hit_at_10": int(bool(first and first <= 10)) if available else None,
        "reciprocal_rank_at_10": (
            round(1 / first, 8)
            if available and first and first <= 10
            else (0.0 if available else None)
        ),
    }


def mean(values) -> float | None:
    kept = [float(value) for value in values if value is not None]
    return round(sum(kept) / len(kept), 6) if kept else None


def run_dev_profiles(
    queries: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gold = {row["query_id"]: row for row in gold_rows}
    encoder = LocalBgeM3Encoder()
    service = c6._service(encoder)
    rows: list[dict[str, Any]] = []
    try:
        for profile_id, sparse, dense, kg, governance in PROFILES:
            for query in queries:
                request = HybridRetrievalRequest(
                    query=query["query"],
                    top_k=10,
                    include_catalog=False,
                    enable_sparse=sparse,
                    enable_dense=dense,
                    nonblocking_dense=False,
                    use_kg=kg,
                    use_governance_rerank=governance,
                    use_scientific_evidence=kg,
                )
                result = service.search(request)
                hits = [hit.model_dump(mode="json") for hit in result.hits]
                rows.append({
                    "query_id": query["query_id"],
                    "profile_id": profile_id,
                    "evidence_available": gold[query["query_id"]]["evidence_available"],
                    "expected_abstention": gold[query["query_id"]]["expected_abstention"],
                    **evaluate_hits(gold[query["query_id"]], hits),
                    "answerability": (
                        result.answerability.model_dump(mode="json")
                        if result.answerability is not None
                        else None
                    ),
                    "retrieved_chunk_ids": [hit["chunk_id"] for hit in hits],
                })
    finally:
        worker = getattr(service.dense_encoder, "_worker", None)
        if worker is not None:
            worker.close()
    indexed = {(row["profile_id"], row["query_id"]): row for row in rows}
    d_rows = [row for row in rows if row["profile_id"] == "D_scikg_bm25_dense"]
    available = [row for row in d_rows if row["evidence_available"]]
    statuses = Counter(row["answerability"]["status"] for row in d_rows)
    paired = Counter()
    false_filter = 0
    for query in queries:
        query_id = query["query_id"]
        before = indexed["B_bm25_dense", query_id]["first_gold_rank"]
        after = indexed["D_scikg_bm25_dense", query_id]["first_gold_rank"]
        if (before is None and after is not None) or (
            before is not None and after is not None and after < before
        ):
            paired["HELPED"] += 1
        elif (before is not None and after is None) or (
            before is not None and after is not None and after > before
        ):
            paired["HURT"] += 1
            false_filter += 1
        else:
            paired["NEUTRAL"] += 1
    summary = {
        "direct_graph_evidence_resolution": sum(
            bool(row["answerability"]["direct_evidence_chunk_ids"])
            for row in d_rows
        ),
        "statuses": {
            status: statuses.get(status, 0)
            for status in (
                "SUPPORTED",
                "INSUFFICIENT_EVIDENCE",
                "CLARIFICATION_REQUIRED",
                "UNRESOLVED",
            )
        },
        "dev_correct_abstention": sum(
            row["expected_abstention"]
            and row["answerability"]["status"] != "SUPPORTED"
            for row in d_rows
        ),
        "dev_false_certainty": sum(
            row["expected_abstention"]
            and row["answerability"]["status"] == "SUPPORTED"
            for row in d_rows
        ),
        "dev_hit_at_5": mean(row["hit_at_5"] for row in available),
        "dev_hit_at_10": mean(row["hit_at_10"] for row in available),
        "dev_mrr_at_10": mean(row["reciprocal_rank_at_10"] for row in available),
        "scikg_helped": paired["HELPED"],
        "scikg_neutral": paired["NEUTRAL"],
        "scikg_hurt": paired["HURT"],
        "false_filter_events": false_filter,
    }
    return rows, summary


def capture_after() -> dict[str, Any]:
    if not OUTPUT.exists():
        raise FileNotFoundError("capture before must run first")
    queries, gold, loader_audit = load_dev_pair(
        C7 / "query_set.jsonl",
        C7 / "gold.jsonl",
        C7 / "split_manifest.json",
    )
    manifest = json.loads((OUTPUT / "manifest.json").read_text())
    current_protected = {
        str(path.relative_to(ROOT)): tree_hash(path)
        for path in PROTECTED
    }
    if current_protected != manifest["protected_before"]:
        raise RuntimeError("protected_artifact_drift")
    traces, attribution = collect_traces(queries)
    before_attribution = {
        row["query_id"]: row
        for row in (
            json.loads(line)
            for line in (OUTPUT / "failure_attribution.before.jsonl").read_text().splitlines()
        )
    }
    combined = [
        {
            "query_id": row["query_id"],
            "before_earliest_failure": before_attribution[row["query_id"]]["earliest_failure"],
            "after_earliest_failure": row["earliest_failure"],
            "after_secondary_diagnostics": row["secondary_diagnostics"],
        }
        for row in attribution
    ]
    counts = Counter(row["earliest_failure"] for row in attribution)
    rows, dev_summary = run_dev_profiles(queries, gold)
    protected_after = {
        str(path.relative_to(ROOT)): tree_hash(path)
        for path in PROTECTED
    }
    integrity = {
        "protected_before": manifest["protected_before"],
        "protected_after": protected_after,
        "protected_equal": manifest["protected_before"] == protected_after,
        "sealed_payload_accessed": False,
        "sealed_validation_rerun": False,
        "frozen_c7_artifacts_changed": False,
        "corpus_changed": False,
        "kg_content_changed": False,
        "planner_changed": False,
        "canonical_promotion": "none",
    }
    if not integrity["protected_equal"]:
        raise RuntimeError("protected_artifact_drift_after")
    write_jsonl(OUTPUT / "failure_attribution.jsonl", combined)
    write_jsonl(OUTPUT / "dev_resolution_paths.jsonl", traces)
    write_json(OUTPUT / "dev_after_repair.json", {
        "summary": dev_summary,
        "rows": rows,
    })
    write_json(OUTPUT / "integrity.json", integrity)
    manifest.update({
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "after_failure_counts": dict(sorted(counts.items())),
        "one_layer_repair": {
            "applied": True,
            "owner": "engine/scientific_kg_evidence.py::parse_scientific_query",
            "layer": "generic_information_need_parser",
        },
        "loader_audit_after": loader_audit,
        "sealed_payload_accessed": False,
        "sealed_validation_rerun": False,
    })
    write_json(OUTPUT / "manifest.json", manifest)
    return {
        "after_counts": dict(sorted(counts.items())),
        "dev": dev_summary,
        "sealed_payload_accessed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-before", action="store_true")
    parser.add_argument("--capture-after", action="store_true")
    args = parser.parse_args()
    if args.capture_before == args.capture_after:
        parser.error("choose exactly one of --capture-before or --capture-after")
    result = capture_before() if args.capture_before else capture_after()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
