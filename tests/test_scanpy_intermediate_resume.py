from __future__ import annotations

from pathlib import Path

from core.representation_models import RepresentationStatus
from engine.capability_planner import CapabilityPlanCompiler
from engine.representation_profiler import AnnDataRepresentationProfiler
from execution.scanpy_synthetic_fixture import (
    derive_scanpy_core_intermediate_fixtures,
    generate_scanpy_core_synthetic_fixture,
)


def _fixtures(tmp_path: Path):
    source, _, source_manifest = generate_scanpy_core_synthetic_fixture(
        tmp_path / "source"
    )
    _, manifest = derive_scanpy_core_intermediate_fixtures(
        source, source_manifest, tmp_path / "intermediate"
    )
    return tmp_path / "intermediate", manifest


def _compile(path: Path, target: str = "annotation_candidates"):
    ledger = AnnDataRepresentationProfiler().profile(
        path, artifact_id=f"artifact-{path.stem}", batch_key="batch"
    )
    plan, result = CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=ledger,
        target_representations=[target],
        requirement_id=f"resume-{path.stem}",
    )
    return ledger, plan, result


def test_intermediate_states_profile_and_resume_without_repeating_valid_steps(tmp_path):
    root, manifest = _fixtures(tmp_path)
    by_state = {item.state_id: item for item in manifest.states}

    log_ledger, _, log_result = _compile(root / by_state["log_normalized_ready"].h5ad_filename)
    assert set(by_state["log_normalized_ready"].expected_representations) <= log_ledger.available_ids()
    assert log_result.blocked is False
    assert "log1p_normalized" in log_result.reused_representation_ids
    assert not {
        "scanpy_core.calculate_qc",
        "scanpy_core.filter_counts",
        "scanpy_core.normalize_total",
        "scanpy_core.log1p",
    }.intersection(log_result.planned_method_ids)

    pca_ledger, _, pca_result = _compile(root / by_state["pca_ready"].h5ad_filename)
    assert set(by_state["pca_ready"].expected_representations) <= pca_ledger.available_ids()
    assert pca_result.blocked is False
    assert "pca" in pca_result.reused_representation_ids
    assert not {
        "scanpy_core.pca_log_hvg",
        "scanpy_core.pca_scaled",
    }.intersection(pca_result.planned_method_ids)
    assert "scanpy_core.neighbors" in pca_result.planned_method_ids

    cluster_ledger, _, cluster_result = _compile(root / by_state["cluster_ready"].h5ad_filename)
    assert set(by_state["cluster_ready"].expected_representations) <= cluster_ledger.available_ids()
    assert cluster_result.blocked is False
    assert "cluster_labels" in cluster_result.reused_representation_ids
    assert not {
        "scanpy_core.neighbors",
        "scanpy_core.umap",
        "scanpy_core.leiden",
    }.intersection(cluster_result.planned_method_ids)
    assert cluster_result.planned_method_ids == [
        "scanpy_core.rank_markers",
        "scanpy_core.marker_evidence_annotation",
    ]


def test_stale_pca_rebuilds_and_hash_mismatch_blocks(tmp_path):
    root, manifest = _fixtures(tmp_path)
    pca_path = root / next(
        item.h5ad_filename for item in manifest.states if item.state_id == "pca_ready"
    )
    ledger = AnnDataRepresentationProfiler().profile(
        pca_path, artifact_id="artifact-pca", batch_key="batch"
    )
    stale_records = [
        item.model_copy(
            update={
                "status": RepresentationStatus.STALE,
                "stale_reasons": ["upstream_parameter_hash_changed"],
            }
        )
        if item.representation_id == "pca"
        else item
        for item in ledger.records
    ]
    stale_ledger = ledger.model_copy(update={"records": stale_records})
    _, stale_result = CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=stale_ledger,
        target_representations=["neighbor_graph"],
        requirement_id="stale-pca-rebuild",
    )
    assert stale_result.blocked is False
    assert "pca" not in stale_result.reused_representation_ids
    assert any(
        item in stale_result.planned_method_ids
        for item in ("scanpy_core.pca_log_hvg", "scanpy_core.pca_scaled")
    )

    wrong_hash = "f" * 64
    mismatch_records = [
        item.model_copy(update={"cell_index_hash": wrong_hash})
        if item.representation_id == "pca"
        else item
        for item in ledger.records
    ]
    mismatch_ledger = ledger.model_copy(update={"records": mismatch_records})
    mismatch_plan, mismatch_result = CapabilityPlanCompiler().compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=mismatch_ledger,
        target_representations=["neighbor_graph"],
        requirement_id="pca-hash-mismatch",
    )
    assert mismatch_result.blocked is True
    assert any("cell_index_hash_mismatch" in item for item in mismatch_result.blocking_reasons)
    assert mismatch_plan.plan_status == "blocked"
