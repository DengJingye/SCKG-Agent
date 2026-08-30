from __future__ import annotations

import json

import pytest

from core.capability_pack_registry import CapabilityPackRegistry
from core.execution_models import DataProfile
from core.representation_models import RepresentationLedger, RepresentationRecord
from engine.capability_planner import CapabilityPlanCompiler
from execution.capability_notebook import GenericNotebookCompiler, NotebookRendererRegistry
from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer


CELL_HASH = "c" * 64
GENE_HASH = "g" * 64
SOURCE_HASH = "s" * 64


def _profile(*, n_cells: int = 40, n_genes: int = 30) -> DataProfile:
    return DataProfile(
        profile_id=f"profile-{n_cells}x{n_genes}",
        file_path_redacted="registered-artifact",
        n_cells=n_cells,
        n_genes=n_genes,
        count_source_selection={"method": "deterministic_rule"},
    )


def _record(
    representation_id: str,
    value_state: str,
    *,
    gene_hash: bool = True,
) -> RepresentationRecord:
    return RepresentationRecord(
        representation_record_id=f"rep:{representation_id}",
        representation_id=representation_id,
        schema_version="1.0",
        value_state=value_state,
        slot=f"registered/{representation_id}",
        provenance=(
            ["count_source_validated"]
            if representation_id == "raw_counts"
            else [f"validated_{representation_id}"]
        ),
        cell_index_hash=CELL_HASH,
        gene_index_hash=GENE_HASH if gene_hash else None,
        validated=True,
    )


def _ledger(*records: RepresentationRecord) -> RepresentationLedger:
    return RepresentationLedger(
        ledger_id="adaptive-ledger",
        profile_id="adaptive-profile",
        source_artifact_id="registered-input",
        source_hash=SOURCE_HASH,
        cell_index_hash=CELL_HASH,
        gene_index_hash=GENE_HASH,
        records=list(records),
    )


def _raw_plan(*, options: dict[str, object] | None = None):
    return CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=_ledger(_record("raw_counts", "nonnegative_integer")),
        target_representations=["marker_result", "umap"],
        requirement_id="adaptive-scanpy-test",
        options=options,
        data_profile=_profile(),
    )


def test_raw_plan_resolves_reviewed_parameters_and_provenance():
    plan, result = _raw_plan(
        options={
            "preferred_method_ids": [
                "scanpy_core.scale_hvg",
                "scanpy_core.pca_scaled",
            ]
        }
    )

    assert result.blocked is False
    assert "scanpy_core.scale_hvg" in result.planned_method_ids
    assert "scanpy_core.pca_scaled" in result.planned_method_ids
    nodes = {node.operation: node for node in plan.steps}
    assert nodes["scanpy_core.highly_variable_genes"].parameters == {
        "n_top_genes": 30
    }
    assert nodes["scanpy_core.pca_scaled"].parameters == {"n_comps": 29}
    assert nodes["scanpy_core.neighbors"].parameters == {"n_neighbors": 15}
    assert nodes["scanpy_core.leiden"].parameters == {
        "resolution": 1.0,
        "random_state": 0,
    }
    assert nodes["scanpy_core.umap"].parameters == {"random_state": 0}
    assert all(
        node.tool_contract_id == "Scanpy:1.11.2"
        for node in plan.steps
        if node.tool_name == "Scanpy"
    )
    pca_provenance = nodes["scanpy_core.pca_scaled"].parameter_provenance[0]
    assert pca_provenance.origin_type == "source_bound_prior"
    assert pca_provenance.policy_rule_id == "cap_by_min_cells_features_minus_one"
    assert pca_provenance.tool_version == "1.11.2"
    filter_origins = {
        item.parameter_name: item.origin_type
        for item in nodes["scanpy_core.filter_counts"].parameter_provenance
    }
    assert filter_origins == {
        "min_genes": "contract_default",
        "min_cells": "contract_default",
    }


