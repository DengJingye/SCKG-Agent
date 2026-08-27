import hashlib

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from core.representation_models import RepresentationLedger, RepresentationRecord
from engine.capability_planner import CapabilityPlanCompiler
from engine.representation_profiler import (
    AnnDataRepresentationProfiler,
    mark_descendants_stale,
)
from tests.fixtures.anndata_factory import write_phase1_fixtures


CELL_HASH = "c" * 64
GENE_HASH = "g" * 64
SOURCE_HASH = "s" * 64


def _record(rep_id, *, status="current", validated=True, parents=None, metadata=None):
    states = {
        "registered_anndata": "table",
        "raw_counts": "nonnegative_integer",
        "qc_metrics": "table",
        "filtered_counts": "nonnegative_integer",
        "library_size_normalized": "nonnegative_continuous",
        "log1p_normalized": "nonnegative_continuous",
        "hvg_selection": "boolean_mask",
        "scaled_hvg": "real_continuous",
        "pca": "real_continuous",
        "integrated_representation": "real_continuous",
        "neighbor_graph": "graph",
        "umap": "real_continuous",
        "cluster_labels": "categorical",
        "marker_result": "table",
        "annotation_candidates": "table",
    }
    provenance = {
        "registered_anndata": ["data_registry"],
        "raw_counts": ["count_source_validated"],
        "log1p_normalized": ["log1p"],
        "scaled_hvg": ["scale_hvg_only"],
        "pca": ["pca_seed_bound"],
        "integrated_representation": ["validated_integration_action"],
    }.get(rep_id, [f"{rep_id}_validated"])
    return RepresentationRecord(
        representation_record_id=f"rep:{rep_id}",
        representation_id=rep_id,
        schema_version="1.0",
        value_state=states[rep_id],
        slot=f"slot/{rep_id}",
        provenance=provenance,
        cell_index_hash=CELL_HASH if rep_id != "hvg_selection" else None,
        gene_index_hash=GENE_HASH if rep_id not in {"pca", "integrated_representation", "neighbor_graph", "umap", "cluster_labels"} else None,
        parent_record_ids=parents or [],
        status=status,
        validated=validated,
        metadata=(
            {"artifact_id": "fixture", "source_hash": SOURCE_HASH}
            if rep_id == "registered_anndata"
            else {"full_gene_matrix": True}
            if rep_id == "log1p_normalized"
            else {"batch_key": "batch"}
            if rep_id == "integrated_representation"
            else metadata or {}
        ),
        stale_reasons=[] if status == "current" else ["upstream_hash_changed"],
    )


def _ledger(rep_ids, *, stale=(), blocking=()):
    records = []
    previous = None
    for rep_id in rep_ids:
        record = _record(
            rep_id,
            status="stale" if rep_id in stale else "current",
            parents=[previous] if previous else [],
        )
        records.append(record)
        previous = record.representation_record_id
    return RepresentationLedger(
        ledger_id="ledger-fixture",
        profile_id="profile-fixture",
        source_artifact_id="fixture",
        source_hash=SOURCE_HASH,
        cell_index_hash=CELL_HASH,
        gene_index_hash=GENE_HASH,
        records=records,
        blocking_errors=list(blocking),
    )


def test_profiler_records_coexisting_anndata_states_without_mutation(tmp_path):
    source = write_phase1_fixtures(tmp_path)["counts_layer"]
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    adata = ad.read_h5ad(source)
    adata.var["highly_variable"] = [True] * min(4, adata.n_vars) + [False] * max(0, adata.n_vars - 4)
    adata.obsm["X_pca"] = np.zeros((adata.n_obs, 3), dtype=float)
    adata.obsp["connectivities"] = np.eye(adata.n_obs)
    adata.obsp["distances"] = np.eye(adata.n_obs)
    adata.obs["leiden"] = pd.Categorical([str(index % 2) for index in range(adata.n_obs)])
    enriched = tmp_path / "enriched.h5ad"
    adata.write_h5ad(enriched)
    enriched_before = hashlib.sha256(enriched.read_bytes()).hexdigest()

    ledger = AnnDataRepresentationProfiler().profile(enriched, artifact_id="fixture")

    assert {"registered_anndata", "raw_counts", "hvg_selection", "pca", "neighbor_graph", "cluster_labels"} <= ledger.available_ids()
    assert hashlib.sha256(enriched.read_bytes()).hexdigest() == enriched_before
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_processed_anndata_can_resume_without_raw_counts_but_raw_steps_stay_blocked(tmp_path):
    rng = np.random.default_rng(31)
    values = np.log1p(rng.gamma(shape=2.0, scale=1.0, size=(18, 12))).astype(np.float32)
    adata = ad.AnnData(
        X=values,
        obs=pd.DataFrame(index=[f"cell-{index}" for index in range(values.shape[0])]),
        var=pd.DataFrame(index=[f"gene-{index}" for index in range(values.shape[1])]),
    )
    adata.raw = adata.copy()
    adata.obsm["X_pca"] = rng.normal(size=(adata.n_obs, 4)).astype(np.float32)
    adata.obsm["X_umap"] = rng.normal(size=(adata.n_obs, 2)).astype(np.float32)
    adata.obsp["connectivities"] = np.eye(adata.n_obs, dtype=np.float32)
    adata.obsp["distances"] = np.eye(adata.n_obs, dtype=np.float32)
    adata.obs["louvain"] = pd.Categorical([str(index % 3) for index in range(adata.n_obs)])
    adata.uns["rank_genes_groups"] = {"params": {"groupby": "louvain"}}
    path = tmp_path / "processed.h5ad"
    adata.write_h5ad(path)

    ledger = AnnDataRepresentationProfiler().profile(path, artifact_id="processed-fixture")

    assert not ledger.blocking_errors
    assert "count_source_unresolved_counts_dependent_steps_unavailable" in ledger.warnings
    assert {
        "log1p_normalized",
        "pca",
        "neighbor_graph",
        "umap",
        "cluster_labels",
        "marker_result",
    } <= ledger.available_ids()

    _, resume = CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=ledger,
        target_representations=["annotation_candidates", "umap"],
        requirement_id="processed-resume",
    )
    _, raw_dependent = CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=ledger,
        target_representations=["qc_metrics"],
        requirement_id="processed-requires-raw",
    )

    assert resume.blocked is False
    assert resume.planned_method_ids == ["scanpy_core.marker_evidence_annotation"]
    assert raw_dependent.blocked is True
    assert "no_registered_producer:raw_counts" in raw_dependent.blocking_reasons


