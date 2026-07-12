from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Sequence

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_pipeline.github_crawler import GitHubCrawler


DEFAULT_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_source_manifest_v1.tsv"
)
DEFAULT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_source_fetch_summary.json"
)
USER_AGENT = "scKG-Agent evidence recovery fetcher; contact=local-research-use"
MIN_TEXT_CHARS = 500


class TextExtractingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if tag.lower() in {"p", "br", "div", "section", "article", "h1", "h2", "h3", "li", "tr"}:
            self._parts.append("\n")
        if tag.lower() == "meta":
            attr_map = {key.lower(): value or "" for key, value in attrs}
            name = attr_map.get("name", "").lower()
            prop = attr_map.get("property", "").lower()
            if name in {"citation_title", "citation_abstract", "description"} or prop in {
                "og:title",
                "og:description",
            }:
                self._parts.append("\n")
                self._parts.append(attr_map.get("content", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag.lower() in {"p", "div", "section", "article", "h1", "h2", "h3", "li", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        raw = " ".join(part.strip() for part in self._parts if part.strip())
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\s*\n\s*", "\n", raw)
        return dedupe_lines(raw)


def read_tsv(path: Path) -> tuple[List[Dict[str, str]], List[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader), list(reader.fieldnames or [])


def write_tsv(path: Path, rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fetch_sources(
    rows: List[Dict[str, str]],
    *,
    refresh: bool = False,
    limit: int | None = None,
    timeout: int = 20,
    dry_run: bool = False,
    allow_pdf: bool = False,
) -> Dict[str, object]:
    summary = {
        "rows": len(rows),
        "attempted": 0,
        "fetched": 0,
        "skipped_existing": 0,
        "skipped_pdf": 0,
        "empty_text": 0,
        "missing_url": 0,
        "fetch_error": 0,
        "fetched_github_readme": 0,
        "dry_run": dry_run,
    }
    attempted = 0
    github_crawler: GitHubCrawler | None = None
    for row in rows:
        if limit is not None and attempted >= limit:
            break
        local_path = resolve_local_path(row.get("local_text_path", ""))
        if local_path.exists() and not refresh:
            row["fetch_status"] = "fetched_existing"
            row["notes"] = append_note(row.get("notes", ""), "local_text_path already exists; reused existing text")
            summary["skipped_existing"] += 1
            continue
        url = clean(row.get("source_url"))
        if not url:
            row["fetch_status"] = "missing_url"
            summary["missing_url"] += 1
            continue
        attempted += 1
        summary["attempted"] += 1
        if dry_run:
            row["fetch_status"] = "dry_run_pending"
            row["notes"] = append_note(row.get("notes", ""), "fetch dry-run; no network request made")
            continue
        try:
            if is_github_readme_source(row, url):
                if github_crawler is None:
                    github_crawler = GitHubCrawler()
                result = github_crawler.fetch_readme_text(url, timeout=timeout)
                if result.get("error"):
                    row["fetch_status"] = "fetch_error"
                    row["notes"] = append_note(row.get("notes", ""), f"github_readme_error={result['error']}")
                    summary["fetch_error"] += 1
                    continue
                text = normalize_text(str(result.get("text", "")))
                if len(text) < MIN_TEXT_CHARS:
                    row["fetch_status"] = "empty_text"
                    row["notes"] = append_note(
                        remove_stale_fetch_notes(row.get("notes", "")),
                        f"GitHub README shorter than {MIN_TEXT_CHARS} chars",
                    )
                    summary["empty_text"] += 1
                    continue
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text(text, encoding="utf-8")
                row["fetch_status"] = "fetched_github_readme"
                if result.get("source_url"):
                    row["source_url"] = str(result["source_url"])
                row["notes"] = append_note(
                    remove_stale_fetch_notes(row.get("notes", "")),
                    "fetched_at="
                    f"{datetime.now(timezone.utc).isoformat()}; "
                    f"repo={result.get('repo_full_name', '')}; readme_path={result.get('readme_path', '')}; "
                    f"download_url={result.get('download_url', '')}",
                )
                summary["fetched"] += 1
                summary["fetched_github_readme"] += 1
                continue
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain,*/*"},
                timeout=timeout,
                allow_redirects=True,
            )
            content_type = response.headers.get("content-type", "").lower()
            if "application/pdf" in content_type or response.url.lower().endswith(".pdf"):
                if not allow_pdf:
                    row["fetch_status"] = "skipped_pdf"
                    row["notes"] = append_note(row.get("notes", ""), "PDF detected; PDF text parsing not enabled")
                    summary["skipped_pdf"] += 1
                    continue
            response.raise_for_status()
            text = response.text if "text/plain" in content_type else html_to_text(response.text)
            text = normalize_text(text)
            if len(text) < MIN_TEXT_CHARS:
                row["fetch_status"] = "empty_text"
                row["notes"] = append_note(
                    remove_stale_fetch_notes(row.get("notes", "")),
                    f"Fetched text shorter than {MIN_TEXT_CHARS} chars",
                )
                summary["empty_text"] += 1
                continue
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(text, encoding="utf-8")
            row["fetch_status"] = "fetched_text"
            row["notes"] = append_note(
                remove_stale_fetch_notes(row.get("notes", "")),
                f"fetched_at={datetime.now(timezone.utc).isoformat()}; final_url={response.url}; content_type={content_type}",
            )
            summary["fetched"] += 1
        except Exception as exc:
            row["fetch_status"] = "fetch_error"
            row["notes"] = append_note(row.get("notes", ""), f"fetch_error={type(exc).__name__}: {exc}")
            summary["fetch_error"] += 1
    return summary


def html_to_text(html: str) -> str:
    parser = TextExtractingHTMLParser()
    parser.feed(html or "")
    return parser.text()


def dedupe_lines(text: str) -> str:
    seen = set()
    lines: List[str] = []
    for line in text.splitlines():
        normalized = " ".join(line.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        lines.append(normalized)
    return "\n\n".join(lines)


def normalize_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_github_readme_source(row: Dict[str, str], url: str) -> bool:
    source_type = clean(row.get("preferred_source_type")).lower()
    record_id = clean(row.get("record_id")).lower()
    return source_type == "github_readme" or ("github.com/" in url.lower() and "readme" in record_id)


def resolve_local_path(value: str) -> Path:
    path = Path(clean(value))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def append_note(existing: str, note: str) -> str:
    existing = clean(existing)
    note = clean(note)
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}; {note}"


def remove_stale_fetch_notes(existing: str) -> str:
    stale_prefixes = (
        "github_readme_error=",
        "fetch_error=",
        "GitHub README shorter than",
        "Fetched text shorter than",
    )
    parts = [part.strip() for part in clean(existing).split(";") if part.strip()]
    kept = [
        part
        for part in parts
        if not any(part.startswith(prefix) for prefix in stale_prefixes)
        and "NameResolutionError" not in part
    ]
    return "; ".join(kept)


def clean(value: object) -> str:
    return str(value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch open HTML/text sources for Evidence Recovery.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-pdf", action="store_true", help="Allow PDF responses but save raw decoded text only.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    rows, fields = read_tsv(args.manifest)
    summary = fetch_sources(
        rows,
        refresh=args.refresh,
        limit=args.limit,
        timeout=args.timeout,
        dry_run=args.dry_run,
        allow_pdf=args.allow_pdf,
    )
    if not args.dry_run:
        write_tsv(args.manifest, rows, fields)
    args.summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
