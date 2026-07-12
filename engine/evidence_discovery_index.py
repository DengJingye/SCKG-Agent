from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

from core.settings import get_settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLICATIONS_PATH = PROJECT_ROOT / "data" / "tool_publications.tsv"
BENCHMARKS_PATH = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
INDEX_DIR = PROJECT_ROOT / "data" / "indexes"
CHUNKS_PATH = INDEX_DIR / "evidence_chunks.jsonl"
VECTORS_PATH = INDEX_DIR / "evidence_vectors.jsonl"
APPROVED_STATUSES = {"reviewed", "verified", "human_reviewed"}
INDEX_VERSION = "evidence-discovery-v0.1"


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    evidence_id: str
    source_kind: str
    source_table: str
    source_record_id: str
    source_id: str = ""
    source_type: str = ""
    source_span: str = ""
    tool_name: str = ""
    tool_alias: str = ""
    task: str = ""
    modality: str = ""
    species: str = ""
    work_group_id: str = ""
    canonical_flag: str = ""
    duplicate_of: str = ""
    review_status: str = ""
    trust_level: str = ""
    graph_layer: str = ""
    recommendation_eligible: str = ""
    authority_tier: str = ""
    canonical_scope: str = ""
    evidence_category: str = ""
    audit_support_level: str = ""
    doi: str = ""
    pmid: str = ""
    source_url: str = ""
    title: str = ""
    claim_text: str = ""
    claim_span: str = ""
    chunk_text: str = ""
    claim_boundary: str = "Retrieval/discovery only; cannot promote evidence or change ranking."
    use_for: List[str] = field(default_factory=lambda: ["retrieval"])
    kg_version: str = "v0.1"
    embedding_version: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class EvidenceChunkRecord:
    chunk: EvidenceChunk
    dense_vector: Optional[List[float]]
    sparse_terms: List[str]
    content_hash: str
    index_version: str
    embedding_provider: str
    embedding_model: str
    indexed_at: str


def build_formal_tsv_chunks(
    publications_path: Path = PUBLICATIONS_PATH,
    benchmarks_path: Path = BENCHMARKS_PATH,
) -> List[EvidenceChunk]:
    chunks: List[EvidenceChunk] = []
    if publications_path.exists():
        chunks.extend(publication_chunks(read_tsv(publications_path)))
    if benchmarks_path.exists():
        chunks.extend(benchmark_chunks(read_tsv(benchmarks_path)))
    return chunks


