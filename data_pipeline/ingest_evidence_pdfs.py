from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_PDF_DIR = PROJECT_ROOT / "data" / "evidence_sources" / "pdfs"
DEFAULT_SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "doublet_detection_source_manifest.tsv"
)
DEFAULT_OUTPUT_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_source_manifest.tsv"
)
DEFAULT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_ingest_summary.json"
)
DEFAULT_BAD_CANDIDATE_OVERRIDES = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "pdf_bad_candidate_overrides.tsv"
)
TEXT_ROOT = PROJECT_ROOT / "data" / "evidence_sources" / "text"

SOURCE_FIELDS = [
    "source_id",
    "evidence_kind",
    "tool_name",
    "record_id",
    "source_title",
    "source_url",
    "doi_or_pmid",
    "preferred_source_type",
    "local_text_path",
    "fetch_status",
    "fetch_priority",
    "notes",
    "pdf_path",
    "pdf_status",
    "text_chars",
    "page_count",
    "candidate_issue",
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
        for row in rows:
            writer.writerow({field: one_line(row.get(field, "")) for field in fields})


def ingest_pdfs(
    rows: Sequence[Dict[str, str]],
    *,
    pdf_dir: Path,
    bad_candidate_rows: Sequence[Dict[str, str]] = (),
    overwrite: bool = False,
) -> Dict[str, Any]:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_files = discover_pdf_files(pdf_dir)
    bad_by_record = {
        row.get("record_id", ""): row
        for row in bad_candidate_rows
        if row.get("record_id")
    }
    output_rows: List[Dict[str, Any]] = []
    summary = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "pdf_dir": str(pdf_dir.relative_to(PROJECT_ROOT)) if pdf_dir.is_relative_to(PROJECT_ROOT) else str(pdf_dir),
        "source_rows": len(rows),
        "pdf_files": len(pdf_files),
        "matched_rows": 0,
        "extracted_rows": 0,
        "missing_pdf_rows": 0,
        "extract_error_rows": 0,
        "bad_candidate_override_rows": 0,
        "extractor": detect_extractor(),
        "output_manifest": str(DEFAULT_OUTPUT_MANIFEST.relative_to(PROJECT_ROOT)),
        "rows": [],
        "suggested_filenames": [],
    }
    for row in rows:
        out = dict(row)
        match = match_pdf_for_row(row, pdf_files)
        suggested = suggested_pdf_filename(row)
        out["pdf_path"] = ""
        out["pdf_status"] = "missing_pdf"
        out["text_chars"] = "0"
        out["page_count"] = "0"
        out["candidate_issue"] = ""
        bad_candidate = bad_by_record.get(row.get("record_id", ""))
        if bad_candidate:
            summary["bad_candidate_override_rows"] += 1
            out["pdf_status"] = "bad_candidate_override"
            out["candidate_issue"] = bad_candidate.get("issue", "")
            out["notes"] = append_note(
                out.get("notes", ""),
                (
                    "Skipped PDF ingest because this record has a bad-candidate override: "
                    f"{bad_candidate.get('notes', '')}"
                ),
            )
        elif not match:
            summary["missing_pdf_rows"] += 1
            out["notes"] = append_note(
                out.get("notes", ""),
                f"Expected PDF filename can include record_id/DOI/title; suggested={suggested}",
            )
        else:
            summary["matched_rows"] += 1
            out["pdf_path"] = rel(match)
            text_path = resolve_text_path(out)
            if text_path.exists() and not overwrite:
                text = text_path.read_text(encoding="utf-8", errors="ignore")
                out["pdf_status"] = "text_existing"
                out["fetch_status"] = "pdf_text_existing"
                out["text_chars"] = str(len(text))
                out["notes"] = append_note(out.get("notes", ""), f"reused_existing_pdf_text={rel(text_path)}")
            else:
                try:
                    extracted = extract_pdf_text(match)
                except Exception as exc:
                    extracted = {
                        "ok": False,
                        "text": "",
                        "page_count": 0,
                        "extractor": detect_extractor(),
                        "error": f"PDF text extraction raised {type(exc).__name__}: {exc}",
                    }
                if extracted["ok"]:
                    text_path.parent.mkdir(parents=True, exist_ok=True)
                    text_path.write_text(extracted["text"], encoding="utf-8")
                    out["local_text_path"] = rel(text_path)
                    out["fetch_status"] = "pdf_text_extracted"
                    out["pdf_status"] = "pdf_text_extracted"
                    out["text_chars"] = str(len(extracted["text"]))
                    out["page_count"] = str(extracted.get("page_count") or 0)
                    out["notes"] = append_note(
                        out.get("notes", ""),
                        f"PDF text extracted by {extracted.get('extractor')}; discovery only, not promotion evidence",
                    )
                    summary["extracted_rows"] += 1
                else:
                    out["pdf_status"] = "extract_error"
                    out["notes"] = append_note(out.get("notes", ""), extracted["error"])
                    summary["extract_error_rows"] += 1
        output_rows.append(out)
        summary["suggested_filenames"].append(
            {
                "tool_name": row.get("tool_name", ""),
                "evidence_kind": row.get("evidence_kind", ""),
                "record_id": row.get("record_id", ""),
                "suggested_filename": suggested,
            }
        )
        summary["rows"].append(
            {
                "tool_name": out.get("tool_name", ""),
                "evidence_kind": out.get("evidence_kind", ""),
                "record_id": out.get("record_id", ""),
                "pdf_status": out.get("pdf_status", ""),
                "pdf_path": out.get("pdf_path", ""),
                "local_text_path": out.get("local_text_path", ""),
                "text_chars": int(out.get("text_chars") or 0),
                "candidate_issue": out.get("candidate_issue", ""),
                "notes": out.get("notes", ""),
            }
        )
    summary["output_rows"] = output_rows
    return summary


