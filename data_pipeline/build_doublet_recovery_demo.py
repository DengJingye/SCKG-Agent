from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from urllib.parse import quote

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.trace_context import DEFAULT_TRACE_PATH, load_traces
from data_pipeline.fetch_evidence_sources import fetch_sources
from engine.evidence_discovery_index import (
    EvidenceChunk,
    build_formal_tsv_chunks,
    compact,
    governance_rerank,
    query_string,
    rrf_fusion,
    source_manifest_chunks,
    sparse_search,
    snippet_from_chunk,
)


BENCHMARK_AUDIT = PROJECT_ROOT / "data" / "evidence_candidates" / "formal_benchmark_audit.tsv"
PUBLICATION_AUDIT = PROJECT_ROOT / "data" / "evidence_candidates" / "formal_publication_audit.tsv"
OUTPUT_JSON = PROJECT_ROOT / "data" / "evidence_candidates" / "doublet_detection_recovery_demo.json"
OUTPUT_TSV = PROJECT_ROOT / "data" / "evidence_candidates" / "doublet_detection_recovery_demo.tsv"
SOURCE_MANIFEST = PROJECT_ROOT / "data" / "evidence_candidates" / "doublet_detection_source_manifest.tsv"
TEXT_ROOT = PROJECT_ROOT / "data" / "evidence_sources" / "text"
TARGET_TOOLS = ["Scrublet", "DoubletFinder"]
TARGET_CONSTRAINTS = {
    "task": "Doublet Detection",
    "task_family": "QC",
    "modality": "scRNA-seq",
    "platform": "10x Genomics",
    "species": "Human",
    "output_goal": "doublet detection with benchmark evidence",
    "strictness": "strict",
}

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
]

