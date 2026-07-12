from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from core.execution_models import (
    BootstrapInterval,
    ExecutionRun,
    ScientificEvaluationResult,
)
from execution.scientific_dataset import scientific_pilot_limitations


SCIENTIFIC_BOOTSTRAP_SEED = 20260713


class ScientificEvaluator:
    def evaluate(
        self,
        *,
        run: ExecutionRun,
        configuration_hash: str,
        split_role: str,
        frozen_threshold: float | None = None,
        bootstrap_iterations: int = 500,
        bootstrap_seed: int = SCIENTIFIC_BOOTSTRAP_SEED,
        predictions_output: Path | None = None,
    ) -> ScientificEvaluationResult:
        if run.execution_purpose != "scientific_pilot":
            raise ValueError("ScientificEvaluator only accepts scientific pilot runs")
        if run.status != "succeeded":
            raise ValueError("cannot scientifically evaluate a failed execution run")
        result_path = run.artifact_paths.get("doublet_results.tsv")
        if not result_path:
            raise ValueError("doublet result artifact missing")
        obs_ids, scores, labels = _read_predictions(Path(result_path))
        if len(np.unique(labels)) != 2:
            raise ValueError("scientific evaluation requires both singlets and doublets")
        if split_role == "development":
            threshold = (
                _select_f1_threshold(scores, labels)
                if frozen_threshold is None
                else float(frozen_threshold)
            )
            threshold_source = "development_optimized"
        elif split_role == "evaluation":
            if frozen_threshold is None:
                raise ValueError("evaluation requires threshold frozen on development")
            threshold = float(frozen_threshold)
            threshold_source = "frozen_from_development"
        else:
            raise ValueError("split_role must be development or evaluation")

        metrics, matrix = _metrics(scores, labels, threshold)
        intervals = _bootstrap_intervals(
            scores,
            labels,
            threshold=threshold,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )
        if predictions_output is not None:
            predictions_output.parent.mkdir(parents=True, exist_ok=True)
            calls = scores >= threshold
            with predictions_output.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, delimiter="\t")
                writer.writerow(
                    ["obs_id", "doublet_score", "gold_doublet", "frozen_threshold", "predicted_doublet"]
                )
                for obs_id, score, label, call in zip(obs_ids, scores, labels, calls):
                    writer.writerow(
                        [obs_id, repr(float(score)), bool(label), repr(threshold), bool(call)]
                    )
        return ScientificEvaluationResult(
            evaluation_id="scientific-" + hashlib.sha256(
                f"{run.run_id}:{configuration_hash}:{threshold}".encode("utf-8")
            ).hexdigest()[:16],
            run_id=run.run_id,
            configuration_hash=configuration_hash,
            split_role=split_role,
            threshold=threshold,
            threshold_source=threshold_source,
            metrics=metrics,
            confusion_matrix=matrix,
            bootstrap_ci=intervals,
            runtime_seconds=run.runtime_seconds,
            peak_memory_mb=run.peak_memory_mb,
            limitations=scientific_pilot_limitations(),
        )


def _read_predictions(path: Path) -> tuple[list[str], np.ndarray, np.ndarray]:
    obs_ids: list[str] = []
    scores: list[float] = []
    labels: list[bool] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            obs_ids.append(row["obs_id"])
            scores.append(float(row["doublet_score"]))
            label = row["ground_truth_doublet"].strip().lower()
            if label not in {"true", "false"}:
                raise ValueError("ground truth label is not boolean")
            labels.append(label == "true")
    score_array = np.asarray(scores, dtype=np.float64)
    label_array = np.asarray(labels, dtype=bool)
    if not len(score_array) or np.any(~np.isfinite(score_array)):
        raise ValueError("scientific prediction scores are empty or non-finite")
    return obs_ids, score_array, label_array


def _select_f1_threshold(scores: np.ndarray, labels: np.ndarray) -> float:
    candidates = np.unique(scores)
    best = None
    for threshold in candidates:
        calls = scores >= threshold
        f1 = f1_score(labels, calls, zero_division=0)
        precision = precision_score(labels, calls, zero_division=0)
        key = (f1, precision, float(threshold))
        if best is None or key > best[0]:
            best = (key, float(threshold))
    if best is None:
        raise ValueError("no threshold candidates available")
    return best[1]


def _metrics(
    scores: np.ndarray, labels: np.ndarray, threshold: float
) -> tuple[dict[str, float], dict[str, int]]:
    calls = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(labels, calls, labels=[False, True]).ravel()
    metrics = {
        "auprc": float(average_precision_score(labels, scores)),
        "auroc": float(roc_auc_score(labels, scores)),
        "precision": float(precision_score(labels, calls, zero_division=0)),
        "recall": float(recall_score(labels, calls, zero_division=0)),
        "f1": float(f1_score(labels, calls, zero_division=0)),
    }
    matrix = {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}
    return metrics, matrix


def _bootstrap_intervals(
    scores: np.ndarray,
    labels: np.ndarray,
    *,
    threshold: float,
    iterations: int,
    seed: int,
) -> dict[str, BootstrapInterval]:
    if iterations <= 0:
        raise ValueError("bootstrap iterations must be positive")
    rng = np.random.default_rng(seed)
    negative = np.flatnonzero(~labels)
    positive = np.flatnonzero(labels)
    values = {name: [] for name in ("auprc", "auroc", "precision", "recall", "f1")}
    for _ in range(iterations):
        indices = np.concatenate(
            [
                rng.choice(negative, size=len(negative), replace=True),
                rng.choice(positive, size=len(positive), replace=True),
            ]
        )
        sampled_metrics, _ = _metrics(scores[indices], labels[indices], threshold)
        for name, value in sampled_metrics.items():
            values[name].append(value)
    estimates, _ = _metrics(scores, labels, threshold)
    return {
        name: BootstrapInterval(
            metric=name,
            estimate=estimates[name],
            lower=float(np.quantile(metric_values, 0.025)),
            upper=float(np.quantile(metric_values, 0.975)),
            confidence_level=0.95,
            bootstrap_iterations=iterations,
        )
        for name, metric_values in values.items()
    }