def test_parameter_overrides_are_bounded_and_keep_user_provenance():
    plan, _ = _raw_plan(
        options={
            "scanpy_core.neighbors": {"n_neighbors": 8},
            "scanpy_core.leiden": {"resolution": 0.6},
        }
    )
    nodes = {node.operation: node for node in plan.steps}
    assert nodes["scanpy_core.neighbors"].parameters["n_neighbors"] == 8
    assert nodes["scanpy_core.neighbors"].parameter_provenance[0].origin_type == (
        "user_override"
    )
    leiden = {
        item.parameter_name: item
        for item in nodes["scanpy_core.leiden"].parameter_provenance
    }
    assert leiden["resolution"].origin_type == "user_override"
    assert leiden["random_state"].origin_type == "source_bound_prior"

    with pytest.raises(ValueError, match="dataset-shape bound"):
        _raw_plan(
            options={"scanpy_core.neighbors": {"n_neighbors": 40}}
        )
    with pytest.raises(ValueError, match="unknown parameters"):
        _raw_plan(
            options={"scanpy_core.neighbors": {"unreviewed_parameter": 1}}
        )
    with pytest.raises(ValueError, match="unknown methods"):
        _raw_plan(options={"scanpy_core.unregistered": {"value": 1}})


def test_notebook_embeds_resolved_parameters_and_human_readable_provenance(
    tmp_path,
):
    registry = CapabilityPackRegistry()
    manifest = registry.load("scanpy_core", "1.0.0")
    plan, _ = _raw_plan(
        options={
            "preferred_method_ids": [
                "scanpy_core.scale_hvg",
                "scanpy_core.pca_scaled",
            ],
            "scanpy_core.neighbors": {"n_neighbors": 8},
        }
    )
    output_path = tmp_path / "adaptive.ipynb"
    artifact = GenericNotebookCompiler(
        NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])
    ).compile(
        plan=plan,
        step_contracts=registry.load_step_contracts(manifest),
        output_path=output_path,
        title="Adaptive Scanpy Core workflow",
    )

    notebook = json.loads(output_path.read_text(encoding="utf-8"))
    by_id = {cell["id"]: cell for cell in notebook["cells"]}
    assert (
        'STEP_PARAMETERS = {"n_comps": 29}'
        in by_id["scanpy_core-pca_scaled-code"]["source"]
    )
    assert (
        'STEP_PARAMETERS = {"n_neighbors": 8}'
        in by_id["scanpy_core-neighbors-code"]["source"]
    )
    assert "Resolved parameters and provenance" in by_id[
        "scanpy_core-neighbors-description"
    ]["source"]
    assert "user_override" in by_id["scanpy_core-neighbors-description"]["source"]
    assert artifact["execution_request_count"] == 0
    assert notebook["metadata"]["sckg"]["editable_not_trusted_execution"] is True
    assert all(
        cell.get("execution_count") is None and cell.get("outputs") == []
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )


def test_processed_ledger_reuses_valid_representations_without_preprocessing():
    processed = _ledger(
        _record("pca", "real_continuous", gene_hash=False),
        _record("neighbor_graph", "graph", gene_hash=False),
        _record("umap", "real_continuous", gene_hash=False),
        _record("cluster_labels", "categorical", gene_hash=False),
        _record("marker_result", "table"),
    )
    plan, result = CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=processed,
        target_representations=["annotation_candidates", "umap"],
        requirement_id="processed-reuse-test",
        data_profile=_profile(n_cells=2638, n_genes=1838),
    )

    assert result.blocked is False
    assert result.planned_method_ids == [
        "scanpy_core.marker_evidence_annotation"
    ]
    assert {"marker_result", "cluster_labels", "umap"} <= set(
        result.reused_representation_ids
    )
    assert [step.operation for step in plan.steps] == [
        "scanpy_core.marker_evidence_annotation"
    ]
    assert plan.steps[0].parameters == {}
