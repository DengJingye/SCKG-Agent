#!/usr/bin/env python3
"""Run a reproducible Scrublet workflow on raw-count AnnData or demo data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import anndata as ad
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import sparse


RECIPE_VERSION = "1.0.0"


def build_demo_anndata(seed: int = 20260722) -> ad.AnnData:
    """Create PBMC-like raw counts plus synthetic count-sum doublets."""

    rng = np.random.default_rng(seed)
    n_singlets, n_genes, n_clusters = 450, 700, 3
    labels = np.repeat(np.arange(n_clusters), n_singlets // n_clusters)
    base_means = rng.gamma(shape=0.7, scale=0.8, size=n_genes)
    counts = np.zeros((n_singlets, n_genes), dtype=np.int32)
    for cluster in range(n_clusters):
        cell_indices = np.flatnonzero(labels == cluster)
        means = base_means.copy()
        start = cluster * 45
        means[start : start + 45] += 4.0
        library_factors = rng.lognormal(mean=0.0, sigma=0.25, size=len(cell_indices))
        counts[cell_indices] = rng.poisson(library_factors[:, None] * means[None, :])

    n_doublets = 50
    pairs = np.asarray(
        [rng.choice(n_singlets, size=2, replace=False) for _ in range(n_doublets)]
    )
    doublets = counts[pairs[:, 0]] + counts[pairs[:, 1]]
    matrix = sparse.csr_matrix(np.vstack([counts, doublets]))
    obs = pd.DataFrame(
        {
            "sample": "demo_capture_1",
            "ground_truth_doublet": [False] * n_singlets + [True] * n_doublets,
        },
        index=[f"demo_cell_{index:04d}" for index in range(n_singlets + n_doublets)],
    )
    var = pd.DataFrame(index=[f"gene_{index:04d}" for index in range(n_genes)])
    adata = ad.AnnData(X=matrix, obs=obs, var=var)
    adata.uns["sckg_demo"] = {
        "synthetic": True,
        "seed": seed,
        "metric_type": "synthetic_engineering_metric",
    }
    return adata


def select_count_matrix(
    adata: ad.AnnData,
    requested_layer: str | None = None,
) -> tuple[Any, str]:
    """Select a non-negative integer count source without modifying AnnData."""

    candidates: list[tuple[str, Any]] = []
    if requested_layer:
        if requested_layer not in adata.layers:
            raise ValueError(f"requested count layer is missing: {requested_layer}")
        candidates.append((f"layers/{requested_layer}", adata.layers[requested_layer]))
    elif "counts" in adata.layers:
        candidates.append(("layers/counts", adata.layers["counts"]))
    candidates.append(("X", adata.X))
    if adata.raw is not None:
        candidates.append(("raw.X", adata.raw.X))

    for source_name, matrix in candidates:
        if _is_raw_count_matrix(matrix):
            return matrix, source_name
    raise ValueError(
        "No valid raw-count source found. Expected non-negative integer values in "
        "layers['counts'], X, or raw.X; log-normalized/scaled matrices are blocked."
    )


def run_scrublet(
    adata: ad.AnnData,
    *,
    count_matrix: Any,
    sample_key: str | None,
    expected_doublet_rate: float,
    n_prin_comps: int,
    random_seed: int,
    threshold: float | None,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    import scrublet

    if sample_key:
        if sample_key not in adata.obs:
            raise ValueError(f"sample key is missing from adata.obs: {sample_key}")
        groups = adata.obs[sample_key].astype(str).to_numpy()
    else:
        groups = np.repeat("all_cells", adata.n_obs)

    scores = np.full(adata.n_obs, np.nan, dtype=float)
    predicted = np.zeros(adata.n_obs, dtype=bool)
    run_summaries: list[dict[str, Any]] = []
    for group_index, group in enumerate(pd.unique(groups)):
        indices = np.flatnonzero(groups == group)
        if len(indices) < 100:
            raise ValueError(
                f"sample '{group}' has only {len(indices)} cells; this recipe requires at "
                "least 100 cells for a stable engineering run"
            )
        matrix = count_matrix[indices]
        if not sparse.issparse(matrix):
            matrix = sparse.csr_matrix(matrix)
        else:
            matrix = matrix.tocsr()
        pcs = min(n_prin_comps, max(2, min(matrix.shape[0] - 1, matrix.shape[1] - 1)))
        scrub = scrublet.Scrublet(
            matrix,
            expected_doublet_rate=expected_doublet_rate,
            sim_doublet_ratio=2.0,
            random_state=random_seed + group_index,
        )
        group_scores, group_predictions = scrub.scrub_doublets(
            min_counts=3,
            min_cells=3,
            min_gene_variability_pctl=85,
            n_prin_comps=pcs,
            use_approx_neighbors=True,
            verbose=False,
        )
        if threshold is not None:
            group_predictions = scrub.call_doublets(threshold=threshold, verbose=False)
        scores[indices] = np.asarray(group_scores, dtype=float)
        predicted[indices] = np.asarray(group_predictions, dtype=bool)
        run_summaries.append(
            {
                "sample": str(group),
                "n_cells": len(indices),
                "n_prin_comps": pcs,
                "threshold": float(scrub.threshold_),
                "predicted_doublets": int(np.sum(group_predictions)),
            }
        )
    return scores, predicted, run_summaries


def write_outputs(
    adata: ad.AnnData,
    *,
    output_dir: Path,
    scores: np.ndarray,
    predicted: np.ndarray,
    count_matrix: Any,
    count_source: str,
    run_summaries: list[dict[str, Any]],
    parameters: dict[str, Any],
    demo_mode: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = pd.DataFrame(
        {
            "cell_id": adata.obs_names.astype(str),
            "doublet_score": scores,
            "predicted_doublet": predicted,
        }
    )
    if "ground_truth_doublet" in adata.obs:
        result["ground_truth_doublet"] = (
            adata.obs["ground_truth_doublet"].astype(bool).to_numpy()
        )
    result.to_csv(output_dir / "doublet_results.tsv", sep="\t", index=False)

    annotated = adata.copy()
    annotated.obs["scrublet_doublet_score"] = scores
    annotated.obs["scrublet_predicted_doublet"] = predicted
    annotated.write_h5ad(output_dir / "doublet_annotated.h5ad")

    _plot_score_distribution(scores, predicted, output_dir)
    library_size = np.asarray(count_matrix.sum(axis=1)).reshape(-1)
    _plot_score_vs_library_size(scores, predicted, library_size, output_dir)

    summary = {
        "recipe_id": "doublet-detection-scrublet-python",
        "recipe_version": RECIPE_VERSION,
        "demo_mode": demo_mode,
        "synthetic_demo": demo_mode,
        "metric_type": "synthetic_engineering_metric" if demo_mode else "user_analysis",
        "scrublet_actually_executed": True,
        "input_modified": False,
        "count_source": count_source,
        "n_cells": adata.n_obs,
        "n_genes": int(count_matrix.shape[1]),
        "predicted_doublets": int(np.sum(predicted)),
        "predicted_doublet_fraction": float(np.mean(predicted)),
        "parameters": parameters,
        "sample_runs": run_summaries,
        "outputs": [
            "doublet_results.tsv",
            "doublet_annotated.h5ad",
            "doublet_score_distribution.png",
            "doublet_score_vs_library_size.png",
        ],
        "limitations": [
            "Homotypic doublets and continuous cell states remain difficult.",
            "Expected doublet rate and threshold require dataset-level review.",
            "Demo metrics are engineering checks, not biological validation.",
        ],
    }
    (output_dir / "workflow_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _plot_score_distribution(
    scores: np.ndarray,
    predicted: np.ndarray,
    output_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.hist(scores[~predicted], bins=35, alpha=0.75, label="predicted singlet")
    if np.any(predicted):
        ax.hist(scores[predicted], bins=25, alpha=0.75, label="predicted doublet")
    ax.set(xlabel="Scrublet doublet score", ylabel="Cells", title="Doublet score distribution")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_dir / "doublet_score_distribution.png", dpi=180)
    plt.close(fig)


def _plot_score_vs_library_size(
    scores: np.ndarray,
    predicted: np.ndarray,
    library_size: np.ndarray,
    output_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    colors = np.where(predicted, "#d45745", "#277da1")
    ax.scatter(np.log1p(library_size), scores, c=colors, s=11, alpha=0.65, linewidths=0)
    ax.set(
        xlabel="log1p total UMI counts",
        ylabel="Scrublet doublet score",
        title="Score and library size diagnostic",
    )
    fig.tight_layout()
    fig.savefig(output_dir / "doublet_score_vs_library_size.png", dpi=180)
    plt.close(fig)


def _is_raw_count_matrix(matrix: Any) -> bool:
    values = np.asarray(matrix.data if sparse.issparse(matrix) else matrix).reshape(-1)
    return bool(
        values.size
        and np.all(np.isfinite(values))
        and np.all(values >= 0)
        and np.allclose(values, np.rint(values), atol=1e-8)
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="run the deterministic demo")
    source.add_argument("--input", type=Path, help="input AnnData .h5ad")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-key", default=None)
    parser.add_argument("--counts-layer", default=None)
    parser.add_argument("--expected-doublet-rate", type=float, default=0.06)
    parser.add_argument("--n-prin-comps", type=int, default=30)
    parser.add_argument("--random-seed", type=int, default=20260722)
    parser.add_argument("--threshold", type=float, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not 0.001 <= args.expected_doublet_rate <= 0.25:
        raise ValueError("expected-doublet-rate must be between 0.001 and 0.25")
    if not 2 <= args.n_prin_comps <= 100:
        raise ValueError("n-prin-comps must be between 2 and 100")
    if args.threshold is not None and not 0.0 <= args.threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")

    if args.demo:
        adata = build_demo_anndata(seed=args.random_seed)
    else:
        input_path = Path(args.input).expanduser().resolve()
        if input_path.suffix.casefold() != ".h5ad" or not input_path.is_file():
            raise ValueError("--input must point to an existing .h5ad file")
        adata = ad.read_h5ad(input_path)
    count_matrix, count_source = select_count_matrix(adata, args.counts_layer)
    scores, predicted, run_summaries = run_scrublet(
        adata,
        count_matrix=count_matrix,
        sample_key=args.sample_key,
        expected_doublet_rate=args.expected_doublet_rate,
        n_prin_comps=args.n_prin_comps,
        random_seed=args.random_seed,
        threshold=args.threshold,
    )
    summary = write_outputs(
        adata,
        output_dir=args.output,
        scores=scores,
        predicted=predicted,
        count_matrix=count_matrix,
        count_source=count_source,
        run_summaries=run_summaries,
        parameters={
            "expected_doublet_rate": args.expected_doublet_rate,
            "n_prin_comps": args.n_prin_comps,
            "random_seed": args.random_seed,
            "sample_key": args.sample_key,
            "counts_layer": args.counts_layer,
            "threshold": args.threshold,
        },
        demo_mode=bool(args.demo),
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
