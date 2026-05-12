import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evidence_schemas import BENCHMARK_FIELDS


DEFAULT_HUMAN_REVIEW = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_benchmark_human_review.tsv"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"

FORMALIZE_DECISIONS = {"formalize", "ingest_formal", "promote"}
QUARANTINE_DECISIONS = {"quarantine", "reject_noise", "hold_candidate", "no_candidate_found"}
APPROVED_FORMAL_STATUS = "human_reviewed"
TRUSTED_CORE = "trusted_core"
BOOLEAN_TRUE = {"true", "yes", "1"}

REQUIRED_SOURCE_FIELDS = ["benchmark_id", "tool_name", "benchmark_name", "source_url"]
REQUIRED_CONTEXT_FIELDS = ["task", "dataset", "metric", "direction", "evaluation_protocol"]
RESULT_FIELDS = ["rank", "score", "normalized_score", "result_text"]
COMPARISON_FIELDS = ["n_tools_compared", "rank_scope"]


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


def load_existing_formal(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    rows, _ = read_tsv(path)
    return rows


def promote_rows(
    review_rows: List[Dict[str, str]],
    existing_rows: List[Dict[str, str]],
    refresh_existing: bool = False,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    existing_by_id = {
        row.get("benchmark_id", ""): row
        for row in existing_rows
        if row.get("benchmark_id")
    }
    promoted: List[Dict[str, str]] = []
    quarantine_count = 0
    skipped_existing = 0
    refreshed_existing = 0

    for review in review_rows:
        benchmark_id = (review.get("benchmark_id") or "").strip()
        decision = (review.get("decision") or "").strip().lower()
        if decision in QUARANTINE_DECISIONS:
            quarantine_count += 1
            continue
        if decision not in FORMALIZE_DECISIONS:
            raise ValueError(f"Unsupported benchmark review decision for {benchmark_id}: {decision}")
        validate_promotable(review)
        if benchmark_id in existing_by_id:
            if refresh_existing:
                refreshed = refresh_formal_row(existing_by_id[benchmark_id], review)
                if refreshed:
                    refreshed_existing += 1
            else:
                skipped_existing += 1
            continue
        promoted.append(formal_row(review))

    all_rows = existing_rows + promoted
    all_rows.sort(key=lambda row: (row.get("tool_name", ""), row.get("benchmark_id", "")))
    summary = {
        "existing_rows": len(existing_rows),
        "promoted_rows": len(promoted),
        "quarantine_review_rows": quarantine_count,
        "skipped_existing": skipped_existing,
        "refreshed_existing": refreshed_existing,
        "output_rows": len(all_rows),
    }
    return all_rows, summary


def validate_promotable(review: Dict[str, str]) -> None:
    benchmark_id = review.get("benchmark_id", "")
    missing = [
        field
        for field in REQUIRED_SOURCE_FIELDS + REQUIRED_CONTEXT_FIELDS
        if not (review.get(field) or "").strip()
    ]
    if missing:
        raise ValueError(f"{benchmark_id} is missing required formal fields: {','.join(missing)}")
    if not any((review.get(field) or "").strip() for field in RESULT_FIELDS):
        raise ValueError(f"{benchmark_id} is missing result evidence: rank, score, normalized_score, or result_text")
    if not any((review.get(field) or "").strip() for field in COMPARISON_FIELDS):
        raise ValueError(f"{benchmark_id} is missing comparison context: n_tools_compared or rank_scope")
    if normalize_bool(review.get("recommendation_use_allowed_now", "")) != "true":
        raise ValueError(f"{benchmark_id} is not marked recommendation_use_allowed_now=true")
    if (review.get("review_status") or "").strip().lower() != APPROVED_FORMAL_STATUS:
        raise ValueError(f"{benchmark_id} is not human_reviewed")
    if (review.get("trust_level") or "").strip().lower() != TRUSTED_CORE:
        raise ValueError(f"{benchmark_id} is not trusted_core")


def refresh_formal_row(existing: Dict[str, str], review: Dict[str, str]) -> bool:
    refreshed = False
    row = formal_row(review)
    for field in BENCHMARK_FIELDS:
        if existing.get(field, "") != row.get(field, ""):
            existing[field] = row.get(field, "")
            refreshed = True
    return refreshed


def formal_row(review: Dict[str, str]) -> Dict[str, str]:
    row = {field: review.get(field, "") for field in BENCHMARK_FIELDS}
    row.update(
        {
            "canonical_flag": review.get("canonical_flag", "") or "true",
            "record_type": review.get("record_type", "") or "benchmark",
            "source_record_id": review.get("source_record_id", "") or review.get("paper_doi", ""),
            "trust_level": TRUSTED_CORE,
            "review_status": APPROVED_FORMAL_STATUS,
            "reviewed_by": review.get("reviewed_by", ""),
            "review_time": review.get("review_time", ""),
            "source_type": review.get("source_type", "") or "paper",
            "confidence": review.get("confidence", "") or "0.90",
            "extraction_method": review.get("extraction_method", "") or "human_benchmark_review",
            "kg_version": review.get("kg_version", "") or "v0.1",
            "notes": append_note(
                review.get("notes", ""),
                "formal_benchmark_ingest_from_human_review; qualitative_result_allowed"
                if not any((review.get(field) or "").strip() for field in ["rank", "score", "normalized_score"])
                else "formal_benchmark_ingest_from_human_review",
            ),
        }
    )
    return row


def append_note(existing: str, note: str) -> str:
    existing = (existing or "").strip()
    note = (note or "").strip()
    if not existing:
        return note
    if not note or note in existing:
        return existing
    return f"{existing}; {note}"


def normalize_bool(value: str) -> str:
    normalized = (value or "").strip().lower()
    return "true" if normalized in BOOLEAN_TRUE else "false"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote human-reviewed benchmark facts into the formal benchmark table."
    )
    parser.add_argument("--human-review", type=Path, default=DEFAULT_HUMAN_REVIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Refresh already promoted benchmark IDs from the human-review table.",
    )
    args = parser.parse_args()

    review_rows, _ = read_tsv(args.human_review)
    existing_rows = load_existing_formal(args.output)
    rows, summary = promote_rows(
        review_rows,
        existing_rows,
        refresh_existing=args.refresh_existing,
    )
    if not args.dry_run:
        write_tsv(args.output, rows, BENCHMARK_FIELDS)
    print(json.dumps({"output": str(args.output), "dry_run": args.dry_run, **summary}, indent=2))


if __name__ == "__main__":
    main()
