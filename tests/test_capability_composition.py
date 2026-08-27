from __future__ import annotations

import pytest

from core.capability_composition_models import CapabilityCompositionRequest
from core.representation_models import RepresentationLedger, RepresentationRecord
from engine.capability_composer import CapabilityWorkflowComposer


CELL_HASH = "c" * 64
GENE_HASH = "g" * 64
SOURCE_HASH = "s" * 64
SELECTION_HASH = "d" * 64


def _record(representation_id: str) -> RepresentationRecord:
    value_states = {
        "filtered_counts": "nonnegative_integer",
        "log1p_normalized": "nonnegative_continuous",
        "hvg_selection": "boolean_mask",
        "pca": "real_continuous",
        "neighbor_graph": "graph",
    }
    provenance = {
        "filtered_counts": ["filter_thresholds_reviewed"],
        "log1p_normalized": ["log1p"],
        "hvg_selection": ["hvg_flavor_bound"],
        "pca": ["pca_seed_bound"],
        "neighbor_graph": ["neighbor_representation_bound"],
    }
    return RepresentationRecord(
        representation_record_id=f"rep:{representation_id}",
        representation_id=representation_id,
        schema_version="1.0",
        value_state=value_states[representation_id],
        slot=f"slot/{representation_id}",
        provenance=provenance[representation_id],
        cell_index_hash=CELL_HASH,
        gene_index_hash=(
            GENE_HASH
            if representation_id
            not in {"pca", "neighbor_graph"}
            else None
        ),
        metadata={"batch_key": "batch"} if representation_id == "pca" else {},
        validated=True,
    )


def _ledger(
    representations: tuple[str, ...] = ("filtered_counts",),
    *,
    batch_count: int = 3,
) -> RepresentationLedger:
    return RepresentationLedger(
        ledger_id="ledger-composition",
        profile_id="profile-composition",
        source_artifact_id="fixture",
        source_hash=SOURCE_HASH,
        cell_index_hash=CELL_HASH,
        gene_index_hash=GENE_HASH,
        records=[_record(item) for item in representations],
        metadata={"batch_key": "batch", "batch_count": batch_count},
    )


def _compose(
    *,
    ledger: RepresentationLedger,
    doublet: bool = False,
    exclude: bool = False,
    integration: bool = False,
    selection_hash: str | None = None,
):
    return CapabilityWorkflowComposer().compose(
        request=CapabilityCompositionRequest(
            pack_id="scanpy_core",
            pack_version="1.0.0",
            requirement_id="composition-test",
            target_representations=["umap"],
            enable_doublet_detection=doublet,
            exclude_predicted_doublets=exclude,
            doublet_selection_hash=selection_hash,
            enable_batch_integration=integration,
        ),
        ledger=ledger,
    )


@pytest.mark.parametrize(
    ("doublet", "integration", "required_methods", "forbidden_methods"),
    [
        (False, False, {"scanpy_core.neighbors"}, {"scanpy_core.doublet_detection_action", "scanpy_core.batch_integration_action"}),
        (True, False, {"scanpy_core.doublet_detection_action", "scanpy_core.neighbors"}, {"scanpy_core.confirm_doublet_exclusion", "scanpy_core.batch_integration_action"}),
        (False, True, {"scanpy_core.batch_integration_action", "scanpy_core.neighbors_integrated"}, {"scanpy_core.doublet_detection_action"}),
    ],
)
def test_optional_action_bundle_combinations(
    doublet, integration, required_methods, forbidden_methods
):
    representations = ("filtered_counts", "pca") if integration else ("filtered_counts",)
    plan, result, composition = _compose(
        ledger=_ledger(representations),
        doublet=doublet,
        integration=integration,
    )

    assert result.blocked is False
    assert required_methods <= set(result.planned_method_ids)
    assert not (forbidden_methods & set(result.planned_method_ids))
    assert plan.execution_eligible is False
    assert composition.cell_set_changed is False


def test_doublet_exclusion_and_integration_invalidate_downstream_lineage():
    ledger = _ledger(
        (
            "filtered_counts",
            "log1p_normalized",
            "hvg_selection",
            "pca",
            "neighbor_graph",
        )
    )

    plan, result, composition = _compose(
        ledger=ledger,
        doublet=True,
        exclude=True,
        selection_hash=SELECTION_HASH,
        integration=True,
    )

    assert result.blocked is False
    assert {
        "scanpy_core.doublet_detection_action",
        "scanpy_core.confirm_doublet_exclusion",
        "scanpy_core.normalize_after_doublet_exclusion",
        "scanpy_core.batch_integration_action",
        "scanpy_core.neighbors_integrated",
    } <= set(result.planned_method_ids)
    assert composition.selected_action_bundle_refs == [
        "action:batch-integration",
        "action:doublet-detection",
    ]
    assert composition.cell_set_changed is True
    assert composition.resulting_cell_index_hash != CELL_HASH
    assert composition.invalidated_approval is True
    assert composition.confirmation_required is True
    assert {"log1p_normalized", "hvg_selection", "pca", "neighbor_graph"} <= set(
        composition.stale_representation_ids
    )
    assert plan.execution_eligible is False


def test_doublet_exclusion_requires_bound_selection_hash():
    plan, result, composition = _compose(
        ledger=_ledger(),
        doublet=True,
        exclude=True,
    )

    assert result.blocked is True
    assert "doublet_exclusion_requires_confirmed_selection_hash" in result.blocking_reasons
    assert composition.cell_set_changed is False
    assert plan.plan_status == "blocked"


def test_batch_integration_requires_two_reviewed_batches():
    ledger = _ledger(("filtered_counts", "pca"), batch_count=1)

    plan, result, composition = _compose(ledger=ledger, integration=True)

    assert result.blocked is True
    assert "batch_integration_requires_at_least_two_batches" in result.blocking_reasons
    assert "action:batch-integration" in composition.selected_action_bundle_refs
    assert plan.execution_eligible is False
