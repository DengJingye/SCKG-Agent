"""Temporary fixtures only: no retrieval, mutation of artifacts or benchmark runs."""
import json
from pathlib import Path

import numpy as np
import pytest

from observability.dashboard.evidence_data import (
    EvidenceDashboardData, LEGACY_BOUNDARY, UNKNOWN, NOT_MEASURED, field_value,
)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def snapshot(root, name, ids=("a", "b"), tools=None):
    directory = root / "data/indexes" / name
    directory.mkdir(parents=True, exist_ok=True)
    rows = [{"chunk_id": cid, "source_bound": True, "source_id": "s", "chunk_text": "text",
             "tool_names": tools or ["A", "B"], "retrieval_status": "candidate"} for cid in ids]
    (directory / "evidence_chunks.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    dump(directory / "evidence_index_manifest.json", {"build_id": name or "base", "evidence_chunk_count": len(ids)})
    dump(directory / "evidence_vector_metadata.json", {"build_id": name or "base", "chunk_ids": list(ids), "shape": [len(ids), 2]})
    np.save(directory / "evidence_vectors.npy", np.zeros((len(ids), 2)))
    (root / "engine").mkdir(exist_ok=True)
    (root / "engine/source_corpus_v2.py").write_text('CORE_TOOLS = ("A", "B")\nQUALIFIED_TOOLS = ("A",)\n')
    return directory


def test_snapshots_never_mix_and_shared_chunks_deduplicate(tmp_path):
    one = snapshot(tmp_path, "", ids=("a", "b"))
    two = snapshot(tmp_path, "second", ids=("x",), tools=["A"])
    service = EvidenceDashboardData(tmp_path)
    first = service.snapshot(one)
    second = service.snapshot(two)
    assert first["vector_count"] == 2 and second["vector_count"] == 1
    assert first["coverage"]["CORE_TOOLS"] == "2/2"
    assert second["coverage"]["CORE_TOOLS"] == "1/2"
    assert sum(r["vector_count"] for r in first["rows"]) == 4  # shared chunks
    assert {r["tool"]: r["vector_count"] for r in second["rows"]} == {"A": 1, "B": 0}
    assert service.snapshot(one)["vector_count"] == 2  # switching back
    assert not any("algorithm" in p["file"] for p in first["provenance"])


@pytest.mark.parametrize("fault", ["missing", "malformed", "unreadable", "foreign_ids", "duplicate_ids", "shape", "build", "matrix", "missing_identity"])
def test_vector_corruption_is_unknown_not_zero(tmp_path, fault):
    directory = snapshot(tmp_path, "one")
    path = directory / "evidence_vector_metadata.json"
    metadata = json.loads(path.read_text())
    if fault == "missing":
        path.unlink()
    elif fault == "malformed":
        path.write_text("{broken")
    elif fault == "unreadable":
        path.unlink()
        path.mkdir()
    elif fault == "matrix":
        np.save(directory / "evidence_vectors.npy", np.zeros((1, 3)))
    else:
        if fault == "foreign_ids": metadata["chunk_ids"] = ["x", "y"]
        if fault == "duplicate_ids": metadata["chunk_ids"] = ["a", "a"]
        if fault == "shape": metadata["shape"] = [9, 2]
        if fault == "build": metadata["build_id"] = "another-snapshot"
        if fault == "missing_identity": metadata.pop("build_id")
        dump(path, metadata)
    result = EvidenceDashboardData(tmp_path).snapshot(directory)
    assert result["vector_count"] == UNKNOWN
    assert all(row["vector_count"] == UNKNOWN for row in result["rows"])
    assert result["errors"]


@pytest.mark.parametrize("fault", ["missing_chunks", "malformed_chunks", "missing_tool", "missing_bound", "hash_mismatch"])
def test_missing_source_metadata_cannot_claim_100_percent(tmp_path, fault):
    directory = snapshot(tmp_path, "one")
    path = directory / "evidence_chunks.jsonl"
    if fault == "missing_chunks": path.unlink()
    elif fault == "malformed_chunks": path.write_text("broken")
    elif fault == "hash_mismatch":
        dump(directory / "evidence_index_manifest.json", {"build_id": "one", "artifacts": {path.name: "bad-hash"}})
    else:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0].pop("tool_names" if fault == "missing_tool" else "source_bound")
        path.write_text("\n".join(json.dumps(r) for r in rows))
    result = EvidenceDashboardData(tmp_path).snapshot(directory)
    assert result["coverage"]["CORE_TOOLS"] == UNKNOWN
    assert result["errors"]


