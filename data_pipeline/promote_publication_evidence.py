import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evidence_schemas import PUBLICATION_FIELDS


DEFAULT_CANDIDATES = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_tool_publication_candidates_dedup.tsv"
)
DEFAULT_MANUAL_ANCHORS = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_publication_manual_anchors.tsv"
)
DEFAULT_HUMAN_REVIEW = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_publication_human_review.tsv"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "tool_publications.tsv"

FORMALIZE_DECISIONS = {"formalize", "ingest_formal", "promote"}
SUPPORTING_DECISIONS = {"supporting"}
QUARANTINE_DECISIONS = {"quarantine", "reject_noise", "needs_manual_lookup", "no_candidate_found"}
APPROVED_FORMAL_STATUS = "human_reviewed"
TRUSTED_CORE = "trusted_core"
RECOMMENDATION_ELIGIBLE_SCOPES = {"core_tool", "major_version"}
RECOMMENDATION_ELIGIBLE_CATEGORIES = {"architectural_core"}
RECOMMENDATION_ELIGIBLE_AUTHORITY_TIERS = {"canonical_primary", "canonical_secondary"}
BOOLEAN_TRUE = {"true", "yes", "1"}
BOOLEAN_FALSE = {"false", "no", "0"}
CANONICAL_SCOPE_AUTHORITY_TIERS = {
    "core_tool": "canonical_primary",
    "major_version": "canonical_secondary",
    "ecosystem_component": "ecosystem_support",
    "workflow_protocol": "contextual_support",
    "non_canonical": "contextual_support",
    "provenance_only": "provenance_only",
    "manual_anchor_required": "manual_required",
}


def read_tsv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader), list(reader.fieldnames or [])


def read_optional_tsv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        return [], []
    return read_tsv(path)


