from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import PROJECT_ROOT
from engine.evidence_graph_builder import EvidenceGraphBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the evidence-governed scKG v2 JSONL snapshot.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "knowledge_graph_v2",
    )
    args = parser.parse_args()
    builder = EvidenceGraphBuilder(
        data_dir=PROJECT_ROOT / "data",
        output_dir=args.output_dir,
    )
    _, _, report = builder.build(write=True)
    print(
        json.dumps(
            {
                "status": "passed" if report.integrity_passed else "failed",
                "snapshot_version": report.snapshot_version,
                "node_count": report.node_count,
                "edge_count": report.edge_count,
                "node_counts_by_layer": report.node_counts_by_layer,
                "dangling_edge_count": report.dangling_edge_count,
                "frozen_recommendation_leakage_count": report.frozen_recommendation_leakage_count,
                "hypothesis_recommendation_leakage_count": (
                    report.hypothesis_recommendation_leakage_count
                ),
                "connected_component_count": report.connected_component_count,
                "largest_component_ratio": report.largest_component_ratio,
                "isolated_tool_count": report.isolated_tool_count,
                "tool_semantic_coverage_rate": report.tool_semantic_coverage_rate,
                "formal_publication_allowed_count": report.formal_publication_allowed_count,
                "formal_benchmark_allowed_count": report.formal_benchmark_allowed_count,
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not report.integrity_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
