from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from engine.evidence_rag_pipeline import build_controlled_rag_context


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLICATIONS_PATH = PROJECT_ROOT / "data" / "tool_publications.tsv"
BENCHMARKS_PATH = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"

APPROVED_STATUSES = {"reviewed", "verified", "human_reviewed"}


def _load_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@lru_cache(maxsize=1)
def _publication_rows() -> tuple[Dict[str, str], ...]:
    return tuple(_load_tsv(PUBLICATIONS_PATH))


@lru_cache(maxsize=1)
def _benchmark_rows() -> tuple[Dict[str, str], ...]:
    return tuple(_load_tsv(BENCHMARKS_PATH))


def build_formal_rag_context(
    *,
    constraints: Dict[str, Any],
    tool_names: Sequence[str],
    max_snippets: int = 12,
) -> Dict[str, Any]:
    context = build_controlled_rag_context(
        constraints=constraints,
        tool_names=tool_names,
        max_snippets=max_snippets,
    )
    if context.get("snippets"):
        return context

    # Backward-compatible exact matcher for sparse queries where lexical
    # retrieval finds no overlap.
    snippets = _select_snippets(constraints=constraints, tool_names=tool_names, max_snippets=max_snippets)
    context.update(
        {
            "mode": "formal_exact_fallback",
            "retrieved_count": len(snippets),
            "snippet_count": len(snippets),
            "matched_tools": sorted({snippet["tool_name"] for snippet in snippets if snippet.get("tool_name")}),
            "snippets": snippets,
        }
    )
    return context