def extract_pdf_text(path: Path) -> Dict[str, Any]:
    if shutil.which("pdftotext"):
        return extract_with_pdftotext(path)
    try:
        return extract_with_pypdf(path)
    except ModuleNotFoundError:
        return {
            "ok": False,
            "text": "",
            "error": (
                "No PDF extractor available. Install pypdf (`pip install pypdf`) "
                "or Poppler pdftotext, then rerun."
            ),
        }
    except Exception as exc:
        repaired = extract_with_ghostscript_repair(path)
        if repaired["ok"]:
            repaired["notes"] = f"pypdf failed first ({type(exc).__name__}: {exc}); extracted after Ghostscript repair"
            return repaired
        return {
            "ok": False,
            "text": "",
            "page_count": 0,
            "extractor": detect_extractor(),
            "error": f"pypdf failed: {type(exc).__name__}: {exc}; {repaired.get('error', '')}",
        }


def extract_with_pdftotext(path: Path) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "out.txt"
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), str(output)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return {"ok": False, "text": "", "error": f"pdftotext failed: {result.stderr.strip()}"}
        text = normalize_pdf_text(output.read_text(encoding="utf-8", errors="ignore"))
        return {"ok": bool(text), "text": text, "page_count": 0, "extractor": "pdftotext", "error": ""}


def extract_with_pypdf(path: Path) -> Dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: List[str] = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(f"\n\n[PDF_PAGE {index}]\n\n{page_text}")
    text = normalize_pdf_text("\n".join(parts))
    return {
        "ok": bool(text),
        "text": text,
        "page_count": len(reader.pages),
        "extractor": "pypdf",
        "error": "" if text else "PDF text extraction produced empty text",
    }


