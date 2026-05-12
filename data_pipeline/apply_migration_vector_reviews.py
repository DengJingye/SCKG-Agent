import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REVIEW_PACKET = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "migration_vector_gap_review_packet_v0_9.tsv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "migration_hypothesis_review_packet.tsv"
)

MIGRATION_REVIEW_FIELDS = [
    "query_id",
    "target_task",
    "target_modality",
    "source_tool",
    "source_task",
    "transferable_mechanism",
    "vector_similarity",
    "graph_jaccard",
    "io_compatibility",
    "compatibility_gaps",
    "risk_level",
    "candidate_decision",
    "reviewer_decision",
    "reviewer_notes",
]

ALLOWED_REVIEW_DECISIONS = {
    "accept_exploratory",
    "revise_mechanism",
    "reject_incompatible",
    "needs_more_evidence",
}


def read_tsv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader), list(reader.fieldnames or [])


def write_tsv(path: Path, rows: List[Dict[str, str]], fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def row_key(row: Dict[str, str]) -> tuple[str, str, str]:
    return (
        (row.get("query_id") or "").strip(),
        (row.get("source_tool") or "").strip().lower(),
        (row.get("target_task") or "").strip().lower(),
    )


def normalize_review_row(row: Dict[str, str]) -> Dict[str, str]:
    return {field: (row.get(field) or "").strip() for field in MIGRATION_REVIEW_FIELDS}


def reviewed_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    reviewed: List[Dict[str, str]] = []
    for row in rows:
        decision = (row.get("reviewer_decision") or "").strip()
        if not decision:
            continue
        if decision not in ALLOWED_REVIEW_DECISIONS:
            raise ValueError(
                f"Unsupported reviewer_decision for {row.get('query_id')}: {decision}"
            )
        normalized = normalize_review_row(row)
        missing = [
            field
            for field in ["query_id", "target_task", "target_modality", "source_tool", "source_task"]
            if not normalized.get(field)
        ]
        if missing:
            raise ValueError(f"{row.get('query_id')} missing required fields: {missing}")
        reviewed.append(normalized)
    return reviewed


def merge_rows(
    existing_rows: List[Dict[str, str]],
    new_rows: List[Dict[str, str]],
) -> tuple[List[Dict[str, str]], Dict[str, int]]:
    merged_by_key = {row_key(row): normalize_review_row(row) for row in existing_rows}
    inserted = 0
    replaced = 0
    for row in new_rows:
        key = row_key(row)
        if key in merged_by_key:
            replaced += 1
        else:
            inserted += 1
        merged_by_key[key] = row
    merged = list(merged_by_key.values())
    merged.sort(key=lambda row: (row.get("source_tool", "").lower(), row.get("target_task", ""), row.get("query_id", "")))
    return merged, {"inserted": inserted, "replaced": replaced, "output_rows": len(merged)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge human-reviewed migration vector decisions into the candidate-layer migration review packet."
    )
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_REVIEW_PACKET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true", help="Write merged output. Default is dry run.")
    args = parser.parse_args()

    candidate_rows, _ = read_tsv(args.review_packet)
    existing_rows, existing_fields = read_tsv(args.output)
    if existing_fields != MIGRATION_REVIEW_FIELDS:
        raise ValueError(f"{args.output} header mismatch: {existing_fields}")

    approved_rows = reviewed_rows(candidate_rows)
    merged_rows, summary = merge_rows(existing_rows, approved_rows)
    summary.update(
        {
            "review_packet": str(args.review_packet),
            "output": str(args.output),
            "reviewed_rows": len(approved_rows),
            "dry_run": not args.apply,
        }
    )

    if args.apply:
        write_tsv(args.output, merged_rows, MIGRATION_REVIEW_FIELDS)
        summary["applied"] = True
    else:
        summary["applied"] = False

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
