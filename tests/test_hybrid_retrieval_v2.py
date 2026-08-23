import json
import time

import numpy as np

from core.knowledge_intelligence_models import HybridRetrievalRequest
from engine.evidence_discovery_index import EvidenceChunk, chunk_to_dict
from engine.hybrid_retrieval import HybridRetrievalService


def _write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def test_fts5_bm25_prefers_source_bound_chunk_and_dense_falls_back(tmp_path):
    index_dir = tmp_path / "indexes"
    evidence = EvidenceChunk(
        chunk_id="source:scrublet-input",
        evidence_id="src-1",
        source_kind="source_document",
        source_table="source_documents_v2.jsonl",
        source_record_id="src-1",
        source_id="src-1",
        source_document_id="src-1",
        source_span="Methods paragraph 2",
        tool_name="Scrublet",
        tool_names=["Scrublet"],
        task="doublet_detection",
        canonical_task="doublet_detection",
        task_tags=["doublet_detection"],
        claim_type="input_requirement",
        title="Scrublet methods",
        chunk_text="Scrublet requires a nonnegative raw count matrix as input.",
        content_hash="abc",
        source_bound=True,
        retrieval_status="retrieval_only",
    )
    catalog = EvidenceChunk(
        chunk_id="catalog:scrublet",
        evidence_id="catalog-1",
        source_kind="catalog_tool",
        source_table="catalog.json",
        source_record_id="catalog-1",
        tool_name="Scrublet",
        tool_names=["Scrublet"],
        title="Scrublet catalog entry",
        chunk_text="Scrublet is a doublet detection tool.",
        content_hash="def",
        source_bound=True,
        retrieval_status="catalog_only",
    )
    _write_jsonl(index_dir / "evidence_chunks.jsonl", [chunk_to_dict(evidence)])
    _write_jsonl(index_dir / "scrna_tools_catalog_chunks.jsonl", [chunk_to_dict(catalog)])
    (index_dir / "evidence_index_manifest.json").write_text(
        json.dumps({"build_id": "test-build"}), encoding="utf-8"
    )
    service = HybridRetrievalService(
        evidence_chunks_path=index_dir / "evidence_chunks.jsonl",
        catalog_chunks_path=index_dir / "scrna_tools_catalog_chunks.jsonl",
        fts_index_path=index_dir / "evidence_fts5.sqlite",
        index_manifest_path=index_dir / "evidence_index_manifest.json",
        coverage_path=index_dir / "coverage.json",
        dense_matrix_path=index_dir / "vectors.npy",
        dense_metadata_path=index_dir / "vectors.json",
        graph_dir=tmp_path / "missing-graph",
    )

    result = service.search(
        HybridRetrievalRequest(
            query="What raw count input does Scrublet require?",
            tool_names=["Scrublet"],
            claim_types=["input_requirement"],
            top_k=2,
            enable_dense=True,
        )
    )

    assert result.mode == "kg_bm25"
    assert result.dense_status == "vector_index_missing"
    assert result.hits[0].chunk_id == "source:scrublet-input"
    assert result.hits[0].source_bound is True
    assert result.governance_leakage_count == 0
    assert service.index_build_id == "test-build"


def test_index_is_reused_without_reparsing_jsonl(tmp_path):
    index_dir = tmp_path / "indexes"
    chunk = EvidenceChunk(
        chunk_id="source:harmony",
        evidence_id="src-h",
        source_kind="source_document",
        source_table="source.jsonl",
        source_record_id="src-h",
        tool_name="Harmony",
        tool_names=["Harmony"],
        chunk_text="Harmony integrates PCA embeddings across batches.",
        source_span="README usage",
        source_bound=True,
        retrieval_status="retrieval_only",
    )
    chunks_path = index_dir / "evidence_chunks.jsonl"
    _write_jsonl(chunks_path, [chunk_to_dict(chunk)])
    catalog_path = index_dir / "catalog.jsonl"
    _write_jsonl(catalog_path, [])
    manifest = index_dir / "manifest.json"
    manifest.write_text(json.dumps({"build_id": "stable"}), encoding="utf-8")
    kwargs = dict(
        evidence_chunks_path=chunks_path,
        catalog_chunks_path=catalog_path,
        fts_index_path=index_dir / "fts.sqlite",
        index_manifest_path=manifest,
        coverage_path=index_dir / "coverage.json",
        graph_dir=tmp_path / "missing",
    )
    first = HybridRetrievalService(**kwargs)
    mtime = first.fts_index_path.stat().st_mtime_ns
    second = HybridRetrievalService(**kwargs)

    assert second.fts_index_path.stat().st_mtime_ns == mtime
    assert second.search(HybridRetrievalRequest(query="Harmony batches", enable_dense=False)).hits


