from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.evidence_discovery_index import CHUNKS_PATH, EvidenceChunk, load_chunks, sparse_search


DEFAULT_REVIEW_PACKET = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1.tsv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1_prefilled.tsv"
)
DEFAULT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1_prefill_summary.json"
)
SOURCE_KINDS = {"source_publication", "source_benchmark", "document"}


def read_tsv(path: Path) -> tuple[List[Dict[str, str]], List[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader), list(reader.fieldnames or [])


def write_tsv(path: Path, rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: one_line(row.get(field, "")) for field in fields})


def prefill_packet(
    packet_rows: List[Dict[str, str]],
    chunks: Sequence[EvidenceChunk],
    *,
    allow_formal_fallback: bool = False,
) -> Dict[str, object]:
    summary = {
        "rows": len(packet_rows),
        "prefilled_rows": 0,
        "publication_prefilled": 0,
        "benchmark_prefilled": 0,
        "no_candidate_chunk": 0,
        "allow_formal_fallback": allow_formal_fallback,
    }
    for row in packet_rows:
        if clean(row.get("promotion_ready")).lower() == "true":
            continue
        candidate = best_chunk_for_row(row, chunks, allow_formal_fallback=allow_formal_fallback)
        if candidate is None:
            summary["no_candidate_chunk"] += 1
            continue
        changed = apply_prefill(row, candidate)
        if changed:
            summary["prefilled_rows"] += 1
            if row.get("evidence_kind") == "publication":
                summary["publication_prefilled"] += 1
            elif row.get("evidence_kind") == "benchmark":
                summary["benchmark_prefilled"] += 1
    return summary


def best_chunk_for_row(
    row: Dict[str, str],
    chunks: Sequence[EvidenceChunk],
    *,
    allow_formal_fallback: bool,
) -> EvidenceChunk | None:
    record_id = clean(row.get("record_id"))
    tool_key = normalize(row.get("tool_name", ""))
    evidence_kind = clean(row.get("evidence_kind"))
    candidate_chunks = [
        chunk
        for chunk in chunks
        if (allow_formal_fallback or chunk.source_kind in SOURCE_KINDS)
        and (not tool_key or normalize(chunk.tool_name) == tool_key)
        and (
            not record_id
            or chunk.evidence_id == record_id
            or chunk.source_record_id.startswith(f"{record_id}:")
            or chunk.source_record_id == record_id
        )
    ]
    if not candidate_chunks and not record_id:
        candidate_chunks = [
            chunk
            for chunk in chunks
            if (allow_formal_fallback or chunk.source_kind in SOURCE_KINDS)
            and (not tool_key or normalize(chunk.tool_name) == tool_key)
            and evidence_kind in chunk.source_kind
        ]
    if not candidate_chunks:
        return None
    query = query_for_row(row)
    ranked = sparse_search(candidate_chunks, query)
    sparse_scores = {chunk.chunk_id: score for chunk, score in ranked}
    scored = [
        (
            chunk,
            sparse_scores.get(chunk.chunk_id, 0.0)
            + chunk_quality_score(chunk.chunk_text, row)
            + record_match_bonus(chunk, record_id),
        )
        for chunk in candidate_chunks
    ]
    scored.sort(key=lambda item: (-item[1], item[0].chunk_id))
    return scored[0][0]


def apply_prefill(row: Dict[str, str], chunk: EvidenceChunk) -> bool:
    changed = False
    candidate_span = compact(chunk.chunk_text, 500)
    if candidate_span and not clean(row.get("source_span")):
        row["source_span"] = candidate_span
        changed = True
    if row.get("evidence_kind") == "publication" and not clean(row.get("claim_text")):
        row["claim_text"] = publication_claim(row, candidate_span)
        changed = True
    if row.get("evidence_kind") == "benchmark":
        changed = apply_benchmark_prefill(row, candidate_span) or changed
    row["reviewer_notes"] = append_note(
        row.get("reviewer_notes", ""),
        f"auto_prefill_candidate_chunk={chunk.chunk_id}; manual confirmation required",
    )
    row["promotion_ready"] = "false"
    return changed


def apply_benchmark_prefill(row: Dict[str, str], span: str) -> bool:
    changed = False
    if not clean(row.get("claim_text")):
        row["claim_text"] = compact(span, 300)
        changed = True
    if not clean(row.get("rank")):
        rank = infer_rank(span)
        if rank:
            row["rank"] = rank
            changed = True
    if not clean(row.get("normalized_score")):
        score = infer_normalized_score(span)
        if score:
            row["normalized_score"] = score
            changed = True
    return changed


