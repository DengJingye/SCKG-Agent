from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_samples


def bootstrap_integration_metrics(
    prediction_path,
    *,
    iterations: int = 500,
    seed: int = 20260719,
) -> dict[str, dict[str, float | int]]:
    table = pd.read_csv(prediction_path, sep="\t")
    embedding_columns = [name for name in table if name.startswith("integrated_")]
    embedding = table[embedding_columns].to_numpy(dtype=float)
    labels = table["cell_type"].astype(str).to_numpy()
    batches = table["batch"].astype(str).to_numpy()
    biology_values = np.clip((silhouette_samples(embedding, labels) + 1.0) / 2.0, 0.0, 1.0)
    mixing_values = np.full(len(table), np.nan, dtype=float)
    for label in sorted(set(labels.tolist())):
        mask = labels == label
        batch_count = len(set(batches[mask].tolist()))
        if mask.sum() < 4 or batch_count < 2 or batch_count >= mask.sum():
            continue
        mixing_values[mask] = np.clip(
            1.0 - np.abs(silhouette_samples(embedding[mask], batches[mask])),
            0.0,
            1.0,
        )
    valid_mixing = np.flatnonzero(np.isfinite(mixing_values))
    if not len(valid_mixing):
        raise ValueError("scientific integration evaluation has no valid batch-mixing cells")
    rng = np.random.default_rng(seed)
    biology_bootstrap = np.empty(iterations, dtype=float)
    mixing_bootstrap = np.empty(iterations, dtype=float)
    for index in range(iterations):
        biology_indices = rng.integers(0, len(biology_values), len(biology_values))
        mixing_indices = rng.choice(valid_mixing, size=len(valid_mixing), replace=True)
        biology_bootstrap[index] = float(np.mean(biology_values[biology_indices]))
        mixing_bootstrap[index] = float(np.mean(mixing_values[mixing_indices]))
    return {
        "batch_mixing_asw": _interval(
            float(np.mean(mixing_values[valid_mixing])), mixing_bootstrap, iterations
        ),
        "biology_conservation_asw": _interval(
            float(np.mean(biology_values)), biology_bootstrap, iterations
        ),
    }


def _interval(estimate: float, values: np.ndarray, iterations: int):
    return {
        "estimate": estimate,
        "lower": float(np.quantile(values, 0.025)),
        "upper": float(np.quantile(values, 0.975)),
        "confidence_level": 0.95,
        "bootstrap_iterations": iterations,
        "method": "cell-level bootstrap over precomputed silhouette samples",
    }
