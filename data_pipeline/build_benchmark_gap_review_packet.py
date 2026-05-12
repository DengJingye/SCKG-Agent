from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evidence_policy import (
    is_main_benchmark_evidence,
    is_main_publication_evidence,
)
from core.models import Evidence
from core.task_ontology import build_task_query_terms, task_alignment_score, task_family, tool_task_hints


DEFAULT_PREDICTIONS = (
    PROJECT_ROOT
    / "eval"
    / "ablation_deepseek_aura_v0_2_blind_after_cell2location_benchmark"
    / "predictions_evidence_gate_auditor.jsonl"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "benchmark_gap_review_packet.tsv"
)

FIELDNAMES = [
    "query_id",
    "rank",
    "tool_name",
    "task",
    "recommendation_type",
    "has_main_publication",
    "has_main_benchmark",
    "current_publication_evidence",
    "current_benchmark_evidence",
    "missing_components",
    "candidate_action",
    "suggested_decision",
    "risk_notes",
    "reviewer_decision",
    "reviewer_notes",
]

TASK_ACTIONS = {
    "RNA Velocity": "review_velocity_benchmark_or_keep_caveat",
    "Spatial Deconvolution": "review_spatial_deconvolution_benchmark_or_protocol",
    "Foundation Model Representation": "review_foundation_model_benchmark_scope",
    "Optimal Transport Trajectory": "review_optimal_transport_trusted_evidence",
    "Perturbation Differential Expression": "review_perturbation_benchmark_or_protocol_caveat",
}


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_packet(
    predictions_path: Path,
    top_k: int = 3,
    existing_review_path: Path | None = None,
) -> List[Dict[str, str]]:
    existing_reviews = load_existing_reviews(existing_review_path)
    rows: List[Dict[str, str]] = []
    seen = set()
    for prediction in load_jsonl(predictions_path):
        task = str((prediction.get("parsed_constraints") or {}).get("task") or "Unknown")
        query_id = str(prediction.get("id") or prediction.get("query_id") or "")
        recommendation_type = str(prediction.get("recommendation_type") or "")
        missing = sorted(set(_as_list(prediction.get("missing_components"))))
        scored_tools = sorted(
            prediction.get("scored_tools") or [],
            key=lambda item: _safe_rank(item.get("rank")),
        )[:top_k]
        for tool in scored_tools:
            tool_name = str(tool.get("tool_name") or "")
            if not tool_name:
                continue
            evidence_items = [
                evidence for evidence in _load_evidence_items(tool)
                if evidence is not None
            ]
            publication_evidence = [
                evidence for evidence in evidence_items
                if is_main_publication_evidence(evidence)
            ]
            benchmark_evidence = [
                evidence for evidence in evidence_items
                if is_main_benchmark_evidence(evidence)
            ]
            if not publication_evidence or benchmark_evidence:
                continue
            alignment = task_alignment_score(
                build_task_query_terms(task, task_family(task)),
                tool_task_hints(tool_name),
            )
            candidate_action = TASK_ACTIONS.get(task, "manual_benchmark_source_lookup")
            suggested = suggested_decision(task)
            risk_notes = ""
            if alignment < 0.75:
                candidate_action = "review_task_alignment_before_benchmark_lookup"
                suggested = "fix_task_link_or_mark_supporting_only"
                risk_notes = (
                    "tool-task hint alignment is weak; do not search/promote benchmark "
                    "until the tool is confirmed as a primary method for this task"
                )
            key = (tool_name, task)
            if key in seen:
                continue
            seen.add(key)
            row = {
                "query_id": query_id,
                "rank": str(_safe_rank(tool.get("rank"))),
                "tool_name": tool_name,
                "task": task,
                "recommendation_type": recommendation_type,
                "has_main_publication": "true",
                "has_main_benchmark": "false",
                "current_publication_evidence": summarize_evidence(publication_evidence),
                "current_benchmark_evidence": "none",
                "missing_components": ";".join(missing_for_tool(tool, missing)),
                "candidate_action": candidate_action,
                "suggested_decision": suggested,
                "risk_notes": risk_notes,
                "reviewer_decision": "",
                "reviewer_notes": "",
            }
            review_key = (query_id, tool_name, task)
            if review_key in existing_reviews:
                row["reviewer_decision"] = existing_reviews[review_key].get("reviewer_decision", "")
                row["reviewer_notes"] = existing_reviews[review_key].get("reviewer_notes", "")
            rows.append(row)
    return sorted(rows, key=lambda row: (row["task"], row["rank"], row["tool_name"]))


def load_existing_reviews(path: Path | None) -> Dict[tuple[str, str, str], Dict[str, str]]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    reviews: Dict[tuple[str, str, str], Dict[str, str]] = {}
    for row in rows:
        key = (
            str(row.get("query_id") or ""),
            str(row.get("tool_name") or ""),
            str(row.get("task") or ""),
        )
        if row.get("reviewer_decision") or row.get("reviewer_notes"):
            reviews[key] = row
    return reviews


def _load_evidence_items(tool: Dict[str, Any]) -> List[Evidence | None]:
    evidence = tool.get("evidence") or {}
    return [_evidence_from_dict(item) for item in evidence.get("items") or []]


def _evidence_from_dict(item: Dict[str, Any]) -> Evidence | None:
    try:
        return Evidence.model_validate(item)
    except Exception:
        return None


def summarize_evidence(items: Iterable[Evidence]) -> str:
    summaries = []
    for item in items:
        label = item.evidence_id
        if item.source_url:
            label = f"{label}|{item.source_url}"
        summaries.append(label)
    return ";".join(sorted(set(summaries)))


def missing_for_tool(tool: Dict[str, Any], prediction_missing: List[str]) -> List[str]:
    evidence = tool.get("evidence") or {}
    tool_missing = _as_list(evidence.get("missing_evidence"))
    missing = sorted(set(tool_missing + prediction_missing))
    return missing


def suggested_decision(task: str) -> str:
    if task in {
        "Optimal Transport Trajectory",
        "Perturbation Differential Expression",
    }:
        return "keep_caveat_only_or_defer_benchmark"
    if task == "Foundation Model Representation":
        return "extract_if_third_party_else_defer"
    return "manual_benchmark_source_lookup"


def _safe_rank(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10_000


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def write_packet(rows: List[Dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a candidate-only review packet for top-k tools missing trusted benchmark evidence."
    )
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--existing-review",
        type=Path,
        default=None,
        help="Optional TSV whose reviewer_decision/reviewer_notes should be preserved.",
    )
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    existing_review_path = args.existing_review or (args.output if args.output.exists() else None)
    rows = build_packet(
        args.predictions,
        top_k=args.top_k,
        existing_review_path=existing_review_path,
    )
    write_packet(rows, args.output)
    print(f"wrote {args.output} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
