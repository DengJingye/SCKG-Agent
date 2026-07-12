from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_pipeline.download_evidence_pdfs import suggested_pdf_filename


DEFAULT_SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_source_manifest_full.tsv"
)
DEFAULT_MANUAL_CHECKLIST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "pdf_manual_download_checklist.tsv"
)
DEFAULT_BAD_CANDIDATE_OVERRIDES = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "pdf_bad_candidate_overrides.tsv"
)
DEFAULT_OUTPUT_TSV = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core_literature_source_coverage.tsv"
)
DEFAULT_ALIAS_OUTPUT_TSV = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "literature_source_coverage.tsv"
)
DEFAULT_OUTPUT_JSON = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core_literature_source_coverage_summary.json"
)
DEFAULT_OUTPUT_MD = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core_literature_manual_download_queue.md"
)
MIN_SOURCE_TEXT_CHARS = 1000
OUTPUT_FIELDS = [
    "priority",
    "coverage_status",
    "action",
    "tool_name",
    "evidence_kind",
    "record_id",
    "source_title",
    "doi_or_pmid",
    "source_url",
    "fetch_status",
    "pdf_status",
    "text_chars",
    "local_text_path",
    "pdf_path",
    "suggested_pdf_path",
    "selected_pdf_url",
    "primary_candidate_urls",
    "candidate_issue",
    "dashboard_status",
    "notes",
]


def read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows([{field: one_line(row.get(field, "")) for field in OUTPUT_FIELDS} for row in rows])


def build_coverage_rows(
    manifest_rows: Sequence[Dict[str, str]],
    checklist_rows: Sequence[Dict[str, str]],
    bad_candidate_rows: Sequence[Dict[str, str]] = (),
) -> List[Dict[str, Any]]:
    checklist_by_record = {row.get("record_id", ""): row for row in checklist_rows if row.get("record_id")}
    bad_by_record = {row.get("record_id", ""): row for row in bad_candidate_rows if row.get("record_id")}
    rows: List[Dict[str, Any]] = []
    for row in manifest_rows:
        checklist = checklist_by_record.get(row.get("record_id", ""), {})
        bad_candidate = bad_by_record.get(row.get("record_id", ""), {})
        local_text_path = resolve_path(row.get("local_text_path", ""))
        text_chars = file_chars(local_text_path)
        text_available = text_chars >= MIN_SOURCE_TEXT_CHARS
        action = checklist.get("action") or default_action(row, text_available)
        if row.get("pdf_status") == "extract_error" and not text_available:
            action = "pdf_extraction_failed_use_alternate_text_or_repair"
        if bad_candidate and not text_available:
            action = bad_candidate.get("recommended_action") or "resolve_wrong_doi_or_replace_source"
        coverage_status = coverage_status_for_text(text_chars)
        selected_pdf_url = checklist.get("selected_pdf_url", "")
        primary_candidate_urls = checklist.get("primary_candidate_urls", "")
        candidate_issue = bad_candidate.get("issue", "")
        suggested_path = checklist.get("suggested_pdf_path") or suggested_pdf_path(row)
        if bad_candidate:
            selected_pdf_url = ""
            primary_candidate_urls = ""
            suggested_path = ""
        dashboard_status = dashboard_status_for_action(action, text_available)
        notes = bad_candidate.get("notes") or checklist.get("notes") or row.get("notes", "")
        if action == "pdf_extraction_failed_use_alternate_text_or_repair":
            notes = row.get("notes", "") or notes
        rows.append(
            {
                "priority": action_priority(action),
                "coverage_status": coverage_status,
                "action": action if not text_available else "already_ingested",
                "tool_name": row.get("tool_name", ""),
                "evidence_kind": row.get("evidence_kind", ""),
                "record_id": row.get("record_id", ""),
                "source_title": row.get("source_title", ""),
                "doi_or_pmid": row.get("doi_or_pmid", ""),
                "source_url": row.get("source_url", ""),
                "fetch_status": row.get("fetch_status", ""),
                "pdf_status": row.get("pdf_status", ""),
                "text_chars": text_chars,
                "local_text_path": row.get("local_text_path", ""),
                "pdf_path": row.get("pdf_path", ""),
                "suggested_pdf_path": suggested_path,
                "selected_pdf_url": selected_pdf_url,
                "primary_candidate_urls": primary_candidate_urls,
                "candidate_issue": candidate_issue,
                "dashboard_status": dashboard_status,
                "notes": notes,
            }
        )
    rows.sort(key=lambda item: (int(item["priority"]), item["tool_name"], item["evidence_kind"], item["source_title"]))
    return rows


