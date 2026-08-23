from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from data_pipeline.scrna_tools_catalog import (
    build_catalog_audit,
    parse_catalog_payload,
    write_catalog_snapshot,
)
from engine.evidence_discovery_index import catalog_tool_chunks


def _rows() -> list[dict[str, object]]:
    return [
        {
            "Tool": "Alpha",
            "Platform": "Python",
            "Code": "https://example.org/alpha",
            "Description": "Cell annotation tool.",
            "License": "MIT",
            "Added": "2020-01-01",
            "Updated": "2026-01-01",
            "Categories": ["Classification"],
            "Publications": [
                {"Title": "Alpha paper", "DOI": "10.1/alpha", "Date": "2020", "Citations": 3}
            ],
            "Preprints": [],
            "Citations": 3,
            "GitHub": "org/alpha",
        },
        {
            "Tool": "Beta",
            "Platform": "R",
            "Description": "Clustering tool.",
            "Added": "2021-01-01",
            "Updated": "2026-02-01",
            "Categories": ["Clustering"],
            "Publications": [],
            "Preprints": [],
        },
    ]


def _write_tsv(path: Path, names: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Tool", "Platform", "Code", "Description", "License", "Added", "Updated"],
            delimiter="\t",
        )
        writer.writeheader()
        for name in names:
            writer.writerow(
                {
                    "Tool": name,
                    "Platform": "Python",
                    "Code": "NA",
                    "Description": "old",
                    "License": "NA",
                    "Added": "2020-01-01",
                    "Updated": "2020-01-01",
                }
            )


def test_catalog_parser_rejects_duplicate_or_category_free_tools():
    rows = _rows()
    rows[1]["Tool"] = "Alpha"
    with pytest.raises(ValueError, match="duplicate"):
        parse_catalog_payload(json.dumps(rows).encode())

    rows = _rows()
    rows[1]["Categories"] = []
    with pytest.raises(ValueError, match="no category"):
        parse_catalog_payload(json.dumps(rows).encode())


def test_catalog_audit_reports_name_and_field_drift(tmp_path: Path):
    current = tmp_path / "scrna_tools.tsv"
    _write_tsv(current, ["Alpha", "Legacy"])
    rows = parse_catalog_payload(json.dumps(_rows()).encode())

    audit = build_catalog_audit(rows, current_tsv=current, source_sha256="abc")

    assert audit["catalog_alignment_status"] == "drift_detected"
    assert audit["source_only_tools"] == ["Beta"]
    assert audit["local_only_tools"] == ["Legacy"]
    assert audit["publication_count"] == 1
    assert audit["category_count"] == 2


def test_catalog_apply_writes_full_snapshot_and_compatibility_view(tmp_path: Path):
    rows = parse_catalog_payload(json.dumps(_rows()).encode())
    snapshot = tmp_path / "catalog" / "snapshot.json"
    compatibility = tmp_path / "scrna_tools.tsv"
    audit_path = tmp_path / "audit.json"

    result = write_catalog_snapshot(
        rows,
        snapshot_path=snapshot,
        compatibility_tsv=compatibility,
        audit_path=audit_path,
        source_sha256="abc",
    )

    saved = json.loads(snapshot.read_text(encoding="utf-8"))
    with compatibility.open(encoding="utf-8") as handle:
        compatibility_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert saved["tool_count"] == 2
    assert saved["tools"][0]["Categories"]
    assert len(compatibility_rows) == 2
    assert result["catalog_alignment_status"] == "aligned"
    assert result["pre_apply_drift"]["source_only_tools"] == ["Alpha", "Beta"]

    chunks = catalog_tool_chunks(snapshot)
    assert len(chunks) == 2
    assert chunks[0].source_kind == "catalog_tool"
    assert chunks[0].graph_layer == "retrieval_only"
    assert "cannot support recommendation" in chunks[0].claim_boundary
