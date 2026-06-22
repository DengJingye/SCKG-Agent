from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLICATIONS_PATH = PROJECT_ROOT / "data" / "tool_publications.tsv"
BENCHMARKS_PATH = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
APPROVED_STATUSES = {"reviewed", "verified", "human_reviewed"}


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    source_kind: str
    tool_name: str
    title: str
    doi: str
    source_url: str
    task: str
    modality: str
    text: str
    metadata: Dict[str, Any]


def build_controlled_rag_context(
    *,
    constraints: Dict[str, Any],
    tool_names: Sequence[str],
    max_snippets: int = 12,
) -> Dict[str, Any]:
    """Run a minimal governed RAG pipeline over formal evidence TSVs.

    This baseline intentionally uses lexical retrieval/rerank so it works in
    offline smoke tests. It does not mutate evidence, rank tools, or promote
    candidate records.
    """

    started = time.perf_counter()
    chunks = list(_formal_chunks())
    query_terms = _query_terms(constraints=constraints, tool_names=tool_names)
    retrieved = _retrieve(chunks, query_terms)
    reranked = _rerank(retrieved, constraints=constraints, tool_names=tool_names)
    snippets = [_snippet(chunk, score) for chunk, score in reranked[:max_snippets]]
    latency_ms = (time.perf_counter() - started) * 1000
    return {
        "pipeline": [
            "formal_tsv_rows",
            "evidence_chunks",
            "offline_lexical_retrieval",
            "deterministic_rerank",
            "formal_rag_snippets",
        ],
        "mode": "offline_lexical_fallback",
        "source_tables": [
            "data/tool_publications.tsv",
            "data/tool_benchmarks.tsv",
        ],
        "selection_policy": [
            "Use formal reviewed publication/benchmark rows only.",
            "Treat snippets as explanation/provenance only; never rank from them directly.",
            "Do not promote candidate evidence or change trusted_core status.",
        ],
        "chunk_count": len(chunks),
        "retrieved_count": len(retrieved),
        "snippet_count": len(snippets),
        "latency_ms": round(latency_ms, 3),
        "matched_tools": sorted({snippet["tool_name"] for snippet in snippets if snippet.get("tool_name")}),
        "snippets": snippets,
    }


@lru_cache(maxsize=1)
def _formal_chunks() -> tuple[EvidenceChunk, ...]:
    chunks: List[EvidenceChunk] = []
    for row in _load_tsv(PUBLICATIONS_PATH):
        if _status(row.get("review_status")) not in APPROVED_STATUSES:
            continue
        text = _join_nonempty(
            row.get("title"),
            row.get("claim_span"),
            row.get("claim_text"),
            row.get("abstract"),
            row.get("task"),
            row.get("modality"),
            row.get("species"),
        )
        if not text:
            continue
        chunks.append(
            EvidenceChunk(
                chunk_id=row.get("publication_id", ""),
                source_kind="publication",
                tool_name=row.get("tool_name", ""),
                title=row.get("title", ""),
                doi=row.get("doi", ""),
                source_url=row.get("source_url", "") or row.get("paper_url", ""),
                task=row.get("task", ""),
                modality=row.get("modality", ""),
                text=text,
                metadata={
                    "review_status": row.get("review_status", ""),
                    "authority_tier": row.get("authority_tier", ""),
                    "canonical_scope": row.get("canonical_scope", ""),
                    "claim_boundary": "Explanation/provenance only; cannot promote evidence or change ranking.",
                },
            )
        )
    for row in _load_tsv(BENCHMARKS_PATH):
        if _status(row.get("review_status")) not in APPROVED_STATUSES:
            continue
        text = _join_nonempty(
            row.get("benchmark_name"),
            row.get("claim_span"),
            row.get("result_text"),
            row.get("evaluation_protocol"),
            row.get("metric"),
            row.get("task"),
            row.get("modality"),
            row.get("species"),
        )
        if not text:
            continue
        chunks.append(
            EvidenceChunk(
                chunk_id=row.get("benchmark_id", ""),
                source_kind="benchmark",
                tool_name=row.get("tool_name", ""),
                title=row.get("benchmark_name", ""),
                doi=row.get("paper_doi", ""),
                source_url=row.get("source_url", ""),
                task=row.get("task", ""),
                modality=row.get("modality", ""),
                text=text,
                metadata={
                    "review_status": row.get("review_status", ""),
                    "metric": row.get("metric", ""),
                    "rank_scope": row.get("rank_scope", ""),
                    "claim_boundary": "Explanation/provenance only; cannot promote evidence or change ranking.",
                },
            )
        )
    return tuple(chunks)


