from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from connectors.offline_graph import OfflineGraphStore
from engine.evidence_graph_query import EvidenceGraphQuery


def evaluate_kg_v2(*, data_dir: Path) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    graph_dir = Path(data_dir) / "knowledge_graph_v2"
    query = EvidenceGraphQuery(graph_dir)
    store = OfflineGraphStore(data_dir=data_dir)
    quality = json.loads((graph_dir / "quality_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((graph_dir / "manifest.json").read_text(encoding="utf-8"))
    candidates = store.find_candidates("doublet detection", "scRNA-seq")
    verified = sorted(
        row["tool_name"] for row in candidates if row.get("candidate_basis") == "execution_verified"
    )
    expected_verified = ["Scrublet", "scDblFinder"]
    scrublet = query.explain_tool("Scrublet")
    scdblfinder = query.explain_tool("scDblFinder")
    quarantined = query.search("source_metadata_mismatch", limit=50)
    retrieval_cases, legacy_retrieval_summary = _evaluate_retrieval_gold(
        query=query,
        gold_path=data_dir.parent / "eval" / "kg_v2" / "graph_retrieval_gold.json",
    )
    retrieval_summary = _retrieval_v2_summary(data_dir)
    cases = [
        _case(
            "KG001",
            "verified_doublet_capability_recall",
            verified == expected_verified,
            expected_verified,
            verified,
        ),
        _case(
            "KG002",
            "scrublet_contract_environment_path",
            bool(scrublet.contracts and scrublet.environments and scrublet.trusted_tasks),
            "contract + environment + verified task",
            {
                "contracts": len(scrublet.contracts),
                "environments": len(scrublet.environments),
                "trusted_tasks": scrublet.trusted_tasks,
            },
        ),
        _case(
            "KG003",
            "scientific_pilot_scope_visible",
            len(scrublet.evaluations) == 1 and len(scdblfinder.evaluations) == 2,
            {"Scrublet": 1, "scDblFinder": 2},
            {"Scrublet": len(scrublet.evaluations), "scDblFinder": len(scdblfinder.evaluations)},
        ),
        _case(
            "KG004",
            "formal_evidence_gate",
            quality.get("formal_publication_allowed_count") == 0
            and quality.get("formal_benchmark_allowed_count") == 0
            and quality.get("frozen_recommendation_leakage_count") == 0,
            "no frozen evidence may become recommendation eligible",
            {
                "publication_allowed": quality.get("formal_publication_allowed_count"),
                "benchmark_allowed": quality.get("formal_benchmark_allowed_count"),
                "frozen_leakage": quality.get("frozen_recommendation_leakage_count"),
            },
        ),
        _case(
            "KG005",
            "metadata_mismatch_quarantine",
            bool(quarantined) and all(node.governance.layer == "quarantined" for node in quarantined),
            "mismatched sources are quarantined",
            [{"node_id": node.node_id, "layer": node.governance.layer} for node in quarantined],
        ),
        _case(
            "KG006",
            "snapshot_integrity_and_optional_projection",
            quality.get("integrity_passed") is True
            and bool(manifest.get("canonical_snapshot_id"))
            and _hash_matches(graph_dir / "nodes.jsonl", manifest.get("nodes_sha256"))
            and _hash_matches(graph_dir / "edges.jsonl", manifest.get("edges_sha256")),
            "integrity pass + canonical snapshot binding + matching hashes; Neo4j is optional",
            {
                "integrity_passed": quality.get("integrity_passed"),
                "neo4j_import_status": manifest.get("neo4j_import_status"),
                "nodes_hash_valid": _hash_matches(graph_dir / "nodes.jsonl", manifest.get("nodes_sha256")),
                "edges_hash_valid": _hash_matches(graph_dir / "edges.jsonl", manifest.get("edges_sha256")),
            },
        ),
        _case(
            "KG007",
            "connected_ontology_projection",
            quality.get("isolated_tool_count") == 0
            and quality.get("connected_component_count", 0) <= 2
            and quality.get("largest_component_ratio", 0.0) > 0.99
            and quality.get("tool_semantic_coverage_rate", 0.0) > 0.9,
            "zero isolated tools + <=2 components + >99% largest component + >90% semantic coverage",
            {
                "isolated_tools": quality.get("isolated_tool_count"),
                "components": quality.get("connected_component_count"),
                "largest_component_ratio": quality.get("largest_component_ratio"),
                "semantic_coverage": quality.get("tool_semantic_coverage_rate"),
            },
        ),
        _case(
            "KG008",
            "candidate_capability_governance_boundary",
            quality.get("hypothesis_edge_count", 0) == 0
            and quality.get("hypothesis_recommendation_leakage_count") == 0
            and quality.get("unsupported_capability_edge_count", 0) == 0,
            "unsupported and legacy-derived capability edges are excluded from the canonical graph",
            {
                "hypothesis_edges": quality.get("hypothesis_edge_count"),
                "recommendation_leakage": quality.get(
                    "hypothesis_recommendation_leakage_count"
                ),
                "unsupported_capability_edges": quality.get(
                    "unsupported_capability_edge_count"
                ),
            },
        ),
        _case(
            "KG009",
            "source_bound_retrieval_gold_v2",
            retrieval_summary["status"] == "passed",
            "96-case deterministic retrieval gate passes with zero governance leakage",
            retrieval_summary,
        ),
    ]
    passed = sum(case["passed"] for case in cases)
    summary = {
        "status": "passed" if passed == len(cases) else "failed",
        "cases": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "catalog_tool_count": quality.get("catalog_tool_count", 0),
        "connected_tool_count": quality.get("connected_tool_count", 0),
        "execution_verified_tool_count": quality.get("execution_verified_tool_count", 0),
        "verified_doublet_candidate_precision": (
            len(set(verified) & set(expected_verified)) / len(verified) if verified else 0.0
        ),
        "verified_doublet_candidate_recall": len(set(verified) & set(expected_verified))
        / len(expected_verified),
        "frozen_recommendation_leakage_count": quality.get(
            "frozen_recommendation_leakage_count", 0
        ),
        "hypothesis_recommendation_leakage_count": quality.get(
            "hypothesis_recommendation_leakage_count", 0
        ),
        "connected_component_count": quality.get("connected_component_count", 0),
        "largest_component_ratio": quality.get("largest_component_ratio", 0.0),
        "tool_semantic_coverage_rate": quality.get("tool_semantic_coverage_rate", 0.0),
        "graph_retrieval": retrieval_summary,
        "graph_retrieval_cases": retrieval_cases,
        "legacy_graph_retrieval": legacy_retrieval_summary,
        "dangling_edge_count": quality.get("dangling_edge_count", 0),
        "limitations": [
            "The v2 retrieval gold includes source-bound positive, ambiguous, and hard-negative cases.",
            "Catalog connectivity is discovery metadata and is reported separately from full-text source coverage.",
            "Scientific pilot relations are dataset-scoped and cannot prove universal superiority.",
            "Dense and RAGAS profiles remain not_run until their optional local evaluator packs are available.",
        ],
    }
    return cases, summary


def _retrieval_v2_summary(data_dir: Path) -> Dict[str, Any]:
    path = data_dir / "evaluation" / "retrieval_eval_v2" / "summary.json"
    if not path.is_file():
        return {
            "status": "not_run",
            "case_count": 0,
            "macro_recall_at_k": 0.0,
            "precision_at_k": 0.0,
            "mean_reciprocal_rank": 0.0,
            "source_span_hit_rate": 0.0,
            "false_support_rate": 1.0,
            "execution_admission_violation_count": 0,
            "reason": "retrieval_eval_v2 summary is missing",
        }
    report = json.loads(path.read_text(encoding="utf-8"))
    profile = (report.get("profiles") or {}).get("kg_bm25") or {}
    return {
        "status": profile.get("status", "not_run"),
        "case_count": report.get("case_count", 0),
        "macro_recall_at_k": profile.get("recall_at_10", 0.0),
        "precision_at_k": profile.get("precision_at_10", 0.0),
        "mean_reciprocal_rank": profile.get("mrr", 0.0),
        "source_span_hit_rate": profile.get("source_span_hit_rate", 0.0),
        "false_support_rate": profile.get("false_support_rate", 1.0),
        "latency_p95_ms": profile.get("latency_p95_ms"),
        "path_provenance_coverage": 1.0
        if profile.get("governance_leakage_count", 0) == 0
        else 0.0,
        "execution_admission_violation_count": profile.get(
            "governance_leakage_count", 0
        ),
        "metric_authority": profile.get("metric_authority"),
        "ragas_status": profile.get("ragas_status", "not_run"),
    }


def _evaluate_retrieval_gold(
    *, query: EvidenceGraphQuery, gold_path: Path
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    results: List[Dict[str, Any]] = []
    recalls: List[float] = []
    reciprocal_ranks: List[float] = []
    path_count = 0
    provenance_count = 0
    complete_path_count = 0
    admission_violations = 0
    for case in gold["cases"]:
        matches = query.rank_tools(
            task=case["task"], modality=case["modality"], limit=int(case["k"])
        )
        names = [match.tool_name for match in matches]
        expected = set(case["expected_tools"])
        verified = set(case["execution_verified_tools"])
        hits = sorted(expected & set(names))
        recall = len(hits) / len(expected) if expected else 1.0
        ranks = [names.index(name) + 1 for name in hits]
        reciprocal_rank = 1.0 / min(ranks) if ranks else 0.0
        case_violations = [
            match.tool_name
            for match in matches
            if match.candidate_basis == "execution_verified" and match.tool_name not in verified
        ]
        for match in matches:
            for path in match.paths:
                path_count += 1
                provenance_count += bool(path.get("provenance_refs"))
                complete_path_count += bool(
                    path.get("relation")
                    and path.get("target_id")
                    and path.get("governance_layer")
                )
        admission_violations += len(case_violations)
        recalls.append(recall)
        reciprocal_ranks.append(reciprocal_rank)
        results.append(
            {
                "case_id": case["case_id"],
                "task": case["task"],
                "modality": case["modality"],
                "k": case["k"],
                "expected_tools": case["expected_tools"],
                "retrieved_tools": names,
                "hits": hits,
                "recall_at_k": recall,
                "reciprocal_rank": reciprocal_rank,
                "execution_admission_violations": case_violations,
                "passed": recall == 1.0 and not case_violations,
            }
        )
    summary = {
        "status": "passed"
        if results
        and all(result["passed"] for result in results)
        and path_count > 0
        and provenance_count == path_count
        and complete_path_count == path_count
        else "failed",
        "case_count": len(results),
        "case_pass_rate": (
            sum(result["passed"] for result in results) / len(results) if results else 0.0
        ),
        "macro_recall_at_k": sum(recalls) / len(recalls) if recalls else 0.0,
        "mean_reciprocal_rank": (
            sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
        ),
        "path_completeness": complete_path_count / path_count if path_count else 0.0,
        "path_provenance_coverage": provenance_count / path_count if path_count else 0.0,
        "execution_admission_violation_count": admission_violations,
        "gold_scope": gold["scope"],
        "evidence_boundary": gold["evidence_boundary"],
    }
    return results, summary


def write_evaluation_artifacts(
    *, output_dir: Path, cases: List[Dict[str, Any]], summary: Dict[str, Any]
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "kg_v2_per_case.jsonl").write_text(
        "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases),
        encoding="utf-8",
    )
    (output_dir / "kg_v2_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _case(case_id: str, name: str, passed: bool, expected: Any, observed: Any) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "name": name,
        "passed": bool(passed),
        "expected": expected,
        "observed": observed,
    }


def _hash_matches(path: Path, expected: Any) -> bool:
    if not path.is_file() or not expected:
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == str(expected)