STATUS_FIELDS = [
    "tool_name",
    "evidence_kind",
    "record_id",
    "source_title",
    "source_url",
    "runtime_recommendation_allowed",
    "audit_labels",
    "metric",
    "rank",
    "score",
    "source_text_status",
    "source_fetch_status",
    "source_text_chars",
    "promotion_status",
    "promotion_blockers",
    "next_action",
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


def build_source_manifest_rows(
    publication_rows: Sequence[Dict[str, str]],
    benchmark_rows: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for row in publication_rows:
        source_url = row.get("source_url") or row.get("paper_url") or ""
        record_id = row.get("publication_id", "")
        rows.append(
            source_row(
                evidence_kind="publication",
                tool_name=row.get("tool_name", ""),
                record_id=record_id,
                source_title=row.get("title", ""),
                source_url=source_url,
                doi_or_pmid=row.get("doi") or row.get("pmid") or "",
                priority="1",
            )
        )
    for row in benchmark_rows:
        source_url = row.get("source_url", "")
        record_id = row.get("benchmark_id", "")
        rows.append(
            source_row(
                evidence_kind="benchmark",
                tool_name=row.get("tool_name", ""),
                record_id=record_id,
                source_title=row.get("benchmark_name", ""),
                source_url=source_url,
                doi_or_pmid=row.get("paper_doi", ""),
                priority="2",
            )
        )
    rows.sort(key=lambda item: (item["tool_name"].lower(), item["evidence_kind"], item["record_id"]))
    return rows


def source_row(
    *,
    evidence_kind: str,
    tool_name: str,
    record_id: str,
    source_title: str,
    source_url: str,
    doi_or_pmid: str,
    priority: str,
) -> Dict[str, str]:
    local_path = TEXT_ROOT / f"{safe_name(tool_name)}_{safe_name(record_id)}.txt"
    source_id = stable_id("|".join([evidence_kind, tool_name, record_id, source_url]))
    return {
        "source_id": source_id,
        "evidence_kind": evidence_kind,
        "tool_name": tool_name,
        "record_id": record_id,
        "source_title": source_title,
        "source_url": source_url,
        "doi_or_pmid": doi_or_pmid,
        "preferred_source_type": preferred_source_type(source_url),
        "local_text_path": str(local_path.relative_to(PROJECT_ROOT)),
        "fetch_status": "not_fetched",
        "fetch_priority": priority,
        "notes": "Doublet recovery demo source. Discovery only; not promotion evidence.",
    }


def build_status_rows(
    publication_rows: Sequence[Dict[str, str]],
    benchmark_rows: Sequence[Dict[str, str]],
    manifest_rows: Sequence[Dict[str, str]],
) -> List[Dict[str, Any]]:
    manifest_by_record = {row["record_id"]: row for row in manifest_rows}
    rows: List[Dict[str, Any]] = []
    for row in publication_rows:
        record_id = row.get("publication_id", "")
        source = manifest_by_record.get(record_id, {})
        blockers = publication_blockers(row, source)
        rows.append(
            {
                "tool_name": row.get("tool_name", ""),
                "evidence_kind": "publication",
                "record_id": record_id,
                "source_title": row.get("title", ""),
                "source_url": row.get("source_url") or row.get("paper_url") or "",
                "runtime_recommendation_allowed": row.get("runtime_recommendation_allowed", ""),
                "audit_labels": row.get("audit_labels", ""),
                "metric": "",
                "rank": "",
                "score": "",
                "source_text_status": source_text_status(source),
                "source_fetch_status": source.get("fetch_status", ""),
                "source_text_chars": source_text_chars(source),
                "promotion_status": "blocked" if blockers else "review_ready",
                "promotion_blockers": "; ".join(blockers),
                "next_action": publication_next_action(blockers),
            }
        )
    for row in benchmark_rows:
        record_id = row.get("benchmark_id", "")
        source = manifest_by_record.get(record_id, {})
        blockers = benchmark_blockers(row, source)
        rows.append(
            {
                "tool_name": row.get("tool_name", ""),
                "evidence_kind": "benchmark",
                "record_id": record_id,
                "source_title": row.get("benchmark_name", ""),
                "source_url": row.get("source_url", ""),
                "runtime_recommendation_allowed": row.get("runtime_recommendation_allowed", ""),
                "audit_labels": row.get("audit_labels", ""),
                "metric": row.get("metric", ""),
                "rank": row.get("rank", ""),
                "score": row.get("score", ""),
                "source_text_status": source_text_status(source),
                "source_fetch_status": source.get("fetch_status", ""),
                "source_text_chars": source_text_chars(source),
                "promotion_status": "blocked" if blockers else "review_ready",
                "promotion_blockers": "; ".join(blockers),
                "next_action": benchmark_next_action(blockers),
            }
        )
    return rows


def publication_blockers(row: Dict[str, str], source: Dict[str, str]) -> List[str]:
    blockers: List[str] = []
    labels = row.get("audit_labels", "")
    if row.get("runtime_recommendation_allowed", "").lower() != "true":
        blockers.append("runtime_gate_false")
    if "title_only_claim_span" in labels or not row.get("claim_span"):
        blockers.append("source_span_missing_or_title_only")
    if "reviewer_identity_unclear" in labels or row.get("reviewed_by", "").lower() in {"", "human_review"}:
        blockers.append("traceable_reviewer_missing")
    if not local_text_exists(source):
        blockers.append("source_text_not_available")
    elif metadata_text_only(source):
        blockers.append("source_text_metadata_only")
    return blockers


def benchmark_blockers(row: Dict[str, str], source: Dict[str, str]) -> List[str]:
    blockers: List[str] = []
    labels = row.get("audit_labels", "")
    if row.get("runtime_recommendation_allowed", "").lower() != "true":
        blockers.append("runtime_gate_false")
    if "qualitative_only" in labels:
        blockers.append("qualitative_only")
    if "missing_source_span" in labels or not row.get("claim_span"):
        blockers.append("source_span_missing")
    if not any(row.get(field) for field in ("rank", "score", "normalized_score")):
        blockers.append("numeric_rank_or_score_missing")
    if not (row.get("rank_scope") or row.get("n_tools_compared")):
        blockers.append("rank_scope_missing")
    if not local_text_exists(source):
        blockers.append("source_text_not_available")
    elif metadata_text_only(source):
        blockers.append("source_text_metadata_only")
    return blockers


def build_retrieval_snippets(manifest_path: Path) -> Dict[str, Any]:
    target_keys = {normalize(tool) for tool in TARGET_TOOLS}
    chunks: List[EvidenceChunk] = [
        chunk for chunk in build_formal_tsv_chunks()
        if normalize(chunk.tool_name) in target_keys
    ]
    source_chunks = source_manifest_chunks(manifest_path)
    chunks.extend(chunk for chunk in source_chunks if normalize(chunk.tool_name) in target_keys)
    query = query_string(constraints=TARGET_CONSTRAINTS, tool_names=TARGET_TOOLS)
    sparse_ranked = sparse_search(chunks, query)
    fused = rrf_fusion(sparse_ranked, [])
    reranked = governance_rerank(fused, constraints=TARGET_CONSTRAINTS, tool_names=TARGET_TOOLS)
    snippets = [snippet_from_chunk(chunk, score) for chunk, score in reranked[:12]]
    return {
        "query": query,
        "chunk_count": len(chunks),
        "source_chunk_count": len(source_chunks),
        "snippet_count": len(snippets),
        "matched_tools": sorted({item.get("tool_name") for item in snippets if item.get("tool_name")}),
        "snippets": snippets,
    }


def latest_kg_gate_snapshot() -> Dict[str, Any]:
    traces = [trace for trace in load_traces(DEFAULT_TRACE_PATH) if trace.get("trace_type") == "agent_run"]
    if not traces:
        return {}
    traces.sort(key=lambda item: item.get("started_at", ""), reverse=True)
    for trace in traces:
        for stage in trace.get("stages", []):
            if stage.get("stage") != "kg_hard_filter":
                continue
            output = ((stage.get("data") or {}).get("output_summary") or {})
            raw_tools = output.get("raw_candidate_tools") or []
            if any(tool in raw_tools for tool in TARGET_TOOLS):
                return {
                    "trace_id": trace.get("trace_id", ""),
                    "query": (trace.get("metadata") or {}).get("query", ""),
                    "provider": output.get("provider", ""),
                    "raw_candidate_count": output.get("raw_candidate_count", 0),
                    "admitted_candidate_count": output.get("candidate_tool_count", 0),
                    "blocked_reason_counts": output.get("blocked_reason_counts") or {},
                    "target_tools_seen": [tool for tool in TARGET_TOOLS if tool in raw_tools],
                    "target_tool_diagnostics": [
                        item
                        for item in output.get("candidate_diagnostics", [])
                        if item.get("tool_name") in TARGET_TOOLS
                    ],
                }
    return {}


def run_demo(*, fetch_live: bool, refresh: bool, timeout: int) -> Dict[str, Any]:
    publications = [
        row for row in read_tsv(PUBLICATION_AUDIT)
        if row.get("tool_name") in TARGET_TOOLS
    ]
    benchmarks = [
        row for row in read_tsv(BENCHMARK_AUDIT)
        if row.get("tool_name") in TARGET_TOOLS
        and row.get("task") == TARGET_CONSTRAINTS["task"]
    ]
    manifest_rows = build_source_manifest_rows(publications, benchmarks)
    if fetch_live:
        fetch_sources(manifest_rows, refresh=refresh, timeout=timeout, dry_run=False)
        fetch_crossref_metadata_fallback(manifest_rows, refresh=refresh, timeout=timeout)
    write_tsv(SOURCE_MANIFEST, manifest_rows, SOURCE_FIELDS)
    status_rows = build_status_rows(publications, benchmarks, manifest_rows)
    write_tsv(OUTPUT_TSV, status_rows, STATUS_FIELDS)
    retrieval = build_retrieval_snippets(SOURCE_MANIFEST)
    summary = {
        "demo": "doublet_detection_evidence_recovery",
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "target_tools": TARGET_TOOLS,
        "constraints": TARGET_CONSTRAINTS,
        "fetch_live": fetch_live,
        "source_manifest": str(SOURCE_MANIFEST.relative_to(PROJECT_ROOT)),
        "status_tsv": str(OUTPUT_TSV.relative_to(PROJECT_ROOT)),
        "formal_rows": len(status_rows),
        "publication_rows": len(publications),
        "benchmark_rows": len(benchmarks),
        "source_text_available": sum(1 for row in manifest_rows if local_text_exists(row)),
        "promotion_ready_count": sum(1 for row in status_rows if row["promotion_status"] == "review_ready"),
        "blocked_count": sum(1 for row in status_rows if row["promotion_status"] == "blocked"),
        "kg_gate_snapshot": latest_kg_gate_snapshot(),
        "formal_evidence_status": status_rows,
        "retrieval": retrieval,
        "source_manifest_rows": manifest_rows,
        "guardrail": (
            "This demo is evidence discovery only. It does not edit formal TSV, Neo4j, "
            "MCDM ranking, or trusted recommendation evidence."
        ),
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return summary


def source_text_status(source: Dict[str, str]) -> str:
    if not source:
        return "missing_manifest"
    if local_text_exists(source):
        if metadata_text_only(source):
            return "metadata_text_available"
        return "local_text_available"
    return source.get("fetch_status") or "not_fetched"


def source_text_chars(source: Dict[str, str]) -> int:
    path = resolve_local_path(source.get("local_text_path", "")) if source else None
    if not path or not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8", errors="ignore"))


def fetch_crossref_metadata_fallback(
    rows: List[Dict[str, str]],
    *,
    refresh: bool,
    timeout: int,
) -> None:
    for row in rows:
        local_path = resolve_local_path(row.get("local_text_path", ""))
        if local_path.exists() and local_path.stat().st_size > 0 and not refresh:
            continue
        doi = clean(row.get("doi_or_pmid"))
        if not doi or "/" not in doi:
            continue
        try:
            response = requests.get(
                f"https://api.crossref.org/works/{quote(doi, safe='')}",
                headers={"User-Agent": "scKG-Agent evidence recovery metadata fallback"},
                timeout=timeout,
            )
            response.raise_for_status()
            message = response.json().get("message") or {}
            text = crossref_message_to_text(message, row)
            if len(text) < 120:
                row["notes"] = append_note(row.get("notes", ""), "crossref metadata shorter than 120 chars")
                continue
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(text, encoding="utf-8")
            row["fetch_status"] = "crossref_metadata_text"
            row["notes"] = append_note(
                row.get("notes", ""),
                "Crossref metadata fallback saved; metadata only, not full-text source span",
            )
        except Exception as exc:
            row["notes"] = append_note(
                row.get("notes", ""),
                f"crossref_fallback_error={type(exc).__name__}: {exc}",
            )


def crossref_message_to_text(message: Dict[str, Any], row: Dict[str, str]) -> str:
    title = first(message.get("title")) or row.get("source_title", "")
    abstract = strip_markup(message.get("abstract", ""))
    container = first(message.get("container-title"))
    published = (
        ((message.get("published-print") or message.get("published-online") or {}).get("date-parts") or [[""]])[0]
    )
    published_text = "-".join(str(part) for part in published if part)
    subjects = "; ".join(message.get("subject") or [])
    parts = [
        f"Title: {title}",
        f"Evidence kind: {row.get('evidence_kind', '')}",
        f"Tool: {row.get('tool_name', '')}",
        f"DOI: {message.get('DOI') or row.get('doi_or_pmid', '')}",
        f"Type: {message.get('type', '')}",
        f"Container: {container}",
        f"Published: {published_text}",
        f"URL: {message.get('URL') or row.get('source_url', '')}",
        f"Subjects: {subjects}",
        f"Reference count: {message.get('reference-count', '')}",
        f"Abstract: {abstract}",
        (
            "Boundary: Crossref metadata is evidence discovery text only. It is not a verified "
            "figure/table/section source span and cannot promote evidence."
        ),
    ]
    return "\n\n".join(part for part in parts if part and not part.endswith(": "))


def local_text_exists(source: Dict[str, str]) -> bool:
    path = resolve_local_path(source.get("local_text_path", "")) if source else None
    return bool(path and path.exists() and path.stat().st_size > 0)


def metadata_text_only(source: Dict[str, str]) -> bool:
    if source.get("fetch_status") == "crossref_metadata_text":
        return True
    path = resolve_local_path(source.get("local_text_path", "")) if source else None
    if not path or not path.exists():
        return False
    sample = path.read_text(encoding="utf-8", errors="ignore")[:1200]
    return "Crossref metadata is evidence discovery text only" in sample


def resolve_local_path(value: str) -> Path:
    path = Path(value or "")
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def publication_next_action(blockers: Sequence[str]) -> str:
    if "source_text_metadata_only" in blockers:
        return "open full source and confirm non-title method claim span"
    if "source_text_not_available" in blockers:
        return "fetch/open source text, then identify non-title source span"
    if "traceable_reviewer_missing" in blockers:
        return "assign traceable reviewer id and confirm claim span"
    return "ready for human promotion review"


def benchmark_next_action(blockers: Sequence[str]) -> str:
    if "source_text_metadata_only" in blockers:
        return "open full paper/figure/table; metadata is not enough for numeric benchmark promotion"
    if "source_text_not_available" in blockers:
        return "fetch/open benchmark source text, then inspect figure/table/section"
    if "numeric_rank_or_score_missing" in blockers:
        return "recover AUPRC rank/score or keep benchmark_result retrieval-only"
    return "ready for human promotion review"


def preferred_source_type(source_url: str) -> str:
    lowered = (source_url or "").lower()
    if lowered.endswith(".pdf"):
        return "pdf_second_priority"
    if "doi.org" in lowered:
        return "doi_landing_or_open_html"
    if lowered.startswith("http"):
        return "open_html_or_official_doc"
    return "manual_lookup_required"


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in (value or ""))[:90] or "unknown"


def normalize(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def one_line(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return " ".join(str(value or "").split())


def append_note(existing: str, note: str) -> str:
    existing = clean(existing)
    note = clean(note)
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}; {note}"


def strip_markup(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(text.split())


def first(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0] or "")
    return str(value or "")


def clean(value: object) -> str:
    return str(value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a visible Doublet Detection evidence recovery demo.")
    parser.add_argument("--fetch-live", action="store_true", help="Fetch DOI/open HTML source pages before building demo.")
    parser.add_argument("--refresh", action="store_true", help="Refetch source text even if local files exist.")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    summary = run_demo(fetch_live=args.fetch_live, refresh=args.refresh, timeout=args.timeout)
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
