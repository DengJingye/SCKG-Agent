from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import PROJECT_ROOT
from engine.decision_graph_builder import DecisionGraphBuilder
from engine.decision_graph_query import DecisionGraphQuery


def main() -> None:
    output_dir = PROJECT_ROOT / "data" / "decision_graph_v3"
    _, edges, quality = DecisionGraphBuilder(
        data_dir=PROJECT_ROOT / "data", output_dir=output_dir
    ).build(write=True)
    query = DecisionGraphQuery(output_dir)
    candidates = query.find_tools("doublet detection")
    scrublet = query.tool_dossier("Scrublet")
    source_only = query.tool_dossier("CellRank")
    checks = {
        "integrity_passed": quality.integrity_passed,
        "catalog_tools": quality.catalog_tool_count,
        "scoped_tools": quality.scoped_tool_count,
        "source_rich_tools": quality.source_rich_tool_count,
        "decision_ready_tools": quality.decision_ready_tool_count,
        "actions": query.list_actions(),
        "action_implementation_count": quality.action_implementation_count,
        "action_bundle_count": quality.action_bundle_count,
        "hypothesis_edges": quality.hypothesis_edge_count,
        "all_edges_have_provenance": all(edge.governance.provenance_refs for edge in edges),
        "doublet_candidates": [item.tool_name for item in candidates],
        "scrublet_readiness": scrublet.readiness,
        "scrublet_inputs": [item["label"] for item in scrublet.inputs],
        "scrublet_outputs": [item["label"] for item in scrublet.outputs],
        "cellrank_readiness": source_only.readiness,
        "cellrank_blockers": source_only.blockers,
    }
    assert quality.integrity_passed
    assert quality.hypothesis_edge_count == 0
    assert quality.decision_ready_tool_count == 2
    assert quality.action_count == 2
    assert quality.action_implementation_count == 2
    assert quality.action_bundle_count == 2
    assert {item.tool_name for item in candidates} == {"Scrublet", "scDblFinder"}
    assert scrublet.readiness == "decision_ready"
    assert source_only.readiness == "source_material"
    print(json.dumps(checks, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
