from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import anndata as ad
import harmonypy as hm
import matplotlib
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.decomposition import TruncatedSVD


matplotlib.use("Agg")
import matplotlib.pyplot as plt


def build_demo(seed: int = 17) -> ad.AnnData:
    rng = np.random.default_rng(seed)
    n_batches, n_types, cells_per_group, n_genes = 3, 3, 45, 320
    batches: list[str] = []
    cell_types: list[str] = []
    matrices: list[np.ndarray] = []
    type_effects = rng.gamma(1.8, 0.8, size=(n_types, n_genes))
    batch_effects = rng.normal(0.0, 0.35, size=(n_batches, n_genes))
    for batch_index in range(n_batches):
        for type_index in range(n_types):
            log_mu = (
                0.2
                + type_effects[type_index]
                + batch_effects[batch_index]
            )
            values = rng.poisson(np.exp(np.clip(log_mu, -2.0, 3.0)), size=(cells_per_group, n_genes))
            matrices.append(values.astype(np.int32))
            batches.extend([f"batch_{batch_index + 1}"] * cells_per_group)
            cell_types.extend([f"type_{type_index + 1}"] * cells_per_group)
    counts = sparse.csr_matrix(np.vstack(matrices))
    adata = ad.AnnData(X=counts)
    adata.layers["counts"] = counts.copy()
    adata.obs["batch"] = batches
    adata.obs["cell_type"] = cell_types
    adata.obs_names = [f"demo_cell_{index:04d}" for index in range(adata.n_obs)]
    adata.var_names = [f"gene_{index:04d}" for index in range(adata.n_vars)]
    return adata


def prepare_expression(adata: ad.AnnData, matrix_state: str) -> sparse.csr_matrix:
    matrix = adata.layers["counts"] if "counts" in adata.layers else adata.X
    matrix = sparse.csr_matrix(matrix, dtype=np.float64)
    if matrix.shape[0] < 10 or matrix.shape[1] < 10:
        raise ValueError("Batch integration requires at least 10 cells and 10 genes.")
    if matrix.nnz and (not np.isfinite(matrix.data).all() or matrix.data.min() < 0):
        raise ValueError("Expression values must be finite and non-negative.")
    if matrix_state == "raw_counts":
        totals = np.asarray(matrix.sum(axis=1)).ravel()
        if np.any(totals <= 0):
            raise ValueError("Raw-count input contains empty cells.")
        matrix = sparse.diags(10_000.0 / totals) @ matrix
        matrix.data = np.log1p(matrix.data)
    return sparse.csr_matrix(matrix)


