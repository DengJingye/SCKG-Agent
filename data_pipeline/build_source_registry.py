from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_source_manifest_full.tsv"
)
DEFAULT_BAD_CANDIDATE_OVERRIDES = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "pdf_bad_candidate_overrides.tsv"
)
DEFAULT_DOWNLOAD_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_download_full_summary.json"
)
DEFAULT_INGEST_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_ingest_full_summary.json"
)
DEFAULT_SOURCE_REGISTRY = PROJECT_ROOT / "data" / "evidence_candidates" / "source_registry.tsv"
DEFAULT_PDF_CANDIDATE_REGISTRY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "pdf_candidate_registry.tsv"
)
DEFAULT_SOURCE_VALIDATION_REPORT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "source_validation_report.tsv"
)
DEFAULT_ACQUISITION_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "source_acquisition_summary.json"
)
DEFAULT_EXTRACTION_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "source_extraction_summary.json"
)
MIN_SOURCE_TEXT_CHARS = 1000

SOURCE_REGISTRY_FIELDS = [
    "source_id",
    "source_key",
    "canonical_title",
    "doi",
    "source_url",
    "source_type",
    "source_status",
    "local_pdf_path",
    "local_text_path",
    "recommended_pdf_path",
    "validation_status",
    "validation_issue",
    "referring_record_ids",
    "referring_tool_names",
    "evidence_kinds",
    "source_row_count",
    "text_chars",
    "notes",
]

PDF_CANDIDATE_FIELDS = [
    "source_id",
    "record_id",
    "tool_name",
    "expected_title",
    "doi",
    "source_url",
    "candidate_url",
    "candidate_source",
    "candidate_kind",
    "candidate_title",
    "title_similarity",
    "discovery_status",
    "validation_status",
    "validation_issue",
    "quarantine",
    "target_pdf",
]

VALIDATION_REPORT_FIELDS = [
    "source_id",
    "source_status",
    "validation_status",
    "validation_issue",
    "recommended_action",
    "canonical_title",
    "doi",
    "source_url",
    "referring_record_ids",
    "referring_tool_names",
    "local_pdf_path",
    "local_text_path",
]