class _DeterministicDenseEncoder:
    model_name = "test/dense"
    model_revision = "revision-1"
    snapshot_digest = "a" * 64

    def encode(self, texts):
        values = []
        for text in texts:
            lowered = text.casefold()
            values.append(
                [
                    float("scrublet" in lowered or "doublet" in lowered),
                    float("harmony" in lowered or "batch" in lowered),
                ]
            )
        return np.asarray(values, dtype=np.float32)


def test_dense_index_records_source_identity_and_rejects_stale_digest(tmp_path):
    index_dir = tmp_path / "indexes"
    chunk = EvidenceChunk(
        chunk_id="source:scrublet-dense",
        evidence_id="src-dense",
        source_kind="source_document",
        source_table="source.jsonl",
        source_record_id="src-dense",
        source_id="src-dense",
        tool_name="Scrublet",
        tool_names=["Scrublet"],
        chunk_text="Scrublet detects doublets from raw count matrices.",
        source_span="Methods",
        content_hash="content-digest",
        source_bound=True,
        retrieval_status="retrieval_only",
    )
    chunks_path = index_dir / "evidence.jsonl"
    catalog_path = index_dir / "catalog.jsonl"
    manifest_path = index_dir / "manifest.json"
    _write_jsonl(chunks_path, [chunk_to_dict(chunk)])
    _write_jsonl(catalog_path, [])
    manifest_path.write_text(json.dumps({"build_id": "dense-build"}), encoding="utf-8")
    kwargs = dict(
        evidence_chunks_path=chunks_path,
        catalog_chunks_path=catalog_path,
        fts_index_path=index_dir / "fts.sqlite",
        index_manifest_path=manifest_path,
        coverage_path=index_dir / "coverage.json",
        dense_matrix_path=index_dir / "vectors.npy",
        dense_metadata_path=index_dir / "vectors.json",
        graph_dir=tmp_path / "missing",
    )
    service = HybridRetrievalService(**kwargs)
    metadata = service.build_dense_index(_DeterministicDenseEncoder())

    assert metadata["model_revision"] == "revision-1"
    assert metadata["snapshot_digest"] == "a" * 64
    assert metadata["source_digest"]
    assert metadata["normalized"] is True

    stored = json.loads((index_dir / "vectors.json").read_text(encoding="utf-8"))
    stored["source_digest"] = "stale"
    (index_dir / "vectors.json").write_text(json.dumps(stored), encoding="utf-8")
    reloaded = HybridRetrievalService(**kwargs)
    result = reloaded.search(
        HybridRetrievalRequest(
            query="Scrublet doublet",
            enable_sparse=False,
            enable_dense=True,
            use_kg=False,
        )
    )

    assert result.dense_status == "vector_index_missing"
    assert result.hits == []


def test_nonblocking_dense_falls_back_then_uses_bounded_query_cache(tmp_path):
    index_dir = tmp_path / "indexes"
    chunk = EvidenceChunk(
        chunk_id="source:scrublet-cache",
        evidence_id="src-cache",
        source_kind="source_document",
        source_table="source.jsonl",
        source_record_id="src-cache",
        source_id="src-cache",
        tool_name="Scrublet",
        tool_names=["Scrublet"],
        chunk_text="Scrublet detects doublets from raw count matrices.",
        source_span="Methods",
        content_hash="cache-digest",
        source_bound=True,
        retrieval_status="retrieval_only",
    )
    _write_jsonl(index_dir / "evidence.jsonl", [chunk_to_dict(chunk)])
    _write_jsonl(index_dir / "catalog.jsonl", [])
    (index_dir / "manifest.json").write_text(
        json.dumps({"build_id": "cache-build"}),
        encoding="utf-8",
    )
    service = HybridRetrievalService(
        evidence_chunks_path=index_dir / "evidence.jsonl",
        catalog_chunks_path=index_dir / "catalog.jsonl",
        fts_index_path=index_dir / "fts.sqlite",
        index_manifest_path=index_dir / "manifest.json",
        coverage_path=index_dir / "coverage.json",
        dense_matrix_path=index_dir / "vectors.npy",
        dense_metadata_path=index_dir / "vectors.json",
        dense_encoder=_DeterministicDenseEncoder(),
        graph_dir=tmp_path / "missing",
        query_cache_size=2,
    )
    service.build_dense_index(_DeterministicDenseEncoder())
    request = HybridRetrievalRequest(
        query="Scrublet doublet",
        enable_sparse=False,
        enable_dense=True,
        nonblocking_dense=True,
        use_kg=False,
    )

    first = service.search(request)
    assert first.dense_status == "query_warming_sparse_fallback"
    for _ in range(100):
        second = service.search(request)
        if second.dense_status == "ready":
            break
        time.sleep(0.01)

    assert second.dense_status == "ready"
    assert second.hits[0].chunk_id == "source:scrublet-cache"
    assert service.embedding_worker_status.state == "ready"


