from pathlib import Path

from eval.kg_v2_evaluation import evaluate_kg_v2


def test_repository_kg_v2_fixed_evaluation_passes():
    root = Path(__file__).resolve().parents[1]
    cases, summary = evaluate_kg_v2(data_dir=root / "data")

    assert len(cases) == 9
    assert summary["status"] == "passed"
    assert summary["verified_doublet_candidate_precision"] == 1.0
    assert summary["verified_doublet_candidate_recall"] == 1.0
    assert summary["frozen_recommendation_leakage_count"] == 0
    assert summary["hypothesis_recommendation_leakage_count"] == 0
    assert summary["execution_verified_tool_count"] == 4
    assert summary["connected_component_count"] <= 2
    assert summary["largest_component_ratio"] > 0.99
    assert summary["tool_semantic_coverage_rate"] > 0.9
    assert summary["graph_retrieval"]["case_count"] == 96
    assert summary["graph_retrieval"]["macro_recall_at_k"] >= 0.90
    assert summary["graph_retrieval"]["precision_at_k"] >= 0.70
    assert summary["graph_retrieval"]["path_provenance_coverage"] == 1.0
    assert summary["graph_retrieval"]["execution_admission_violation_count"] == 0