def read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[Dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows([{field: one_line(row.get(field, "")) for field in fields} for row in rows])


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def build_source_registry(
    manifest_rows: Sequence[Dict[str, str]],
    bad_candidate_rows: Sequence[Dict[str, str]] = (),
) -> List[Dict[str, Any]]:
    bad_by_record = {row.get("record_id", ""): row for row in bad_candidate_rows if row.get("record_id")}
    groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in manifest_rows:
        groups[source_key(row)].append(row)

    registry_rows: List[Dict[str, Any]] = []
    for key, rows in groups.items():
        source_id = stable_source_id(key)
        bad_rows = [bad_by_record[row.get("record_id", "")] for row in rows if row.get("record_id", "") in bad_by_record]
        text_candidates = [(file_chars(resolve_path(row.get("local_text_path", ""))), row) for row in rows]
        best_text_chars, best_text_row = max(text_candidates, key=lambda item: item[0], default=(0, {}))
        text_available = best_text_chars >= MIN_SOURCE_TEXT_CHARS
        extract_error_rows = [row for row in rows if row.get("pdf_status") == "extract_error"]
        pdf_rows = [row for row in rows if row.get("pdf_path")]

        if bad_rows or any(row.get("pdf_status") == "bad_candidate_override" for row in rows):
            source_status = "source_metadata_mismatch"
            validation_status = "source_metadata_mismatch"
            validation_issue = join_unique(
                [
                    *(row.get("issue", "") for row in bad_rows),
                    *(row.get("candidate_issue", "") for row in rows),
                    *(row.get("notes", "") for row in bad_rows),
                ]
            )
            local_pdf_path = ""
            local_text_path = ""
        elif text_available:
            source_status = "source_text_available"
            validation_status = "validated_source_text_available"
            validation_issue = ""
            local_pdf_path = choose_first(row.get("pdf_path", "") for row in rows)
            local_text_path = best_text_row.get("local_text_path", "")
        elif extract_error_rows:
            source_status = "pdf_extraction_failed"
            validation_status = "pdf_exists_but_extract_failed"
            validation_issue = join_unique(row.get("notes", "") for row in extract_error_rows)
            local_pdf_path = choose_first(row.get("pdf_path", "") for row in extract_error_rows)
            local_text_path = choose_first(row.get("local_text_path", "") for row in extract_error_rows)
        elif pdf_rows:
            source_status = "pdf_available_no_text"
            validation_status = "pdf_exists_without_text"
            validation_issue = "PDF path exists in manifest but no usable source text was extracted."
            local_pdf_path = choose_first(row.get("pdf_path", "") for row in pdf_rows)
            local_text_path = choose_first(row.get("local_text_path", "") for row in pdf_rows)
        else:
            source_status = "source_missing"
            validation_status = "needs_acquisition"
            validation_issue = "No validated source text or local PDF is available."
            local_pdf_path = ""
            local_text_path = choose_first(row.get("local_text_path", "") for row in rows)

        canonical_title = choose_title(rows)
        registry_rows.append(
            {
                "source_id": source_id,
                "source_key": key,
                "canonical_title": canonical_title,
                "doi": choose_doi(rows),
                "source_url": choose_first(row.get("source_url", "") for row in rows),
                "source_type": choose_first(row.get("preferred_source_type", "") for row in rows),
                "source_status": source_status,
                "local_pdf_path": local_pdf_path,
                "local_text_path": local_text_path,
                "recommended_pdf_path": recommended_source_pdf_path(source_id, canonical_title),
                "validation_status": validation_status,
                "validation_issue": validation_issue,
                "referring_record_ids": join_unique(row.get("record_id", "") for row in rows),
                "referring_tool_names": join_unique(row.get("tool_name", "") for row in rows),
                "evidence_kinds": join_unique(row.get("evidence_kind", "") for row in rows),
                "source_row_count": len(rows),
                "text_chars": best_text_chars,
                "notes": join_unique(row.get("notes", "") for row in rows),
            }
        )
    registry_rows.sort(key=lambda row: (row["source_status"], row["canonical_title"].casefold(), row["source_id"]))
    return registry_rows


def build_pdf_candidate_registry(
    manifest_rows: Sequence[Dict[str, str]],
    *,
    source_registry_rows: Sequence[Dict[str, Any]],
    download_summary: Dict[str, Any],
    bad_candidate_rows: Sequence[Dict[str, str]] = (),
) -> List[Dict[str, Any]]:
    source_id_by_key = {row["source_key"]: row["source_id"] for row in source_registry_rows}
    bad_by_record = {row.get("record_id", ""): row for row in bad_candidate_rows if row.get("record_id")}
    download_by_record = {
        row.get("record_id", ""): row
        for row in download_summary.get("rows", [])
        if isinstance(row, dict) and row.get("record_id")
    }
    candidate_rows: List[Dict[str, Any]] = []
    for row in manifest_rows:
        source_id = source_id_by_key.get(source_key(row), stable_source_id(source_key(row)))
        download_row = download_by_record.get(row.get("record_id", ""), {})
        raw_candidates = normalize_candidate_rows(download_row)
        if not raw_candidates:
            raw_candidates = [
                {
                    "url": "",
                    "source": "",
                    "candidate_kind": "",
                    "status": download_row.get("status", "not_discovered") or "not_discovered",
                }
            ]
        for candidate in raw_candidates:
            validation = validate_candidate(row, candidate, bad_by_record.get(row.get("record_id", ""), {}))
            target_pdf = "" if validation["quarantine"] else download_row.get("target_pdf", "")
            candidate_rows.append(
                {
                    "source_id": source_id,
                    "record_id": row.get("record_id", ""),
                    "tool_name": row.get("tool_name", ""),
                    "expected_title": row.get("source_title", ""),
                    "doi": normalize_doi(row.get("doi_or_pmid", "")),
                    "source_url": row.get("source_url", ""),
                    "candidate_url": candidate.get("url", ""),
                    "candidate_source": candidate.get("source", ""),
                    "candidate_kind": candidate.get("candidate_kind", ""),
                    "candidate_title": candidate.get("candidate_title", "") or candidate.get("title", ""),
                    "title_similarity": validation["title_similarity"],
                    "discovery_status": candidate.get("status", download_row.get("status", "")),
                    "validation_status": validation["validation_status"],
                    "validation_issue": validation["validation_issue"],
                    "quarantine": "true" if validation["quarantine"] else "false",
                    "target_pdf": target_pdf,
                }
            )
    candidate_rows.sort(key=lambda item: (item["validation_status"], item["source_id"], item["record_id"]))
    return candidate_rows


def build_validation_report(source_registry_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in source_registry_rows:
        rows.append(
            {
                "source_id": row.get("source_id", ""),
                "source_status": row.get("source_status", ""),
                "validation_status": row.get("validation_status", ""),
                "validation_issue": row.get("validation_issue", ""),
                "recommended_action": recommended_action(row),
                "canonical_title": row.get("canonical_title", ""),
                "doi": row.get("doi", ""),
                "source_url": row.get("source_url", ""),
                "referring_record_ids": row.get("referring_record_ids", ""),
                "referring_tool_names": row.get("referring_tool_names", ""),
                "local_pdf_path": row.get("local_pdf_path", ""),
                "local_text_path": row.get("local_text_path", ""),
            }
        )
    rows.sort(key=lambda item: (action_priority(item["recommended_action"]), item["canonical_title"].casefold()))
    return rows


def build_acquisition_summary(
    *,
    manifest_rows: Sequence[Dict[str, str]],
    source_registry_rows: Sequence[Dict[str, Any]],
    candidate_rows: Sequence[Dict[str, Any]],
    download_summary: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "source_rows": len(manifest_rows),
        "source_records": len(source_registry_rows),
        "shared_source_records": sum(1 for row in source_registry_rows if int(row.get("source_row_count") or 0) > 1),
        "candidate_rows": len(candidate_rows),
        "candidate_validation_status_counts": dict(Counter(row.get("validation_status", "") for row in candidate_rows)),
        "candidate_quarantine_rows": sum(1 for row in candidate_rows if row.get("quarantine") == "true"),
        "source_status_counts": dict(Counter(row.get("source_status", "") for row in source_registry_rows)),
        "validation_status_counts": dict(Counter(row.get("validation_status", "") for row in source_registry_rows)),
        "download_summary": {
            key: download_summary.get(key)
            for key in [
                "live",
                "source_rows",
                "attempted_rows",
                "candidate_found",
                "downloaded",
                "download_failed",
                "skipped_existing",
                "not_found",
                "errors",
            ]
            if key in download_summary
        },
        "guardrail": (
            "Candidate discovery and source validation do not promote formal evidence. "
            "Metadata mismatches stay quarantined until DOI/title/source is corrected."
        ),
    }


def build_extraction_summary(
    *,
    source_registry_rows: Sequence[Dict[str, Any]],
    ingest_summary: Dict[str, Any],
) -> Dict[str, Any]:
    source_status_counts = Counter(row.get("source_status", "") for row in source_registry_rows)
    return {
        "source_records": len(source_registry_rows),
        "source_text_available": source_status_counts.get("source_text_available", 0),
        "source_metadata_mismatch": source_status_counts.get("source_metadata_mismatch", 0),
        "pdf_extraction_failed": source_status_counts.get("pdf_extraction_failed", 0),
        "source_missing": source_status_counts.get("source_missing", 0),
        "ingest_summary": {
            key: ingest_summary.get(key)
            for key in [
                "pdf_files",
                "source_rows",
                "matched_rows",
                "extracted_rows",
                "extract_errors",
                "bad_candidate_skips",
                "extractor",
            ]
            if key in ingest_summary
        },
        "guardrail": (
            "Extraction failures are not download tasks. Use alternate text, repair extraction, "
            "or replace with a validated source."
        ),
    }


def source_key(row: Dict[str, str]) -> str:
    doi = normalize_doi(row.get("doi_or_pmid", ""))
    if doi:
        return f"doi:{doi}"
    source_url = normalize_url(row.get("source_url", ""))
    if source_url:
        return f"url:{source_url}"
    return f"title:{normalize_title(row.get('source_title', ''))}"


def stable_source_id(key: str) -> str:
    return "SRC_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def normalize_doi(value: str) -> str:
    text = clean(value).lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = text.removeprefix("doi:")
    return text.strip()


def normalize_url(value: str) -> str:
    return clean(value).rstrip("/").lower()


def normalize_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).split())


