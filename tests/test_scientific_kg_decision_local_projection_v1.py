from __future__ import annotations

from engine.capability_planner import CapabilityPlanCompiler
from eval.scientific_action_space_demo_v1 import demo_scenarios


def _compile(scenario_id: str, target: str):
    ledger = next(
        ledger
        for current_id, _, ledger in demo_scenarios()
        if current_id == scenario_id
    )
    _, result = CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=ledger,
        target_representations=[target],
        requirement_id=f"decision-local-projection:{scenario_id}",
    )
    return result


def _claims(result) -> list[str]:
    decision = result.scientific_applicability_results[0]
    return [item.claim_revision_id for item in decision.evidence_references]


def test_leiden_reuse_projects_only_graph_input_evidence() -> None:
    result = _compile("valid-neighbor-graph-to-leiden", "cluster_labels")

    assert _claims(result) == ["claim-revision:uat:leiden-input:v1"]
    assert result.reused_representation_ids == ["neighbor_graph"]


def test_invalid_graph_projects_requirement_but_not_runtime_state_evidence() -> None:
    result = _compile("stale-or-misaligned-graph", "cluster_labels")

    assert _claims(result) == ["claim-revision:uat:leiden-input:v1"]
    assert result.blocked is True
    decision = result.scientific_applicability_results[0]
    assert "representation_stale" in decision.incompatibility_reasons
    assert (
        "scientific_kg:scanpy_core.leiden:representation_stale"
        in result.blocking_reasons
    )


def test_cross_ecosystem_feed_projects_producer_output_and_consumer_input() -> None:
    result = _compile("harmony-embedding-to-neighbors", "neighbor_graph")

    assert _claims(result) == [
        "claim-revision:uat:harmony-output:v1",
        "claim-revision:uat:neighbors-input:v1",
    ]
    assert result.reused_representation_ids == ["integrated_representation"]


def test_scrublet_block_projects_only_raw_input_requirement() -> None:
    result = _compile(
        "scrublet-rejects-transformed-expression",
        "doublet_scores_and_calls",
    )

    assert _claims(result) == ["claim-revision:uat:scrublet-input:v1"]
    assert result.blocked is True
    assert all(
        "normalized-record-state" not in item.claim_revision_id
        for decision in result.scientific_applicability_results
        for item in decision.evidence_references
    )
