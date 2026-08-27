from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import anndata as ad
import matplotlib
import numpy as np
import pandas as pd
import scanpy as sc

from execution.wrappers.integration_common import load_request, sha256


matplotlib.use("Agg")
import matplotlib.pyplot as plt


ALLOWED_PARAMETERS = {
    "operation",
    "scale",
    "min_genes",
    "min_cells",
    "max_pct_counts_mt",
    "target_sum",
    "n_top_genes",
    "n_comps",
    "n_neighbors",
    "leiden_resolution",
    "max_scale_value",
}


def main(argv: list[str] | None = None) -> int:
    request, _, artifacts_dir = load_request(argv)
    parameters = dict(request["parameters"])
    unknown = sorted(set(parameters) - ALLOWED_PARAMETERS)
    if unknown:
        raise ValueError("unknown Scanpy Core parameters: " + ", ".join(unknown))
    if parameters.get("operation") != "scanpy_core_workflow":
        raise ValueError("unsupported Scanpy Core operation")
    input_path = Path(request["input_path"]).resolve(strict=True)
    if input_path.suffix.casefold() != ".h5ad":
        raise ValueError("Scanpy Core wrapper only accepts .h5ad")
    if sha256(input_path) != request["expected_input_hash"]:
        raise ValueError("input hash mismatch")
    adata = ad.read_h5ad(input_path)
    _validate_input(adata, int(request["expected_cells"]))
    counts = _count_matrix(adata)
    adata = ad.AnnData(
        X=counts.copy(),
        obs=adata.obs.copy(),
        var=adata.var.copy(),
    )
    adata.obs_names = adata.obs_names.astype(str)
    adata.var_names = adata.var_names.astype(str)
    adata.layers["counts"] = counts.copy()
    checkpoints = artifacts_dir / "checkpoints"
    checkpoints.mkdir()
    lineage: list[dict[str, object]] = []

    adata.var["mt"] = (
        np.asarray(adata.var["mitochondrial"], dtype=bool)
        if "mitochondrial" in adata.var
        else adata.var_names.str.upper().str.startswith("MT-")
    )
    qc_vars = ["mt"] if bool(np.asarray(adata.var["mt"], dtype=bool).any()) else []
    sc.pp.calculate_qc_metrics(adata, qc_vars=qc_vars, percent_top=None, inplace=True)
    _checkpoint(
        adata,
        checkpoints,
        "01_qc",
        lineage,
        ["raw_counts"],
        "qc_metrics",
        {"qc_vars": qc_vars},
    )
    cell_mask = np.asarray(adata.obs["n_genes_by_counts"], dtype=int) >= int(
        parameters["min_genes"]
    )
    if "pct_counts_mt" in adata.obs:
        cell_mask &= np.asarray(adata.obs["pct_counts_mt"], dtype=float) <= float(
            parameters["max_pct_counts_mt"]
        )
    adata = adata[cell_mask].copy()
    sc.pp.filter_genes(adata, min_cells=int(parameters["min_cells"]))
    if adata.n_obs < 10 or adata.n_vars < 10:
        raise ValueError("filtering left insufficient cells or genes")
    _checkpoint(
        adata,
        checkpoints,
        "02_filter",
        lineage,
        ["raw_counts", "qc_metrics"],
        "filtered_counts",
        {
            "min_genes": int(parameters["min_genes"]),
            "min_cells": int(parameters["min_cells"]),
            "max_pct_counts_mt": float(parameters["max_pct_counts_mt"]),
        },
    )
    sc.pp.normalize_total(adata, target_sum=float(parameters["target_sum"]))
    _checkpoint(
        adata,
        checkpoints,
        "03_normalize",
        lineage,
        ["filtered_counts"],
        "library_size_normalized",
        {"target_sum": float(parameters["target_sum"])},
    )
    sc.pp.log1p(adata)
    adata.layers["log1p"] = adata.X.copy()
    _checkpoint(
        adata,
        checkpoints,
        "04_log1p",
        lineage,
        ["library_size_normalized"],
        "log1p_normalized",
        {},
    )
    n_top = min(int(parameters["n_top_genes"]), max(2, adata.n_vars - 1))
    sc.pp.highly_variable_genes(adata, n_top_genes=n_top, flavor="seurat")
    _checkpoint(
        adata,
        checkpoints,
        "05_hvg",
        lineage,
        ["log1p_normalized"],
        "hvg_selection",
        {"n_top_genes": n_top, "flavor": "seurat"},
    )

    hvg = adata[:, adata.var["highly_variable"]].copy()
    if bool(parameters["scale"]):
        sc.pp.scale(hvg, max_value=float(parameters["max_scale_value"]))
        pca_source = "scaled_hvg"
        _checkpoint(
            hvg,
            checkpoints,
            "06_scale_hvg",
            lineage,
            ["log1p_normalized", "hvg_selection"],
            "scaled_hvg",
            {"max_scale_value": float(parameters["max_scale_value"])},
        )
    else:
        pca_source = "log_hvg"
    n_comps = min(int(parameters["n_comps"]), hvg.n_obs - 1, hvg.n_vars - 1)
    if n_comps < 2:
        raise ValueError("insufficient cells or HVGs for PCA")
    sc.tl.pca(hvg, n_comps=n_comps, random_state=int(request["execution_seed"]))
    adata.obsm["X_pca"] = np.asarray(hvg.obsm["X_pca"], dtype=np.float32)
    adata.uns["pca"] = hvg.uns["pca"]
    adata.varm["PCs"] = np.zeros((adata.n_vars, n_comps), dtype=np.float32)
    adata.varm["PCs"][adata.var["highly_variable"].to_numpy()] = np.asarray(hvg.varm["PCs"], dtype=np.float32)
    _checkpoint(
        adata,
        checkpoints,
        "07_pca",
        lineage,
        [pca_source],
        "pca",
        {"n_comps": n_comps, "random_state": int(request["execution_seed"])},
    )

    n_neighbors = min(int(parameters["n_neighbors"]), adata.n_obs - 1)
    sc.pp.neighbors(adata, use_rep="X_pca", n_neighbors=n_neighbors, random_state=int(request["execution_seed"]))
    _checkpoint(
        adata,
        checkpoints,
        "08_neighbors",
        lineage,
        ["pca"],
        "neighbor_graph",
        {"n_neighbors": n_neighbors, "use_rep": "X_pca"},
    )
    sc.tl.umap(adata, random_state=int(request["execution_seed"]))
    _checkpoint(
        adata,
        checkpoints,
        "09_umap",
        lineage,
        ["neighbor_graph"],
        "umap",
        {"random_state": int(request["execution_seed"])},
    )
    sc.tl.leiden(
        adata,
        resolution=float(parameters["leiden_resolution"]),
        random_state=int(request["execution_seed"]),
        key_added="leiden",
    )
    _checkpoint(
        adata,
        checkpoints,
        "10_leiden",
        lineage,
        ["neighbor_graph"],
        "cluster_labels",
        {
            "resolution": float(parameters["leiden_resolution"]),
            "random_state": int(request["execution_seed"]),
        },
    )
    sc.tl.rank_genes_groups(adata, groupby="leiden", layer="log1p", method="wilcoxon")
    _checkpoint(
        adata,
        checkpoints,
        "11_markers",
        lineage,
        ["full_gene_unscaled_log1p", "cluster_labels"],
        "marker_result",
        {"groupby": "leiden", "layer": "log1p", "method": "wilcoxon"},
    )

    _write_plots(adata, artifacts_dir)
    output_path = artifacts_dir / "scanpy_core_output.h5ad"
    adata.write_h5ad(output_path)
    ledger = {
        "schema_version": "sckg-representation-ledger-artifact-v1",
        "input_hash": request["expected_input_hash"],
        "cell_index_hash": _hash_names(adata.obs_names),
        "gene_index_hash": _hash_names(adata.var_names),
        "scale_enabled": bool(parameters["scale"]),
        "pca_source": pca_source,
        "marker_source": "full_gene_unscaled_log1p",
        "lineage": lineage,
    }
    (artifacts_dir / "representation_ledger.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (artifacts_dir / "parameters.json").write_text(
        json.dumps(
            {"parameters": parameters, "execution_seed": int(request["execution_seed"])},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    metadata = {
        "tool_name": "Scanpy",
        "tool_version": sc.__version__,
        "input_hash": request["expected_input_hash"],
        "n_cells": adata.n_obs,
        "n_genes": adata.n_vars,
        "execution_seed": int(request["execution_seed"]),
        "execution_purpose": request["purpose"],
        "tool_actually_executed": True,
        "user_data_used": False,
    }
    (artifacts_dir / "result_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, sort_keys=True))
    return 0


def _validate_input(adata: ad.AnnData, expected_cells: int) -> None:
    if adata.n_obs != expected_cells or adata.n_obs < 10 or adata.n_vars < 10:
        raise ValueError("input dimensions do not satisfy Scanpy Core qualification")
    if not adata.obs_names.is_unique or not adata.var_names.is_unique:
        raise ValueError("cell and gene identifiers must be unique")


def _count_matrix(adata: ad.AnnData):
    matrix = adata.layers["counts"] if "counts" in adata.layers else adata.X
    values = matrix.data if hasattr(matrix, "data") else np.asarray(matrix)
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all() or np.any(values < 0) or not np.allclose(values, np.rint(values)):
        raise ValueError("Scanpy Core qualification requires nonnegative integer counts")
    return matrix


def _checkpoint(
    adata,
    root: Path,
    name: str,
    lineage: list[dict[str, object]],
    consumes: list[str],
    produces: str,
    parameters: dict[str, object],
) -> None:
    path = root / f"{name}.h5ad"
    adata.write_h5ad(path)
    artifact_hash = sha256(path)
    lineage.append(
        {
            "step_id": name,
            "status": "completed",
            "consumes": consumes,
            "produces": produces,
            "artifact": f"checkpoints/{path.name}",
            "artifact_hash": artifact_hash,
            "parent_artifact_hashes": (
                [lineage[-1]["artifact_hash"]] if lineage else []
            ),
            "parameter_hash": _json_hash(parameters),
            "parameters": parameters,
            "provenance": [
                "fixed_wrapper:scanpy_core_v1_11_2",
                "tool_contract:scanpy:1.11.2",
                f"operation:{name}",
            ],
            "cell_index_hash": _hash_names(adata.obs_names),
            "gene_index_hash": _hash_names(adata.var_names),
        }
    )


def _write_plots(adata: ad.AnnData, output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    axes[0].hist(adata.obs["total_counts"], bins=24, color="#287271")
    axes[0].set(title="Total counts", xlabel="UMIs", ylabel="cells")
    axes[1].hist(adata.obs["n_genes_by_counts"], bins=24, color="#d07a5f")
    axes[1].set(title="Detected genes", xlabel="genes")
    fig.tight_layout(); fig.savefig(output / "qc_diagnostics.png", dpi=130); plt.close(fig)

    variance = np.asarray(adata.uns["pca"]["variance_ratio"])
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    ax.plot(np.arange(1, len(variance) + 1), variance, marker="o", color="#287271")
    ax.set(title="PCA variance explained", xlabel="component", ylabel="variance ratio")
    fig.tight_layout(); fig.savefig(output / "pca_variance.png", dpi=130); plt.close(fig)

    coords = np.asarray(adata.obsm["X_umap"])
    labels = adata.obs["leiden"].astype(str)
    fig, ax = plt.subplots(figsize=(5.4, 4.4))
    for label in sorted(labels.unique()):
        mask = labels == label
        ax.scatter(coords[mask, 0], coords[mask, 1], s=18, label=label, alpha=0.8)
    ax.set(title="UMAP and Leiden clusters", xlabel="UMAP1", ylabel="UMAP2")
    ax.legend(title="cluster", fontsize=7)
    fig.tight_layout(); fig.savefig(output / "umap_clusters.png", dpi=130); plt.close(fig)

    names = pd.DataFrame(adata.uns["rank_genes_groups"]["names"]).head(5)
    scores = pd.DataFrame(adata.uns["rank_genes_groups"]["scores"]).head(5)
    fig, ax = plt.subplots(figsize=(max(5, len(scores.columns) * 1.2), 4.2))
    image = ax.imshow(scores.to_numpy(dtype=float).T, aspect="auto", cmap="viridis")
    ax.set_yticks(range(len(scores.columns)), labels=[f"cluster {item}" for item in scores.columns])
    ax.set_xticks(range(5), labels=["rank 1", "rank 2", "rank 3", "rank 4", "rank 5"], rotation=35)
    ax.set_title("Top marker scores")
    for row in range(names.shape[1]):
        for col in range(names.shape[0]):
            ax.text(col, row, str(names.iloc[col, row]), ha="center", va="center", fontsize=6, color="white")
    fig.colorbar(image, ax=ax, label="Wilcoxon score")
    fig.tight_layout(); fig.savefig(output / "marker_diagnostics.png", dpi=130); plt.close(fig)


def _hash_names(names) -> str:
    return hashlib.sha256("\n".join(map(str, names)).encode("utf-8")).hexdigest()


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
