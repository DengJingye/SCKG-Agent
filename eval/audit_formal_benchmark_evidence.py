from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evidence_schemas import APPROVED_REVIEW_STATUSES


DEFAULT_BENCHMARKS = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evidence_candidates" / "formal_benchmark_audit.tsv"

NUMERIC_FIELDS = ("rank", "score", "normalized_score")
SOURCE_SPAN_FIELDS = ("claim_span", "evaluation_protocol")
CAVEAT_MARKERS = (
    "negative-control",
    "negative control",
    "caveat",
    "critique",
    "not positive ranking",
    "not as a positive",
    "do not claim",
    "not overall-best",
    "not overall best",
    "not universal",
    "sensitivity",
    "assumption",
    "reverse known",
)
SELF_REPORTED_MARKERS = (
    "self-reported",
    "author-reported",
    "primary method",
    "no independent",
    "third-party independent benchmarking is scarce",
)

FIELDNAMES = [
    "benchmark_id",
    "tool_name",
    "task",
    "modality",
    "benchmark_name",
    "paper_doi",
    "source_url",
    "review_status",
    "trust_level",
    "metric",
    "rank",
    "score",
    "normalized_score",
    "rank_scope",
    "n_tools_compared",
    "audit_labels",
    "runtime_recommendation_allowed",
    "recommended_action",
    "notes",
]


def read_tsv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader), list(reader.fieldnames or [])


def write_tsv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def audit_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    return [audit_row(row) for row in rows]


def audit_row(row: Dict[str, str]) -> Dict[str, str]:
    labels: List[str] = []
    if has_numeric_result(row):
        labels.append("numeric_supported")
    else:
        labels.append("qualitative_only")

    if not any(clean(row.get(field)) for field in SOURCE_SPAN_FIELDS):
        labels.append("missing_source_span")
    if not clean(row.get("metric")):
        labels.append("missing_metric")
    if not clean(row.get("rank_scope")):
        labels.append("missing_rank_scope")
    if not clean(row.get("n_tools_compared")):
        labels.append("missing_n_tools_compared")
    if is_caveat(row):
        labels.append("negative_control_caveat")
    if is_self_reported_or_unclear(row):
        labels.append("self_reported_or_unclear")
    if clean(row.get("review_status")).lower() not in APPROVED_REVIEW_STATUSES:
        labels.append("unapproved_review_status")

    allowed = runtime_recommendation_allowed(row, labels)
    return {
        "benchmark_id": clean(row.get("benchmark_id")),
        "tool_name": clean(row.get("tool_name")),
        "task": clean(row.get("task")),
        "modality": clean(row.get("modality")),
        "benchmark_name": clean(row.get("benchmark_name")),
        "paper_doi": clean(row.get("paper_doi")),
        "source_url": clean(row.get("source_url")),
        "review_status": clean(row.get("review_status")),
        "trust_level": clean(row.get("trust_level")),
        "metric": clean(row.get("metric")),
        "rank": clean(row.get("rank")),
        "score": clean(row.get("score")),
        "normalized_score": clean(row.get("normalized_score")),
        "rank_scope": clean(row.get("rank_scope")),
        "n_tools_compared": clean(row.get("n_tools_compared")),
        "audit_labels": ";".join(labels),
        "runtime_recommendation_allowed": "true" if allowed else "false",
        "recommended_action": recommended_action(labels),
        "notes": clean(row.get("notes")),
    }


def has_numeric_result(row: Dict[str, str]) -> bool:
    return any(parse_number(row.get(field)) is not None for field in NUMERIC_FIELDS)


def runtime_recommendation_allowed(row: Dict[str, str], labels: List[str]) -> bool:
    return (
        "numeric_supported" in labels
        and "missing_metric" not in labels
        and "missing_rank_scope" not in labels
        and "negative_control_caveat" not in labels
        and "unapproved_review_status" not in labels
        and clean(row.get("trust_level")).lower() == "trusted_core"
    )


def recommended_action(labels: List[str]) -> str:
    if "unapproved_review_status" in labels:
        return "exclude_from_formal_until_reviewed"
    if "negative_control_caveat" in labels:
        return "keep_retrieval_caveat_only"
    if "qualitative_only" in labels:
        return "downgrade_to_retrieval_until_numeric_source_verified"
    if "missing_metric" in labels or "missing_rank_scope" in labels:
        return "complete_source_bound_metadata_before_recommendation"
    if "self_reported_or_unclear" in labels:
        return "manual_verify_independence_before_recommendation"
    return "eligible_after_manual_spot_check"


def is_caveat(row: Dict[str, str]) -> bool:
    text = row_text(row)
    benchmark_type = clean(row.get("benchmark_type")).lower()
    return (
        "negative_control" in benchmark_type
        or "caveat" in benchmark_type
        or any(marker in text for marker in CAVEAT_MARKERS)
    )


def is_self_reported_or_unclear(row: Dict[str, str]) -> bool:
    text = row_text(row)
    return any(marker in text for marker in SELF_REPORTED_MARKERS)


def row_text(row: Dict[str, str]) -> str:
    return " ".join(
        clean(row.get(field)).lower()
        for field in ("benchmark_type", "result_text", "claim_span", "evaluation_protocol", "notes")
    )


def clean(value: object) -> str:
    return str(value or "").strip()


def parse_number(value: object) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def summarize(rows: List[Dict[str, str]]) -> Dict[str, object]:
    label_counts: Dict[str, int] = {}
    allowed = 0
    for row in rows:
        for label in row["audit_labels"].split(";"):
            label_counts[label] = label_counts.get(label, 0) + 1
        if row["runtime_recommendation_allowed"] == "true":
            allowed += 1
    return {
        "rows": len(rows),
        "runtime_recommendation_allowed": allowed,
        "label_counts": label_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit formal benchmark evidence quality.")
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json-summary", type=Path, default=None)
    args = parser.parse_args()

    rows, _ = read_tsv(args.benchmarks)
    audited = audit_rows(rows)
    write_tsv(args.output, audited)
    summary = summarize(audited)
    if args.json_summary:
        args.json_summary.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **summary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
