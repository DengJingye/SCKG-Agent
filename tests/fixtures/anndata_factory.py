from __future__ import annotations

from pathlib import Path
from typing import Dict

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse


FIXTURE_SEED = 20260711


def write_phase1_fixtures(directory: Path) -> Dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "raw_x": directory / "raw_counts_x.h5ad",
        "counts_layer": directory / "log1p_x_counts_layer.h5ad",
        "scaled": directory / "scaled_x_no_counts.h5ad",
        "raw_x_distinct": directory / "log1p_x_raw_counts_raw.h5ad",
        "nan": directory / "nan_x.h5ad",
        "inf": directory / "inf_x.h5ad",
        "empty": directory / "empty.h5ad",
        "corrupt": directory / "corrupt.h5ad",
        "duplicate_names": directory / "duplicate_names.h5ad",
    }

    counts = _counts()
    obs = _obs(counts.shape[0])
    var = _var(counts.shape[1])

    raw = ad.AnnData(X=sparse.csr_matrix(counts), obs=obs.copy(), var=var.copy())
    _mark_fixture(raw, "phase1_raw_counts_x")
    raw.write_h5ad(paths["raw_x"])

    layered = ad.AnnData(X=np.log1p(counts).astype(np.float32), obs=obs.copy(), var=var.copy())
    layered.layers["counts"] = sparse.csr_matrix(counts)
    _mark_fixture(layered, "phase1_counts_layer")
    layered.write_h5ad(paths["counts_layer"])

    logged = np.log1p(counts).astype(np.float64)
    means = logged.mean(axis=0, keepdims=True)
    stds = logged.std(axis=0, keepdims=True)
    stds[stds == 0] = 1.0
    scaled_x = ((logged - means) / stds).astype(np.float32)
    scaled = ad.AnnData(X=scaled_x, obs=obs.copy(), var=var.copy())
    _mark_fixture(scaled, "phase1_scaled_x")
    scaled.write_h5ad(paths["scaled"])

    raw_distinct = ad.AnnData(
        X=np.log1p(counts).astype(np.float32),
        obs=obs.copy(),
        var=var.copy(),
    )
    raw_distinct.raw = ad.AnnData(
        X=sparse.csr_matrix(counts),
        obs=obs.copy(),
        var=var.copy(),
    )
    _mark_fixture(raw_distinct, "phase1_raw_x_distinct")
    raw_distinct.write_h5ad(paths["raw_x_distinct"])

    nan_x = counts.astype(np.float32)
    nan_x[0, 0] = np.nan
    ad.AnnData(X=nan_x, obs=obs.copy(), var=var.copy()).write_h5ad(paths["nan"])

    inf_x = counts.astype(np.float32)
    inf_x[0, 0] = np.inf
    ad.AnnData(X=inf_x, obs=obs.copy(), var=var.copy()).write_h5ad(paths["inf"])

    ad.AnnData(
        X=np.empty((0, counts.shape[1]), dtype=np.float32),
        obs=pd.DataFrame(index=pd.Index([], dtype=str)),
        var=var.copy(),
    ).write_h5ad(paths["empty"])

    duplicate = ad.AnnData(X=sparse.csr_matrix(counts), obs=obs.copy(), var=var.copy())
    duplicate.obs_names = ["duplicate"] * duplicate.n_obs
    duplicate.var_names = ["gene"] * duplicate.n_vars
    duplicate.write_h5ad(paths["duplicate_names"])

    paths["corrupt"].write_bytes(b"not-an-hdf5-file")
    return paths


def write_phase5_batch_fixtures(directory: Path) -> Dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "valid_pca": directory / "batch_valid_pca.h5ad",
        "valid_needs_pca": directory / "batch_valid_needs_pca.h5ad",
        "missing_batch_key": directory / "batch_missing_key.h5ad",
        "single_batch": directory / "batch_single.h5ad",
        "missing_batch_labels": directory / "batch_missing_labels.h5ad",
        "invalid_pca": directory / "batch_invalid_pca.h5ad",
    }
    counts = _counts(n_cells=60, n_genes=30)
    obs = _batch_obs(counts.shape[0])
    var = _var(counts.shape[1])
    normalized = np.log1p(counts / np.maximum(counts.sum(axis=1, keepdims=True), 1) * 1e4)
    centered = normalized - normalized.mean(axis=0, keepdims=True)
    u, singular_values, _ = np.linalg.svd(centered, full_matrices=False)
    pca = (u[:, :10] * singular_values[:10]).astype(np.float32)

    valid = ad.AnnData(X=normalized.astype(np.float32), obs=obs.copy(), var=var.copy())
    valid.layers["counts"] = sparse.csr_matrix(counts)
    valid.obsm["X_pca"] = pca
    _mark_fixture(valid, "phase5_batch_valid_pca")
    valid.write_h5ad(paths["valid_pca"])

    needs_pca = ad.AnnData(
        X=normalized.astype(np.float32),
        obs=obs.copy(),
        var=var.copy(),
    )
    _mark_fixture(needs_pca, "phase5_batch_valid_needs_pca")
    needs_pca.write_h5ad(paths["valid_needs_pca"])

    missing_key = valid.copy()
    del missing_key.obs["batch"]
    missing_key.write_h5ad(paths["missing_batch_key"])

    single = valid.copy()
    single.obs["batch"] = pd.Categorical(["batch_a"] * single.n_obs)
    single.write_h5ad(paths["single_batch"])

    missing_labels = valid.copy()
    batch_values = missing_labels.obs["batch"].astype(object)
    batch_values.iloc[0] = None
    missing_labels.obs["batch"] = pd.Categorical(batch_values)
    missing_labels.write_h5ad(paths["missing_batch_labels"])

    invalid_pca = valid.copy()
    invalid_values = np.asarray(invalid_pca.obsm["X_pca"]).copy()
    invalid_values[0, 0] = np.nan
    invalid_pca.obsm["X_pca"] = invalid_values
    invalid_pca.write_h5ad(paths["invalid_pca"])
    return paths


def _counts(n_cells: int = 48, n_genes: int = 24) -> np.ndarray:
    rng = np.random.default_rng(FIXTURE_SEED)
    counts = rng.poisson(lam=1.4, size=(n_cells, n_genes)).astype(np.int32)
    counts[0, 0] = 7
    counts[1, 1] = 3
    return counts


def _obs(n_cells: int) -> pd.DataFrame:
    batches = ["batch_a" if index % 2 == 0 else "batch_b" for index in range(n_cells)]
    return pd.DataFrame(
        {"batch": pd.Categorical(batches)},
        index=[f"cell_{index:03d}" for index in range(n_cells)],
    )


def _batch_obs(n_cells: int) -> pd.DataFrame:
    batches = [f"batch_{index % 3}" for index in range(n_cells)]
    cell_types = ["T" if index % 2 == 0 else "B" for index in range(n_cells)]
    return pd.DataFrame(
        {
            "batch": pd.Categorical(batches),
            "cell_type": pd.Categorical(cell_types),
        },
        index=[f"batch_cell_{index:03d}" for index in range(n_cells)],
    )


def _var(n_genes: int) -> pd.DataFrame:
    return pd.DataFrame(index=[f"gene_{index:03d}" for index in range(n_genes)])


def _mark_fixture(adata: ad.AnnData, fixture_id: str) -> None:
    adata.uns["sckg_fixture"] = {
        "fixture_id": fixture_id,
        "synthetic": True,
        "maintainer_approved": True,
        "user_data": False,
    }
