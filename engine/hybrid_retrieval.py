from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

import numpy as np

from core.canonical_task_ontology import (
    canonical_task,
    canonical_task_for_text,
    canonical_task_ids_for_tool,
)
from core.knowledge_intelligence_models import (
    ChatStageTiming,
    EmbeddingWorkerStatus,
    HybridRetrievalHit,
    HybridRetrievalRequest,
    HybridRetrievalResult,
    RetrievalCoverageReport,
)
from core.settings import PROJECT_ROOT
from engine.evidence_discovery_index import EvidenceChunk, load_chunks
from engine.knowledge_foundation_safety import formal_evidence_is_quarantined


DEFAULT_EVIDENCE_CHUNKS = PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl"
DEFAULT_CATALOG_CHUNKS = PROJECT_ROOT / "data" / "indexes" / "scrna_tools_catalog_chunks.jsonl"
DEFAULT_FTS_INDEX = PROJECT_ROOT / "data" / "indexes" / "evidence_fts5.sqlite"
DEFAULT_INDEX_MANIFEST = PROJECT_ROOT / "data" / "indexes" / "evidence_index_manifest.json"
DEFAULT_COVERAGE = PROJECT_ROOT / "data" / "indexes" / "retrieval_coverage_v2.json"
DEFAULT_DENSE_MATRIX = PROJECT_ROOT / "data" / "indexes" / "evidence_vectors.npy"
DEFAULT_DENSE_METADATA = PROJECT_ROOT / "data" / "indexes" / "evidence_vector_metadata.json"
DEFAULT_MODEL_PACK_MANIFEST = (
    PROJECT_ROOT / "model_packs/manifests/retrieval-bge-m3.json"
)
LOCAL_EMBEDDING_MODEL = "BAAI/bge-m3"

_GOVERNANCE_BOOSTABLE_CLAIM_TYPES = frozenset(
    {
        "input_requirement",
        "output",
        "parameter",
        "failure_mode",
        "metric",
        "benchmark",
        "workflow",
    }
)


class DenseEncoder(Protocol):
    model_name: str

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class LocalBgeM3Encoder:
    model_name = LOCAL_EMBEDDING_MODEL

    def __init__(self) -> None:
        from engine.local_embedding_worker import LocalEmbeddingWorker

        self._worker = LocalEmbeddingWorker()
        self.model_revision = self._worker.revision
        self.snapshot_digest = self._worker.snapshot_digest

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return self._worker.encode(texts)


