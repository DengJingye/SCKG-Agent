from __future__ import annotations

from engine.capability_planner import CapabilityPlanCompiler
from eval.scientific_action_space_demo_v1 import demo_scenarios


def _scenario_ledgers():
    return {scenario_id: ledger for scenario_id, _, ledger in demo_scenarios()}


def _compile(scenario_id: str, target: str):
    ledger = _scenario_ledgers()[scenario_id]
    return CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=ledger,
        target_representations=[target],
        requirement_id=f"kg-planner-integration:{scenario_id}",
    )


def _decision(result, action_id: str):
    return next(
        item
        for item in result.scientific_applicability_results
        if item.action_id == action_id
    )


def test_valid_neighbor_graph_is_reused_by_real_planner_for_leiden() -> None:
    plan, result = _compile("valid-neighbor-graph-to-leiden", "cluster_labels")

    decision = _decision(result, "scanpy_core.leiden")
    assert decision.applicable is True
    assert decision.blocked is False
    assert decision.reusable_representation_ids == ["neighbor_graph"]
    assert decision.evidence_references
    assert result.blocked is False
    assert result.planned_method_ids == ["scanpy_core.leiden"]
    assert result.reused_representation_ids == ["neighbor_graph"]
    assert not any(
        "pca" in step.operation or "neighbors" in step.operation
        for step in plan.steps
    )


def test_stale_or_misaligned_graph_reuse_is_rejected_with_kg_reason() -> None:
    _, result = _compile("stale-or-misaligned-graph", "cluster_labels")

    decision = _decision(result, "scanpy_core.leiden")
    assert decision.applicable is False
    assert decision.blocked is True
    assert decision.reusable_representation_ids == []
    assert "representation_stale" in decision.incompatibility_reasons
    assert "observation_identity_mismatch" in decision.incompatibility_reasons
    assert result.blocked is True
    assert "neighbor_graph" not in result.reused_representation_ids
    assert any(
        "scientific_kg:scanpy_core.leiden:representation_stale" == reason
        for reason in result.blocking_reasons
    )
    assert any(
        "scientific_kg:scanpy_core.leiden:observation_identity_mismatch" == reason
        for reason in result.blocking_reasons
    )


def test_harmony_embedding_enables_integrated_neighbors_without_pca() -> None:
    plan, result = _compile("harmony-embedding-to-neighbors", "neighbor_graph")

    decision = _decision(result, "scanpy_core.neighbors_integrated")
    assert decision.applicable is True
    assert decision.reusable_representation_ids == ["integrated_representation"]
    assert any(
        item.claim_revision_id == "claim-revision:uat:harmony-output:v1"
        for item in decision.evidence_references
    )
    assert result.blocked is False
    assert result.planned_method_ids == ["scanpy_core.neighbors_integrated"]
    assert result.reused_representation_ids == ["integrated_representation"]
    assert all("pca" not in step.operation for step in plan.steps)


def test_scrublet_transformed_only_input_reports_preserved_raw_umi_requirement() -> None:
    _, result = _compile(
        "scrublet-rejects-transformed-expression",
        "doublet_scores_and_calls",
    )

    decision = _decision(result, "scanpy_core.doublet_detection_action")
    assert decision.applicable is False
    assert decision.blocked is True
    assert decision.missing_requirements[0].required_representation_type_ids == [
        "representation-type:raw_umi_counts"
    ]
    assert "forbidden_transformation:normalized" in decision.incompatibility_reasons
    assert result.blocked is True
    assert any(
        "scientific_kg:scanpy_core.doublet_detection_action:missing_compatible_representation"
        == reason
        for reason in result.blocking_reasons
    )


def test_candidate_decisions_are_source_bound_and_candidate_scoped() -> None:
    for scenario_id, target in (
        ("valid-neighbor-graph-to-leiden", "cluster_labels"),
        ("stale-or-misaligned-graph", "cluster_labels"),
        ("harmony-embedding-to-neighbors", "neighbor_graph"),
        ("scrublet-rejects-transformed-expression", "doublet_scores_and_calls"),
    ):
        _, result = _compile(scenario_id, target)
        assert result.scientific_applicability_results
        for decision in result.scientific_applicability_results:
            assert decision.knowledge_status == "candidate"
            assert decision.evidence_references
            assert all(
                len(item.content_hash) == 64
                for item in decision.evidence_references
            )