def build_summary(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    action_counts = Counter(row["action"] for row in rows)
    status_counts = Counter(row["coverage_status"] for row in rows)
    per_tool: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "source_text_available": 0, "source_text_too_short": 0, "missing": 0}
    )
    for row in rows:
        tool = row.get("tool_name", "")
        per_tool[tool]["total"] += 1
        if row.get("coverage_status") == "source_text_available":
            per_tool[tool]["source_text_available"] += 1
        elif row.get("coverage_status") == "source_text_too_short":
            per_tool[tool]["source_text_too_short"] += 1
            per_tool[tool]["missing"] += 1
        else:
            per_tool[tool]["missing"] += 1
    return {
        "rows": len(rows),
        "source_text_available": status_counts.get("source_text_available", 0),
        "source_text_too_short": status_counts.get("source_text_too_short", 0),
        "missing_source_text": status_counts.get("missing_source_text", 0),
        "action_counts": dict(action_counts),
        "coverage_status_counts": dict(status_counts),
        "per_tool": dict(sorted(per_tool.items())),
        "manual_queue_rows": sum(
            1 for row in rows
            if row.get("coverage_status") != "source_text_available"
        ),
        "min_source_text_chars": MIN_SOURCE_TEXT_CHARS,
        "guardrail": (
            "Literature source coverage is retrieval-only until review packet validation. "
            "PDF text cannot promote formal TSV evidence automatically."
        ),
    }


def write_markdown(rows: Sequence[Dict[str, Any]], summary: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# scKG Core Literature Resolution Queue",
        "",
        "This queue lists unresolved paper/protocol/benchmark source rows.",
        "",
        "Current unresolved rows are not automatically PDF download tasks. Check the action field:",
        "",
        "- `resolve_wrong_doi_or_replace_source`: do not download; fix the wrong DOI/source or replace the benchmark source.",
        "- `pdf_extraction_failed_use_alternate_text_or_repair`: PDF already exists; repair extraction, use HTML/full text, or replace with an extractable PDF.",
        "- `manual_search_required` / `manual_download_or_browser_login`: only these actions are download/search tasks.",
        "",
        f"- source rows: {summary['rows']}",
        f"- source text available: {summary['source_text_available']}",
        f"- source text too short: {summary['source_text_too_short']}",
        f"- missing source text: {summary['missing_source_text']}",
        f"- min source text chars: {summary['min_source_text_chars']}",
        "",
        "Guardrail: source text is evidence discovery input only. It does not promote formal TSV evidence.",
        "",
    ]
    for action in (
        "resolve_wrong_doi_or_replace_source",
        "pdf_extraction_failed_use_alternate_text_or_repair",
        "manual_search_required",
        "manual_download_or_browser_login",
        "not_checked",
    ):
        items = [
            row for row in rows
            if row.get("coverage_status") != "source_text_available" and row.get("action") == action
        ]
        if not items:
            continue
        lines.extend([f"## {action} ({len(items)})", ""])
        for item in items:
            if action == "resolve_wrong_doi_or_replace_source":
                action_lines = [
                    "  - Do not save/download the listed bad candidate PDF.",
                    "  - Next step: correct the DOI/source record or replace this benchmark source.",
                ]
            elif action == "pdf_extraction_failed_use_alternate_text_or_repair":
                action_lines = [
                    f"  - Existing PDF: `{item.get('pdf_path') or '(none)'}`",
                    "  - Next step: repair/extract with another parser, use publisher HTML/full text, or replace with an extractable PDF.",
                ]
            else:
                action_lines = [f"  - Save as: `{item['suggested_pdf_path']}`"]
            lines.extend(
                [
                    f"- {item['tool_name']} / {item['evidence_kind']}: {item['source_title']}",
                    f"  - DOI/source: {item['source_url']}",
                    *action_lines,
                    f"  - Current text chars: {item.get('text_chars', 0)}",
                    f"  - Candidate issue: {item.get('candidate_issue') or '(none)'}",
                    f"  - Selected PDF URL: {item['selected_pdf_url'] or '(none)'}",
                    f"  - Candidate URLs: {item['primary_candidate_urls'] or '(none)'}",
                    f"  - Notes: {item['notes']}",
                    "",
                ]
            )
    path.write_text("\n".join(lines), encoding="utf-8")


