from __future__ import annotations

import hashlib

import anndata as ad
import numpy as np
from scipy import sparse

from execution.scanpy_synthetic_fixture import (
    SCANPY_SYNTHETIC_FIXTURE_SEED,
    generate_scanpy_core_synthetic_fixture,
    load_scanpy_synthetic_manifest,
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scanpy_fixture_is_versioned_deterministic_and_structured(tmp_path):
    first, first_manifest_path, first_manifest = generate_scanpy_core_synthetic_fixture(
        tmp_path / "first"
    )
    second, _, second_manifest = generate_scanpy_core_synthetic_fixture(
        tmp_path / "second"
    )
    loaded = load_scanpy_synthetic_manifest(first_manifest_path)
    adata = ad.read_h5ad(first)

    assert first_manifest.seed == SCANPY_SYNTHETIC_FIXTURE_SEED
    assert first_manifest.shape == [180, 240]
    assert first_manifest.h5ad_sha256 == _sha256(first)
    assert second_manifest.h5ad_sha256 == _sha256(second)
    assert first_manifest.h5ad_sha256 == second_manifest.h5ad_sha256
    assert loaded == first_manifest
    assert sparse.issparse(adata.X)
    assert np.all(adata.X.data >= 0)
    assert np.allclose(adata.X.data, np.rint(adata.X.data))
    assert {"synthetic_group", "batch", "expected_low_quality", "library_size_factor"} <= set(adata.obs)
    assert {"gene_role", "marker_group", "mitochondrial"} <= set(adata.var)
    assert adata.obs["synthetic_group"].nunique() == 3
    assert adata.obs["batch"].nunique() == 2
    assert int(adata.obs["expected_low_quality"].sum()) == 9
    assert loaded.scientific_claim_allowed is False
    assert loaded.user_data is False


def test_planted_markers_and_qc_structure_are_measurable(tmp_path):
    path, _, manifest = generate_scanpy_core_synthetic_fixture(tmp_path / "fixture")
    adata = ad.read_h5ad(path)
    counts = adata.layers["counts"].toarray()
    groups = adata.obs["synthetic_group"].astype(str).to_numpy()

    for group, marker_genes in manifest.marker_genes.items():
        marker_indices = adata.var_names.get_indexer(marker_genes)
        inside = counts[groups == group][:, marker_indices].mean()
        outside = counts[groups != group][:, marker_indices].mean()
        assert inside > outside * 3.0

    totals = counts.sum(axis=1)
    low_quality = adata.obs["expected_low_quality"].to_numpy(dtype=bool)
    assert np.median(totals[low_quality]) < np.median(totals[~low_quality]) * 0.5
    batch_indices = adata.var_names.get_indexer(manifest.batch_shift_genes)
    batch_1 = counts[adata.obs["batch"].astype(str).to_numpy() == "batch_1"][:, batch_indices].mean()
    batch_2 = counts[adata.obs["batch"].astype(str).to_numpy() == "batch_2"][:, batch_indices].mean()
    assert batch_2 > batch_1 * 1.5