def publication_chunks(rows: Iterable[Dict[str, str]]) -> List[EvidenceChunk]:
    chunks: List[EvidenceChunk] = []
    for row in rows:
        if status(row.get("review_status")) not in APPROVED_STATUSES:
            continue
        text = join_nonempty(
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
        record_id = clean(row.get("publication_id")) or stable_id("publication", text)
        chunks.append(
            EvidenceChunk(
                chunk_id=f"publication:{record_id}",
                evidence_id=record_id,
                source_id=record_id,
                source_type="formal_publication_tsv",
                source_span=clean(row.get("claim_span")) or clean(row.get("title")),
                source_kind="publication",
                source_table="data/tool_publications.tsv",
                source_record_id=record_id,
                tool_name=clean(row.get("tool_name")),
                tool_alias=clean(row.get("tool_alias")),
                task=clean(row.get("task")),
                modality=clean(row.get("modality")),
                species=clean(row.get("species")),
                work_group_id=clean(row.get("work_group_id")),
                canonical_flag=clean(row.get("canonical_flag")),
                duplicate_of=clean(row.get("duplicate_of")),
                review_status=clean(row.get("review_status")),
                trust_level=clean(row.get("trust_level")),
                graph_layer=clean(row.get("graph_layer")),
                recommendation_eligible=clean(row.get("recommendation_eligible")),
                authority_tier=clean(row.get("authority_tier")),
                canonical_scope=clean(row.get("canonical_scope")),
                evidence_category=clean(row.get("evidence_category")),
                audit_support_level=clean(row.get("audit_support_level")),
                doi=clean(row.get("doi")),
                pmid=clean(row.get("pmid")),
                source_url=clean(row.get("source_url")) or clean(row.get("paper_url")),
                title=clean(row.get("title")),
                claim_text=clean(row.get("claim_text")),
                claim_span=clean(row.get("claim_span")),
                chunk_text=text,
                kg_version=clean(row.get("kg_version")) or "v0.1",
                embedding_version=get_settings().embedding_version,
                created_at=clean(row.get("created_at")),
            )
        )
    return chunks


def benchmark_chunks(rows: Iterable[Dict[str, str]]) -> List[EvidenceChunk]:
    chunks: List[EvidenceChunk] = []
    for row in rows:
        if status(row.get("review_status")) not in APPROVED_STATUSES:
            continue
        text = join_nonempty(
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
        record_id = clean(row.get("benchmark_id")) or stable_id("benchmark", text)
        chunks.append(
            EvidenceChunk(
                chunk_id=f"benchmark:{record_id}",
                evidence_id=record_id,
                source_id=record_id,
                source_type="formal_benchmark_tsv",
                source_span=clean(row.get("claim_span")) or clean(row.get("benchmark_name")),
                source_kind="benchmark",
                source_table="data/tool_benchmarks.tsv",
                source_record_id=record_id,
                tool_name=clean(row.get("tool_name")),
                tool_alias=clean(row.get("tool_alias")),
                task=clean(row.get("task")),
                modality=clean(row.get("modality")),
                species=clean(row.get("species")),
                work_group_id=clean(row.get("work_group_id")),
                canonical_flag=clean(row.get("canonical_flag")),
                duplicate_of=clean(row.get("duplicate_of")),
                review_status=clean(row.get("review_status")),
                trust_level=clean(row.get("trust_level")),
                doi=clean(row.get("paper_doi")),
                pmid=clean(row.get("paper_pmid")),
                source_url=clean(row.get("source_url")),
                title=clean(row.get("benchmark_name")) or clean(row.get("paper_title")),
                claim_text=clean(row.get("result_text")),
                claim_span=clean(row.get("claim_span")),
                chunk_text=text,
                kg_version=clean(row.get("kg_version")) or "v0.1",
                embedding_version=get_settings().embedding_version,
                created_at=clean(row.get("created_at")),
            )
        )
    return chunks


def document_chunks(document_paths: Iterable[Path]) -> List[EvidenceChunk]:
    chunks: List[EvidenceChunk] = []
    for path in document_paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for idx, paragraph in enumerate(split_paragraphs(text), start=1):
            record_id = f"{path.stem}:{idx}"
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"document:{stable_id(str(path), paragraph)}",
                    evidence_id=record_id,
                    source_id=str(path),
                    source_type="local_document",
                    source_span=f"paragraph:{idx}",
                    source_kind="document",
                    source_table=str(path),
                    source_record_id=record_id,
                    title=path.name,
                    chunk_text=paragraph,
                    source_url=str(path),
                    review_status="unreviewed",
                    trust_level="source_based",
                    graph_layer="review_needed",
                    embedding_version=get_settings().embedding_version,
                )
            )
    return chunks


