from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import PROJECT_ROOT
from engine.evidence_discovery_index import load_chunks
from engine.hybrid_retrieval import HybridRetrievalService
from eval.retrieval_evaluation import (
    PROFILES,
    build_gold_cases,
    evaluate_profile,
    read_gold_cases,
    write_gold_cases,
)


DEFAULT_GOLD = PROJECT_ROOT / "eval" / "fixtures" / "retrieval_gold_v2.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "retrieval_eval_v2"
DEFAULT_ROUTE_POLICY = PROJECT_ROOT / "data" / "indexes" / "retrieval_route_policy.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic scKG retrieval evaluation v2.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--route-policy-output", type=Path, default=DEFAULT_ROUTE_POLICY)
    parser.add_argument("--rebuild-gold", action="store_true")
    args = parser.parse_args()

    chunks = load_chunks(PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl")
    if args.rebuild_gold or not args.gold.is_file():
        write_gold_cases(args.gold, build_gold_cases(chunks))
    cases = read_gold_cases(args.gold)
    service = HybridRetrievalService()
    worker_status = service.wait_for_dense_ready(timeout=60.0)
    args.output.mkdir(parents=True, exist_ok=True)
    summaries = {}
    for profile in PROFILES:
        summary, case_results = evaluate_profile(service, cases, profile)
        summaries[profile.profile_id] = summary.model_dump(mode="json")
        (args.output / f"cases_{profile.profile_id}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in case_results),
            encoding="utf-8",
        )
    report = {
        "schema_version": "retrieval-eval-report-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold_path": str(args.gold.relative_to(PROJECT_ROOT)),
        "case_count": len(cases),
        "development_count": sum(case.split == "development" for case in cases),
        "evaluation_count": sum(case.split == "evaluation" for case in cases),
        "profiles": summaries,
        "primary_gate": "deterministic ID-based retrieval metrics",
        "ragas_policy": "optional secondary diagnostic; never authorizes evidence or execution",
        "embedding_worker": worker_status.model_dump(mode="json"),
    }
    route_decision = _route_decision(summaries)
    report["route_decision"] = route_decision
    (args.output / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.output / "route_decision.json").write_text(
        json.dumps(route_decision, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.route_policy_output.parent.mkdir(parents=True, exist_ok=True)
    args.route_policy_output.write_text(
        json.dumps(route_decision, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _route_decision(profiles: dict[str, dict]) -> dict:
    baseline = profiles.get("kg_bm25") or {}
    hybrid = profiles.get("kg_hybrid_tool_contract") or {}
    required = {
        "recall_at_10": 0.90,
        "precision_at_10": 0.70,
        "mrr": 0.75,
        "source_span_hit_rate": 0.85,
    }
    failures: list[str] = []
    if hybrid.get("status") != "passed":
        failures.append(f"hybrid_status={hybrid.get('status', 'missing')}")
    for metric, threshold in required.items():
        value = hybrid.get(metric)
        if value is None or float(value) < threshold:
            failures.append(f"{metric}={value}<{threshold}")
    if float(hybrid.get("false_support_rate") or 0.0) > 0.02:
        failures.append("false_support_rate>0.02")
    if float(hybrid.get("parameter_legality_rate") or 0.0) < 1.0:
        failures.append("parameter_legality_rate<1.0")
    if int(hybrid.get("governance_leakage_count") or 0):
        failures.append("governance_leakage_count>0")
    if float(hybrid.get("latency_p95_ms") or float("inf")) >= 500.0:
        failures.append("latency_p95_ms>=500")

    primary = tuple(required)
    improved = [
        metric
        for metric in primary
        if float(hybrid.get(metric) or 0.0) > float(baseline.get(metric) or 0.0) + 1e-6
    ]
    materially_regressed = [
        metric
        for metric in primary
        if float(hybrid.get(metric) or 0.0) + 0.01 < float(baseline.get(metric) or 0.0)
    ]
    if not improved:
        failures.append("no_primary_metric_improved_over_kg_bm25")
    if materially_regressed:
        failures.append("material_regression:" + ",".join(materially_regressed))
    default_profile = "kg_hybrid_tool_contract" if not failures else "kg_bm25"
    return {
        "schema_version": "retrieval-route-policy-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "default_profile": default_profile,
        "dense_default_enabled": default_profile != "kg_bm25",
        "baseline_profile": "kg_bm25",
        "hybrid_candidate": "kg_hybrid_tool_contract",
        "improved_primary_metrics": improved,
        "materially_regressed_metrics": materially_regressed,
        "decision_failures": failures,
        "policy": (
            "Hybrid is default only after deterministic quality, governance, and "
            "latency gates pass; otherwise KG+BM25 remains default."
        ),
    }


if __name__ == "__main__":
    main()