def choose_doi(rows: Sequence[Dict[str, str]]) -> str:
    return choose_first(normalize_doi(row.get("doi_or_pmid", "")) for row in rows)


def choose_title(rows: Sequence[Dict[str, str]]) -> str:
    titles = [clean(row.get("source_title", "")) for row in rows if clean(row.get("source_title", ""))]
    if not titles:
        return ""
    return max(titles, key=len)


def choose_first(values: Iterable[str]) -> str:
    for value in values:
        text = clean(value)
        if text:
            return text
    return ""


def join_unique(values: Iterable[Any]) -> str:
    seen: List[str] = []
    for value in values:
        text = one_line(value)
        if text and text not in seen:
            seen.append(text)
    return "; ".join(seen)


def recommended_source_pdf_path(source_id: str, title: str) -> str:
    return f"data/evidence_sources/pdfs/sources/{source_id}_{safe_name(title)[:80]}.pdf"


def recommended_action(row: Dict[str, Any]) -> str:
    status = row.get("validation_status", "")
    if status == "validated_source_text_available":
        return "none"
    if status == "source_metadata_mismatch":
        return "correct_doi_or_replace_source"
    if status == "pdf_exists_but_extract_failed":
        return "repair_extractor_or_use_html"
    if status == "pdf_exists_without_text":
        return "extract_source_text"
    return "discover_or_manual_acquire"


