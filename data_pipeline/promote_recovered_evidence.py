from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evidence_schemas import BENCHMARK_FIELDS, PUBLICATION_FIELDS


DEFAULT_REVIEW_PACKET = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1.tsv"
)
DEFAULT_PUBLICATIONS = PROJECT_ROOT / "data" / "tool_publications.tsv"
DEFAULT_BENCHMARKS = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
DEFAULT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_recovery_promotion_summary.json"
)

PROMOTE_DECISIONS = {"promote", "formalize", "restore_recommendation"}
NON_PROMOTE_DECISIONS = {"needs_manual_review", "keep_retrieval_only", "reject", "quarantine", ""}
GENERIC_REVIEWERS = {"", "human_review", "gpt", "chatgpt", "ai", "llm"}
AI_REVIEWER_MARKERS = {
    "ai_assisted",
    "ai_review",
    "openai",
    "deepseek",
    "chatgpt",
    "gpt",
    "llm",
    "model_review",
    "auto_review",
}
RECOMMENDATION_SCOPES = {"core_tool", "major_version"}
RECOMMENDATION_TIERS = {"canonical_primary", "canonical_secondary"}


def read_tsv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader), list(reader.fieldnames or [])


def write_tsv(path: Path, rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def promote_recovered(
    review_rows: Sequence[Dict[str, str]],
    publication_rows: List[Dict[str, str]],
    benchmark_rows: List[Dict[str, str]],
) -> Dict[str, object]:
    publications_by_id = index_by_id(publication_rows, "publication_id")
    benchmarks_by_id = index_by_id(benchmark_rows, "benchmark_id")
    summary = {
        "review_rows": len(review_rows),
        "publication_promoted": 0,
        "benchmark_promoted": 0,
        "non_promote_rows": 0,
        "validation_errors": [],
    }
    for review in review_rows:
        decision = clean(review.get("decision")).lower()
        if decision in NON_PROMOTE_DECISIONS:
            summary["non_promote_rows"] += 1
            continue
        if decision not in PROMOTE_DECISIONS:
            summary["validation_errors"].append(
                f"{review.get('record_id', '')}: unsupported decision={decision}"
            )
            continue
        try:
            if clean(review.get("evidence_kind")) == "publication":
                update_publication(publications_by_id, review)
                summary["publication_promoted"] += 1
            elif clean(review.get("evidence_kind")) == "benchmark":
                update_benchmark(benchmarks_by_id, review)
                summary["benchmark_promoted"] += 1
            else:
                raise ValueError("unknown evidence_kind")
        except ValueError as exc:
            summary["validation_errors"].append(f"{review.get('record_id', '')}: {exc}")
    return summary


def update_publication(rows_by_id: Dict[str, Dict[str, str]], review: Dict[str, str]) -> None:
    record_id = clean(review.get("record_id"))
    row = rows_by_id.get(record_id)
    if row is None:
        raise ValueError("publication row not found in formal TSV")
    ensure_ready(review)
    source_span = clean(review.get("source_span"))
    claim_text = clean(review.get("claim_text"))
    if not source_span or not claim_text:
        raise ValueError("publication promotion requires source_span and claim_text")
    if normalize_space(source_span).lower() == normalize_space(row.get("title", "")).lower():
        raise ValueError("publication source_span cannot be title-only")
    if reviewer_unclear(review):
        raise ValueError("reviewed_by must be a traceable reviewer id")
    task = clean(review.get("verified_task"))
    modality = clean(review.get("verified_modality"))
    if not task or not modality:
        raise ValueError("publication promotion requires verified_task and verified_modality")
    recommendation_eligible = normalize_bool(review.get("recommendation_eligible"))
    canonical_scope = clean(review.get("canonical_scope"))
    authority_tier = clean(review.get("authority_tier"))
    if recommendation_eligible == "true" and (
        canonical_scope not in RECOMMENDATION_SCOPES or authority_tier not in RECOMMENDATION_TIERS
    ):
        raise ValueError("recommendation_eligible=true requires canonical scope and authority tier")
    row.update(
        {
            "claim_span": source_span,
            "claim_text": claim_text,
            "task": task,
            "modality": modality,
            "reviewed_by": clean(review.get("reviewed_by")),
            "review_time": clean(review.get("review_time")),
            "review_status": "human_reviewed",
            "trust_level": "trusted_core",
            "canonical_scope": canonical_scope,
            "authority_tier": authority_tier,
            "recommendation_eligible": recommendation_eligible,
            "evidence_category": row.get("evidence_category") or "architectural_core",
            "audit_support_level": "source_span_verified",
            "human_review_decision": "formalize",
            "notes": append_note(
                row.get("notes", ""),
                recovery_note(review, "publication_recovered_from_source_span"),
            ),
        }
    )


def update_benchmark(rows_by_id: Dict[str, Dict[str, str]], review: Dict[str, str]) -> None:
    record_id = clean(review.get("record_id"))
    row = rows_by_id.get(record_id)
    if row is None:
        raise ValueError("benchmark row not found in formal TSV")
    ensure_ready(review)
    if reviewer_unclear(review):
        raise ValueError("reviewed_by must be a traceable reviewer id")
    source_span = clean(review.get("source_span"))
    metric = clean(review.get("metric"))
    if not source_span or not metric:
        raise ValueError("benchmark promotion requires source_span and metric")
    if not any(clean(review.get(field)) for field in ("rank", "score", "normalized_score")):
        raise ValueError("benchmark promotion requires rank, score, or normalized_score")
    if not (clean(review.get("rank_scope")) or clean(review.get("n_tools_compared"))):
        raise ValueError("benchmark promotion requires rank_scope or n_tools_compared")
    if clean(review.get("caveat_type")).lower() in {"caveat", "negative_control", "negative-control"}:
        raise ValueError("caveat/negative-control benchmark cannot be promoted as main evidence")
    task = clean(review.get("verified_task"))
    modality = clean(review.get("verified_modality"))
    if not task or not modality:
        raise ValueError("benchmark promotion requires verified_task and verified_modality")
    row.update(
        {
            "metric": metric,
            "rank": clean(review.get("rank")),
            "score": clean(review.get("score")),
            "normalized_score": clean(review.get("normalized_score")),
            "rank_scope": clean(review.get("rank_scope")),
            "n_tools_compared": clean(review.get("n_tools_compared")),
            "claim_span": source_span,
            "result_text": clean(review.get("claim_text")) or row.get("result_text", ""),
            "task": task,
            "modality": modality,
            "reviewed_by": clean(review.get("reviewed_by")),
            "review_time": clean(review.get("review_time")),
            "review_status": "human_reviewed",
            "trust_level": "trusted_core",
            "confidence": row.get("confidence") or "0.90",
            "extraction_method": "recovered_numeric_benchmark_review",
            "notes": append_note(
                row.get("notes", ""),
                recovery_note(review, "benchmark_recovered_from_numeric_source_span"),
            ),
        }
    )


def ensure_ready(review: Dict[str, str]) -> None:
    if normalize_bool(review.get("promotion_ready")) != "true":
        raise ValueError("promotion_ready must be true")


def reviewer_unclear(review: Dict[str, str]) -> bool:
    reviewer = clean(review.get("reviewed_by")).lower()
    if reviewer in GENERIC_REVIEWERS:
        return True
    return any(marker in reviewer for marker in AI_REVIEWER_MARKERS)


def recovery_note(review: Dict[str, str], tag: str) -> str:
    parts = [
        tag,
        f"reviewed_by={clean(review.get('reviewed_by'))}",
        f"source_section={clean(review.get('source_section'))}",
        f"source_figure_or_table={clean(review.get('source_figure_or_table'))}",
        f"reviewer_notes={clean(review.get('reviewer_notes'))}",
    ]
    return "; ".join(part for part in parts if part and not part.endswith("="))


def index_by_id(rows: Sequence[Dict[str, str]], id_field: str) -> Dict[str, Dict[str, str]]:
    return {row.get(id_field, ""): row for row in rows if row.get(id_field)}


def append_note(existing: str, note: str) -> str:
    existing = clean(existing)
    note = clean(note)
    if not existing:
        return note
    if not note or note in existing:
        return existing
    return f"{existing}; {note}"


def normalize_bool(value: object) -> str:
    return "true" if clean(value).lower() in {"true", "yes", "1"} else "false"


def normalize_space(value: object) -> str:
    return " ".join(str(value or "").split())


def clean(value: object) -> str:
    return str(value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote reviewed Evidence Recovery v1 rows.")
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_REVIEW_PACKET)
    parser.add_argument("--publications", type=Path, default=DEFAULT_PUBLICATIONS)
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--apply", action="store_true", help="Write updated formal TSVs.")
    args = parser.parse_args()

    review_rows, _ = read_tsv(args.review_packet)
    publication_rows, _ = read_tsv(args.publications)
    benchmark_rows, _ = read_tsv(args.benchmarks)
    summary = promote_recovered(review_rows, publication_rows, benchmark_rows)
    if args.apply and not summary["validation_errors"]:
        write_tsv(args.publications, publication_rows, PUBLICATION_FIELDS)
        write_tsv(args.benchmarks, benchmark_rows, BENCHMARK_FIELDS)
    summary = {
        "apply": args.apply,
        "publications": str(args.publications),
        "benchmarks": str(args.benchmarks),
        **summary,
    }
    args.summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["validation_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