def _select_snippets(
    *,
    constraints: Dict[str, Any],
    tool_names: Sequence[str],
    max_snippets: int,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for row in _publication_rows():
        snippet = _publication_snippet(row, constraints, tool_names)
        if snippet:
            candidates.append(snippet)
    for row in _benchmark_rows():
        snippet = _benchmark_snippet(row, constraints, tool_names)
        if snippet:
            candidates.append(snippet)
    candidates.sort(
        key=lambda row: (
            -float(row.get("relevance_score", 0.0)),
            row.get("source_kind", ""),
            row.get("tool_name", ""),
            row.get("record_id", ""),
        )
    )
    deduped: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        deduped.setdefault(item["record_id"], item)
        if len(deduped) >= max_snippets:
            break
    return list(deduped.values())


def _publication_snippet(
    row: Dict[str, str],
    constraints: Dict[str, Any],
    tool_names: Sequence[str],
) -> Optional[Dict[str, Any]]:
    if _status(row.get("review_status")) not in APPROVED_STATUSES:
        return None
    if not _has_tool_or_task_match(row, constraints, tool_names):
        return None
    score = _relevance_score(row, constraints, tool_names)
    if score <= 0:
        return None
    claim_span = _first_nonempty(row.get("claim_span"), row.get("claim_text"), row.get("title"))
    if not claim_span:
        return None
    return {
        "record_id": row.get("publication_id", ""),
        "source_kind": "publication",
        "tool_name": row.get("tool_name", ""),
        "tool_alias": row.get("tool_alias", ""),
        "title": row.get("title", ""),
        "doi": row.get("doi", ""),
        "source_url": row.get("source_url", "") or row.get("paper_url", ""),
        "task": row.get("task", ""),
        "modality": row.get("modality", ""),
        "species": row.get("species", ""),
        "claim_span": claim_span,
        "claim_text": row.get("claim_text", ""),
        "evaluation_protocol": row.get("evaluation_protocol", ""),
        "paper_type": row.get("paper_type", ""),
        "review_status": row.get("review_status", ""),
        "authority_tier": row.get("authority_tier", ""),
        "canonical_scope": row.get("canonical_scope", ""),
        "evidence_category": row.get("evidence_category", ""),
        "relevance_score": round(score, 3),
        "claim_boundary": "Explanation/provenance only; cannot promote evidence or change ranking.",
    }


def _benchmark_snippet(
    row: Dict[str, str],
    constraints: Dict[str, Any],
    tool_names: Sequence[str],
) -> Optional[Dict[str, Any]]:
    if _status(row.get("review_status")) not in APPROVED_STATUSES:
        return None
    if not _has_tool_or_task_match(row, constraints, tool_names):
        return None
    score = _relevance_score(row, constraints, tool_names)
    if score <= 0:
        return None
    claim_span = _first_nonempty(row.get("claim_span"), row.get("result_text"), row.get("benchmark_name"))
    if not claim_span:
        return None
    return {
        "record_id": row.get("benchmark_id", ""),
        "source_kind": "benchmark",
        "tool_name": row.get("tool_name", ""),
        "tool_alias": row.get("tool_alias", ""),
        "title": row.get("benchmark_name", ""),
        "doi": row.get("paper_doi", ""),
        "source_url": row.get("source_url", ""),
        "task": row.get("task", ""),
        "modality": row.get("modality", ""),
        "species": row.get("species", ""),
        "metric": row.get("metric", ""),
        "direction": row.get("direction", ""),
        "rank_scope": row.get("rank_scope", ""),
        "n_tools_compared": row.get("n_tools_compared", ""),
        "claim_span": claim_span,
        "result_text": row.get("result_text", ""),
        "evaluation_protocol": row.get("evaluation_protocol", ""),
        "benchmark_type": row.get("benchmark_type", ""),
        "review_status": row.get("review_status", ""),
        "relevance_score": round(score, 3),
        "claim_boundary": "Explanation/provenance only; cannot promote evidence or change ranking.",
    }


def _relevance_score(row: Dict[str, str], constraints: Dict[str, Any], tool_names: Sequence[str]) -> float:
    score = 0.0
    tool_name = _normalize(row.get("tool_name", ""))
    title = _normalize(
        " ".join(
            [
                row.get("title", ""),
                row.get("benchmark_name", ""),
                row.get("paper_title", ""),
                row.get("claim_text", ""),
                row.get("result_text", ""),
                row.get("evaluation_protocol", ""),
            ]
        )
    )
    task = _normalize(constraints.get("task", ""))
    modality = _normalize(constraints.get("modality", ""))
    task_text = _normalize(
        " ".join(
            [
                row.get("task", ""),
                row.get("subtask", ""),
                row.get("paper_type", ""),
            ]
        )
    )
    modality_text = _normalize(
        " ".join(
            [
                row.get("modality", ""),
                row.get("technology", ""),
                row.get("species", ""),
            ]
        )
    )

    if tool_name and any(_normalize(name) == tool_name for name in tool_names):
        score += 0.55
    if task and task in task_text:
        score += 0.25
    if modality and modality in modality_text:
        score += 0.1
    if any(term in title for term in ("benchmark", "benchmarking", "benchmarking ")):
        score += 0.1
    return min(score, 1.0)


def _has_tool_or_task_match(
    row: Dict[str, str],
    constraints: Dict[str, Any],
    tool_names: Sequence[str],
) -> bool:
    """Keep formal RAG snippets anchored to the current context.

    Modality-only matches are too broad for user-visible KG-RAG snippets: they
    can pull unrelated scRNA-seq benchmark claims into a perturbation or
    migration report. Tool or task overlap is the minimum provenance link.
    """

    tool_name = _normalize(row.get("tool_name", ""))
    if tool_name and any(_normalize(name) == tool_name for name in tool_names):
        return True

    task = _normalize(constraints.get("task", ""))
    if not task:
        return False
    task_text = _normalize(
        " ".join(
            [
                row.get("task", ""),
                row.get("subtask", ""),
                row.get("paper_type", ""),
            ]
        )
    )
    return bool(task and task in task_text)


def _status(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _normalize(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _first_nonempty(*values: Optional[str]) -> str:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return ""