def query_for_row(row: Dict[str, str]) -> str:
    values = [
        row.get("tool_name", ""),
        row.get("source_title", ""),
        row.get("task", ""),
        row.get("modality", ""),
        row.get("metric", ""),
        row.get("recovery_goal", ""),
    ]
    if row.get("evidence_kind") == "benchmark":
        values.extend(["rank", "score", "metric", "benchmark", "table", "figure"])
    else:
        values.extend(["method", "tool", "software", "workflow"])
    return " ".join(value for value in values if value)


def chunk_quality_score(text: str, row: Dict[str, str]) -> float:
    lowered = (text or "").lower()
    hard_boilerplate_phrases = [
        "advertisement view all journals search log in",
        "content explore content about the journal publish with us",
        "terms & conditions your us state privacy rights",
        "sign up for the nature briefing",
    ]
    if any(phrase in lowered for phrase in hard_boilerplate_phrases):
        return -1.0
    score = 0.0
    positive_terms = [
        "benchmark",
        "method",
        "methods",
        "single-cell",
        "scrna",
        "dataset",
        "datasets",
        "integration",
        "performance",
        "cell type",
        "rna",
        "analysis",
        "results",
        "we benchmarked",
        "we introduce",
        "we present",
        "accuracy",
        "score",
        "rank",
    ]
    negative_terms = [
        "advertisement",
        "view all journals",
        "search log in",
        "sign up for alerts",
        "privacy",
        "cookies",
        "javascript",
        "download pdf",
        "publish with us",
        "nature careers",
        "internet explorer",
    ]
    score += 0.03 * sum(1 for term in positive_terms if term in lowered)
    score -= 0.18 * sum(1 for term in negative_terms if term in lowered)
    title = clean(row.get("source_title")).lower()
    if title and title in lowered:
        score += 0.04
    if row.get("evidence_kind") == "benchmark" and any(term in lowered for term in ["table", "figure", "rank", "score"]):
        score += 0.06
    if 200 <= len(text) <= 1200:
        score += 0.04
    return score


def record_match_bonus(chunk: EvidenceChunk, record_id: str) -> float:
    if not record_id:
        return 0.0
    if chunk.evidence_id == record_id:
        return 0.08
    if chunk.source_record_id.startswith(f"{record_id}:"):
        return 0.08
    return 0.0


def publication_claim(row: Dict[str, str], span: str) -> str:
    tool = clean(row.get("tool_name"))
    task = clean(row.get("verified_task") or row.get("task"))
    modality = clean(row.get("verified_modality") or row.get("modality"))
    pieces = [f"{tool} has source-span support as a publication-linked tool"]
    if task:
        pieces.append(f"for {task}")
    if modality:
        pieces.append(f"in {modality}")
    pieces.append("pending manual confirmation")
    return " ".join(pieces) + f". Candidate span: {compact(span, 180)}"


def infer_rank(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\brank(?:ed)?\s*(?:#|no\.?|number)?\s*1\b", lowered) or "ranked first" in lowered:
        return "1"
    match = re.search(r"\brank(?:ed)?\s*(?:#|no\.?|number)?\s*(\d{1,2})\b", lowered)
    return match.group(1) if match else ""


def infer_normalized_score(text: str) -> str:
    match = re.search(r"\b(?:normalized score|score)\s*[:=]?\s*(0?\.\d+|1\.0+)\b", text.lower())
    return match.group(1) if match else ""


def append_note(existing: str, note: str) -> str:
    existing = clean(existing)
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}; {note}"


def compact(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def clean(value: object) -> str:
    return str(value or "").strip()


def normalize(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def main() -> None:
    parser = argparse.ArgumentParser(description="Prefill Evidence Recovery review packet from evidence chunks.")
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_REVIEW_PACKET)
    parser.add_argument("--chunks", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--allow-formal-fallback",
        action="store_true",
        help="Allow formal TSV chunks as fallback candidates when no source document chunks exist.",
    )
    args = parser.parse_args()

    rows, fields = read_tsv(args.review_packet)
    chunks = load_chunks(args.chunks) if args.chunks.exists() else []
    summary = prefill_packet(rows, chunks, allow_formal_fallback=args.allow_formal_fallback)
    write_tsv(args.output, rows, fields)
    summary = {"output": str(args.output), "chunks": len(chunks), **summary}
    args.summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
