from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.trace_context import load_traces
from data_pipeline import run_evidence_gap_acquisition_pilot_v1 as pilot


EXTRACTED_TEXT = """
Package SoupX
Version 1.6.2
SoupChannel Construct a SoupChannel object
Arguments
tod Table of droplets. A matrix with columns being each droplet and rows each gene.
toc Table of counts. Just those columns of tod that contain cells.
Value A SoupChannel object.
""".strip()


def _fake_download(candidates, target, *, session, timeout):
    assert candidates == [
        {
            "url": "https://cran.r-project.org/web/packages/SoupX/SoupX.pdf",
            "source": "direct_pdf_url",
        }
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4\nsynthetic bounded test artifact\n")
    return {
        "status": "downloaded",
        "selected_pdf_url": candidates[0]["url"],
        "target_pdf": str(target),
        "error": "",
    }


def _fake_extract(path: Path):
    assert path.read_bytes().startswith(b"%PDF")
    return {
        "ok": True,
        "text": EXTRACTED_TEXT,
        "page_count": 26,
        "extractor": "test-fixture",
    }


def test_inventory_reuses_existing_acquisition_components():
    rows = pilot.architecture_inventory()
    assert {row["status"] for row in rows} <= {
        "usable_as_is",
        "usable_as_is_not_invoked_in_cp5",
        "needs_thin_acquisition_adapter",
    }
    assert any("CrossrefClient" in row["component"] for row in rows)
    assert any("download_evidence_pdfs" in row["component"] for row in rows)
    assert any("Trace" in row["responsibility"] or "audit" in row["responsibility"] for row in rows)


def test_selected_gap_and_source_are_existing_candidate_records():
    gap = pilot.load_selected_gap()
    source = pilot.discover_authoritative_source()
    assert gap["gap_id"] == pilot.PILOT_GAP_ID
    assert gap["candidate_only"] is True
    assert source["ecosystem"] == "SoupX"
    assert source["authority"] == "official"
    assert source["version"] == "1.6.2"


def test_bounded_span_is_exact_and_candidate_only():
    row = pilot.extract_bounded_span(EXTRACTED_TEXT)
    assert row["exact_text"].startswith("tod Table of droplets")
    assert row["exact_text"].endswith("contain cells.")
    assert row["content_hash"] == pilot.sha256_bytes(row["exact_text"].encode())
    assert row["review_status"] == "candidate_pending_review"


def test_acquire_then_reuse_is_deduplicated_and_traceable(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "download_first_valid_pdf", _fake_download)
    monkeypatch.setattr(pilot, "extract_pdf_text", _fake_extract)

    acquired = pilot.run_pilot(output_root=tmp_path, mode="acquire")
    assert acquired["status"] == "PASS"
    assert acquired["source_identity_reused"] is False
    registry_before = (tmp_path / "source_registry.json").read_bytes()

    def _download_must_not_run(*args, **kwargs):
        raise AssertionError("reuse mode must not redownload the source")

    monkeypatch.setattr(pilot, "download_first_valid_pdf", _download_must_not_run)
    reused = pilot.run_pilot(output_root=tmp_path, mode="reuse")
    assert reused["status"] == "PASS"
    assert reused["source_identity_reused"] is True
    assert reused["artifact_reused"] is True
    assert (tmp_path / "source_registry.json").read_bytes() == registry_before

    registry = json.loads(registry_before)
    assert len(registry["source_works"]) == 1
    assert len(registry["source_revisions"]) == 1
    assert len(registry["source_artifacts"]) == 1
    assert json.loads((tmp_path / "summary.json").read_text())["promotion_performed"] is False

    for mode in ("acquire", "reuse"):
        traces = load_traces(tmp_path / "runs" / mode / "trace.jsonl")
        assert len(traces) == 1
        stages = [span["stage"] for span in traces[0]["spans"]]
        assert stages == [
            "REQUEST",
            "STATE_INSPECTION",
            "RETRIEVAL",
            "DECISION",
            "RETRIEVAL",
            "VALIDATION",
            "VALIDATION",
        ]


def test_acquire_is_write_once(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "download_first_valid_pdf", _fake_download)
    monkeypatch.setattr(pilot, "extract_pdf_text", _fake_extract)
    pilot.run_pilot(output_root=tmp_path, mode="acquire")
    with pytest.raises(FileExistsError, match="pilot_run_already_exists"):
        pilot.run_pilot(output_root=tmp_path, mode="acquire")
