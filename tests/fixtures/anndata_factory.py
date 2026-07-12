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


def _var(n_genes: int) -> pd.DataFrame:
    return pd.DataFrame(index=[f"gene_{index:03d}" for index in range(n_genes)])


def _mark_fixture(adata: ad.AnnData, fixture_id: str) -> None:
    adata.uns["sckg_fixture"] = {
        "fixture_id": fixture_id,
        "synthetic": True,
        "maintainer_approved": True,
        "user_data": False,
    }
