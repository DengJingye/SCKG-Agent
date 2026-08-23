from __future__ import annotations

import hashlib
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from engine.annotation_data_profiler import AnnotationDataProfiler
from execution.annotation_probe_builder import AnnotationProbeBuilder
from tests.annotation_helpers import GENES, build_reference


def test_celltypist_profile_accepts_log1p_10000_and_binds_reference(tmp_path):
    reference = build_reference(tmp_path / "reference")
    probe = AnnotationProbeBuilder().build(
        output_dir=tmp_path / "probe",
        split_role="development",
        random_seed=17,
        reference=reference,
    )

    profile = AnnotationDataProfiler().profile(
        probe.probe_artifact_path,
        tool_name="CellTypist",
        reference=reference,
        explicit_species="human",
    )

    assert profile.expression_state == "log1p_normalized"
    assert profile.normalization_target == "ready_log1p_10000"
    assert profile.gene_identifier_type == "gene_symbol"
    assert profile.gene_overlap_rate == 1.0
    assert profile.blocking_errors == []


def test_annotation_profile_distinguishes_raw_scaled_duplicate_and_species(tmp_path):
    reference = build_reference(tmp_path / "reference")
    obs = pd.DataFrame(index=[f"cell-{index}" for index in range(12)])
    raw = ad.AnnData(
        X=sparse.csr_matrix(np.arange(12 * len(GENES)).reshape(12, -1) % 4),
        obs=obs,
        var=pd.DataFrame(index=GENES),
    )
    raw_path = tmp_path / "raw.h5ad"
    raw.write_h5ad(raw_path)
    raw_profile = AnnotationDataProfiler().profile(
        raw_path,
        tool_name="CellTypist",
        reference=reference,
        explicit_species="human",
    )
    assert raw_profile.normalization_target == "normalize_log1p_10000"
    assert "celltypist_requires_deterministic_log1p_10000_transform" in raw_profile.warnings

    scaled = ad.AnnData(
        X=np.linspace(-2.0, 2.0, 12 * len(GENES)).reshape(12, -1),
        obs=obs.copy(),
        var=pd.DataFrame(index=GENES),
    )
    scaled_path = tmp_path / "scaled.h5ad"
    scaled.write_h5ad(scaled_path)
    scaled_profile = AnnotationDataProfiler().profile(
        scaled_path,
        tool_name="CellTypist",
        reference=reference,
        explicit_species="human",
    )
    assert scaled_profile.normalization_target == "blocked"
    assert "annotation_expression_state_invalid" in scaled_profile.blocking_errors

    duplicated = raw.copy()
    duplicated.var_names = [*GENES[:-1], GENES[-2]]
    duplicate_path = tmp_path / "duplicate.h5ad"
    duplicated.write_h5ad(duplicate_path)
    duplicate_profile = AnnotationDataProfiler().profile(
        duplicate_path,
        tool_name="SingleR",
        reference=reference.model_copy(
            update={
                "tool_name": "SingleR",
                "reference_type": "singler_reference",
                "reference_id": "singler-immune-reference-v1",
            }
        ),
        explicit_species="mouse",
    )
    assert "duplicate_gene_identifiers" in duplicate_profile.blocking_errors
    assert "reference_species_mismatch" in duplicate_profile.blocking_errors


def test_annotation_profile_blocks_missing_or_tampered_reference(tmp_path):
    reference = build_reference(tmp_path / "reference")
    probe = AnnotationProbeBuilder().build(
        output_dir=tmp_path / "probe",
        split_role="development",
        random_seed=21,
        reference=reference,
    )
    model_path = Path(reference.local_path)
    model_path.write_text("tampered\n", encoding="utf-8")
    assert hashlib.sha256(model_path.read_bytes()).hexdigest() != reference.sha256

    profile = AnnotationDataProfiler().profile(
        probe.probe_artifact_path,
        tool_name="CellTypist",
        reference=reference,
        explicit_species="human",
    )
    assert "reference_digest_mismatch" in profile.blocking_errors

    missing = AnnotationDataProfiler().profile(
        probe.probe_artifact_path,
        tool_name="CellTypist",
        reference=None,
        explicit_species="human",
    )
    assert "annotation_reference_missing" in missing.blocking_errors