class HybridRetrievalService:
    """Cached local KG + FTS5 BM25 + optional local dense retrieval."""

    def __init__(
        self,
        *,
        evidence_chunks_path: Path = DEFAULT_EVIDENCE_CHUNKS,
        catalog_chunks_path: Path = DEFAULT_CATALOG_CHUNKS,
        fts_index_path: Path = DEFAULT_FTS_INDEX,
        index_manifest_path: Path = DEFAULT_INDEX_MANIFEST,
        coverage_path: Path = DEFAULT_COVERAGE,
        dense_matrix_path: Path = DEFAULT_DENSE_MATRIX,
        dense_metadata_path: Path = DEFAULT_DENSE_METADATA,
        dense_encoder: Optional[DenseEncoder] = None,
        graph_dir: Path | None = None,
        query_cache_size: int = 256,
    ) -> None:
        self.evidence_chunks_path = Path(evidence_chunks_path)
        self.catalog_chunks_path = Path(catalog_chunks_path)
        self.fts_index_path = Path(fts_index_path)
        self.index_manifest_path = Path(index_manifest_path)
        self.coverage_path = Path(coverage_path)
        self.dense_matrix_path = Path(dense_matrix_path)
        self.dense_metadata_path = Path(dense_metadata_path)
        self.dense_encoder = dense_encoder
        self.graph_dir = Path(graph_dir or PROJECT_ROOT / "data" / "knowledge_graph_v2")
        self._lock = threading.RLock()
        self._chunks_by_id: Dict[str, EvidenceChunk] = {}
        self._dense_matrix: Optional[np.ndarray] = None
        self._dense_chunk_ids: List[str] = []
        self._dense_source_digest = ""
        self._graph_query = None
        self._query_cache_size = max(1, int(query_cache_size))
        self._query_embedding_cache: OrderedDict[tuple[str, str, str], np.ndarray] = (
            OrderedDict()
        )
        self._query_pending: set[tuple[str, str, str]] = set()
        self._query_queue: Queue[tuple[str, tuple[str, str, str]]] = Queue(
            maxsize=self._query_cache_size
        )
        self._query_worker_thread: Optional[threading.Thread] = None
        self._worker_ready = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        now = datetime.now(timezone.utc)
        self._worker_status = EmbeddingWorkerStatus(
            state="ready" if dense_encoder is not None else "not_started",
            model=getattr(dense_encoder, "model_name", LOCAL_EMBEDDING_MODEL),
            model_revision=str(getattr(dense_encoder, "model_revision", "")),
            source_digest="",
            started_at=now if dense_encoder is not None else None,
            ready_at=now if dense_encoder is not None else None,
        )
        if dense_encoder is not None:
            self._worker_ready.set()
        self._ensure_index()

    def search(self, request: HybridRetrievalRequest) -> HybridRetrievalResult:
        started = time.perf_counter()
        stage_timings: list[ChatStageTiming] = []
        stage_started = time.perf_counter()
        inferred_tool_names = (
            []
            if request.tool_names
            else self._named_tools_in_query(request.query)
        )
        effective_request = (
            request.model_copy(update={"tool_names": inferred_tool_names})
            if inferred_tool_names
            else request
        )
        operation_scope_blocker = _unsupported_operation_request(request.query)
        inferred_task = canonical_task_for_text(
            " ".join([request.query, *request.canonical_tasks])
        )
        task_ids = set(request.canonical_tasks)
        if inferred_task is not None:
            task_ids.add(inferred_task.task_id)
        inferred_claim_types = set(request.claim_types) or _infer_claim_types(request.query)
        stage_timings.append(
            _stage_timing("intent", stage_started, detail="deterministic task/claim normalization")
        )
        stage_started = time.perf_counter()
        if request.use_kg:
            candidate_tools, graph_warning = self._kg_candidates(
                task_ids=sorted(task_ids),
                explicit_tools=effective_request.tool_names,
            )
        else:
            candidate_tools = {
                _tool_key(value) for value in effective_request.tool_names if value
            }
            graph_warning = ""
        stage_timings.append(
            _stage_timing(
                "kg_filter",
                stage_started,
                status="completed" if request.use_kg else "skipped",
                detail=f"candidate_tools={len(candidate_tools)}",
            )
        )
        stage_started = time.perf_counter()
        sparse = (
            self._bm25_search(
                request.query,
                limit=max(request.top_k * 12, 120),
            )
            if request.enable_sparse
            else []
        )
        sparse = self._filter_ranked(
            sparse,
            request=effective_request,
            task_ids=task_ids,
            candidate_tools=candidate_tools,
        )
        stage_timings.append(
            _stage_timing(
                "bm25",
                stage_started,
                status="completed" if request.enable_sparse else "skipped",
                detail=f"hits={len(sparse)}",
            )
        )
        dense_status = "not_requested"
        dense: List[tuple[str, float]] = []
        warnings = [graph_warning] if graph_warning else []
        if operation_scope_blocker:
            warnings.append(operation_scope_blocker)
        stage_started = time.perf_counter()
        if request.enable_dense:
            dense, dense_status = self._dense_search(
                request.query,
                limit=max(request.top_k * 12, 120),
                nonblocking=request.nonblocking_dense,
            )
            dense = self._filter_ranked(
                dense,
                request=effective_request,
                task_ids=task_ids,
                candidate_tools=candidate_tools,
            )
            if dense_status != "ready":
                warnings.append(
                    "Local BAAI/bge-m3 model pack or vector index is unavailable; used KG+BM25 fallback."
                )
        stage_timings.append(
            _stage_timing(
                "dense_encode",
                stage_started,
                status=(
                    "completed"
                    if dense_status == "ready"
                    else "skipped"
                    if dense_status == "not_requested"
                    else "fallback"
                ),
                detail=f"status={dense_status};hits={len(dense)}",
            )
        )
        stage_started = time.perf_counter()
        fused = _rrf(sparse, dense)
        reranked = (
            self._governance_rerank(
                fused,
                request=effective_request,
                task_ids=task_ids,
                claim_types=inferred_claim_types,
                candidate_tools=candidate_tools,
            )
            if request.use_governance_rerank
            else list(fused)
        )
        if not effective_request.tool_names:
            reranked = _diversify_ranked_by_tool(
                reranked,
                chunks_by_id=self._chunks_by_id,
                top_k=request.top_k,
            )
        if operation_scope_blocker:
            reranked = []
        stage_timings.append(
            _stage_timing(
                "fusion",
                stage_started,
                detail=f"fused={len(fused)};reranked={len(reranked)}",
            )
        )
        hits = []
        for chunk_id, score, sparse_rank, dense_rank in reranked[: request.top_k]:
            chunk = self._chunks_by_id[chunk_id]
            mentioned_tools = _chunk_mentioned_tools(chunk)
            matched_explicit = next(
                (
                    tool
                    for tool in effective_request.tool_names
                    if _tool_key(tool) in {_tool_key(value) for value in mentioned_tools}
                ),
                "",
            )
            display_tool = matched_explicit or chunk.tool_name
            # Source binding is a governed identity assertion.  A non-empty
            # locator and text cannot upgrade an unbound formal row.
            source_bound = bool(chunk.source_bound)
            recommendation_eligible = str(chunk.recommendation_eligible).casefold() == "true"
            hits.append(
                HybridRetrievalHit(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_document_id or chunk.source_id,
                    tool_name=display_tool,
                    tool_names=mentioned_tools,
                    canonical_task=chunk.canonical_task or chunk.task,
                    claim_type=chunk.claim_type,
                    source_span=chunk.source_span,
                    title=chunk.title,
                    text=_compact(chunk.chunk_text, 900),
                    score=round(score, 8),
                    sparse_rank=sparse_rank,
                    dense_rank=dense_rank,
                    governance_status=chunk.retrieval_status or chunk.graph_layer or "retrieval_only",
                    source_bound=source_bound,
                    recommendation_eligible=recommendation_eligible,
                )
            )
        dense_used = bool(dense and dense_status == "ready")
        leakage = sum(hit.recommendation_eligible for hit in hits if hit.governance_status == "catalog_only")
        return HybridRetrievalResult(
            query=request.query,
            mode=_retrieval_mode(
                use_kg=request.use_kg,
                sparse_used=request.enable_sparse,
                dense_used=dense_used,
            ),
            hits=hits,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            index_build_id=self.index_build_id,
            embedding_model=LOCAL_EMBEDDING_MODEL if dense_used else "",
            dense_status=dense_status,
            pipeline=[
                "query_classification",
                "canonical_task_normalization",
                "kg_hard_filter" if request.use_kg else "kg_filter_skipped",
                "sqlite_fts5_bm25" if request.enable_sparse else "sparse_retrieval_skipped",
                "local_bge_m3" if dense_used else "local_dense_skipped",
                "rrf_fusion",
                "source_governance_rerank" if request.use_governance_rerank else "governance_rerank_skipped",
                "tool_contract_gate" if request.use_contract_gate else "tool_contract_gate_skipped",
                "retrieval_context_only",
            ],
            warnings=warnings,
            governance_leakage_count=leakage,
            stage_timings=stage_timings,
        )

    def _named_tools_in_query(self, query: str) -> list[str]:
        normalized = str(query or "").casefold()
        compact_query = _tool_key(normalized)
        generic_keys = {
            "scrna",
            "scrnaseq",
            "singlecell",
            "singlerna",
            "rnaseq",
        }
        tool_inventory: dict[str, str] = {}
        for chunk in self._chunks_by_id.values():
            for tool in chunk.tool_names or ([chunk.tool_name] if chunk.tool_name else []):
                key = _tool_key(tool)
                if not key or key in generic_keys or len(key) < 4:
                    continue
                current = tool_inventory.get(key, "")
                if not current or (current.islower() and not str(tool).islower()):
                    tool_inventory[key] = str(tool)
        matches: list[str] = []
        for key, tool in sorted(
            tool_inventory.items(), key=lambda item: (-len(item[0]), item[0])
        ):
            literal = tool.casefold()
            if literal in normalized or (len(key) >= 7 and key in compact_query):
                matches.append(tool)
        return matches

    def start_dense_warmup(self) -> EmbeddingWorkerStatus:
        """Load the local model off the request path and return immediately."""

        with self._lock:
            if self._dense_matrix is None or not self._dense_chunk_ids:
                self._worker_status = EmbeddingWorkerStatus(
                    state="failed",
                    model=LOCAL_EMBEDDING_MODEL,
                    source_digest=self._dense_source_digest,
                    failure_reason="vector_index_missing",
                )
                self._worker_ready.set()
                return self._worker_status
            if self.dense_encoder is not None:
                self._mark_worker_ready(self.dense_encoder)
                return self._worker_status
            if self._worker_status.state in {"warming", "ready"}:
                return self._worker_status
            self._worker_ready.clear()
            self._worker_status = EmbeddingWorkerStatus(
                state="warming",
                model=LOCAL_EMBEDDING_MODEL,
                source_digest=self._dense_source_digest,
                started_at=datetime.now(timezone.utc),
            )
            self._worker_thread = threading.Thread(
                target=self._warm_dense_encoder,
                name="sckg-bge-m3-warmup",
                daemon=True,
            )
            self._worker_thread.start()
            return self._worker_status

    def wait_for_dense_ready(self, timeout: float = 60.0) -> EmbeddingWorkerStatus:
        status = self.start_dense_warmup()
        if status.state == "warming":
            self._worker_ready.wait(timeout=max(0.0, float(timeout)))
        return self.embedding_worker_status

    @property
    def embedding_worker_status(self) -> EmbeddingWorkerStatus:
        with self._lock:
            return self._worker_status.model_copy(deep=True)

    def _warm_dense_encoder(self) -> None:
        try:
            encoder = LocalBgeM3Encoder()
            encoder.encode(["single-cell evidence retrieval warmup"])
            with self._lock:
                self.dense_encoder = encoder
                self._mark_worker_ready(encoder)
        except Exception as exc:
            with self._lock:
                self._worker_status = EmbeddingWorkerStatus(
                    state="failed",
                    model=LOCAL_EMBEDDING_MODEL,
                    source_digest=self._dense_source_digest,
                    failure_reason=f"{type(exc).__name__}:{str(exc)[:240]}",
                    started_at=self._worker_status.started_at,
                )
                self._worker_ready.set()

    def _mark_worker_ready(self, encoder: DenseEncoder) -> None:
        now = datetime.now(timezone.utc)
        self._worker_status = EmbeddingWorkerStatus(
            state="ready",
            model=getattr(encoder, "model_name", LOCAL_EMBEDDING_MODEL),
            model_revision=str(getattr(encoder, "model_revision", "")),
            source_digest=self._dense_source_digest,
            started_at=self._worker_status.started_at or now,
            ready_at=now,
        )
        self._worker_ready.set()

    def search_tools_for_task(self, task: str, *, top_k: int = 12) -> HybridRetrievalResult:
        return self.search(
            HybridRetrievalRequest(query=task, canonical_tasks=[task], top_k=top_k)
        )

    def search_parameter_evidence(
        self, query: str, *, tool_names: Sequence[str] = (), top_k: int = 12
    ) -> HybridRetrievalResult:
        return self.search(
            HybridRetrievalRequest(
                query=query,
                tool_names=list(tool_names),
                claim_types=["parameter"],
                top_k=top_k,
            )
        )

    def search_input_requirements(
        self, query: str, *, tool_names: Sequence[str] = (), top_k: int = 12
    ) -> HybridRetrievalResult:
        return self.search(
            HybridRetrievalRequest(
                query=query,
                tool_names=list(tool_names),
                claim_types=["input_requirement"],
                top_k=top_k,
            )
        )

    def search_failure_modes(
        self, query: str, *, tool_names: Sequence[str] = (), top_k: int = 12
    ) -> HybridRetrievalResult:
        return self.search(
            HybridRetrievalRequest(
                query=query,
                tool_names=list(tool_names),
                claim_types=["failure_mode"],
                top_k=top_k,
            )
        )

    def search_metric_definitions(
        self, query: str, *, tool_names: Sequence[str] = (), top_k: int = 12
    ) -> HybridRetrievalResult:
        return self.search(
            HybridRetrievalRequest(
                query=query,
                tool_names=list(tool_names),
                claim_types=["metric"],
                top_k=top_k,
            )
        )

    def get_source_span(self, chunk_id: str) -> Dict[str, Any]:
        chunk = self._chunks_by_id.get(chunk_id)
        if chunk is None:
            raise KeyError(f"unknown evidence chunk: {chunk_id}")
        return {
            "chunk_id": chunk.chunk_id,
            "source_id": chunk.source_document_id or chunk.source_id,
            "source_span": chunk.source_span,
            "page": chunk.page,
            "section": chunk.section,
            "content_hash": chunk.content_hash,
            "claim_boundary": chunk.claim_boundary,
        }

    def get_retrieval_coverage(self) -> RetrievalCoverageReport:
        if not self.coverage_path.is_file():
            raise FileNotFoundError("retrieval coverage report is missing")
        return RetrievalCoverageReport.model_validate_json(
            self.coverage_path.read_text(encoding="utf-8")
        )

    @property
    def index_build_id(self) -> str:
        with sqlite3.connect(self.fts_index_path) as conn:
            row = conn.execute(
                "SELECT value FROM index_metadata WHERE key = 'build_id'"
            ).fetchone()
        return str(row[0]) if row else ""

    @property
    def chunk_count(self) -> int:
        return len(self._chunks_by_id)

    def build_dense_index(self, encoder: DenseEncoder, *, batch_size: int = 8) -> Dict[str, Any]:
        source_chunks = sorted(
            [
                chunk
                for chunk in self._chunks_by_id.values()
                if chunk.source_bound and chunk.retrieval_status != "catalog_only"
            ],
            key=lambda item: item.chunk_id,
        )
        vectors = []
        for start in range(0, len(source_chunks), batch_size):
            batch = source_chunks[start : start + batch_size]
            values = np.asarray(encoder.encode([chunk.chunk_text for chunk in batch]), dtype=np.float32)
            if values.ndim != 2 or values.shape[0] != len(batch):
                raise ValueError("dense encoder returned an invalid matrix shape")
            vectors.append(_normalize_rows(values))
        matrix = np.vstack(vectors) if vectors else np.empty((0, 0), dtype=np.float32)
        self.dense_matrix_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(self.dense_matrix_path, matrix)
        metadata = {
            "schema_version": "dense-index-v2",
            "build_id": self.index_build_id,
            "model": encoder.model_name,
            "model_revision": str(getattr(encoder, "model_revision", "")),
            "snapshot_digest": str(getattr(encoder, "snapshot_digest", "")),
            "source_digest": _source_chunk_digest(source_chunks),
            "chunk_ids": [chunk.chunk_id for chunk in source_chunks],
            "shape": list(matrix.shape),
            "normalized": True,
            "rebuild_command": "python scripts/build_bge_m3_dense_index.py",
        }
        self.dense_metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self.dense_encoder = encoder
        self._dense_matrix = matrix
        self._dense_chunk_ids = list(metadata["chunk_ids"])
        self._dense_source_digest = str(metadata["source_digest"])
        self._mark_worker_ready(encoder)
        return metadata

    def _ensure_index(self) -> None:
        with self._lock:
            build_id = self._expected_build_id()
            if self.fts_index_path.is_file():
                try:
                    with sqlite3.connect(self.fts_index_path) as conn:
                        row = conn.execute(
                            "SELECT value FROM index_metadata WHERE key = 'build_id'"
                        ).fetchone()
                    if row and row[0] == build_id:
                        self._load_chunk_cache()
                        self._load_dense_index()
                        return
                except sqlite3.Error:
                    pass
            self._build_fts_index(build_id)
            self._load_chunk_cache()
            self._load_dense_index()

    def _build_fts_index(self, build_id: str) -> None:
        evidence = load_chunks(self.evidence_chunks_path) if self.evidence_chunks_path.is_file() else []
        catalog = load_chunks(self.catalog_chunks_path) if self.catalog_chunks_path.is_file() else []
        chunks = {chunk.chunk_id: chunk for chunk in [*evidence, *catalog]}
        self.fts_index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.fts_index_path.with_suffix(".sqlite.tmp")
        if temporary.exists():
            temporary.unlink()
        with sqlite3.connect(temporary) as conn:
            conn.executescript(
                """
                CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
                CREATE VIRTUAL TABLE chunk_fts USING fts5(
                    chunk_id UNINDEXED,
                    tool_names,
                    canonical_task,
                    claim_type,
                    title,
                    chunk_text,
                    tokenize='unicode61 remove_diacritics 2'
                );
                """
            )
            conn.execute("INSERT INTO index_metadata(key, value) VALUES ('build_id', ?)", (build_id,))
            conn.execute("INSERT INTO index_metadata(key, value) VALUES ('schema_version', 'fts5-bm25-v2')")
            for chunk in sorted(chunks.values(), key=lambda item: item.chunk_id):
                payload = json.dumps(chunk.__dict__, ensure_ascii=False, sort_keys=True)
                conn.execute("INSERT INTO chunks(chunk_id, payload_json) VALUES (?, ?)", (chunk.chunk_id, payload))
                conn.execute(
                    "INSERT INTO chunk_fts(chunk_id, tool_names, canonical_task, claim_type, title, chunk_text) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        chunk.chunk_id,
                        " ".join(chunk.tool_names or ([chunk.tool_name] if chunk.tool_name else [])),
                        " ".join(chunk.task_tags or ([chunk.canonical_task or chunk.task] if (chunk.canonical_task or chunk.task) else [])),
                        chunk.claim_type,
                        chunk.title,
                        chunk.chunk_text,
                    ),
                )
        temporary.replace(self.fts_index_path)

    def _load_chunk_cache(self) -> None:
        with sqlite3.connect(self.fts_index_path) as conn:
            rows = conn.execute("SELECT chunk_id, payload_json FROM chunks").fetchall()
        self._chunks_by_id = {
            str(chunk_id): EvidenceChunk(**json.loads(payload)) for chunk_id, payload in rows
        }

    def _load_dense_index(self) -> None:
        self._dense_matrix = None
        self._dense_chunk_ids = []
        self._dense_source_digest = ""
        if not self.dense_matrix_path.is_file() or not self.dense_metadata_path.is_file():
            return
        try:
            metadata = json.loads(self.dense_metadata_path.read_text(encoding="utf-8"))
            if metadata.get("build_id") != self.index_build_id:
                return
            source_chunks = sorted(
                [
                    chunk
                    for chunk in self._chunks_by_id.values()
                    if chunk.source_bound and chunk.retrieval_status != "catalog_only"
                ],
                key=lambda item: item.chunk_id,
            )
            if metadata.get("source_digest") != _source_chunk_digest(source_chunks):
                return
            matrix = np.load(self.dense_matrix_path, mmap_mode="r")
            chunk_ids = [str(value) for value in metadata.get("chunk_ids", [])]
            expected_chunk_ids = [chunk.chunk_id for chunk in source_chunks]
            if matrix.ndim != 2 or matrix.shape[0] != len(chunk_ids):
                return
            if chunk_ids != expected_chunk_ids:
                return
            if metadata.get("model") == LOCAL_EMBEDDING_MODEL:
                manifest = json.loads(
                    DEFAULT_MODEL_PACK_MANIFEST.read_text(encoding="utf-8")
                )
                if metadata.get("model_revision") != manifest.get("revision"):
                    return
            self._dense_matrix = matrix
            self._dense_chunk_ids = chunk_ids
            self._dense_source_digest = str(metadata.get("source_digest") or "")
            if self.dense_encoder is not None:
                self._mark_worker_ready(self.dense_encoder)
        except (OSError, ValueError, json.JSONDecodeError):
            return

    def _expected_build_id(self) -> str:
        if self.index_manifest_path.is_file():
            value = json.loads(self.index_manifest_path.read_text(encoding="utf-8"))
            if value.get("build_id"):
                return str(value["build_id"])
        digest = hashlib.sha256()
        for path in (self.evidence_chunks_path, self.catalog_chunks_path):
            if path.is_file():
                digest.update(path.read_bytes())
        return "adhoc-" + digest.hexdigest()[:16]

    def _bm25_search(self, query: str, *, limit: int) -> List[tuple[str, float]]:
        tokens = _query_tokens(query)
        if not tokens:
            return []
        expression = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens[:40])
        with sqlite3.connect(self.fts_index_path) as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, bm25(chunk_fts, 0.0, 4.0, 3.0, 2.0, 1.5, 1.0) AS raw_score
                FROM chunk_fts
                WHERE chunk_fts MATCH ?
                ORDER BY raw_score
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
        return [(str(chunk_id), 1.0 / (1.0 + abs(float(raw_score)))) for chunk_id, raw_score in rows]

    def _dense_search(
        self,
        query: str,
        *,
        limit: int,
        nonblocking: bool = False,
    ) -> tuple[List[tuple[str, float]], str]:
        if self._dense_matrix is None or not self._dense_chunk_ids:
            return [], "vector_index_missing"
        encoder = self.dense_encoder
        if encoder is None:
            status = self.start_dense_warmup()
            return [], (
                "warming_sparse_fallback"
                if status.state in {"warming", "not_started"}
                else status.failure_reason or "local_model_pack_missing"
            )
        revision = str(getattr(encoder, "model_revision", ""))
        cache_key = (query, revision, self._dense_source_digest)
        with self._lock:
            cached = self._query_embedding_cache.get(cache_key)
            if cached is not None:
                self._query_embedding_cache.move_to_end(cache_key)
        if cached is None:
            if nonblocking:
                self._enqueue_query_embedding(query, cache_key)
                return [], "query_warming_sparse_fallback"
            query_matrix = _normalize_rows(
                np.asarray(encoder.encode([query]), dtype=np.float32)
            )
            cached = np.asarray(query_matrix[0], dtype=np.float32)
            with self._lock:
                self._query_embedding_cache[cache_key] = cached
                self._query_embedding_cache.move_to_end(cache_key)
                while len(self._query_embedding_cache) > self._query_cache_size:
                    self._query_embedding_cache.popitem(last=False)
        query_vector = cached
        if query_vector.shape[0] != self._dense_matrix.shape[1]:
            return [], "embedding_dimension_mismatch"
        scores = np.asarray(self._dense_matrix @ query_vector, dtype=np.float32)
        top = np.argsort(-scores)[:limit]
        return [
            (self._dense_chunk_ids[int(index)], float(scores[int(index)]))
            for index in top
            if float(scores[int(index)]) > 0
        ], "ready"

    def _enqueue_query_embedding(
        self,
        query: str,
        cache_key: tuple[str, str, str],
    ) -> None:
        with self._lock:
            if cache_key in self._query_pending:
                return
            if self._query_worker_thread is None or not self._query_worker_thread.is_alive():
                self._query_worker_thread = threading.Thread(
                    target=self._query_embedding_loop,
                    name="sckg-query-embedding-cache",
                    daemon=True,
                )
                self._query_worker_thread.start()
            try:
                self._query_queue.put_nowait((query, cache_key))
            except Full:
                return
            self._query_pending.add(cache_key)

    def _query_embedding_loop(self) -> None:
        while True:
            try:
                query, cache_key = self._query_queue.get(timeout=30.0)
            except Empty:
                return
            try:
                encoder = self.dense_encoder
                if encoder is None:
                    continue
                matrix = _normalize_rows(
                    np.asarray(encoder.encode([query]), dtype=np.float32)
                )
                with self._lock:
                    self._query_embedding_cache[cache_key] = np.asarray(
                        matrix[0],
                        dtype=np.float32,
                    )
                    self._query_embedding_cache.move_to_end(cache_key)
                    while len(self._query_embedding_cache) > self._query_cache_size:
                        self._query_embedding_cache.popitem(last=False)
            finally:
                with self._lock:
                    self._query_pending.discard(cache_key)
                self._query_queue.task_done()

    def _filter_ranked(
        self,
        ranked: Sequence[tuple[str, float]],
        *,
        request: HybridRetrievalRequest,
        task_ids: set[str],
        candidate_tools: set[str],
    ) -> List[tuple[str, float]]:
        explicit_tools = {_tool_key(value) for value in request.tool_names}
        source_types = {value.casefold() for value in request.source_types}
        filtered = []
        for chunk_id, score in ranked:
            chunk = self._chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            if formal_evidence_is_quarantined(chunk):
                continue
            chunk_tools = {
                _tool_key(value)
                for value in (chunk.tool_names or [chunk.tool_name])
                if value
            }
            mentioned_tools = {
                _tool_key(value) for value in _chunk_mentioned_tools(chunk)
            }
            if explicit_tools and not (explicit_tools & mentioned_tools):
                continue
            if task_ids and not explicit_tools:
                governed_tool_tasks = {
                    task_id
                    for tool in _chunk_mentioned_tools(chunk)
                    for task_id in canonical_task_ids_for_tool(tool)
                }
                if governed_tool_tasks and not (task_ids & governed_tool_tasks):
                    continue
            if candidate_tools and chunk_tools and not (candidate_tools & chunk_tools):
                continue
            if source_types and chunk.source_type.casefold() not in source_types:
                continue
            if not request.include_catalog and chunk.retrieval_status == "catalog_only":
                continue
            filtered.append((chunk_id, score))
        return filtered

    def _governance_rerank(
        self,
        fused: Sequence[tuple[str, float, Optional[int], Optional[int]]],
        *,
        request: HybridRetrievalRequest,
        task_ids: set[str],
        claim_types: set[str],
        candidate_tools: set[str],
    ) -> List[tuple[str, float, Optional[int], Optional[int]]]:
        explicit_tools = {_tool_key(value) for value in request.tool_names}
        reranked = []
        for chunk_id, score, sparse_rank, dense_rank in fused:
            chunk = self._chunks_by_id[chunk_id]
            chunk_tools = {
                _tool_key(value)
                for value in (chunk.tool_names or [chunk.tool_name])
                if value
            }
            mentioned_tools = {
                _tool_key(value) for value in _chunk_mentioned_tools(chunk)
            }
            chunk_tasks = set(chunk.task_tags or ([chunk.canonical_task or chunk.task] if (chunk.canonical_task or chunk.task) else []))
            adjusted = score
            if explicit_tools & mentioned_tools:
                adjusted += 0.12
            elif candidate_tools & chunk_tools:
                adjusted += 0.035
            if task_ids & chunk_tasks:
                adjusted += 0.06
            boostable_claim_types = (
                claim_types & _GOVERNANCE_BOOSTABLE_CLAIM_TYPES
            )
            if (
                chunk.claim_type in boostable_claim_types
                and _chunk_supports_claim_type(chunk, boostable_claim_types)
            ):
                adjusted += 0.05
            adjusted += _query_content_relevance(
                request.query,
                chunk,
                claim_types=claim_types,
            )
            if chunk.retrieval_status == "retrieval_only" and chunk.source_bound:
                adjusted += 0.06
            if chunk.source_kind == "source_document":
                adjusted += 0.05
            if chunk.retrieval_status == "catalog_only":
                adjusted -= 0.045
            if chunk.source_kind in {"publication", "benchmark"} and not chunk.claim_text:
                adjusted -= 0.08
            if not chunk.source_span:
                adjusted -= 0.04
            reranked.append((chunk_id, adjusted, sparse_rank, dense_rank))
        return sorted(reranked, key=lambda item: (-item[1], item[0]))

    def _kg_candidates(
        self, *, task_ids: Sequence[str], explicit_tools: Sequence[str]
    ) -> tuple[set[str], str]:
        candidates = {_tool_key(value) for value in explicit_tools if value}
        if not task_ids or not self.graph_dir.is_dir():
            return candidates, ""
        try:
            if self._graph_query is None:
                from engine.evidence_graph_query import EvidenceGraphQuery

                self._graph_query = EvidenceGraphQuery(self.graph_dir)
            for task_id in task_ids:
                label = canonical_task(task_id).label
                for match in self._graph_query.rank_tools(task=label, modality="scRNA-seq", limit=200):
                    candidates.add(_tool_key(match.tool_name))
            return candidates, ""
        except Exception as exc:
            return candidates, f"KG hard filter unavailable ({type(exc).__name__}); BM25 fallback remained local."


