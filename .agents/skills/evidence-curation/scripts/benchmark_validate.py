#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


PLACEHOLDER_NAME_MARKERS = (
    "supplemental information",
    "supplementary information",
    "supplementary",
    "supplement",
    "appendix",
    "supporting information",
    "table s",
    "figure s",
    "additional file",
    "unknown",
    "none",
    "placeholder",
)

REQUIRED_CORE_FIELDS = [
    "benchmark_name",
    "tool_name",
    "source_url",
]

SCIENTIFIC_FIELDS = [
    "task",
    "modality",
    "dataset",
    "metric",
    "direction",
    "evaluation_protocol",
]

NUMERIC_FIELDS = [
    "rank",
    "score",
    "normalized_score",
    "n_tools_compared",
]


def read_tsv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = [dict(row) for row in reader]
        fieldnames = list(reader.fieldnames or [])
    return rows, fieldnames


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def norm(value: str) -> str:
    return clean(value).lower()


def is_placeholder_benchmark_name(value: str) -> bool:
    text = norm(value)
    if not text:
        return True
    return any(marker in text for marker in PLACEHOLDER_NAME_MARKERS)


def missing_fields(row: Dict[str, str], fields: Sequence[str]) -> List[str]:
    return [field for field in fields if not clean(row.get(field, ""))]


def count_missing(row: Dict[str, str], fields: Sequence[str]) -> int:
    return len(missing_fields(row, fields))


def benchmark_bucket(row: Dict[str, str]) -> Tuple[str, str, str]:
    benchmark_name = clean(row.get("benchmark_name", ""))
    placeholder = is_placeholder_benchmark_name(benchmark_name)
    core_missing = missing_fields(row, REQUIRED_CORE_FIELDS)
    scientific_missing = missing_fields(row, SCIENTIFIC_FIELDS)
    numeric_missing = missing_fields(row, NUMERIC_FIELDS)

    if placeholder:
        return "needs_manual_benchmark_extraction", "manual_extraction", "pending"

    if core_missing:
        if len(core_missing) >= 2:
            return "insufficient_for_ingest", "hold", "pending"
        return "needs_field_completion", "field_completion", "review_needed"

    total_scientific_missing = len(scientific_missing) + len(numeric_missing)

    if total_scientific_missing == 0:
        return "ready_for_human_review", "human_review", "review_needed"

    if total_scientific_missing <= 2:
        return "needs_field_completion", "field_completion", "review_needed"

    return "insufficient_for_ingest", "hold", "pending"


def build_action_row(row: Dict[str, str]) -> Dict[str, str]:
    bucket, action_type, proposed_state = benchmark_bucket(row)
    benchmark_name = clean(row.get("benchmark_name", ""))
    placeholder = is_placeholder_benchmark_name(benchmark_name)

    missing = []
    for field in REQUIRED_CORE_FIELDS + SCIENTIFIC_FIELDS + NUMERIC_FIELDS:
        if not clean(row.get(field, "")):
            missing.append(field)

    reason_parts = []
    if placeholder:
        reason_parts.append("benchmark_name looks like supplemental material or a partial shell")
    if missing:
        reason_parts.append(f"missing_fields={';'.join(missing)}")
    if bucket == "ready_for_human_review":
        reason_parts.append("minimum benchmark structure looks complete")
    elif bucket == "needs_field_completion":
        reason_parts.append("some benchmark fields need manual completion before formal ingest")
    elif bucket == "insufficient_for_ingest":
        reason_parts.append("insufficient benchmark evidence for formal ingest")
    else:
        reason_parts.append("manual extraction required from paper or supplement")

    recommended_review_status = "review_needed" if bucket != "insufficient_for_ingest" else "pending"
    recommended_trust_level = "review_needed" if bucket != "insufficient_for_ingest" else "retrieval_only"

    return {
        "benchmark_id": clean(row.get("benchmark_id", "")),
        "benchmark_name": benchmark_name,
        "tool_name": clean(row.get("tool_name", "")),
        "review_bucket": bucket,
        "action_type": action_type,
        "proposed_state": proposed_state,
        "missing_fields": ";".join(missing),
        "recommended_review_status": recommended_review_status,
        "recommended_trust_level": recommended_trust_level,
        "reason": " | ".join(reason_parts),
        "source_url": clean(row.get("source_url", "")),
        "paper_title": clean(row.get("paper_title", "")),
        "task": clean(row.get("task", "")),
        "modality": clean(row.get("modality", "")),
        "metric": clean(row.get("metric", "")),
        "direction": clean(row.get("direction", "")),
        "rank": clean(row.get("rank", "")),
        "score": clean(row.get("score", "")),
        "normalized_score": clean(row.get("normalized_score", "")),
        "n_tools_compared": clean(row.get("n_tools_compared", "")),
        "evaluation_protocol": clean(row.get("evaluation_protocol", "")),
        "review_status": clean(row.get("review_status", "")),
        "confidence": clean(row.get("confidence", "")),
        "notes": clean(row.get("notes", "")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate benchmark candidates and generate review actions.")
    parser.add_argument(
        "--input",
        default="data/evidence_candidates/tool_benchmark_candidates.tsv",
        help="Input benchmark candidate TSV.",
    )
    parser.add_argument(
        "--output",
        default="data/evidence_candidates/tool_benchmark_review_actions.tsv",
        help="Output review action TSV.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    rows, _ = read_tsv(input_path)
    out_rows = [build_action_row(row) for row in rows]

    fieldnames = [
        "benchmark_id",
        "benchmark_name",
        "tool_name",
        "review_bucket",
        "action_type",
        "proposed_state",
        "missing_fields",
        "recommended_review_status",
        "recommended_trust_level",
        "reason",
        "source_url",
        "paper_title",
        "task",
        "modality",
        "metric",
        "direction",
        "rank",
        "score",
        "normalized_score",
        "n_tools_compared",
        "evaluation_protocol",
        "review_status",
        "confidence",
        "notes",
    ]

    write_tsv(output_path, fieldnames, out_rows)

    print(f"Input rows: {len(rows)}")
    print(f"Action rows: {len(out_rows)}")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()