def test_historical_identity_never_inferred_from_mtime(tmp_path):
    path = tmp_path / "data/evaluation/retrieval_eval_v2/summary.json"
    report = {"generated_at": "2026-08-04T07:38:16+00:00", "case_count": 96,
              "profiles": {"kg_bm25": {"recall_at_10": 0.996212}}}
    dump(path, report)
    before = path.read_bytes()
    result = EvidenceDashboardData(tmp_path).campaign(path)
    assert result["kind"] == "HISTORICAL"
    assert result["boundary"] == LEGACY_BOUNDARY
    assert result["provenance"][0]["run_id"] == UNKNOWN
    assert result["report"] == report and path.read_bytes() == before
    assert "hit_at_10" not in result["report"]["profiles"]["kg_bm25"]


def test_dev_invalidation_preserved(tmp_path):
    path = tmp_path / "eval_v2/retrieval_benchmark_v1_1_dev/report.json"
    dump(path, {"status": "COMPLETE"})
    doc = tmp_path / "docs/status/RETRIEVAL_BENCHMARK_V1_1_DEV_INVALIDATION.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("Status: INVALID")
    result = EvidenceDashboardData(tmp_path).campaign(path)
    assert result["kind"] == "DEVELOPMENT" and "INVALID" in result["invalidation"]
    assert result["report"]["status"] == "COMPLETE"


def test_source_partition_explains_total_and_exposes_stale_summary(tmp_path):
    base = tmp_path / "data/evidence_candidates"
    base.mkdir(parents=True)
    statuses = ["source_text_available"] * 17 + ["pdf_extraction_failed"] * 2 + ["source_metadata_mismatch"]
    registry = base / "source_registry.tsv"
    registry.write_text("source_id\tsource_status\n" + "\n".join(f"s{i}\t{s}" for i, s in enumerate(statuses)))
    dump(base / "source_acquisition_summary.json", {"source_records": 20})
    result = EvidenceDashboardData(tmp_path).source_audit()
    assert result["total"] == 20 and sum(result["counts"].values()) == 20
    assert result["counts"]["source_metadata_mismatch"] == 1
    assert result["counts"]["pdf_extraction_failed"] == 2
    registry.write_text(registry.read_text() + "\ns20\t\n")
    changed = EvidenceDashboardData(tmp_path).source_audit()
    assert changed["total"] == 21 and changed["counts"][UNKNOWN] == 1
    assert changed["errors"] and changed["provenance"][0]["sha256"] != result["provenance"][0]["sha256"]
    registry.unlink()
    missing = EvidenceDashboardData(tmp_path).source_audit()
    assert missing["total"] == UNKNOWN and missing["counts"] is None


@pytest.mark.parametrize("empty", [None, "", "none"])
def test_empty_values_are_field_specific_not_pass(empty):
    assert "无登记问题" in field_value("validation_issue", empty)
    assert ("无需处理" if empty == "none" else UNKNOWN) in field_value("recommended_action", empty)
    assert NOT_MEASURED in field_value("validation_status", empty)
    assert UNKNOWN in field_value("local_text_path", empty)
    assert field_value("text_chars", 0) == "0"


def test_panel_fixture_render_and_snapshot_switch(tmp_path):
    from streamlit.testing.v1 import AppTest
    snapshot(tmp_path, "", ids=("a", "b"))
    snapshot(tmp_path, "second", ids=("x",), tools=["A"])
    dump(tmp_path / "data/evaluation/retrieval_eval_v2/summary.json", {
        "case_count": 96, "profiles": {"kg_bm25": {"recall_at_10": .996212}},
        "generated_at": "2026-08-04T07:38:16+00:00"})
    code = f'from pathlib import Path\nfrom observability.dashboard.evidence_panel import render_evidence_panel\nrender_evidence_panel(Path({str(tmp_path)!r}))'
    app = AppTest.from_string(code).run()
    assert not app.exception
    assert app.metric[1].value == "2"
    assert any(LEGACY_BOUNDARY in w.value for w in app.warning)
    app.selectbox(key="evidence_snapshot").select("second").run()
    assert not app.exception and app.metric[1].value == "1"
    assert any("Core 参考名单：有可用来源关联的工具数 1/2" in m.value for m in app.markdown)
    assert app.metric[-4].value == UNKNOWN  # missing source registry is not zero


@pytest.mark.parametrize("content", ["", "wrong_header\n", "source_id\ns1\n"])
def test_missing_registry_schema_is_unknown(tmp_path, content):
    path = tmp_path / "data/evidence_candidates/source_registry.tsv"
    path.parent.mkdir(parents=True)
    path.write_text(content)
    audit = EvidenceDashboardData(tmp_path).source_audit()
    assert audit["total"] == UNKNOWN and audit["counts"] is None
