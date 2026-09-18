from __future__ import annotations

from core.representation_models import RepresentationLedger, RepresentationRecord
from engine.capability_planner import CapabilityPlanCompiler
from engine.scientific_kg_applicability import ScientificKGApplicability


CELL_HASH = "c" * 64
GENE_HASH = "g" * 64
PARAMETER_HASH = "p" * 64


def _record(
    representation_id: str,
    *,
    representation_type_id: str,
    value_state: str = "state_declared",
    transformations: list[str] | None = None,
    cell_hash: str | None = CELL_HASH,
    gene_hash: str | None = GENE_HASH,
    parameter_hash: str | None = None,
    status: str = "current",
) -> RepresentationRecord:
    return RepresentationRecord(
        representation_record_id=f"rep:core-integration:{representation_id}:{status}",
        representation_id=representation_id,
        schema_version="1.0",
        value_state=value_state,
        slot=f"fixture/{representation_id}",
        provenance=["core_scientific_planner_integration_v1"],
        cell_index_hash=cell_hash,
        gene_index_hash=gene_hash,
        parameter_hash=parameter_hash,
        status=status,
        validated=True,
        stale_reasons=[] if status == "current" else ["upstream_changed"],
        metadata={
            "representation_type_id": representation_type_id,
            "lineage_id": "lineage:core-integration",
            "transformations": transformations or [],
        },
    )


def _ledger(*records: RepresentationRecord) -> RepresentationLedger:
    return RepresentationLedger(
        ledger_id="ledger:core-scientific-planner-integration-v1",
        profile_id="profile:core-scientific-planner-integration-v1",
        source_artifact_id="artifact:core-scientific-planner-integration-v1",
        source_hash="s" * 64,
        cell_index_hash=CELL_HASH,
        gene_index_hash=GENE_HASH,
        records=list(records),
    )


def _compile(ledger: RepresentationLedger, target: str, **options):
    return CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=ledger,
        target_representations=[target],
        requirement_id=f"core-scientific-planner-integration-v1:{target}",
        options=options,
    )


def _decision(result, action_id: str):
    return next(
        decision
        for decision in result.scientific_applicability_results
        if decision.action_id == action_id
    )


def test_log_profile_hvg_uses_only_the_matching_conditional_evidence() -> None:
    log_expression = _record(
        "log1p_normalized",
        representation_type_id="representation-type:log_expression",
        transformations=["normalized", "log1p"],
    )

    _, result = _compile(_ledger(log_expression), "hvg_selection")

    decision = _decision(result, "scanpy_core.highly_variable_genes")
    assert decision.applicable is True
    assert result.planned_method_ids == ["scanpy_core.highly_variable_genes"]
    assert {ref.claim_revision_id for ref in decision.evidence_references} == {
        "claim-revision:uat:hvg-dispersion-log:v1"
    }


def test_existing_log_expression_and_hvg_mask_feed_the_real_pca_path() -> None:
    log_expression = _record(
        "log1p_normalized",
        representation_type_id="representation-type:log_expression",
        transformations=["normalized", "log1p"],
    )
    hvg_mask = _record(
        "hvg_selection",
        representation_type_id="representation-type:hvg_mask",
        value_state="boolean_mask",
        transformations=["feature_selected"],
        cell_hash=None,
    )

    _, result = _compile(
        _ledger(log_expression, hvg_mask),
        "pca",
        preferred_method_ids=["scanpy_core.pca_log_hvg"],
    )

    decision = _decision(result, "scanpy_core.pca_log_hvg")
    assert decision.applicable is True
    assert result.planned_method_ids == ["scanpy_core.pca_log_hvg"]
    assert result.reused_representation_ids == ["hvg_selection", "log1p_normalized"]
    assert decision.evidence_references


def test_existing_pca_feeds_neighbors_through_the_real_planner() -> None:
    pca = _record(
        "pca",
        representation_type_id="representation-type:pca_coordinates",
        value_state="real_continuous",
        gene_hash=None,
        parameter_hash=PARAMETER_HASH,
    )

    _, result = _compile(_ledger(pca), "neighbor_graph")

    decision = _decision(result, "scanpy_core.neighbors")
    assert decision.applicable is True
    assert decision.reusable_representation_ids == ["pca"]
    assert result.planned_method_ids == ["scanpy_core.neighbors"]
    assert result.reused_representation_ids == ["pca"]
    assert decision.evidence_references


def test_stale_pca_is_not_reused_for_neighbors() -> None:
    stale_pca = _record(
        "pca",
        representation_type_id="representation-type:pca_coordinates",
        value_state="real_continuous",
        gene_hash=None,
        parameter_hash=PARAMETER_HASH,
        status="stale",
    )

    _, result = _compile(_ledger(stale_pca), "neighbor_graph")

    decision = _decision(result, "scanpy_core.neighbors")
    assert decision.blocked is True
    assert "representation_stale" in decision.incompatibility_reasons
    assert "pca" not in result.reused_representation_ids
    assert result.blocked is True


def test_neighbor_graph_feeds_umap_without_recomputing_neighbors() -> None:
    graph = _record(
        "neighbor_graph",
        representation_type_id="representation-type:neighbor_graph",
        value_state="graph",
        gene_hash=None,
        parameter_hash=PARAMETER_HASH,
    )
    graph.metadata.update(
        {
            "neighbors_key": "neighbors",
            "connectivities_key": "connectivities",
            "distances_key": "distances",
            "component_roles": ["connectivities", "distances", "parameters"],
        }
    )

    plan, result = _compile(_ledger(graph), "umap")

    decision = _decision(result, "scanpy_core.umap")
    assert decision.applicable is True
    assert result.planned_method_ids == ["scanpy_core.umap"]
    assert result.reused_representation_ids == ["neighbor_graph"]
    assert all(step.operation != "scanpy_core.neighbors" for step in plan.steps)


def test_unintegrated_ecosystem_action_remains_non_actionable() -> None:
    decision = ScientificKGApplicability().assess(
        action_id="soupx.adjustCounts",
        ledger=_ledger(),
    )

    assert decision is None

