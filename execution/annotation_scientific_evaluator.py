from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support

from core.execution_models import (
    AnnotationScientificEvaluationResult,
    AnnotationSplitArtifact,
    BootstrapInterval,
    ExecutionRun,
)
from execution.annotation_scientific_dataset import scientific_pilot_limitations


class AnnotationScientificEvaluator:
    """Evaluate frozen annotation predictions without tuning on evaluation labels."""

    def evaluate(
        self,
        *,
        run: ExecutionRun,
        split: AnnotationSplitArtifact,
        predictions_path: Path,
        bootstrap_iterations: int = 500,
        bootstrap_seed: int = 68_500,
    ) -> AnnotationScientificEvaluationResult:
        if run.execution_purpose != "scientific_pilot":
            raise ValueError("annotation scientific metrics require a scientific-pilot run")
        if run.status != "succeeded" or run.exit_code != 0:
            raise ValueError("failed execution cannot enter scientific evaluation")
        if bootstrap_iterations < 1:
            raise ValueError("bootstrap iterations must be positive")
        source_path = Path(split.path).resolve(strict=True)
        if _sha256(source_path) != split.probe_hash:
            raise ValueError("annotation split hash mismatch")
        adata = ad.read_h5ad(source_path)
        if "ground_truth_cell_type" not in adata.obs:
            raise ValueError("annotation split has no frozen ground-truth labels")
        predictions = pd.read_csv(predictions_path, sep="\t", dtype=str)
        if not {"cell_id", "predicted_label"} <= set(predictions):
            raise ValueError("annotation prediction schema is invalid")
        expected_ids = adata.obs_names.astype(str).tolist()
        if predictions["cell_id"].tolist() != expected_ids:
            raise ValueError("annotation prediction cell order mismatch")

        truth = adata.obs["ground_truth_cell_type"].astype(str).to_numpy()
        predicted = predictions["predicted_label"].astype(str).to_numpy()
        labels = sorted(set(truth) | set(predicted))
        metrics = _metrics(truth, predicted)
        precision, recall, class_f1, support = precision_recall_fscore_support(
            truth,
            predicted,
            labels=labels,
            zero_division=0,
        )
        per_class = {
            label: {
                "precision": float(precision[index]),
                "recall": float(recall[index]),
                "f1": float(class_f1[index]),
                "support": float(support[index]),
            }
            for index, label in enumerate(labels)
        }
        matrix = confusion_matrix(truth, predicted, labels=labels)
        nested_matrix = {
            true_label: {
                predicted_label: int(matrix[row_index, column_index])
                for column_index, predicted_label in enumerate(labels)
            }
            for row_index, true_label in enumerate(labels)
        }
        bootstrap = _bootstrap_metrics(
            truth,
            predicted,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )
        fixture = dict(adata.uns.get("sckg_fixture") or {})
        if fixture.get("label_mapping_digest") != split.label_mapping_digest:
            raise ValueError("annotation split label mapping binding mismatch")
        return AnnotationScientificEvaluationResult(
            evaluation_id=f"annotation-eval-{run.run_id}",
            run_id=run.run_id,
            tool_name=run.tool_name,
            tool_version=run.tool_version,
            configuration_hash=_configuration_hash(run.parameters),
            split_role=split.split_role,
            split_hash=split.probe_hash,
            label_mapping_digest=split.label_mapping_digest,
            n_cells=len(truth),
            metrics=metrics,
            per_class_metrics=per_class,
            confusion_matrix=nested_matrix,
            bootstrap_ci=bootstrap,
            runtime_seconds=run.runtime_seconds,
            peak_memory_mb=run.peak_memory_mb,
            limitations=scientific_pilot_limitations(),
        )


def _metrics(truth: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    recalls = [
        float(np.mean(predicted[truth == label] == label))
        for label in sorted(set(truth))
    ]
    return {
        "macro_f1": float(f1_score(truth, predicted, average="macro", zero_division=0)),
        "balanced_accuracy": float(np.mean(recalls)),
        "unknown_rate": float(np.mean(predicted == "unknown")),
    }


def _bootstrap_metrics(
    truth: np.ndarray,
    predicted: np.ndarray,
    *,
    iterations: int,
    seed: int,
) -> dict[str, BootstrapInterval]:
    rng = np.random.default_rng(seed)
    values: dict[str, list[float]] = {
        "macro_f1": [],
        "balanced_accuracy": [],
    }
    labels = sorted(set(truth))
    indices_by_label = {
        label: np.flatnonzero(truth == label)
        for label in labels
    }
    for _ in range(iterations):
        sampled = np.concatenate(
            [
                rng.choice(indices, size=len(indices), replace=True)
                for indices in indices_by_label.values()
            ]
        )
        sample_metrics = _metrics(truth[sampled], predicted[sampled])
        for metric_name in values:
            values[metric_name].append(sample_metrics[metric_name])
    estimates = _metrics(truth, predicted)
    return {
        metric_name: BootstrapInterval(
            metric=metric_name,
            estimate=estimates[metric_name],
            lower=float(np.quantile(metric_values, 0.025)),
            upper=float(np.quantile(metric_values, 0.975)),
            confidence_level=0.95,
            bootstrap_iterations=iterations,
        )
        for metric_name, metric_values in values.items()
    }


def _configuration_hash(parameters: dict) -> str:
    return hashlib.sha256(
        json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