@lru_cache(maxsize=1)
def get_hybrid_retrieval_service() -> HybridRetrievalService:
    return HybridRetrievalService()


def _rrf(
    sparse: Sequence[tuple[str, float]],
    dense: Sequence[tuple[str, float]],
    *,
    k: int = 60,
) -> List[tuple[str, float, Optional[int], Optional[int]]]:
    values: Dict[str, List[Any]] = {}
    for label, ranked in (("sparse", sparse), ("dense", dense)):
        for rank, (chunk_id, _) in enumerate(ranked, start=1):
            value = values.setdefault(chunk_id, [0.0, None, None])
            value[0] += 1.0 / (k + rank)
            value[1 if label == "sparse" else 2] = rank
    return sorted(
        ((chunk_id, float(value[0]), value[1], value[2]) for chunk_id, value in values.items()),
        key=lambda item: (-item[1], item[0]),
    )


def _infer_claim_types(query: str) -> set[str]:
    text = query.casefold()
    result = set()
    rules = {
        "parameter": ("parameter", "default", "threshold", "参数", "阈值"),
        "input_requirement": ("input", "require", "count", "输入", "需要什么数据"),
        "output": (
            "output",
            "return",
            "artifact",
            "输出",
            "返回",
            "结果",
            "放在哪里",
            "存在哪里",
            "obsm",
        ),
        "failure_mode": ("failure", "limitation", "caveat", "失败", "局限", "注意"),
        "metric": ("metric", "benchmark", "auprc", "auroc", "f1", "指标", "评测"),
        "workflow": ("workflow", "pipeline", "步骤", "流程"),
    }
    for claim_type, markers in rules.items():
        if any(marker in text for marker in markers):
            result.add(claim_type)
    return result