def merge_candidate_rows(*row_groups: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen = set()
    for rows in row_groups:
        for row in rows:
            publication_id = (row.get("publication_id") or "").strip()
            if not publication_id:
                continue
            if publication_id in seen:
                raise ValueError(f"Duplicate publication_id across candidate inputs: {publication_id}")
            merged.append(row)
            seen.add(publication_id)
    return merged


def write_tsv(path: Path, rows: List[Dict[str, str]], fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def index_by_id(rows: Iterable[Dict[str, str]], id_field: str) -> Dict[str, Dict[str, str]]:
    indexed: Dict[str, Dict[str, str]] = {}
    for row in rows:
        record_id = (row.get(id_field) or "").strip()
        if not record_id:
            continue
        if record_id in indexed:
            raise ValueError(f"Duplicate {id_field}: {record_id}")
        indexed[record_id] = row
    return indexed


def load_existing_formal(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    rows, _ = read_tsv(path)
    return rows


def promote_rows(
    candidate_rows: List[Dict[str, str]],
    review_rows: List[Dict[str, str]],
    existing_rows: List[Dict[str, str]],
    refresh_existing: bool = False,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    candidates_by_id = index_by_id(candidate_rows, "publication_id")
    existing_by_id = {
        row.get("publication_id", ""): row
        for row in existing_rows
        if row.get("publication_id")
    }
    promoted: List[Dict[str, str]] = []
    supporting_count = 0
    quarantine_count = 0
    skipped_existing = 0
    refreshed_existing = 0

    for review in review_rows:
        publication_id = (review.get("publication_id") or "").strip()
        decision = (review.get("decision") or "").strip().lower()
        if decision in SUPPORTING_DECISIONS:
            supporting_count += 1
            continue
        if decision in QUARANTINE_DECISIONS:
            quarantine_count += 1
            continue
        if decision not in FORMALIZE_DECISIONS:
            raise ValueError(f"Unsupported review decision for {publication_id}: {decision}")
        candidate = candidates_by_id.get(publication_id)
        if candidate is None:
            raise ValueError(f"Reviewed publication is missing from candidates: {publication_id}")
        validate_promotable(candidate, review)
        if publication_id in existing_by_id:
            if refresh_existing:
                refreshed = refresh_formal_row(existing_by_id[publication_id], candidate, review)
                if refreshed:
                    refreshed_existing += 1
            else:
                skipped_existing += 1
            continue
        promoted.append(formal_row(candidate, review))

    all_rows = existing_rows + promoted
    all_rows.sort(key=lambda row: (row.get("tool_name", ""), row.get("publication_year", ""), row.get("publication_id", "")))
    summary = {
        "existing_rows": len(existing_rows),
        "promoted_rows": len(promoted),
        "supporting_review_rows": supporting_count,
        "quarantine_review_rows": quarantine_count,
        "skipped_existing": skipped_existing,
        "refreshed_existing": refreshed_existing,
        "output_rows": len(all_rows),
    }
    return all_rows, summary


def refresh_formal_row(
    existing: Dict[str, str],
    candidate: Dict[str, str],
    review: Dict[str, str],
) -> bool:
    refreshed = False
    refreshed_values = {
        "trust_level": TRUSTED_CORE,
        "review_status": APPROVED_FORMAL_STATUS,
        "reviewed_by": review.get("reviewed_by", ""),
        "review_time": review.get("review_time", ""),
        "human_review_decision": formal_decision(review),
        "canonical_scope": review.get("canonical_scope", ""),
        "evidence_category": review.get("evidence_category", ""),
        "recommendation_eligible": normalize_bool_text(review.get("recommendation_eligible", "")),
        "authority_tier": authority_tier(review),
        "audit_support_level": review.get("audit_support_level", ""),
    }
    for field, value in refreshed_values.items():
        if existing.get(field, "") != value:
            existing[field] = value
            refreshed = True
    note = (
        "formal_ingest_from_human_review"
        f"; canonical_scope={review.get('canonical_scope', '')}"
        f"; evidence_category={review.get('evidence_category', '')}"
        f"; authority_tier={authority_tier(review)}"
        f"; audit_support_level={review.get('audit_support_level', '')}"
        f"; human_review_notes={review.get('notes', '')}"
    )
    merged_note = append_note(existing.get("notes", "") or candidate.get("notes", ""), note)
    if existing.get("notes", "") != merged_note:
        existing["notes"] = merged_note
        refreshed = True
    return refreshed


def validate_promotable(candidate: Dict[str, str], review: Dict[str, str]) -> None:
    publication_id = candidate.get("publication_id", "")
    missing = [
        field
        for field in ["tool_name", "title", "doi", "publication_year", "source_url", "authors"]
        if not (candidate.get(field) or "").strip()
    ]
    if missing:
        raise ValueError(f"{publication_id} is missing required formal fields: {','.join(missing)}")
    if (candidate.get("canonical_flag") or "").lower() != "true":
        raise ValueError(f"{publication_id} is not canonical and cannot be formally promoted")
    if candidate.get("duplicate_of"):
        raise ValueError(f"{publication_id} has duplicate_of populated and cannot be formally promoted")
    if not review.get("canonical_scope") or not review.get("evidence_category"):
        raise ValueError(f"{publication_id} is missing Schema V2 governance fields")
    recommendation_eligible = normalize_bool_text(review.get("recommendation_eligible", ""))
    if recommendation_eligible not in {"true", "false"}:
        raise ValueError(f"{publication_id} has invalid recommendation_eligible value")
    expected = expected_recommendation_eligible(review)
    if recommendation_eligible != expected:
        raise ValueError(
            f"{publication_id} violates Strategy A: "
            f"canonical_scope={review.get('canonical_scope', '')}, "
            f"evidence_category={review.get('evidence_category', '')}, "
            f"authority_tier={authority_tier(review)}, "
            f"recommendation_eligible must be {expected}"
        )


def expected_recommendation_eligible(review: Dict[str, str]) -> str:
    scope = (review.get("canonical_scope") or "").strip().lower()
    category = (review.get("evidence_category") or "").strip().lower()
    tier = authority_tier(review)
    if (
        scope in RECOMMENDATION_ELIGIBLE_SCOPES
        and category in RECOMMENDATION_ELIGIBLE_CATEGORIES
        and tier in RECOMMENDATION_ELIGIBLE_AUTHORITY_TIERS
    ):
        return "true"
    return "false"


def authority_tier(review: Dict[str, str]) -> str:
    explicit = (review.get("authority_tier") or "").strip().lower()
    if explicit:
        return explicit
    scope = (review.get("canonical_scope") or "").strip().lower()
    return CANONICAL_SCOPE_AUTHORITY_TIERS.get(scope, "contextual_support")


def formal_decision(review: Dict[str, str]) -> str:
    decision = (review.get("decision") or "").strip().lower()
    if decision in FORMALIZE_DECISIONS:
        return "formalize"
    return decision


def normalize_bool_text(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in BOOLEAN_TRUE:
        return "true"
    if normalized in BOOLEAN_FALSE:
        return "false"
    return normalized


def formal_row(candidate: Dict[str, str], review: Dict[str, str]) -> Dict[str, str]:
    row = {field: candidate.get(field, "") for field in PUBLICATION_FIELDS}
    row.update(
        {
            "trust_level": TRUSTED_CORE,
            "review_status": APPROVED_FORMAL_STATUS,
            "reviewed_by": review.get("reviewed_by", ""),
            "review_time": review.get("review_time", ""),
            "human_review_decision": formal_decision(review),
            "canonical_scope": review.get("canonical_scope", ""),
            "evidence_category": review.get("evidence_category", ""),
            "recommendation_eligible": normalize_bool_text(review.get("recommendation_eligible", "")),
            "authority_tier": authority_tier(review),
            "audit_support_level": review.get("audit_support_level", ""),
            "notes": append_note(
                candidate.get("notes", ""),
                (
                    "formal_ingest_from_human_review"
                    f"; canonical_scope={review.get('canonical_scope', '')}"
                    f"; evidence_category={review.get('evidence_category', '')}"
                    f"; authority_tier={authority_tier(review)}"
                    f"; audit_support_level={review.get('audit_support_level', '')}"
                    f"; human_review_notes={review.get('notes', '')}"
                ),
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote human-reviewed publication candidates into the formal publication table."
    )
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument(
        "--manual-anchors",
        type=Path,
        default=DEFAULT_MANUAL_ANCHORS,
        help="Candidate-only manual canonical anchor seed TSV.",
    )
    parser.add_argument("--human-review", type=Path, default=DEFAULT_HUMAN_REVIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Refresh human-review governance fields for already promoted publication IDs.",
    )
    args = parser.parse_args()

    candidate_rows, _ = read_tsv(args.candidates)
    manual_anchor_rows, _ = read_optional_tsv(args.manual_anchors)
    candidate_rows = merge_candidate_rows(candidate_rows, manual_anchor_rows)
    review_rows, _ = read_tsv(args.human_review)
    existing_rows = load_existing_formal(args.output)
    rows, summary = promote_rows(
        candidate_rows,
        review_rows,
        existing_rows,
        refresh_existing=args.refresh_existing,
    )
    if not args.dry_run:
        write_tsv(args.output, rows, PUBLICATION_FIELDS)
    print(json.dumps({"output": str(args.output), "dry_run": args.dry_run, **summary}, indent=2))


if __name__ == "__main__":
    main()
