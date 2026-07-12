from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_source_manifest_v1.tsv"
)
DEFAULT_DOWNLOAD_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_download_full_summary.json"
)
DEFAULT_OUTPUT_TSV = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "pdf_manual_download_checklist.tsv"
)
DEFAULT_OUTPUT_MD = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "pdf_manual_download_checklist.md"
)


def read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_checklist(
    manifest_rows: List[Dict[str, str]],
    summary: Dict[str, Any],
) -> List[Dict[str, str]]:
    summary_by_record = {
        row.get("record_id", ""): row
        for row in summary.get("rows", [])
        if isinstance(row, dict)
    }
    rows: List[Dict[str, str]] = []
    for row in manifest_rows:
        result = summary_by_record.get(row.get("record_id", ""), {})
        target_pdf = result.get("target_pdf") or suggested_pdf_path(row)
        target_exists = (PROJECT_ROOT / target_pdf).exists()
        status = result.get("status", "not_checked")
        candidate_urls = result.get("candidate_urls") or []
        primary_candidates = [
            item.get("url", "")
            for item in candidate_urls
            if item.get("candidate_kind", "primary_article") == "primary_article"
        ]
        action = classify_action(status=status, target_exists=target_exists, primary_candidates=primary_candidates)
        rows.append(
            {
                "action": action,
                "status": status,
                "target_exists": str(target_exists).lower(),
                "tool_name": row.get("tool_name", ""),
                "evidence_kind": row.get("evidence_kind", ""),
                "source_title": row.get("source_title", ""),
                "doi_or_pmid": row.get("doi_or_pmid", ""),
                "source_url": row.get("source_url", ""),
                "suggested_pdf_path": target_pdf,
                "selected_pdf_url": result.get("selected_pdf_url", ""),
                "primary_candidate_urls": " | ".join(primary_candidates),
                "record_id": row.get("record_id", ""),
                "notes": action_notes(action),
            }
        )
    rows.sort(key=lambda item: (action_priority(item["action"]), item["tool_name"], item["source_title"]))
    return rows


def classify_action(*, status: str, target_exists: bool, primary_candidates: List[str]) -> str:
    if target_exists and status in {"downloaded", "skipped_existing"}:
        return "already_downloaded"
    if status == "download_failed" and primary_candidates:
        return "manual_download_or_browser_login"
    if status == "not_found":
        return "manual_search_required"
    if target_exists:
        return "local_file_present_check_before_ingest"
    return "not_checked"


def action_priority(action: str) -> int:
    order = {
        "manual_search_required": 0,
        "manual_download_or_browser_login": 1,
        "not_checked": 2,
        "local_file_present_check_before_ingest": 3,
        "already_downloaded": 4,
    }
    return order.get(action, 99)


def action_notes(action: str) -> str:
    if action == "already_downloaded":
        return "PDF already exists locally; next step is PDF text ingestion."
    if action == "manual_download_or_browser_login":
        return "A primary PDF URL was discovered, but scripted download failed; open source_url or selected_pdf_url in browser and save as suggested_pdf_path."
    if action == "manual_search_required":
        return "No primary PDF URL was exposed by Crossref/DOI landing page; search by title/DOI or use institutional access if legal."
    if action == "local_file_present_check_before_ingest":
        return "A local file exists, but summary status is not a clean downloaded/skipped state; verify before ingestion."
    return "Run download_evidence_pdfs.py first."


def suggested_pdf_path(row: Dict[str, str]) -> str:
    from data_pipeline.download_evidence_pdfs import suggested_pdf_filename

    return f"data/evidence_sources/pdfs/{suggested_pdf_filename(row)}"


def write_tsv(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "action",
        "status",
        "target_exists",
        "tool_name",
        "evidence_kind",
        "source_title",
        "doi_or_pmid",
        "source_url",
        "suggested_pdf_path",
        "selected_pdf_url",
        "primary_candidate_urls",
        "record_id",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buckets: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        buckets.setdefault(row["action"], []).append(row)
    lines = [
        "# scKG PDF Manual Download Checklist",
        "",
        "This checklist is generated from evidence_source_manifest_v1.tsv and evidence_pdf_download_full_summary.json.",
        "",
    ]
    for action in [
        "manual_search_required",
        "manual_download_or_browser_login",
        "not_checked",
        "local_file_present_check_before_ingest",
        "already_downloaded",
    ]:
        items = buckets.get(action, [])
        if not items:
            continue
        lines.extend([f"## {action} ({len(items)})", ""])
        for item in items:
            lines.extend(
                [
                    f"- {item['tool_name']} / {item['evidence_kind']}: {item['source_title']}",
                    f"  - DOI/source: {item['source_url']}",
                    f"  - Save as: `{item['suggested_pdf_path']}`",
                    f"  - Status: {item['status']}",
                    f"  - Notes: {item['notes']}",
                    "",
                ]
            )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a human PDF download checklist from downloader results.")
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--download-summary", type=Path, default=DEFAULT_DOWNLOAD_SUMMARY)
    parser.add_argument("--output-tsv", type=Path, default=DEFAULT_OUTPUT_TSV)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    args = parser.parse_args()
    rows = build_checklist(read_tsv(args.source_manifest), read_json(args.download_summary))
    write_tsv(rows, args.output_tsv)
    write_markdown(rows, args.output_md)
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    print(json.dumps({"rows": len(rows), "counts": counts}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
