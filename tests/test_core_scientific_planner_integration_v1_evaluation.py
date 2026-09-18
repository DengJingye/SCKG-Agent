from __future__ import annotations

from eval.core_scientific_planner_integration_v1 import run


def test_core_planner_integration_development_campaign_is_bounded_and_correct() -> None:
    report = run()

    assert report["status"] == "PASS_WITH_REMAINING_GAPS"
    assert report["case_count"] == 8
    assert report["metrics"]["requirement_state_correctness"] == [8, 8]
    assert report["metrics"]["allow_block_clarify_correctness"] == [8, 8]
    assert report["metrics"]["explanation_evidence_fidelity"] == [8, 8]
    assert report["metrics"]["unnecessary_recomputation"] == [0, 8]
    assert report["metrics"]["incorrect_reuse"] == [0, 8]
    assert report["metrics"]["unsafe_allow"] == [0, 8]
    assert report["metrics"]["false_block"] == [0, 8]
    assert report["metrics"]["behavior_changes_vs_noop"] == [0, 8]
    assert report["boundaries"]["can_feed_relations_actionable"] is False
    assert report["boundaries"]["candidate_knowledge_status_preserved"] is True


def test_unavailable_ecosystems_remain_explicitly_not_ready() -> None:
    report = run()
    gaps = {row["path"]: row for row in report["remaining_target_path_gaps"]}

    assert set(gaps) == {"SoupX", "CellTypist", "SingleR", "scVelo", "CellRank"}
    assert all(row["status"] == "NOT_READY" for row in gaps.values())
    assert report["readiness"]["counts"]["planning_ready"] == 3
