import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REVIEW = PROJECT_ROOT / "data" / "evidence_candidates" / "core50_benchmark_source_human_review.tsv"
DEFAULT_PACKET = PROJECT_ROOT / "data" / "evidence_candidates" / "core50_benchmark_review_packet.tsv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evidence_candidates" / "core50_benchmark_extraction_packet.tsv"

OUTPUT_FIELDS = [
    "tool_name",
    "benchmark_id",
    "source_review_decision",
    "benchmark_name",
    "paper_doi",
    "source_url",
    "extraction_status",
    "benchmark_fact_scope",
    "task",
    "dataset",
    "metric",
    "direction",
    "rank",
    "score",
    "normalized_score",
    "n_tools_compared",
    "comparison_set",
    "evaluation_protocol",
    "reviewer_instruction",
    "formal_ingest_allowed_now",
    "recommendation_use_allowed_now",
    "risk_notes",
]


def load_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})


def build_packet(review_rows: List[Dict[str, str]], packet_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    packet_by_id = {row.get("benchmark_id", ""): row for row in packet_rows}
    rows = []
    for review in review_rows:
        if review.get("extraction_allowed") != "true":
            continue
        source = packet_by_id.get(review.get("benchmark_id", ""), {})
        rows.append(build_row(review, source))
    rows.sort(key=lambda row: (row["tool_name"].lower(), row["benchmark_id"]))
    return rows


def build_row(review: Dict[str, str], source: Dict[str, str]) -> Dict[str, str]:
    tool_name = review.get("tool_name", "")
    if tool_name == "Scanpy":
        fact_scope = "Scanpy-based batch correction algorithm comparison; not a global Scanpy ranking"
        instruction = (
            "Extract exact batch-effect/integration task, datasets, metrics, metric directions, "
            "compared Scanpy-based methods, rank/score values, and protocol from the source. "
            "Do not generalize to overall Scanpy recommendation quality."
        )
    elif tool_name == "scGPT":
        fact_scope = "Geneformer-vs-scGPT comparative interpretability source; not a broad foundation-model benchmark"
        instruction = (
            "Extract exact interpretability/comparative task, dataset or atlas scope, metrics, direction, "
            "comparison set, score/rank values if present, and protocol. Do not generalize to all scGPT tasks."
        )
    else:
        fact_scope = "source-level benchmark extraction"
        instruction = "Extract only source-supported benchmark facts."

    return {
        "tool_name": tool_name,
        "benchmark_id": review.get("benchmark_id", ""),
        "source_review_decision": review.get("source_review_decision", ""),
        "benchmark_name": source.get("benchmark_name", ""),
        "paper_doi": source.get("paper_doi", ""),
        "source_url": source.get("source_url", ""),
        "extraction_status": "needs_human_metric_extraction",
        "benchmark_fact_scope": fact_scope,
        "task": "",
        "dataset": "",
        "metric": "",
        "direction": "",
        "rank": "",
        "score": "",
        "normalized_score": "",
        "n_tools_compared": "",
        "comparison_set": "",
        "evaluation_protocol": "",
        "reviewer_instruction": instruction,
        "formal_ingest_allowed_now": "false",
        "recommendation_use_allowed_now": "false",
        "risk_notes": review.get("reviewer_notes", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the narrow benchmark metric extraction packet from human-reviewed source decisions."
    )
    parser.add_argument("--source-review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = build_packet(load_tsv(args.source_review), load_tsv(args.review_packet))
    write_tsv(args.output, rows)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(rows),
                "tools": dict(Counter(row["tool_name"] for row in rows)),
                "formal_ingest_allowed_now": False,
                "recommendation_use_allowed_now": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