def action_priority(action: str) -> int:
    order = {
        "correct_doi_or_replace_source": 0,
        "repair_extractor_or_use_html": 1,
        "extract_source_text": 2,
        "discover_or_manual_acquire": 3,
        "none": 9,
    }
    return order.get(action, 8)


def normalize_candidate_rows(download_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = download_row.get("candidate_urls") or []
    rows: List[Dict[str, Any]] = []
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict):
                rows.append(dict(item))
            elif isinstance(item, str):
                rows.append({"url": item})
    selected = download_row.get("selected_pdf_url", "")
    if selected and selected not in {row.get("url") for row in rows}:
        rows.insert(0, {"url": selected, "source": "selected_pdf_url"})
    return rows


def validate_candidate(
    source_row: Dict[str, str],
    candidate: Dict[str, Any],
    bad_candidate: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    url = clean(candidate.get("url", ""))
    candidate_title = candidate.get("candidate_title", "") or candidate.get("title", "")
    title_similarity = ""
    if bad_candidate and url and normalize_url(url) == normalize_url(bad_candidate.get("invalid_url", "")):
        return {
            "validation_status": "source_metadata_mismatch",
            "validation_issue": bad_candidate.get("issue", "") or "bad_candidate_override",
            "title_similarity": title_similarity,
            "quarantine": True,
        }
    if bad_candidate and not url:
        return {
            "validation_status": "source_metadata_mismatch",
            "validation_issue": bad_candidate.get("issue", "") or "bad_candidate_override",
            "title_similarity": title_similarity,
            "quarantine": True,
        }
    if not url:
        return {
            "validation_status": "no_candidate",
            "validation_issue": "",
            "title_similarity": title_similarity,
            "quarantine": False,
        }
    if candidate_title:
        score = title_token_similarity(source_row.get("source_title", ""), str(candidate_title))
        title_similarity = f"{score:.3f}"
        if score < 0.35:
            return {
                "validation_status": "source_metadata_mismatch",
                "validation_issue": "candidate_title_mismatch",
                "title_similarity": title_similarity,
                "quarantine": True,
            }
        return {
            "validation_status": "candidate_title_validated",
            "validation_issue": "",
            "title_similarity": title_similarity,
            "quarantine": False,
        }
    return {
        "validation_status": "candidate_unvalidated",
        "validation_issue": "candidate_title_not_extracted",
        "title_similarity": title_similarity,
        "quarantine": False,
    }


def title_token_similarity(expected: str, observed: str) -> float:
    expected_tokens = set(normalize_title(expected).split())
    observed_tokens = set(normalize_title(observed).split())
    if not expected_tokens or not observed_tokens:
        return 0.0
    return len(expected_tokens & observed_tokens) / len(expected_tokens | observed_tokens)


def file_chars(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8", errors="ignore"))


def resolve_path(value: str) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", clean(value)).strip("_") or "unknown"


def clean(value: object) -> str:
    return str(value or "").strip()


def one_line(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def build_all(
    *,
    source_manifest: Path,
    bad_candidate_overrides: Path,
    download_summary_path: Path,
    ingest_summary_path: Path,
) -> Dict[str, Any]:
    manifest_rows = read_tsv(source_manifest)
    bad_candidate_rows = read_tsv(bad_candidate_overrides)
    download_summary = read_json(download_summary_path)
    ingest_summary = read_json(ingest_summary_path)
    registry_rows = build_source_registry(manifest_rows, bad_candidate_rows)
    candidate_rows = build_pdf_candidate_registry(
        manifest_rows,
        source_registry_rows=registry_rows,
        download_summary=download_summary,
        bad_candidate_rows=bad_candidate_rows,
    )
    validation_rows = build_validation_report(registry_rows)
    acquisition_summary = build_acquisition_summary(
        manifest_rows=manifest_rows,
        source_registry_rows=registry_rows,
        candidate_rows=candidate_rows,
        download_summary=download_summary,
    )
    extraction_summary = build_extraction_summary(
        source_registry_rows=registry_rows,
        ingest_summary=ingest_summary,
    )
    return {
        "registry_rows": registry_rows,
        "candidate_rows": candidate_rows,
        "validation_rows": validation_rows,
        "acquisition_summary": acquisition_summary,
        "extraction_summary": extraction_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build source-level literature registry and validation artifacts."
    )
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--bad-candidate-overrides", type=Path, default=DEFAULT_BAD_CANDIDATE_OVERRIDES)
    parser.add_argument("--download-summary", type=Path, default=DEFAULT_DOWNLOAD_SUMMARY)
    parser.add_argument("--ingest-summary", type=Path, default=DEFAULT_INGEST_SUMMARY)
    parser.add_argument("--source-registry", type=Path, default=DEFAULT_SOURCE_REGISTRY)
    parser.add_argument("--pdf-candidate-registry", type=Path, default=DEFAULT_PDF_CANDIDATE_REGISTRY)
    parser.add_argument("--source-validation-report", type=Path, default=DEFAULT_SOURCE_VALIDATION_REPORT)
    parser.add_argument("--acquisition-summary", type=Path, default=DEFAULT_ACQUISITION_SUMMARY)
    parser.add_argument("--extraction-summary", type=Path, default=DEFAULT_EXTRACTION_SUMMARY)
    args = parser.parse_args()

    artifacts = build_all(
        source_manifest=args.source_manifest,
        bad_candidate_overrides=args.bad_candidate_overrides,
        download_summary_path=args.download_summary,
        ingest_summary_path=args.ingest_summary,
    )
    write_tsv(args.source_registry, artifacts["registry_rows"], SOURCE_REGISTRY_FIELDS)
    write_tsv(args.pdf_candidate_registry, artifacts["candidate_rows"], PDF_CANDIDATE_FIELDS)
    write_tsv(args.source_validation_report, artifacts["validation_rows"], VALIDATION_REPORT_FIELDS)
    write_json(args.acquisition_summary, artifacts["acquisition_summary"])
    write_json(args.extraction_summary, artifacts["extraction_summary"])
    print(
        json.dumps(
            {
                "source_registry": rel(args.source_registry),
                "pdf_candidate_registry": rel(args.pdf_candidate_registry),
                "source_validation_report": rel(args.source_validation_report),
                **artifacts["acquisition_summary"],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
