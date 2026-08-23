from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import PROJECT_ROOT
from engine.evidence_graph_builder import EvidenceGraphBuilder
from engine.evidence_graph_query import EvidenceGraphQuery


def main() -> None:
    graph_dir = PROJECT_ROOT / "data" / "knowledge_graph_v2"
    _, _, quality = EvidenceGraphBuilder(
        data_dir=PROJECT_ROOT / "data",
        output_dir=graph_dir,
    ).build(write=True)
    query = EvidenceGraphQuery(graph_dir)
    scrublet = query.explain_tool("Scrublet")
    scdblfinder = query.explain_tool("scDblFinder")
    manifest = json.loads((graph_dir / "manifest.json").read_text(encoding="utf-8"))
    checks = {
        "snapshot_available": query.available,
        "integrity_passed": quality.integrity_passed,
        "dangling_edges_zero": quality.dangling_edge_count == 0,
        "frozen_leakage_zero": quality.frozen_recommendation_leakage_count == 0,
        "hypothesis_leakage_zero": quality.hypothesis_recommendation_leakage_count == 0,
        "tool_isolation_zero": quality.isolated_tool_count == 0,
        "largest_component_over_99pct": quality.largest_component_ratio > 0.99,
        "semantic_coverage_over_90pct": quality.tool_semantic_coverage_rate > 0.9,
        "scrublet_contract_visible": bool(scrublet.contracts),
        "scdblfinder_contract_visible": bool(scdblfinder.contracts),
        "execution_task_visible": "doublet detection" in scrublet.trusted_tasks,
        "formal_evidence_remains_frozen": (
            quality.formal_publication_allowed_count == 0
            and quality.formal_benchmark_allowed_count == 0
        ),
        "catalog_coverage_present": quality.catalog_tool_count >= 1800,
        "two_execution_verified_tools": quality.execution_verified_tool_count == 2,
    }
    summary = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "quality": quality.model_dump(mode="json"),
        "tool_explanations": {
            "Scrublet": {
                "trusted_tasks": scrublet.trusted_tasks,
                "contracts": len(scrublet.contracts),
                "evaluations": len(scrublet.evaluations),
                "frozen_or_quarantined": len(scrublet.frozen_or_quarantined),
            },
            "scDblFinder": {
                "trusted_tasks": scdblfinder.trusted_tasks,
                "contracts": len(scdblfinder.contracts),
                "evaluations": len(scdblfinder.evaluations),
                "frozen_or_quarantined": len(scdblfinder.frozen_or_quarantined),
            },
        },
        "neo4j_imported": manifest.get("neo4j_imported", False),
        "neo4j_import_status": manifest.get("neo4j_import_status", "unknown"),
        "jsonl_is_canonical_snapshot": True,
    }
    output = PROJECT_ROOT / "eval" / "kg_v2_smoke_summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