def _retrieve(
    chunks: Sequence[EvidenceChunk],
    query_terms: Set[str],
) -> List[tuple[EvidenceChunk, float]]:
    scored: List[tuple[EvidenceChunk, float]] = []
    for chunk in chunks:
        tokens = _tokens(_join_nonempty(chunk.tool_name, chunk.task, chunk.modality, chunk.title, chunk.text))
        overlap = len(tokens & query_terms)
        if overlap <= 0:
            continue
        scored.append((chunk, float(overlap) / max(len(query_terms), 1)))
    return sorted(scored, key=lambda item: (-item[1], item[0].source_kind, item[0].tool_name, item[0].chunk_id))


def _rerank(
    retrieved: Sequence[tuple[EvidenceChunk, float]],
    *,
    constraints: Dict[str, Any],
    tool_names: Sequence[str],
) -> List[tuple[EvidenceChunk, float]]:
    tool_keys = {_normalize(name) for name in tool_names if name}
    task_key = _normalize(str(constraints.get("task", "")))
    modality_key = _normalize(str(constraints.get("modality", "")))
    reranked: List[tuple[EvidenceChunk, float]] = []
    for chunk, score in retrieved:
        bonus = 0.0
        if _normalize(chunk.tool_name) in tool_keys:
            bonus += 0.55
        if task_key and task_key in _normalize(chunk.task):
            bonus += 0.2
        if modality_key and modality_key in _normalize(chunk.modality):
            bonus += 0.1
        if chunk.source_kind == "benchmark":
            bonus += 0.05
        reranked.append((chunk, round(min(score + bonus, 1.0), 4)))
    return sorted(reranked, key=lambda item: (-item[1], item[0].source_kind, item[0].tool_name, item[0].chunk_id))


def _snippet(chunk: EvidenceChunk, score: float) -> Dict[str, Any]:
    return {
        "record_id": chunk.chunk_id,
        "source_kind": chunk.source_kind,
        "tool_name": chunk.tool_name,
        "title": chunk.title,
        "doi": chunk.doi,
        "source_url": chunk.source_url,
        "task": chunk.task,
        "modality": chunk.modality,
        "claim_span": _compact(chunk.text, 240),
        "relevance_score": score,
        "claim_boundary": "Explanation/provenance only; cannot promote evidence or change ranking.",
        **chunk.metadata,
    }


def _query_terms(*, constraints: Dict[str, Any], tool_names: Sequence[str]) -> Set[str]:
    raw: List[str] = list(tool_names)
    for key in ("task", "task_family", "modality", "platform", "species", "output_goal", "data_object"):
        value = constraints.get(key)
        if isinstance(value, list):
            raw.extend(str(item) for item in value)
        elif value:
            raw.append(str(value))
    return _tokens(" ".join(raw))


def _tokens(text: str) -> Set[str]:
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_.+-]{1,}", lowered))
    tokens.update(_normalize(piece) for piece in re.split(r"[\s,;|/()]+", text) if len(_normalize(piece)) >= 2)
    return {token for token in tokens if token and token not in {"unknown", "none", "null", "na"}}


def _normalize(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _load_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _status(value: Any) -> str:
    return str(value or "").strip().lower()


def _join_nonempty(*values: Any) -> str:
    return " ".join(str(value).strip() for value in values if value and str(value).strip())


def _compact(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
