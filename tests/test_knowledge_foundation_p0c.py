from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from core.settings import PROJECT_ROOT
from eval.knowledge_foundation_p0c import (
    DEFAULT_OUTPUT_DIR,
    inspect_dense_index,
    run_bm25_fallback_smoke,
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_physical_dense_index_matches_frozen_corpus_and_model_pack() -> None:
    result = inspect_dense_index()

    assert all(result["checks"].values())
    assert result["model"] == "BAAI/bge-m3"
    assert result["model_revision"] == "cb1779f90b988b8deb01f9155c790ef9417d7648"
    assert result["indexed_chunk_count"] == result["eligible_source_chunk_count"] == 773
    assert result["vector_count"] == 773
    assert result["embedding_dimension"] == 1024
    assert result["matrix_dtype"] == "float32"
    assert result["unresolved_chunk_ids"] == []
    assert result["duplicate_chunk_id_count"] == 0


def test_fresh_python_process_cold_reloads_same_dense_index() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "eval.knowledge_foundation_p0c", "--inspect-only"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["checks"]["fresh_service_reloads_physical_index"] is True
    assert result["checks"]["chunk_order_and_membership_match"] is True
    assert result["checks"]["source_digest_matches_frozen_corpus"] is True


def test_missing_dense_artifacts_preserve_governed_bm25_fallback() -> None:
    result = run_bm25_fallback_smoke()

    assert result["dense_status"] == "vector_index_missing"
    assert result["mode"] == "kg_bm25"
    assert result["hit_count"] > 0
    assert result["source_bound_hit_count"] > 0
    assert result["warning_present"] is True


def test_frozen_p0c_result_records_real_query_and_physical_hashes() -> None:
    summary = _json(DEFAULT_OUTPUT_DIR / "summary.json")
    manifest = _json(DEFAULT_OUTPUT_DIR / "manifest.json")

    assert summary["decision"] == "PASS"
    assert summary["dense_available"] is True
    assert all(summary["gates"].values())
    assert summary["dense_query_smoke"]["dense_status"] == "ready"
    assert summary["dense_query_smoke"]["repeat_ranking_identical"] is True
    assert summary["dense_query_smoke"]["hits"][0]["source_bound"] is True
    assert summary["retrieval_benchmark_run"] is False
    assert manifest["dense_available"] is True
    assert set(manifest["physical_dense_artifacts"]) == {
        "evidence_vectors.npy",
        "evidence_vector_metadata.json",
        "evidence_index_manifest.json",
    }
    for name, digest in manifest["artifacts"].items():
        assert _sha256(DEFAULT_OUTPUT_DIR / name) == digest


def test_p0c_artifacts_do_not_embed_absolute_local_paths() -> None:
    for path in DEFAULT_OUTPUT_DIR.iterdir():
        if path.is_file():
            assert str(PROJECT_ROOT) not in path.read_text(encoding="utf-8")