def extract_with_ghostscript_repair(path: Path) -> Dict[str, Any]:
    gs = shutil.which("gs")
    if not gs:
        return {"ok": False, "text": "", "error": "Ghostscript repair unavailable: gs not found"}
    with tempfile.TemporaryDirectory() as tmp:
        repaired = Path(tmp) / "repaired.pdf"
        result = subprocess.run(
            [
                gs,
                "-o",
                str(repaired),
                "-sDEVICE=pdfwrite",
                "-dPDFSETTINGS=/prepress",
                "-dSAFER",
                "-dNOPAUSE",
                "-dBATCH",
                str(path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not repaired.exists():
            return {
                "ok": False,
                "text": "",
                "error": f"Ghostscript repair failed: {result.stderr.strip() or result.stdout.strip()}",
            }
        try:
            extracted = extract_with_pypdf(repaired)
            if extracted["ok"]:
                extracted["extractor"] = "ghostscript_repair+pypdf"
            return extracted
        except Exception as exc:
            return {
                "ok": False,
                "text": "",
                "error": f"Ghostscript repaired PDF still failed pypdf: {type(exc).__name__}: {exc}",
            }


def discover_pdf_files(pdf_dir: Path) -> List[Path]:
    files = []
    for path in sorted(pdf_dir.rglob("*.pdf")):
        if any(part.startswith("quarantine") for part in path.relative_to(pdf_dir).parts):
            continue
        files.append(path)
    return files


def match_pdf_for_row(row: Dict[str, str], pdf_files: Sequence[Path]) -> Path | None:
    if not pdf_files:
        return None
    record_key = normalize(row.get("record_id", ""))
    doi_key = normalize(row.get("doi_or_pmid", ""))
    exact_filename = suggested_pdf_filename(row)
    for path in pdf_files:
        stem = normalize(path.stem)
        if path.name == exact_filename:
            return path
        if record_key and record_key in stem:
            return path
        if doi_key and doi_key in stem:
            return path
    return None


def row_match_keys(row: Dict[str, str]) -> List[str]:
    return tokenize(
        " ".join(
            [
                row.get("tool_name", ""),
                row.get("record_id", ""),
                row.get("source_title", ""),
                row.get("doi_or_pmid", ""),
            ]
        )
    )


def suggested_pdf_filename(row: Dict[str, str]) -> str:
    tool = safe_name(row.get("tool_name", "unknown"))
    record = safe_name(row.get("record_id", "record"))
    return f"{tool}_{record}.pdf"


def resolve_text_path(row: Dict[str, str]) -> Path:
    value = row.get("local_text_path", "")
    if value:
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    return TEXT_ROOT / f"{safe_name(row.get('tool_name', 'unknown'))}_{safe_name(row.get('record_id', 'record'))}.txt"


def detect_extractor() -> str:
    if shutil.which("pdftotext"):
        return "pdftotext"
    try:
        import pypdf  # noqa: F401

        return "pypdf"
    except Exception:
        return "missing"


def normalize_pdf_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def tokenize(value: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9]+", (value or "").lower()) if token]


def normalize(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value or "").strip("_")[:110] or "unknown"


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def append_note(existing: str, note: str) -> str:
    existing = one_line(existing)
    note = one_line(note)
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}; {note}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract evidence PDFs into retrieval-only source text.")
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--output-manifest", type=Path, default=DEFAULT_OUTPUT_MANIFEST)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--bad-candidate-overrides", type=Path, default=DEFAULT_BAD_CANDIDATE_OVERRIDES)
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing extracted text files.")
    args = parser.parse_args()

    rows = read_tsv(args.source_manifest)
    if not rows:
        raise SystemExit(f"Missing or empty source manifest: {args.source_manifest}")
    summary = ingest_pdfs(
        rows,
        pdf_dir=args.pdf_dir,
        bad_candidate_rows=read_tsv(args.bad_candidate_overrides),
        overwrite=args.overwrite,
    )
    output_rows = summary.pop("output_rows")
    write_tsv(args.output_manifest, output_rows, SOURCE_FIELDS)
    summary["output_manifest"] = rel(args.output_manifest)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
