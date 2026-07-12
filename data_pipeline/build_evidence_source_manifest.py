from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_REVIEW_PACKET = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1.tsv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_source_manifest_v1.tsv"
)
DEFAULT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_source_manifest_v1_summary.json"
)
DEFAULT_TEXT_ROOT = PROJECT_ROOT / "data" / "evidence_sources" / "text"

FIELDNAMES = [
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
]


def read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: one_line(row.get(field, "")) for field in FIELDNAMES})


def build_manifest(packet_rows: Iterable[Dict[str, str]], text_root: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen = set()
    for packet in packet_rows:
        source_url = packet.get("source_url", "") or packet.get("suggested_source_lookup", "")
        source_key = "|".join(
            [
                packet.get("evidence_kind", ""),
                packet.get("tool_name", ""),
                packet.get("record_id", ""),
                source_url,
            ]
        )
        source_id = stable_id(source_key)
        if source_id in seen:
            continue
        seen.add(source_id)
        local_path = text_root / f"{safe_name(packet.get('tool_name', 'unknown'))}_{safe_name(packet.get('record_id', source_id))}.txt"
        rows.append(
            {
                "source_id": source_id,
                "evidence_kind": packet.get("evidence_kind", ""),
                "tool_name": packet.get("tool_name", ""),
                "record_id": packet.get("record_id", ""),
                "source_title": packet.get("source_title", ""),
                "source_url": source_url,
                "doi_or_pmid": packet.get("doi_or_pmid", ""),
                "preferred_source_type": preferred_source_type(source_url),
                "local_text_path": str(local_path.relative_to(PROJECT_ROOT)),
                "fetch_status": "not_fetched",
                "fetch_priority": packet.get("priority", ""),
                "notes": "Manual/open-source text capture target. Do not promote without review packet validation.",
            }
        )
    rows.sort(key=lambda row: (int(row["fetch_priority"] or 999), row["tool_name"], row["evidence_kind"], row["record_id"]))
    return rows


def preferred_source_type(source_url: str) -> str:
    lowered = (source_url or "").lower()
    if lowered.endswith(".pdf"):
        return "pdf_second_priority"
    if "doi.org" in lowered:
        return "doi_landing_or_open_html"
    if lowered.startswith("http"):
        return "open_html_or_official_doc"
    return "manual_lookup_required"


def summarize(rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    by_kind: Dict[str, int] = {}
    by_source_type: Dict[str, int] = {}
    for row in rows:
        by_kind[row["evidence_kind"]] = by_kind.get(row["evidence_kind"], 0) + 1
        by_source_type[row["preferred_source_type"]] = by_source_type.get(row["preferred_source_type"], 0) + 1
    return {"rows": len(rows), "by_kind": by_kind, "by_source_type": by_source_type}


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value or "").strip("_")[:90] or "unknown"


def one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source manifest for Evidence Recovery Sprint v1.")
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_REVIEW_PACKET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--text-root", type=Path, default=DEFAULT_TEXT_ROOT)
    args = parser.parse_args()

    rows = build_manifest(read_tsv(args.review_packet), args.text_root)
    write_tsv(args.output, rows)
    summary = {"output": str(args.output), **summarize(rows)}
    args.summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