def test_named_tool_in_query_is_used_as_a_hard_source_constraint(tmp_path):
    index_dir = tmp_path / "indexes"
    chunks = [
        EvidenceChunk(
            chunk_id="source:harmony-shared",
            evidence_id="shared",
            source_kind="source_document",
            source_table="source.jsonl",
            source_record_id="shared",
            source_id="shared",
            tool_name="Harmony",
            tool_names=["Harmony", "Scanorama"],
            chunk_text="Harmony corrects a PCA embedding across batches.",
            source_span="Benchmark paragraph 1",
            source_bound=True,
            retrieval_status="retrieval_only",
        ),
        EvidenceChunk(
            chunk_id="source:scanorama-official",
            evidence_id="scanorama",
            source_kind="source_document",
            source_table="source.jsonl",
            source_record_id="scanorama",
            source_id="scanorama",
            tool_name="Scanorama",
            tool_names=["Scanorama"],
            chunk_text="Scanorama integrates heterogeneous single-cell datasets.",
            source_span="README overview",
            source_bound=True,
            retrieval_status="retrieval_only",
        ),
    ]
    _write_jsonl(index_dir / "evidence.jsonl", [chunk_to_dict(row) for row in chunks])
    _write_jsonl(index_dir / "catalog.jsonl", [])
    (index_dir / "manifest.json").write_text(
        json.dumps({"build_id": "named-tool"}), encoding="utf-8"
    )
    service = HybridRetrievalService(
        evidence_chunks_path=index_dir / "evidence.jsonl",
        catalog_chunks_path=index_dir / "catalog.jsonl",
        fts_index_path=index_dir / "fts.sqlite",
        index_manifest_path=index_dir / "manifest.json",
        coverage_path=index_dir / "coverage.json",
        graph_dir=tmp_path / "missing",
    )

    result = service.search(
        HybridRetrievalRequest(
            query="Find source-bound information about Scanorama",
            enable_dense=False,
            use_kg=False,
        )
    )

    assert [hit.chunk_id for hit in result.hits] == ["source:scanorama-official"]
    assert result.hits[0].tool_names == ["Scanorama"]

    blocked = service.search(
        HybridRetrievalRequest(
            query="Use Scanorama to assemble a reference genome from long reads.",
            enable_dense=False,
            use_kg=False,
        )
    )
    assert blocked.hits == []
    assert "unsupported_operation_scope:genome_assembly" in blocked.warnings


def test_broad_task_search_preserves_tool_diversity(tmp_path):
    index_dir = tmp_path / "indexes"
    chunks = []
    for index in range(6):
        chunks.append(
            EvidenceChunk(
                chunk_id=f"source:harmony-{index}",
                evidence_id=f"harmony-{index}",
                source_kind="source_document",
                source_table="source.jsonl",
                source_record_id=f"harmony-{index}",
                source_id=f"harmony-{index}",
                tool_name="Harmony",
                tool_names=["Harmony"],
                task="batch_integration",
                canonical_task="batch_integration",
                task_tags=["batch_integration"],
                chunk_text="Harmony batch integration embedding method.",
                source_span=f"Harmony paragraph {index}",
                source_bound=True,
                retrieval_status="retrieval_only",
            )
        )
    for tool in ("Scanorama", "Seurat"):
        chunks.append(
            EvidenceChunk(
                chunk_id=f"source:{tool.casefold()}",
                evidence_id=tool.casefold(),
                source_kind="source_document",
                source_table="source.jsonl",
                source_record_id=tool.casefold(),
                source_id=tool.casefold(),
                tool_name=tool,
                tool_names=[tool],
                task="batch_integration",
                canonical_task="batch_integration",
                task_tags=["batch_integration"],
                chunk_text=f"{tool} batch integration embedding method.",
                source_span=f"{tool} overview",
                source_bound=True,
                retrieval_status="retrieval_only",
            )
        )
    _write_jsonl(index_dir / "evidence.jsonl", [chunk_to_dict(row) for row in chunks])
    _write_jsonl(index_dir / "catalog.jsonl", [])
    (index_dir / "manifest.json").write_text(
        json.dumps({"build_id": "tool-diversity"}), encoding="utf-8"
    )
    service = HybridRetrievalService(
        evidence_chunks_path=index_dir / "evidence.jsonl",
        catalog_chunks_path=index_dir / "catalog.jsonl",
        fts_index_path=index_dir / "fts.sqlite",
        index_manifest_path=index_dir / "manifest.json",
        coverage_path=index_dir / "coverage.json",
        graph_dir=tmp_path / "missing",
    )

    result = service.search(
        HybridRetrievalRequest(
            query="single-cell batch integration embedding method",
            canonical_tasks=["batch_integration"],
            top_k=5,
            enable_dense=False,
            use_kg=False,
        )
    )

    assert {hit.tool_name for hit in result.hits} == {
        "Harmony",
        "Scanorama",
        "Seurat",
    }
