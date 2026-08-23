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


DEFAULT_PUBLICATIONS = PROJECT_ROOT / "data" / "tool_publications.tsv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evidence_candidates" / "formal_publication_audit.tsv"

RECOMMENDATION_SCOPES = {"core_tool", "major_version"}
RECOMMENDATION_CATEGORIES = {"architectural_core"}
RECOMMENDATION_TIERS = {"canonical_primary", "canonical_secondary"}
UNCLEAR_REVIEWERS = {"", "human_review", "gpt", "chatgpt", "ai", "llm"}

FIELDNAMES = [
    "publication_id",
    "tool_name",
    "title",
    "doi",
    "pmid",
    "arxiv_id",
    "source_url",
    "paper_url",
    "task",
    "modality",
    "review_status",
    "reviewed_by",
    "extraction_method",
    "canonical_scope",
    "authority_tier",
    "recommendation_eligible",
    "citations",
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
    if is_source_bound(row):
        labels.append("source_bound")
    else:
        labels.append("missing_source_identifier_or_url")
    if has_title_only_claim(row):
        labels.append("title_only_claim_span")
    if not clean(row.get("task")):
        labels.append("missing_task")
    if not clean(row.get("modality")):
        labels.append("missing_modality")
    if clean(row.get("reviewed_by")).lower() in UNCLEAR_REVIEWERS:
        labels.append("reviewer_identity_unclear")
    if clean(row.get("review_status")).lower() not in APPROVED_REVIEW_STATUSES:
        labels.append("unapproved_review_status")
    if not has_recommendation_metadata(row):
        labels.append("non_main_or_incomplete_recommendation_metadata")
    if clean(row.get("extraction_method")).lower() == "crossref_api_candidate_search":
        labels.append("candidate_search_needs_manual_anchor_check")
    if parse_number(row.get("citations")) is not None:
        labels.append("citation_supported")

    allowed = runtime_recommendation_allowed(row, labels)
    return {
        "publication_id": clean(row.get("publication_id")),
        "tool_name": clean(row.get("tool_name")),
        "title": clean(row.get("title")),
        "doi": clean(row.get("doi")),
        "pmid": clean(row.get("pmid")),
        "arxiv_id": clean(row.get("arxiv_id")),
        "source_url": clean(row.get("source_url")),
        "paper_url": clean(row.get("paper_url")),
        "task": clean(row.get("task")),
        "modality": clean(row.get("modality")),
        "review_status": clean(row.get("review_status")),
        "reviewed_by": clean(row.get("reviewed_by")),
        "extraction_method": clean(row.get("extraction_method")),
        "canonical_scope": clean(row.get("canonical_scope")),
        "authority_tier": clean(row.get("authority_tier")),
        "recommendation_eligible": clean(row.get("recommendation_eligible")),
        "citations": clean(row.get("citations")),
        "audit_labels": ";".join(labels),
        "runtime_recommendation_allowed": "true" if allowed else "false",
        "recommended_action": recommended_action(labels),
        "notes": clean(row.get("notes")),
    }


def runtime_recommendation_allowed(row: Dict[str, str], labels: List[str]) -> bool:
    return (
        "source_bound" in labels
        and "title_only_claim_span" not in labels
        and "reviewer_identity_unclear" not in labels
        and "unapproved_review_status" not in labels
        and "non_main_or_incomplete_recommendation_metadata" not in labels
    )


def recommended_action(labels: List[str]) -> str:
    if "unapproved_review_status" in labels:
        return "exclude_from_formal_until_reviewed"
    if "missing_source_identifier_or_url" in labels:
        return "complete_doi_pmid_arxiv_and_url_before_recommendation"
    if "title_only_claim_span" in labels:
        return "add_source_span_or_claim_text_before_recommendation"
    if "reviewer_identity_unclear" in labels:
        return "manual_reviewer_recheck_required"
    if "non_main_or_incomplete_recommendation_metadata" in labels:
        return "keep_retrieval_only_or_complete_canonical_metadata"
    if "candidate_search_needs_manual_anchor_check" in labels:
        return "spot_check_crossref_candidate_mapping"
    return "eligible_after_manual_spot_check"


def is_source_bound(row: Dict[str, str]) -> bool:
    has_identifier = bool(clean(row.get("doi")) or clean(row.get("pmid")) or clean(row.get("arxiv_id")))
    has_url = bool(clean(row.get("source_url")) or clean(row.get("paper_url")))
    return has_identifier and has_url and bool(clean(row.get("title")))


def has_title_only_claim(row: Dict[str, str]) -> bool:
    claim_text = clean(row.get("claim_text"))
    claim_span = clean(row.get("claim_span"))
    title = clean(row.get("title"))
    if claim_text:
        return False
    if not claim_span:
        return True
    return normalize_space(claim_span).lower() == normalize_space(title).lower()


def has_recommendation_metadata(row: Dict[str, str]) -> bool:
    return (
        clean(row.get("recommendation_eligible")).lower() in {"true", "yes", "1"}
        and clean(row.get("canonical_scope")).lower() in RECOMMENDATION_SCOPES
        and clean(row.get("evidence_category")).lower() in RECOMMENDATION_CATEGORIES
        and clean(row.get("authority_tier")).lower() in RECOMMENDATION_TIERS
    )


def clean(value: object) -> str:
    return str(value or "").strip()


def normalize_space(value: str) -> str:
    return " ".join((value or "").split())


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
    parser = argparse.ArgumentParser(description="Audit formal publication evidence quality.")
    parser.add_argument("--publications", type=Path, default=DEFAULT_PUBLICATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json-summary", type=Path, default=None)
    args = parser.parse_args()

    rows, _ = read_tsv(args.publications)
    audited = audit_rows(rows)
    write_tsv(args.output, audited)
    summary = summarize(audited)
    if args.json_summary:
        args.json_summary.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **summary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
