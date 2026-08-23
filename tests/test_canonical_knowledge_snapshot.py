import json
from pathlib import Path

from core.settings import PROJECT_ROOT


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_repository_canonical_snapshot_and_projections_are_in_sync():
    snapshot = _read(PROJECT_ROOT / "data" / "canonical_knowledge" / "manifest.json")
    catalog_manifest = _read(PROJECT_ROOT / "data" / "knowledge_graph_v2" / "manifest.json")
    decision_manifest = _read(PROJECT_ROOT / "data" / "decision_graph_v3" / "manifest.json")
    quality = _read(PROJECT_ROOT / "data" / "knowledge_graph_v2" / "quality_report.json")

    assert snapshot["integrity_passed"] is True
    assert snapshot["task_count"] == 15
    assert snapshot["catalog_tool_count"] == 1847
    assert snapshot["canonical_tool_node_count"] <= snapshot["catalog_tool_count"]
    assert snapshot["projection_drift_count"] == 0
    assert snapshot["junk_task_count"] == 0
    assert snapshot["unsupported_capability_edge_count"] == 0
    assert snapshot["qualified_tool_governed_path_rate"] == 1.0
    assert catalog_manifest["canonical_snapshot_id"] == snapshot["snapshot_id"]
    assert decision_manifest["canonical_snapshot_id"] == snapshot["snapshot_id"]
    assert quality["source_bound_semantic_coverage_rate"] < quality["catalog_connectivity_rate"]
