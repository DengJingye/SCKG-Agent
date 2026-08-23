from __future__ import annotations

import hashlib

import anndata as ad
import numpy as np

from execution.annotation_probe_builder import AnnotationProbeBuilder, CELL_TYPES
from tests.annotation_helpers import build_reference


def test_annotation_development_and_evaluation_probes_are_isolated(tmp_path):
    reference = build_reference(tmp_path / "reference")
    builder = AnnotationProbeBuilder()
    development = builder.build(
        output_dir=tmp_path / "development",
        split_role="development",
        random_seed=101,
        reference=reference,
    )
    evaluation = builder.build(
        output_dir=tmp_path / "evaluation",
        split_role="evaluation",
        random_seed=202,
        reference=reference,
    )

    assert development.probe_hash != evaluation.probe_hash
    assert development.selected_cell_hash != evaluation.selected_cell_hash
    assert development.ground_truth_hash != evaluation.ground_truth_hash
    assert development.random_seed != evaluation.random_seed
    assert development.reference_digest == evaluation.reference_digest
    assert development.scientific_claim_allowed is False

    adata = ad.read_h5ad(development.probe_artifact_path)
    assert adata.n_obs == 120
    assert set(adata.obs["ground_truth_cell_type"]) == set(CELL_TYPES)
    assert "counts" in adata.layers
    assert np.all(adata.layers["counts"].data >= 0)
    assert np.allclose(adata.layers["counts"].data, np.rint(adata.layers["counts"].data))
    assert bool(adata.uns["sckg_fixture"]["user_data"]) is False


def test_annotation_probe_is_deterministic_and_does_not_escape_root(tmp_path):
    reference = build_reference(tmp_path / "reference")
    builder = AnnotationProbeBuilder()
    first = builder.build(
        output_dir=tmp_path / "one",
        split_role="development",
        random_seed=303,
        reference=reference,
    )
    second = builder.build(
        output_dir=tmp_path / "two",
        split_role="development",
        random_seed=303,
        reference=reference,
    )

    first_adata = ad.read_h5ad(first.probe_artifact_path)
    second_adata = ad.read_h5ad(second.probe_artifact_path)
    assert first.selected_cell_hash == second.selected_cell_hash
    assert first.ground_truth_hash == second.ground_truth_hash
    assert (first_adata.X != second_adata.X).nnz == 0
    assert hashlib.sha256(
        first_adata.obs_names.str.cat(sep="\n").encode("utf-8")
    ).hexdigest() == hashlib.sha256(
        second_adata.obs_names.str.cat(sep="\n").encode("utf-8")
    ).hexdigest()
