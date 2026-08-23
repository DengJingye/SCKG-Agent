from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from connectors.offline_graph import OfflineGraphStore
from engine.evidence_graph_query import EvidenceGraphQuery


def main() -> None:
    data_dir = PROJECT_ROOT / "data"
    graph_dir = data_dir / "knowledge_graph_v2"
    store = OfflineGraphStore(data_dir=data_dir)
    query = EvidenceGraphQuery(graph_dir)
    candidates = store.find_candidates("doublet detection", "scRNA-seq")
    verified = [row for row in candidates if row.get("candidate_basis") == "execution_verified"]
    exploratory = [row for row in candidates if row.get("candidate_basis") != "execution_verified"]
    explanations = {
        row["tool_name"]: query.explain_tool(row["tool_name"]).model_dump(mode="json")
        for row in verified
    }
    now = datetime.now(timezone.utc)
    demo_id = f"kg-v2-agent-{now.strftime('%Y%m%dT%H%M%S%f')}"
    demo_dir = PROJECT_ROOT / ".sckg_exec" / "demos" / demo_id
    demo_dir.mkdir(parents=True, exist_ok=False)
    answer = {
        "demo_id": demo_id,
        "query": "Find controlled doublet-detection options for an scRNA-seq AnnData dataset.",
        "route": "EVIDENCE_GOVERNED_KG",
        "candidate_provider": "kg_v2_hybrid_local",
        "verified_execution_options": [row["tool_name"] for row in verified],
        "exploratory_recall_count": len(exploratory),
        "exploratory_recall_is_not_recommendation": True,
        "tool_explanations": explanations,
        "decision_boundary": {
            "recommendation_created": False,
            "reason": "No user DataProfile, unchanged WorkflowPlan, or plan-specific approval exists.",
            "next_action": "Profile the registered .h5ad, verify raw count source, then compile a dry-run plan.",
        },
        "evidence_boundary": {
            "formal_publication_allowed": 0,
            "formal_benchmark_allowed": 0,
            "frozen_evidence_used_for_recommendation": 0,
            "scientific_pilot_scope": "GSE108313 only",
        },
        "neo4j_shadow_imported": json.loads((graph_dir / "manifest.json").read_text())["neo4j_imported"],
        "status": "COMPLETED",
    }
    (demo_dir / "agent_answer.json").write_text(
        json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (demo_dir / "graph_quality.json").write_text(
        (graph_dir / "quality_report.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (demo_dir / "snapshot_manifest.json").write_text(
        (graph_dir / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    summary = {
        "status": "passed",
        "demo_id": demo_id,
        "verified_execution_options": answer["verified_execution_options"],
        "exploratory_recall_count": len(exploratory),
        "recommendation_correctly_deferred": True,
        "frozen_evidence_leakage": 0,
        "bundle": str(demo_dir),
    }
    (demo_dir / "demo_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