def source_manifest_chunks(manifest_path: Path) -> List[EvidenceChunk]:
    chunks: List[EvidenceChunk] = []
    if not manifest_path.exists():
        return chunks
    for row in read_tsv(manifest_path):
        local_path = clean(row.get("local_text_path"))
        if not local_path:
            continue
        path = Path(local_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for idx, paragraph in enumerate(split_paragraphs(text), start=1):
            if is_boilerplate_paragraph(paragraph):
                continue
            record_id = f"{clean(row.get('record_id'))}:{idx}"
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"source:{stable_id('source', clean(row.get('source_id')) + ':' + str(idx) + ':' + paragraph)}",
                    evidence_id=clean(row.get("record_id")),
                    source_id=clean(row.get("source_id")),
                    source_type=clean(row.get("preferred_source_type")) or clean(row.get("evidence_kind")),
                    source_span=f"paragraph:{idx}",
                    source_kind=f"source_{clean(row.get('evidence_kind')) or 'document'}",
                    source_table=str(manifest_path.relative_to(PROJECT_ROOT))
                    if manifest_path.is_relative_to(PROJECT_ROOT)
                    else str(manifest_path),
                    source_record_id=record_id,
                    tool_name=clean(row.get("tool_name")),
                    source_url=clean(row.get("source_url")),
                    title=clean(row.get("source_title")) or Path(local_path).name,
                    claim_text="",
                    claim_span="",
                    chunk_text=paragraph,
                    claim_boundary=(
                        "Evidence discovery chunk only; manual review packet validation is required before promotion."
                    ),
                    review_status="unreviewed",
                    trust_level="source_based",
                    graph_layer="review_needed",
                    embedding_version=get_settings().embedding_version,
                )
            )
    return chunks


def write_indexes(
    chunks: Sequence[EvidenceChunk],
    *,
    chunks_path: Path = CHUNKS_PATH,
    vectors_path: Path = VECTORS_PATH,
    with_embeddings: bool = False,
) -> Dict[str, Any]:
    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    vector_rows: List[Dict[str, Any]] = []
    with chunks_path.open("w", encoding="utf-8") as chunk_handle:
        for chunk in chunks:
            chunk_handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
            if with_embeddings:
                vector = embed_text(chunk.chunk_text)
                if vector:
                    vector_rows.append({"chunk_id": chunk.chunk_id, "dense_vector": vector})
    with vectors_path.open("w", encoding="utf-8") as vector_handle:
        for row in vector_rows:
            vector_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "chunks": len(chunks),
        "vectors": len(vector_rows),
        "chunks_path": str(chunks_path),
        "vectors_path": str(vectors_path),
        "embedding_model": settings.embedding_model,
    }


def search_hybrid_evidence(
    *,
    constraints: Dict[str, Any],
    tool_names: Sequence[str],
    max_snippets: int = 12,
    chunks_path: Path = CHUNKS_PATH,
    vectors_path: Path = VECTORS_PATH,
) -> Dict[str, Any]:
    started = time.perf_counter()
    chunks = load_chunks(chunks_path) if chunks_path.exists() else build_formal_tsv_chunks()
    vector_by_chunk = load_vectors(vectors_path) if vectors_path.exists() else {}
    query_text = query_string(constraints=constraints, tool_names=tool_names)
    sparse_ranked = sparse_search(chunks, query_text)
    dense_ranked = dense_search(chunks, query_text, vector_by_chunk) if vector_by_chunk else []
    fused = rrf_fusion(sparse_ranked, dense_ranked)
    reranked = governance_rerank(fused, constraints=constraints, tool_names=tool_names)
    snippets = [snippet_from_chunk(chunk, score) for chunk, score in reranked[:max_snippets]]
    latency_ms = (time.perf_counter() - started) * 1000
    return {
        "pipeline": [
            "evidence_chunks_jsonl" if chunks_path.exists() else "formal_tsv_rows",
            "sparse_evidence_retrieval",
            "dense_evidence_retrieval" if dense_ranked else "dense_evidence_retrieval_skipped",
            "rrf_fusion",
            "governance_aware_rerank",
            "retrieval_context",
        ],
        "mode": "local_hybrid_evidence_retrieval",
        "index_version": INDEX_VERSION,
        "source_tables": sorted({chunk.source_table for chunk in chunks}),
        "selection_policy": [
            "Use chunks for evidence discovery only.",
            "Do not promote retrieved chunks into formal evidence.",
            "Do not let RAG chunks change MCDM ranking directly.",
        ],
        "chunk_count": len(chunks),
        "retrieved_count": len(reranked),
        "snippet_count": len(snippets),
        "latency_ms": round(latency_ms, 3),
        "matched_tools": sorted({snippet["tool_name"] for snippet in snippets if snippet.get("tool_name")}),
        "snippets": snippets,
    }