def _query_content_relevance(
    query: str,
    chunk: EvidenceChunk,
    *,
    claim_types: set[str],
) -> float:
    """Small deterministic relevance signal applied after governance boosts."""

    content = " ".join(
        value
        for value in (
            chunk.title,
            chunk.claim_text,
            chunk.claim_span,
            chunk.chunk_text,
            chunk.source_span,
        )
        if value
    ).casefold()
    query_text = str(query or "").casefold()
    query_tokens = {
        token
        for token in _query_tokens(query_text)
        if token not in {"canonical", "task", "claim", "explicit", "tool"}
    }
    content_tokens = set(_query_tokens(content))
    overlap = len(query_tokens & content_tokens) / max(1, min(len(query_tokens), 12))
    score = min(0.06, overlap * 0.12)

    claim_cues = {
        "input_requirement": (
            "input",
            "accepts",
            "starting with",
            "count matrix",
            "raw umi",
            "requires",
        ),
        "output": (
            "output",
            "returns",
            "adds an entry",
            "obsm",
            "x_scanorama",
            "coordinates",
            "embedding",
        ),
        "parameter": ("parameter", "default", "threshold", "range"),
        "failure_mode": ("limitation", "caveat", "failure", "warning"),
        "metric": ("metric", "auprc", "auroc", "f1", "silhouette"),
        "benchmark": ("benchmark", "dataset", "rank"),
    }
    for claim_type in claim_types:
        if any(cue in content for cue in claim_cues.get(claim_type, ())):
            score += 0.025
    if any(marker in query_text for marker in ("放在哪里", "存在哪里", "obsm")):
        if "obsm" in content or "x_scanorama" in content:
            score += 0.06
    if "raw" in query_text and ("raw" in content or "count matrix" in content):
        score += 0.04
    return min(score, 0.14)


