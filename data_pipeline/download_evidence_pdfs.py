from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Sequence
from urllib.parse import quote, urljoin

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "doublet_detection_source_manifest.tsv"
)
DEFAULT_PDF_DIR = PROJECT_ROOT / "data" / "evidence_sources" / "pdfs"
DEFAULT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_download_summary.json"
)
DEFAULT_BAD_CANDIDATE_OVERRIDES = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "pdf_bad_candidate_overrides.tsv"
)
USER_AGENT = "scKG-Agent evidence PDF downloader; polite research use; contact=local"
PDF_MIN_BYTES = 1024


class PdfLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag == "meta":
            name = attr.get("name", "").lower()
            prop = attr.get("property", "").lower()
            if name in {"citation_pdf_url", "dc.identifier", "eprints.document_url"} or prop.endswith("pdf"):
                url = attr.get("content", "")
                if looks_like_pdf_url(url):
                    self.links.append({"url": urljoin(self.base_url, url), "source": f"meta:{name or prop}"})
        if tag == "link":
            rel = attr.get("rel", "").lower()
            href = attr.get("href", "")
            if "alternate" in rel and looks_like_pdf_url(href):
                self.links.append({"url": urljoin(self.base_url, href), "source": "link:alternate"})
        if tag == "a":
            href = attr.get("href", "")
            label = " ".join([attr.get("title", ""), attr.get("aria-label", "")]).lower()
            if looks_like_pdf_url(href) or "pdf" in label:
                self.links.append({"url": urljoin(self.base_url, href), "source": "html:a"})


def read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def download_pdfs(
    rows: Sequence[Dict[str, str]],
    *,
    pdf_dir: Path,
    summary_output: Path = DEFAULT_SUMMARY,
    live: bool,
    overwrite: bool,
    limit: int | None,
    delay_s: float,
    timeout: int,
    unpaywall_email: str,
    bad_candidate_rows: Sequence[Dict[str, str]] = (),
) -> Dict[str, Any]:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    selected = list(rows)[:limit] if limit is not None else list(rows)
    bad_by_record = {row.get("record_id", ""): row for row in bad_candidate_rows if row.get("record_id")}
    summary = {
        "live": live,
        "pdf_dir": rel(pdf_dir),
        "source_rows": len(rows),
        "attempted_rows": len(selected),
        "candidate_found": 0,
        "downloaded": 0,
        "download_failed": 0,
        "skipped_existing": 0,
        "not_found": 0,
        "errors": 0,
        "quarantined_candidates": 0,
        "strategies": [
            "direct_pdf_url",
            "crossref_metadata_links",
            "doi_landing_citation_pdf_url",
            "unpaywall_optional",
        ],
        "guardrail": (
            "Only open/direct PDF URLs are downloaded. The downloader does not bypass paywalls, "
            "does not use Sci-Hub, and stores PDFs as evidence discovery input only."
        ),
        "rows": [],
    }
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"})
    for index, row in enumerate(selected, start=1):
        if index > 1 and delay_s > 0:
            time.sleep(delay_s)
        target = pdf_dir / suggested_pdf_filename(row)
        result = {
            "tool_name": row.get("tool_name", ""),
            "evidence_kind": row.get("evidence_kind", ""),
            "record_id": row.get("record_id", ""),
            "doi_or_pmid": row.get("doi_or_pmid", ""),
            "source_url": row.get("source_url", ""),
            "target_pdf": rel(target),
            "status": "not_found",
            "selected_pdf_url": "",
            "candidate_urls": [],
            "quarantined_candidate_urls": [],
            "candidate_issue": "",
            "error": "",
        }
        if target.exists() and not overwrite:
            result["status"] = "skipped_existing"
            summary["skipped_existing"] += 1
            summary["rows"].append(result)
            continue
        try:
            candidates = discover_pdf_candidates(
                row,
                session=session,
                timeout=timeout,
                unpaywall_email=unpaywall_email,
            )
            valid_candidates, quarantined_candidates = apply_bad_candidate_overrides(
                candidates,
                bad_by_record.get(row.get("record_id", ""), {}),
            )
            result["candidate_urls"] = valid_candidates
            result["quarantined_candidate_urls"] = quarantined_candidates
            if quarantined_candidates:
                summary["quarantined_candidates"] += len(quarantined_candidates)
                result["candidate_issue"] = bad_by_record.get(row.get("record_id", ""), {}).get("issue", "")
            if not candidates:
                summary["not_found"] += 1
                summary["rows"].append(result)
                continue
            if candidates and not valid_candidates:
                summary["candidate_found"] += 1
                result["status"] = "candidate_quarantined_metadata_mismatch"
                result["selected_pdf_url"] = ""
                result["target_pdf"] = ""
                summary["rows"].append(result)
                continue
            summary["candidate_found"] += 1
            if not live:
                result["status"] = "dry_run_candidate_found"
                result["selected_pdf_url"] = valid_candidates[0]["url"]
                summary["rows"].append(result)
                continue
            downloaded = download_first_valid_pdf(valid_candidates, target, session=session, timeout=timeout)
            result.update(downloaded)
            if result["status"] == "downloaded":
                summary["downloaded"] += 1
            else:
                summary["download_failed"] += 1
        except Exception as exc:
            result["status"] = "error"
            result["error"] = f"{type(exc).__name__}: {exc}"
            summary["errors"] += 1
        summary["rows"].append(result)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return summary


