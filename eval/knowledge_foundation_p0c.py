from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from core.knowledge_intelligence_models import HybridRetrievalRequest
from core.settings import PROJECT_ROOT
from engine.evidence_discovery_index import EvidenceChunk
from engine.hybrid_retrieval import (
    DEFAULT_CATALOG_CHUNKS,
    DEFAULT_COVERAGE,
    DEFAULT_DENSE_MATRIX,
    DEFAULT_DENSE_METADATA,
    DEFAULT_EVIDENCE_CHUNKS,
    DEFAULT_FTS_INDEX,
    DEFAULT_INDEX_MANIFEST,
    DEFAULT_MODEL_PACK_MANIFEST,
    HybridRetrievalService,
    LocalBgeM3Encoder,
)
from execution.model_pack_manager import ModelPackManager


DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "evaluation" / "knowledge_foundation_p0c"
)
REPRESENTATIVE_QUERY = (
    "What raw count input does Scrublet require for doublet detection?"
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_chunk_digest(chunks: list[EvidenceChunk]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.chunk_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(chunk.content_hash.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _eligible_source_chunks(service: HybridRetrievalService) -> list[EvidenceChunk]:
    return sorted(
        [
            chunk
            for chunk in service._chunks_by_id.values()
            if chunk.source_bound and chunk.retrieval_status != "catalog_only"
        ],
        key=lambda item: item.chunk_id,
    )


def inspect_dense_index() -> dict[str, Any]:
    metadata = _read_json(DEFAULT_DENSE_METADATA)
    index_manifest = _read_json(DEFAULT_INDEX_MANIFEST)
    model_manifest = _read_json(DEFAULT_MODEL_PACK_MANIFEST)
    model_probe = ModelPackManager().probe().model_dump(mode="json")
    service = HybridRetrievalService()
    chunks = _eligible_source_chunks(service)
    expected_chunk_ids = [chunk.chunk_id for chunk in chunks]
    matrix = np.load(DEFAULT_DENSE_MATRIX, mmap_mode="r")
    norms = np.linalg.norm(matrix, axis=1) if matrix.size else np.asarray([])
    chunk_ids = [str(value) for value in metadata.get("chunk_ids", [])]
    unresolved_chunk_ids = [
        chunk_id for chunk_id in chunk_ids if chunk_id not in service._chunks_by_id
    ]
    duplicate_chunk_ids = len(chunk_ids) - len(set(chunk_ids))
    independently_computed_source_digest = _source_chunk_digest(chunks)

    checks = {
        "physical_artifacts_present": (
            DEFAULT_DENSE_MATRIX.is_file() and DEFAULT_DENSE_METADATA.is_file()
        ),
        "model_pack_ready": model_probe["state"] == "ready",
        "model_identity_matches_manifest": (
            metadata.get("model") == model_manifest["model_id"]
            and metadata.get("model_revision") == model_manifest["revision"]
            and model_probe.get("model_id") == model_manifest["model_id"]
            and model_probe.get("revision") == model_manifest["revision"]
        ),
        "snapshot_identity_matches": (
            bool(metadata.get("snapshot_digest"))
            and metadata.get("snapshot_digest") == model_probe.get("snapshot_digest")
        ),
        "index_build_identity_matches": (
            metadata.get("build_id") == index_manifest.get("build_id")
        ),
        "source_digest_matches_frozen_corpus": (
            metadata.get("source_digest")
            == index_manifest.get("embedding", {}).get("dense_source_digest")
            == independently_computed_source_digest
        ),
        "chunk_order_and_membership_match": chunk_ids == expected_chunk_ids,
        "all_chunk_ids_resolve": not unresolved_chunk_ids,
        "no_duplicate_chunk_ids": duplicate_chunk_ids == 0,
        "vector_count_matches_chunks": (
            matrix.ndim == 2
            and matrix.shape[0] == len(chunk_ids) == len(expected_chunk_ids)
            and matrix.shape[0]
            == index_manifest.get("embedding", {}).get("vector_count")
        ),
        "embedding_dimension_matches_manifest": (
            matrix.ndim == 2
            and matrix.shape[1] == model_manifest["embedding_dimension"]
        ),
        "matrix_is_float32_and_finite": (
            matrix.dtype == np.float32 and bool(np.isfinite(matrix).all())
        ),
        "vectors_are_normalized": (
            bool(metadata.get("normalized"))
            and bool(norms.size)
            and bool(np.allclose(norms, 1.0, atol=1e-5))
        ),
        "fresh_service_reloads_physical_index": (
            service._dense_matrix is not None
            and list(service._dense_matrix.shape) == list(matrix.shape)
            and service._dense_chunk_ids == chunk_ids
            and service._dense_source_digest == metadata.get("source_digest")
        ),
    }
    return {
        "schema_version": "knowledge-foundation-p0c-inspection-v1",
        "model": metadata.get("model"),
        "model_revision": metadata.get("model_revision"),
        "snapshot_digest": metadata.get("snapshot_digest"),
        "model_pack_manifest_sha256": _sha256(DEFAULT_MODEL_PACK_MANIFEST),
        "index_build_id": metadata.get("build_id"),
        "corpus_source_digest": metadata.get("source_digest"),
        "independently_computed_source_digest": independently_computed_source_digest,
        "evidence_chunk_count": service.chunk_count,
        "eligible_source_chunk_count": len(expected_chunk_ids),
        "indexed_chunk_count": len(chunk_ids),
        "vector_count": int(matrix.shape[0]),
        "embedding_dimension": int(matrix.shape[1]),
        "matrix_dtype": str(matrix.dtype),
        "vector_norm_min": float(norms.min()) if norms.size else None,
        "vector_norm_max": float(norms.max()) if norms.size else None,
        "unresolved_chunk_ids": unresolved_chunk_ids,
        "duplicate_chunk_id_count": duplicate_chunk_ids,
        "artifacts": {
            "evidence_vectors.npy": _sha256(DEFAULT_DENSE_MATRIX),
            "evidence_vector_metadata.json": _sha256(DEFAULT_DENSE_METADATA),
            "evidence_index_manifest.json": _sha256(DEFAULT_INDEX_MANIFEST),
        },
        "model_pack": {
            "state": model_probe["state"],
            "environment_ready": model_probe["environment_ready"],
            "snapshot_ready": model_probe["snapshot_ready"],
            "install_root": model_probe["install_root_redacted"],
            "warnings": model_probe["warnings"],
        },
        "checks": checks,
    }


def run_dense_query_smoke() -> dict[str, Any]:
    encoder = LocalBgeM3Encoder()
    try:
        service = HybridRetrievalService(dense_encoder=encoder)
        request = HybridRetrievalRequest(
            query=REPRESENTATIVE_QUERY,
            tool_names=["Scrublet"],
            claim_types=["input_requirement"],
            top_k=5,
            enable_sparse=False,
            enable_dense=True,
            use_kg=False,
            use_governance_rerank=False,
            use_contract_gate=False,
        )
        first = service.search(request)
        second = service.search(request)
        first_ids = [hit.chunk_id for hit in first.hits]
        second_ids = [hit.chunk_id for hit in second.hits]
        return {
            "schema_version": "knowledge-foundation-p0c-dense-query-smoke-v1",
            "query": REPRESENTATIVE_QUERY,
            "request": {
                "tool_names": ["Scrublet"],
                "claim_types": ["input_requirement"],
                "top_k": 5,
                "enable_sparse": False,
                "enable_dense": True,
                "use_kg": False,
                "use_governance_rerank": False,
                "use_contract_gate": False,
            },
            "dense_status": first.dense_status,
            "mode": first.mode,
            "embedding_model": first.embedding_model,
            "index_build_id": first.index_build_id,
            "repeat_ranking_identical": first_ids == second_ids,
            "hit_count": len(first.hits),
            "hits": [
                {
                    "rank": index,
                    "chunk_id": hit.chunk_id,
                    "source_id": hit.source_id,
                    "source_span": hit.source_span,
                    "tool_name": hit.tool_name,
                    "canonical_task": hit.canonical_task,
                    "claim_type": hit.claim_type,
                    "dense_rank": hit.dense_rank,
                    "source_bound": hit.source_bound,
                }
                for index, hit in enumerate(first.hits, start=1)
            ],
            "warnings": first.warnings,
        }
    finally:
        worker = getattr(encoder, "_worker", None)
        if worker is not None:
            worker.close()


def run_bm25_fallback_smoke() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sckg-p0c-fallback-") as directory:
        missing = Path(directory)
        service = HybridRetrievalService(
            evidence_chunks_path=DEFAULT_EVIDENCE_CHUNKS,
            catalog_chunks_path=DEFAULT_CATALOG_CHUNKS,
            fts_index_path=DEFAULT_FTS_INDEX,
            index_manifest_path=DEFAULT_INDEX_MANIFEST,
            coverage_path=DEFAULT_COVERAGE,
            dense_matrix_path=missing / "missing-vectors.npy",
            dense_metadata_path=missing / "missing-metadata.json",
        )
        result = service.search(
            HybridRetrievalRequest(
                query=REPRESENTATIVE_QUERY,
                tool_names=["Scrublet"],
                claim_types=["input_requirement"],
                top_k=5,
                enable_sparse=True,
                enable_dense=True,
                use_kg=True,
            )
        )
    return {
        "schema_version": "knowledge-foundation-p0c-bm25-fallback-smoke-v1",
        "dense_status": result.dense_status,
        "mode": result.mode,
        "hit_count": len(result.hits),
        "source_bound_hit_count": sum(hit.source_bound for hit in result.hits),
        "hit_chunk_ids": [hit.chunk_id for hit in result.hits],
        "warning_present": any("fallback" in value.casefold() for value in result.warnings),
    }


def qualify_dense_retrieval(*, run_live_query: bool) -> dict[str, Any]:
    inspection = inspect_dense_index()
    fallback = run_bm25_fallback_smoke()
    dense_query = run_dense_query_smoke() if run_live_query else None
    gates = {
        **inspection["checks"],
        "bm25_fallback_preserved": (
            fallback["dense_status"] == "vector_index_missing"
            and fallback["mode"] == "kg_bm25"
            and fallback["hit_count"] > 0
            and fallback["source_bound_hit_count"] > 0
            and fallback["warning_present"]
        ),
        "representative_dense_query_ready": bool(
            dense_query
            and dense_query["dense_status"] == "ready"
            and dense_query["mode"] == "dense"
            and dense_query["embedding_model"] == inspection["model"]
            and dense_query["hit_count"] > 0
            and all(hit["source_bound"] for hit in dense_query["hits"])
            and dense_query["repeat_ranking_identical"]
        ),
    }
    return {
        "schema_version": "knowledge-foundation-p0c-summary-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": "PASS" if all(gates.values()) else "NO-GO",
        "dense_available": all(gates.values()),
        "scope": "local_dense_retrieval_qualification_only",
        "canonical_promotion": "none",
        "retrieval_benchmark_run": False,
        "inspection": inspection,
        "dense_query_smoke": dense_query,
        "bm25_fallback_smoke": fallback,
        "gates": gates,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_qualification(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    run_live_query: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = qualify_dense_retrieval(run_live_query=run_live_query)
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "dense_query_smoke.json", summary["dense_query_smoke"] or {})
    _write_json(output_dir / "bm25_fallback_smoke.json", summary["bm25_fallback_smoke"])
    manifest = {
        "schema_version": "knowledge-foundation-p0c-manifest-v1",
        "decision": summary["decision"],
        "dense_available": summary["dense_available"],
        "artifacts": {
            name: _sha256(output_dir / name)
            for name in (
                "summary.json",
                "dense_query_smoke.json",
                "bm25_fallback_smoke.json",
            )
        },
        "physical_dense_artifacts": summary["inspection"]["artifacts"],
        "model_pack_manifest_sha256": summary["inspection"][
            "model_pack_manifest_sha256"
        ],
        "corpus_source_digest": summary["inspection"]["corpus_source_digest"],
    }
    _write_json(output_dir / "manifest.json", manifest)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Qualify the frozen local BGE-M3 dense retrieval index."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-live-query", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()
    if args.inspect_only:
        payload = inspect_dense_index()
    else:
        payload = write_qualification(
            args.output_dir,
            run_live_query=args.run_live_query,
        )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if all(payload.get("checks", payload.get("gates", {})).values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