@pytest.mark.parametrize(
    ("case_id", "representations", "targets", "stale", "expect_blocked", "expected_method", "expected_reuse"),
    [
        ("raw", ["registered_anndata", "raw_counts"], ["marker_result"], (), False, "scanpy_core.rank_markers", "raw_counts"),
        ("log-counts", ["registered_anndata", "raw_counts", "log1p_normalized"], ["marker_result"], (), False, "scanpy_core.rank_markers", "log1p_normalized"),
        ("normalized", ["registered_anndata", "library_size_normalized"], ["marker_result"], (), False, "scanpy_core.log1p", "library_size_normalized"),
        ("log-only", ["registered_anndata", "log1p_normalized"], ["marker_result"], (), False, "scanpy_core.rank_markers", "log1p_normalized"),
        ("valid-pca", ["registered_anndata", "log1p_normalized", "pca"], ["umap"], (), False, "scanpy_core.neighbors", "pca"),
        ("pca-only", ["registered_anndata", "pca"], ["umap"], (), False, "scanpy_core.umap", "pca"),
        ("scaled-only", ["registered_anndata", "scaled_hvg"], ["umap"], (), False, "scanpy_core.pca_scaled", "scaled_hvg"),
        ("integrated", ["registered_anndata", "integrated_representation"], ["umap"], (), False, "scanpy_core.neighbors_integrated", "integrated_representation"),
        ("graph-cluster", ["registered_anndata", "log1p_normalized", "neighbor_graph", "cluster_labels"], ["marker_result", "umap"], (), False, "scanpy_core.rank_markers", "cluster_labels"),
        ("single-batch", ["registered_anndata", "raw_counts"], ["umap"], (), False, "scanpy_core.neighbors", "raw_counts"),
        ("ambiguous-normalization", ["registered_anndata"], ["marker_result"], (), True, None, "registered_anndata"),
        ("stale-pca", ["registered_anndata", "log1p_normalized", "hvg_selection", "pca"], ["umap"], ("pca",), False, "scanpy_core.pca_log_hvg", "log1p_normalized"),
        ("invalid", ["registered_anndata"], ["umap"], (), True, None, "registered_anndata"),
        ("doublet-exclusion-change", ["registered_anndata", "raw_counts", "log1p_normalized", "hvg_selection", "pca"], ["umap"], ("log1p_normalized", "hvg_selection", "pca"), False, "scanpy_core.log1p", "raw_counts"),
    ],
)
def test_scanpy_workflow_gold_states(
    case_id, representations, targets, stale, expect_blocked, expected_method, expected_reuse
):
    ledger = _ledger(
        representations,
        stale=stale,
        blocking=("invalid_matrix",) if case_id == "invalid" else (),
    )
    plan, result = CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=ledger,
        target_representations=targets,
        requirement_id=f"gold-{case_id}",
    )

    assert result.blocked is expect_blocked
    assert plan.execution_eligible is False
    assert "capability_pack_execution_not_eligible" in plan.execution_blockers
    if expected_reuse in representations and expected_reuse not in {"registered_anndata"}:
        assert expected_reuse in result.reused_representation_ids
    if expected_method:
        assert expected_method in result.planned_method_ids


def test_marker_never_uses_scaled_or_integrated_representation():
    ledger = _ledger(["registered_anndata", "scaled_hvg", "integrated_representation", "cluster_labels"])
    plan, result = CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=ledger,
        target_representations=["marker_result"],
        requirement_id="marker-illegal-input",
    )

    assert result.blocked is True
    assert "scanpy_core.rank_markers" not in result.planned_method_ids
    assert not any("scaled_hvg" in node.input_artifacts for node in plan.steps if node.operation == "scanpy_core.rank_markers")


def test_stale_propagation_marks_all_descendants():
    ledger = _ledger(["raw_counts", "filtered_counts", "log1p_normalized", "pca"])
    changed = mark_descendants_stale(
        ledger, parent_record_id="rep:filtered_counts", reason="cell_index_hash_changed"
    )
    status = {item.representation_id: item.status for item in changed.records}

    assert status["raw_counts"] == "current"
    assert status["filtered_counts"] == "stale"
    assert status["log1p_normalized"] == "stale"
    assert status["pca"] == "stale"
