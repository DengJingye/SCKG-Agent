from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent


DEFAULT_GOLD = PROJECT_ROOT / "eval" / "gold_queries_v0_2_blind.jsonl"
DEFAULT_PREDICTIONS = (
    PROJECT_ROOT
    / "eval"
    / "ablation_deepseek_aura_v0_2_blind_full"
    / "predictions_evidence_gate.jsonl"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "recommendation_evidence_coverage_review_packet.tsv"
)


TARGET_TASKS = {
    "Perturbation Differential Expression": {
        "tools": ["MIMOSCA"],
        "candidate_action": "review_perturbation_benchmark_or_protocol_caveat",
    },
    "Spatial Deconvolution": {
        "tools": ["cell2location"],
        "candidate_action": "review_spatial_deconvolution_benchmark_or_protocol",
    },
    "Optimal Transport Trajectory": {
        "tools": ["moscot", "wot"],
        "candidate_action": "review_optimal_transport_trusted_evidence",
    },
    "Foundation Model Representation": {
        "tools": ["scGPT", "CellPLM"],
        "candidate_action": "review_foundation_model_benchmark_scope",
    },
}

PERTURBATION_TERMS = (
    "perturbation",
    "perturb-seq",
    "perturbseq",
    "treatment vs control",
    "treated vs control",
    "扰动",
    "处理前后",
    "干预前后",
    "给药前后",
)

FIELDNAMES = [
    "query_id",
    "tool_name",
    "task",
    "current_evidence_types",
    "missing_components",
    "recommendation_evidence_coverage",
    "candidate_action",
    "reviewer_decision",
    "reviewer_notes",
]


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_packet(gold_path: Path, predictions_path: Path) -> List[Dict[str, str]]:
    gold_by_id = {
        str(record.get("id")): record
        for record in load_jsonl(gold_path)
    }
    rows: List[Dict[str, str]] = []
    seen = set()
    for prediction in load_jsonl(predictions_path):
        query_id = str(prediction.get("id") or prediction.get("query_id") or "")
        gold = gold_by_id.get(query_id, {})
        task = review_task(prediction, gold)
        target = TARGET_TASKS.get(task)
        if not target:
            continue
        missing = sorted(set(_as_list(prediction.get("missing_components"))))
        evidence_items = list((prediction.get("evidence_bundle") or {}).get("items") or [])
        coverage = prediction_recommendation_coverage(evidence_items, missing)
        for tool_name in target["tools"]:
            key = (query_id, tool_name, task)
            if key in seen:
                continue
            seen.add(key)
            tool_evidence = [
                item for item in evidence_items
                if belongs_to_tool(item, tool_name)
            ]
            rows.append(
                {
                    "query_id": query_id,
                    "tool_name": tool_name,
                    "task": task,
                    "current_evidence_types": summarize_evidence(tool_evidence),
                    "missing_components": ";".join(missing),
                    "recommendation_evidence_coverage": f"{coverage:.3f}",
                    "candidate_action": str(target["candidate_action"]),
                    "reviewer_decision": "",
                    "reviewer_notes": "",
                }
            )
    return rows


def review_task(prediction: Dict[str, Any], gold: Dict[str, Any]) -> str:
    parsed = prediction.get("parsed_constraints") or {}
    task = str(parsed.get("task") or "")
    query = " ".join(
        str(value or "")
        for value in [
            prediction.get("user_query"),
            gold.get("query"),
            parsed.get("output_goal"),
        ]
    ).lower()
    if task in {"Differential Expression", "Workflow Planning", ""} and any(
        term in query for term in PERTURBATION_TERMS
    ):
        return "Perturbation Differential Expression"
    return task


def belongs_to_tool(item: Dict[str, Any], tool_name: str) -> bool:
    needle = _tool_key(tool_name)
    if not needle:
        return False
    evidence_id = str(item.get("evidence_id") or "")
    source_title = str(item.get("source_title") or "")
    source_url = str(item.get("source_url") or "")
    haystack = " ".join([evidence_id, source_title, source_url])
    return needle in _tool_key(haystack)


def summarize_evidence(items: Iterable[Dict[str, Any]]) -> str:
    summaries = []
    for item in items:
        source_type = str(item.get("source_type") or "unknown")
        metric_name = str(item.get("metric_name") or "unknown")
        review_status = str(item.get("review_status") or "unknown")
        graph_layer = str(item.get("graph_layer") or "unknown")
        summaries.append(f"{source_type}:{metric_name}:{review_status}:{graph_layer}")
    return ";".join(sorted(set(summaries))) or "none_in_visible_prediction"


def prediction_recommendation_coverage(
    items: List[Dict[str, Any]],
    missing_components: List[str],
) -> float:
    total = len(items) + len(missing_components)
    if total == 0:
        return 0.0
    recommendation_grade = [
        item for item in items
        if item.get("trust_level") in {"verified", "source_based"}
        and item.get("graph_layer") in {"trusted_core", "review_needed"}
        and item.get("review_status") != "rejected"
        and "recommendation" in _as_list(item.get("use_for"))
    ]
    return len(recommendation_grade) / total


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def _tool_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def write_packet(rows: List[Dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a candidate-only review packet for improving recommendation evidence coverage."
    )
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = build_packet(args.gold, args.predictions)
    write_packet(rows, args.output)
    print(f"wrote {args.output} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