def default_action(row: Dict[str, str], text_available: bool) -> str:
    if text_available:
        return "already_ingested"
    if row.get("pdf_status") == "missing_pdf":
        return "manual_search_required"
    return "not_checked"


def dashboard_status_for_action(action: str, text_available: bool) -> str:
    if text_available:
        return "source_text_available"
    if action == "resolve_wrong_doi_or_replace_source":
        return "source_metadata_mismatch"
    if action == "pdf_extraction_failed_use_alternate_text_or_repair":
        return "pdf_exists_but_extract_failed"
    if action in {"manual_search_required", "manual_download_or_browser_login"}:
        return "download_needed"
    return "not_download_task"


def coverage_status_for_text(text_chars: int) -> str:
    if text_chars >= MIN_SOURCE_TEXT_CHARS:
        return "source_text_available"
    if text_chars > 0:
        return "source_text_too_short"
    return "missing_source_text"


def file_chars(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8", errors="ignore"))


def action_priority(action: str) -> int:
    order = {
        "resolve_wrong_doi_or_replace_source": 0,
        "pdf_extraction_failed_use_alternate_text_or_repair": 1,
        "manual_search_required": 2,
        "manual_download_or_browser_login": 3,
        "not_checked": 4,
        "already_ingested": 9,
        "already_downloaded": 9,
    }
    return order.get(action, 8)


def suggested_pdf_path(row: Dict[str, str]) -> str:
    return f"data/evidence_sources/pdfs/{suggested_pdf_filename(row)}"


def resolve_path(value: str) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def one_line(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def main() -> None:
    parser = argparse.ArgumentParser(description="Build paper/protocol/benchmark source coverage artifacts.")
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--manual-checklist", type=Path, default=DEFAULT_MANUAL_CHECKLIST)
    parser.add_argument("--bad-candidate-overrides", type=Path, default=DEFAULT_BAD_CANDIDATE_OVERRIDES)
    parser.add_argument("--output-tsv", type=Path, default=DEFAULT_OUTPUT_TSV)
    parser.add_argument("--alias-output-tsv", type=Path, default=DEFAULT_ALIAS_OUTPUT_TSV)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    args = parser.parse_args()

    rows = build_coverage_rows(
        read_tsv(args.source_manifest),
        read_tsv(args.manual_checklist),
        read_tsv(args.bad_candidate_overrides),
    )
    summary = build_summary(rows)
    summary.update(
        {
            "source_manifest": rel(args.source_manifest),
            "manual_checklist": rel(args.manual_checklist),
            "bad_candidate_overrides": rel(args.bad_candidate_overrides),
            "output_tsv": rel(args.output_tsv),
            "alias_output_tsv": rel(args.alias_output_tsv),
            "output_md": rel(args.output_md),
        }
    )
    write_tsv(args.output_tsv, rows)
    if args.alias_output_tsv != args.output_tsv:
        write_tsv(args.alias_output_tsv, rows)
    write_markdown(rows, summary, args.output_md)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