def apply_bad_candidate_overrides(
    candidates: Sequence[Dict[str, str]],
    bad_candidate: Dict[str, str],
) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    if not bad_candidate:
        return list(candidates), []
    invalid_url = clean(bad_candidate.get("invalid_url"))
    valid: List[Dict[str, str]] = []
    quarantined: List[Dict[str, str]] = []
    for candidate in candidates:
        if invalid_url and clean(candidate.get("url")) == invalid_url:
            quarantined.append({**candidate, "issue": bad_candidate.get("issue", "")})
        else:
            valid.append(candidate)
    return valid, quarantined


def discover_pdf_candidates(
    row: Dict[str, str],
    *,
    session: requests.Session,
    timeout: int,
    unpaywall_email: str,
) -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    source_url = clean(row.get("source_url"))
    doi = clean(row.get("doi_or_pmid"))
    if looks_like_pdf_url(source_url):
        candidates.append({"url": source_url, "source": "direct_pdf_url"})
    if doi and "/" in doi:
        candidates.extend(crossref_pdf_candidates(doi, session=session, timeout=timeout))
        if unpaywall_email:
            candidates.extend(
                unpaywall_pdf_candidates(doi, email=unpaywall_email, session=session, timeout=timeout)
            )
    if source_url and source_url.startswith("http"):
        candidates.extend(landing_page_pdf_candidates(source_url, session=session, timeout=timeout))
    return dedupe_candidates(candidates)


def crossref_pdf_candidates(doi: str, *, session: requests.Session, timeout: int) -> List[Dict[str, str]]:
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    response = session.get(url, timeout=timeout)
    if response.status_code >= 400:
        return []
    message = (response.json().get("message") or {})
    rows: List[Dict[str, str]] = []
    for link in message.get("link") or []:
        pdf_url = link.get("URL") or link.get("url") or ""
        content_type = (link.get("content-type") or "").lower()
        if "pdf" in content_type or looks_like_pdf_url(pdf_url):
            rows.append({"url": pdf_url, "source": "crossref_metadata_link"})
    return rows


def unpaywall_pdf_candidates(
    doi: str,
    *,
    email: str,
    session: requests.Session,
    timeout: int,
) -> List[Dict[str, str]]:
    url = f"https://api.unpaywall.org/v2/{quote(doi, safe='')}?email={quote(email, safe='@.')}"
    response = session.get(url, timeout=timeout)
    if response.status_code >= 400:
        return []
    data = response.json()
    rows: List[Dict[str, str]] = []
    best = data.get("best_oa_location") or {}
    for item in [best, *(data.get("oa_locations") or [])]:
        pdf_url = item.get("url_for_pdf") or ""
        if pdf_url:
            rows.append({"url": pdf_url, "source": "unpaywall_oa_location"})
    return rows