def run_harmony(
    adata: ad.AnnData,
    *,
    batch_key: str,
    matrix_state: str,
    n_components: int,
    theta: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if batch_key not in adata.obs:
        raise ValueError(f"Missing batch column: {batch_key}")
    if adata.obs[batch_key].astype(str).nunique() < 2:
        raise ValueError("Harmony requires at least two batches.")
    expression = prepare_expression(adata, matrix_state)
    max_components = max(2, min(expression.shape) - 1)
    components = min(n_components, max_components)
    pca = TruncatedSVD(n_components=components, random_state=seed).fit_transform(expression)
    metadata = pd.DataFrame({batch_key: adata.obs[batch_key].astype(str).to_numpy()})
    corrected = hm.run_harmony(
        pca,
        metadata,
        [batch_key],
        theta=theta,
        random_state=seed,
        verbose=False,
    ).Z_corr
    if corrected.shape != pca.shape or not np.isfinite(corrected).all():
        raise RuntimeError("Harmony returned an invalid corrected embedding.")
    return pca, np.asarray(corrected, dtype=np.float32)


def plot_embeddings(
    before: np.ndarray,
    after: np.ndarray,
    batches: pd.Series,
    cell_types: pd.Series | None,
    output: Path,
) -> None:
    batch_labels = batches.astype(str)
    label_sets = [
        ("Batch", batch_labels, _discriminative_dimensions(before, batch_labels))
    ]
    if cell_types is not None:
        type_labels = cell_types.astype(str)
        label_sets.append(
            ("Cell type", type_labels, _discriminative_dimensions(before, type_labels))
        )
    fig, axes = plt.subplots(
        len(label_sets),
        2,
        figsize=(10, 4.2 * len(label_sets)),
        squeeze=False,
        constrained_layout=True,
    )
    palette = plt.get_cmap("tab10")
    for row, (label_name, labels, dimensions) in enumerate(label_sets):
        categories = sorted(labels.unique())
        for category_index, category in enumerate(categories):
            mask = labels.to_numpy() == category
            color = palette(category_index % 10)
            axes[row, 0].scatter(
                before[mask, dimensions[0]],
                before[mask, dimensions[1]],
                s=10,
                alpha=0.7,
                color=color,
                label=category,
            )
            axes[row, 1].scatter(
                after[mask, dimensions[0]],
                after[mask, dimensions[1]],
                s=10,
                alpha=0.7,
                color=color,
                label=category,
            )
        axes[row, 0].set_title(f"Before Harmony · {label_name}")
        axes[row, 1].set_title(f"After Harmony · {label_name}")
        axes[row, 1].legend(frameon=False, fontsize=8)
        for axis in axes[row]:
            axis.set_xlabel(f"Component {dimensions[0] + 1}")
            axis.set_ylabel(f"Component {dimensions[1] + 1}")
    fig.savefig(output, dpi=180)
    plt.close(fig)


def _discriminative_dimensions(
    embedding: np.ndarray,
    labels: pd.Series,
) -> tuple[int, int]:
    overall = embedding.mean(axis=0)
    total = np.square(embedding - overall).mean(axis=0) + 1e-12
    between = np.zeros(embedding.shape[1], dtype=np.float64)
    values = labels.to_numpy()
    for category in labels.unique():
        mask = values == category
        between += mask.mean() * np.square(embedding[mask].mean(axis=0) - overall)
    ranked = np.argsort(-(between / total))
    if len(ranked) < 2:
        return (0, 0)
    return int(ranked[0]), int(ranked[1])


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintainer-owned Harmony batch integration recipe.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true")
    source.add_argument("--input", type=Path)
    parser.add_argument("--batch-key", default="batch")
    parser.add_argument("--matrix-state", choices=("raw_counts", "log_normalized"), default="raw_counts")
    parser.add_argument("--theta", type=float, default=2.0)
    parser.add_argument("--n-components", type=int, default=30)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0.0 <= args.theta <= 20.0:
        raise SystemExit("--theta must be between 0 and 20")
    if not 2 <= args.n_components <= 100:
        raise SystemExit("--n-components must be between 2 and 100")

    adata = build_demo(args.seed) if args.demo else ad.read_h5ad(args.input)
    input_shape = [int(adata.n_obs), int(adata.n_vars)]
    before, corrected = run_harmony(
        adata,
        batch_key=args.batch_key,
        matrix_state=args.matrix_state,
        n_components=args.n_components,
        theta=args.theta,
        seed=args.seed,
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    embedding_columns = [f"Harmony_{index + 1}" for index in range(corrected.shape[1])]
    embedding = pd.DataFrame(corrected, index=adata.obs_names, columns=embedding_columns)
    embedding.index.name = "cell_id"
    embedding.to_csv(output / "integrated_embedding.tsv", sep="\t")
    adata.obsm["X_pca_before_harmony"] = before.astype(np.float32)
    adata.obsm["X_harmony"] = corrected
    adata.write_h5ad(output / "harmony_integrated.h5ad")
    plot_embeddings(
        before,
        corrected,
        adata.obs[args.batch_key],
        adata.obs["cell_type"] if "cell_type" in adata.obs else None,
        output / "batch_mixing_before_after.png",
    )

    input_hash = hashlib.sha256(
        "|".join(map(str, adata.obs_names)).encode("utf-8")
    ).hexdigest()
    summary = {
        "schema_version": "workflow-recipe-summary-v1",
        "task": "batch_integration",
        "tool": "Harmony",
        "tool_version": getattr(hm, "__version__", "unknown"),
        "demo_mode": bool(args.demo),
        "synthetic_demo": bool(args.demo),
        "user_data_used": not args.demo,
        "input_shape": input_shape,
        "input_obs_hash": input_hash,
        "batch_key": args.batch_key,
        "batch_count": int(adata.obs[args.batch_key].astype(str).nunique()),
        "parameters": {
            "matrix_state": args.matrix_state,
            "theta": args.theta,
            "n_components": corrected.shape[1],
            "seed": args.seed,
        },
        "harmony_actually_executed": True,
        "artifacts": [
            "integrated_embedding.tsv",
            "harmony_integrated.h5ad",
            "batch_mixing_before_after.png",
            "workflow_summary.json",
        ],
        "limitations": [
            "Batch mixing must be interpreted together with biological conservation.",
            "Harmony corrects an embedding; it does not replace expression-level differential analysis.",
            "The synthetic demo is an engineering smoke, not biological validation.",
        ],
    }
    (output / "workflow_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