def _chunk_mentioned_tools(chunk: EvidenceChunk) -> list[str]:
    """Return tools named by this span, not merely linked at document level."""

    candidates = chunk.tool_names or ([chunk.tool_name] if chunk.tool_name else [])
    content = " ".join(
        value
        for value in (chunk.title, chunk.chunk_text, chunk.source_span)
        if value
    ).casefold()
    compact_content = _tool_key(content)
    mentioned: list[str] = []
    for tool in candidates:
        key = _tool_key(tool)
        if not key:
            continue
        if str(tool).casefold() in content or key in compact_content:
            mentioned.append(str(tool))
    if not mentioned and len(candidates) == 1:
        mentioned = [str(candidates[0])]
    return list(dict.fromkeys(mentioned))


def _chunk_supports_claim_type(
    chunk: EvidenceChunk,
    claim_types: set[str],
) -> bool:
    content = " ".join(
        value
        for value in (chunk.title, chunk.claim_span, chunk.chunk_text, chunk.source_span)
        if value
    ).casefold()
    cues = {
        "input_requirement": (
            "input matrix",
            "raw count",
            "count matrix",
            "starting with",
            "accepts",
            "requires",
            "pca embedding",
            "batch labels",
        ),
        "output": (
            "output",
            "returns",
            "adds an entry",
            "obsm",
            "x_scanorama",
            "embedding",
            "doublet score",
        ),
        "parameter": ("parameter", "default", "threshold", "range", "theta", "pk"),
        "failure_mode": (
            "limitation",
            "caveat",
            "warning",
            "homotypic",
            "multiple samples",
            "expected doublet rate",
        ),
        "metric": ("metric", "auprc", "auroc", "f1", "silhouette"),
        "benchmark": ("benchmark", "dataset", "rank"),
        "workflow": ("workflow", "pipeline", "tutorial"),
    }
    applicable = [claim_type for claim_type in claim_types if claim_type in cues]
    if not applicable:
        return True
    return any(
        any(cue in content for cue in cues[claim_type])
        for claim_type in applicable
    )