def load_chunks(path: Path) -> List[EvidenceChunk]:
    chunks: List[EvidenceChunk] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                chunks.append(EvidenceChunk(**json.loads(line)))
    return chunks


def load_vectors(path: Path) -> Dict[str, List[float]]:
    vectors: Dict[str, List[float]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            vector = row.get("dense_vector")
            if isinstance(vector, list):
                vectors[str(row.get("chunk_id"))] = [float(value) for value in vector]
    return vectors


def sparse_search(chunks: Sequence[EvidenceChunk], query: str) -> List[tuple[EvidenceChunk, float]]:
    query_terms = set(terms(query))
    if not query_terms:
        return []
    scored: List[tuple[EvidenceChunk, float]] = []
    for chunk in chunks:
        chunk_terms = set(terms(join_nonempty(chunk.tool_name, chunk.task, chunk.modality, chunk.title, chunk.chunk_text)))
        overlap = len(query_terms & chunk_terms)
        if overlap <= 0:
            continue
        scored.append((chunk, overlap / max(len(query_terms), 1)))
    return sorted(scored, key=lambda item: (-item[1], item[0].chunk_id))


def dense_search(
    chunks: Sequence[EvidenceChunk],
    query: str,
    vector_by_chunk: Dict[str, List[float]],
) -> List[tuple[EvidenceChunk, float]]:
    query_vector = embed_text(query)
    if not query_vector:
        return []
    scored: List[tuple[EvidenceChunk, float]] = []
    for chunk in chunks:
        vector = vector_by_chunk.get(chunk.chunk_id)
        if not vector:
            continue
        score = cosine(query_vector, vector)
        if score > 0:
            scored.append((chunk, score))
    return sorted(scored, key=lambda item: (-item[1], item[0].chunk_id))


def rrf_fusion(
    sparse_ranked: Sequence[tuple[EvidenceChunk, float]],
    dense_ranked: Sequence[tuple[EvidenceChunk, float]],
    k: int = 60,
) -> List[tuple[EvidenceChunk, float]]:
    by_id: Dict[str, tuple[EvidenceChunk, float]] = {}
    for ranked in (sparse_ranked, dense_ranked):
        for rank, (chunk, _) in enumerate(ranked, start=1):
            previous = by_id.get(chunk.chunk_id, (chunk, 0.0))[1]
            by_id[chunk.chunk_id] = (chunk, previous + 1.0 / (k + rank))
    return sorted(by_id.values(), key=lambda item: (-item[1], item[0].chunk_id))


def governance_rerank(
    fused: Sequence[tuple[EvidenceChunk, float]],
    *,
    constraints: Dict[str, Any],
    tool_names: Sequence[str],
) -> List[tuple[EvidenceChunk, float]]:
    tool_keys = {normalize(name) for name in tool_names if name}
    task_key = normalize(str(constraints.get("task", "")))
    modality_key = normalize(str(constraints.get("modality", "")))
    reranked: List[tuple[EvidenceChunk, float]] = []
    for chunk, score in fused:
        bonus = 0.0
        penalty = 0.0
        if normalize(chunk.tool_name) in tool_keys:
            bonus += 0.08
        if task_key and task_key in normalize(chunk.task):
            bonus += 0.04
        if modality_key and modality_key in normalize(chunk.modality):
            bonus += 0.03
        if chunk.review_status.lower() in APPROVED_STATUSES:
            bonus += 0.03
        if chunk.canonical_flag.lower() == "true":
            bonus += 0.02
        if chunk.graph_layer.lower() in {"experimental", "review_needed"}:
            penalty += 0.04
        reranked.append((chunk, round(max(score + bonus - penalty, 0.0), 6)))
    return sorted(reranked, key=lambda item: (-item[1], item[0].source_kind, item[0].tool_name, item[0].chunk_id))


def snippet_from_chunk(chunk: EvidenceChunk, score: float) -> Dict[str, Any]:
    return {
        "record_id": chunk.source_record_id,
        "chunk_id": chunk.chunk_id,
        "source_id": chunk.source_id,
        "source_type": chunk.source_type,
        "source_span": chunk.source_span,
        "source_kind": chunk.source_kind,
        "tool_name": chunk.tool_name,
        "title": chunk.title,
        "doi": chunk.doi,
        "source_url": chunk.source_url,
        "task": chunk.task,
        "modality": chunk.modality,
        "claim_span": compact(chunk.claim_span or chunk.chunk_text, 260),
        "relevance_score": round(score, 6),
        "claim_boundary": chunk.claim_boundary,
        "review_status": chunk.review_status,
        "trust_level": chunk.trust_level,
        "recommendation_eligible": chunk.recommendation_eligible,
    }


def embed_text(text: str) -> List[float]:
    if not text:
        return []
    settings = get_settings()
    try:
        api_key = settings.require_embedding_api_key()
    except RuntimeError:
        return []
    payload = {"model": settings.embedding_model, "input": text}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        response = requests.post(settings.embedding_api_base, json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        return [float(value) for value in response.json()["data"][0]["embedding"]]
    except Exception:
        return []


def query_string(*, constraints: Dict[str, Any], tool_names: Sequence[str]) -> str:
    values: List[str] = list(tool_names)
    for key in ("task", "task_family", "modality", "platform", "species", "output_goal", "data_object"):
        value = constraints.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value:
            values.append(str(value))
    return " ".join(values)


def read_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def split_paragraphs(text: str) -> List[str]:
    return [
        " ".join(part.split())
        for part in re.split(r"\n\s*\n+", text)
        if len(" ".join(part.split())) >= 80
    ]


def is_boilerplate_paragraph(text: str) -> bool:
    lowered = (text or "").lower()
    hard_boilerplate_phrases = [
        "advertisement view all journals search log in",
        "content explore content about the journal publish with us",
        "terms & conditions your us state privacy rights",
        "sign up for the nature briefing",
    ]
    if any(phrase in lowered for phrase in hard_boilerplate_phrases):
        return True
    markers = {
        "advertisement",
        "view all journals",
        "search log in",
        "sign up for alerts",
        "rss feed",
        "privacy",
        "cookies",
        "javascript",
        "download pdf",
        "publish with us",
        "nature careers",
        "internet explorer",
        "without styles",
    }
    marker_hits = sum(1 for marker in markers if marker in lowered)
    scientific_markers = {
        "benchmark",
        "method",
        "single-cell",
        "scrna",
        "dataset",
        "integration",
        "performance",
        "cell type",
        "rna",
        "analysis",
        "result",
        "metric",
    }
    scientific_hits = sum(1 for marker in scientific_markers if marker in lowered)
    return marker_hits >= 2 and scientific_hits <= 2


def terms(text: str) -> List[str]:
    lowered = (text or "").lower()
    raw = re.findall(r"[a-z0-9][a-z0-9_.+-]{1,}", lowered)
    raw.extend(normalize(piece) for piece in re.split(r"[\s,;|/()]+", text) if len(normalize(piece)) >= 2)
    return [token for token in raw if token and token not in {"unknown", "none", "null", "na"}]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def stable_id(prefix: str, text: str) -> str:
    return f"{prefix}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def status(value: Any) -> str:
    return str(value or "").strip().lower()


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def join_nonempty(*values: Any) -> str:
    return " ".join(str(value).strip() for value in values if value and str(value).strip())


def compact(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