def landing_page_pdf_candidates(
    url: str,
    *,
    session: requests.Session,
    timeout: int,
) -> List[Dict[str, str]]:
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except Exception:
        return []
    content_type = response.headers.get("content-type", "").lower()
    if "application/pdf" in content_type or response.url.lower().endswith(".pdf"):
        return [{"url": response.url, "source": "doi_landing_redirect_pdf"}]
    if "html" not in content_type and "<html" not in response.text[:1000].lower():
        return []
    parser = PdfLinkParser(response.url)
    parser.feed(response.text)
    return parser.links


def download_first_valid_pdf(
    candidates: Sequence[Dict[str, str]],
    target: Path,
    *,
    session: requests.Session,
    timeout: int,
) -> Dict[str, str]:
    primary_candidates = [candidate for candidate in candidates if not is_supplement_pdf_url(candidate["url"])]
    for candidate in primary_candidates:
        url = candidate["url"]
        try:
            response = session.get(
                url,
                timeout=timeout,
                stream=True,
                allow_redirects=True,
                headers={"Accept": "application/pdf,*/*"},
            )
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code >= 400:
                continue
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                chunks.append(chunk)
                size += len(chunk)
                if size > 200 * 1024 * 1024:
                    raise RuntimeError("PDF exceeds 200MB safety limit")
            body = b"".join(chunks)
            if not is_pdf_response(body, content_type, response.url):
                continue
            if len(body) < PDF_MIN_BYTES:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            return {
                "status": "downloaded",
                "selected_pdf_url": response.url,
                "target_pdf": rel(target),
                "error": "",
            }
        except Exception:
            continue
    return {
        "status": "download_failed",
        "selected_pdf_url": primary_candidates[0]["url"] if primary_candidates else "",
        "target_pdf": rel(target),
        "error": "No primary-article candidate returned a valid PDF response.",
    }


def is_pdf_response(body: bytes, content_type: str, url: str) -> bool:
    if body[:4] == b"%PDF":
        return True
    if "application/pdf" in content_type:
        return True
    return url.lower().split("?", 1)[0].endswith(".pdf")


def dedupe_candidates(candidates: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    rows: List[Dict[str, str]] = []
    for item in candidates:
        url = clean(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append(
            {
                "url": url,
                "source": item.get("source", ""),
                "candidate_kind": "supplement" if is_supplement_pdf_url(url) else "primary_article",
            }
        )
    rows.sort(key=lambda item: 1 if item["candidate_kind"] == "supplement" else 0)
    return rows


def is_supplement_pdf_url(value: str) -> bool:
    lowered = (value or "").lower()
    supplement_markers = [
        "/esm/",
        "mediaobjects",
        "moesm",
        "supplement",
        "supplementary",
    ]
    return any(marker in lowered for marker in supplement_markers)


def looks_like_pdf_url(value: str) -> bool:
    lowered = (value or "").lower()
    return lowered.endswith(".pdf") or ".pdf?" in lowered or "/pdf" in lowered


def suggested_pdf_filename(row: Dict[str, str]) -> str:
    tool = safe_name(row.get("tool_name", "unknown"))
    record = safe_name(row.get("record_id", "record"))
    return f"{tool}_{record}.pdf"


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value or "").strip("_")[:110] or "unknown"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def clean(value: object) -> str:
    return str(value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and optionally download open evidence PDFs.")
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--live", action="store_true", help="Actually download PDFs. Default is discovery dry-run.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay-s", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--bad-candidate-overrides", type=Path, default=DEFAULT_BAD_CANDIDATE_OVERRIDES)
    parser.add_argument(
        "--unpaywall-email",
        default=os.getenv("UNPAYWALL_EMAIL", ""),
        help="Optional email for Unpaywall OA lookup. Can also use UNPAYWALL_EMAIL env var.",
    )
    args = parser.parse_args()
    rows = read_tsv(args.source_manifest)
    if not rows:
        raise SystemExit(f"Missing or empty source manifest: {args.source_manifest}")
    summary = download_pdfs(
        rows,
        pdf_dir=args.pdf_dir,
        summary_output=args.summary_output,
        live=args.live,
        overwrite=args.overwrite,
        limit=args.limit,
        delay_s=args.delay_s,
        timeout=args.timeout,
        unpaywall_email=args.unpaywall_email,
        bad_candidate_rows=read_tsv(args.bad_candidate_overrides),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