def _diversify_ranked_by_tool(
    ranked: Sequence[tuple[str, float, Optional[int], Optional[int]]],
    *,
    chunks_by_id: Dict[str, EvidenceChunk],
    top_k: int,
    max_per_tool: int = 3,
) -> List[tuple[str, float, Optional[int], Optional[int]]]:
    """Prevent a broad discovery result from being filled by one tool's pages."""

    selected: list[tuple[str, float, Optional[int], Optional[int]]] = []
    counts: Dict[str, int] = {}
    for item in ranked:
        chunk = chunks_by_id.get(item[0])
        if chunk is None:
            continue
        tools = _chunk_mentioned_tools(chunk)
        group = _tool_key(tools[0] if tools else chunk.tool_name) or item[0]
        if counts.get(group, 0) < max_per_tool and len(selected) < top_k:
            selected.append(item)
            counts[group] = counts.get(group, 0) + 1
    selected_ids = {item[0] for item in selected}
    tail = [item for item in ranked if item[0] not in selected_ids]
    return [*selected, *tail]


def _query_tokens(text: str) -> List[str]:
    values = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+-]+|[\u4e00-\u9fff]{2,}", text or "")
    return list(dict.fromkeys(value.casefold() for value in values if len(value) >= 2))


def _unsupported_operation_request(query: str) -> str:
    text = str(query or "").casefold()
    unsupported_scopes = (
        ("spatial_histology_alignment", ("align spatial histology", "spatial histology images")),
        ("somatic_variant_calling", ("somatic dna variant", "variant from a bam", "bam file")),
        ("genome_assembly", ("assemble a reference genome", "genome from long reads")),
        ("protein_structure_prediction", ("protein structure", "amino-acid sequence", "amino acid sequence")),
        ("fastq_base_calling", ("fastq base calling", "raw fastq base")),
        ("metabolomics_quantification", ("quantify metabolites", "mass spectrometry images")),
        ("crispr_sequence_editing", ("edit crispr guide", "crispr guide sequences")),
        (
            "contract_bypass",
            (
                "execution-qualified without a contract",
                "execution qualified without a contract",
            ),
        ),
    )
    for reason, markers in unsupported_scopes:
        if any(marker in text for marker in markers):
            return f"unsupported_operation_scope:{reason}"
    return ""


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    if matrix.ndim != 2:
        raise ValueError("embedding matrix must be two-dimensional")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _tool_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _retrieval_mode(*, use_kg: bool, sparse_used: bool, dense_used: bool) -> str:
    prefix = "kg_" if use_kg else ""
    if sparse_used and dense_used:
        return prefix + "bm25_dense"
    if dense_used:
        return prefix + "dense"
    return prefix + "bm25"


def _source_chunk_digest(chunks: Sequence[EvidenceChunk]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.chunk_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(chunk.content_hash.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _stage_timing(
    stage: str,
    started: float,
    *,
    status: str = "completed",
    detail: str = "",
) -> ChatStageTiming:
    return ChatStageTiming(
        stage=stage,
        elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
        status=status,
        detail=detail,
    )
