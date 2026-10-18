from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

from core.execution_models import ExecutionRun, ValidationResult


REQUIRED_ARTIFACTS = {
    "doublet_results.tsv",
    "parameters.json",
    "result_metadata.json",
}


class DoubletValidator:
    """Validate Scrublet qualification outputs without biological claims."""

    def validate(self, run: ExecutionRun, *, expected_cells: int) -> ValidationResult:
        failures: list[str] = []
        warnings: list[str] = []
        artifact_checks: dict[str, object] = {}
        sanity_checks: dict[str, object] = {}
        task_metrics: dict[str, object] = {}

        if run.exit_code != 0 or run.status != "succeeded":
            failures.append("execution_not_successful")
        missing = sorted(REQUIRED_ARTIFACTS - set(run.artifact_paths))
        artifact_checks["required_artifacts_present"] = not missing
        artifact_checks["missing_artifacts"] = missing
        if missing:
            failures.append("required_artifact_missing")

        hash_mismatches: list[str] = []
        for name, path_text in run.artifact_paths.items():
            path = Path(path_text)
            expected_hash = run.artifact_hashes.get(name)
            if not path.is_file() or expected_hash != _sha256(path):
                hash_mismatches.append(name)
        artifact_checks["artifact_hashes_valid"] = not hash_mismatches
        artifact_checks["hash_mismatches"] = hash_mismatches
        if hash_mismatches:
            failures.append("artifact_hash_mismatch")

        rows: list[dict[str, str]] = []
        result_path = run.artifact_paths.get("doublet_results.tsv")
        if result_path and Path(result_path).is_file():
            with Path(result_path).open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
        row_count_matches = len(rows) == expected_cells
        sanity_checks["row_count"] = len(rows)
        sanity_checks["row_count_matches_cells"] = row_count_matches
        if not row_count_matches:
            failures.append("score_label_count_mismatch")

        scores: list[float] = []
        predicted: list[bool] = []
        truth: list[bool] = []
        invalid_labels = 0
        invalid_truth = 0
        invalid_scores = 0
        for row in rows:
            try:
                score = float(row.get("doublet_score", "nan"))
                if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                    invalid_scores += 1
                scores.append(score)
            except (TypeError, ValueError):
                invalid_scores += 1
            label = _parse_bool(row.get("predicted_doublet"))
            label_truth = _parse_bool(row.get("ground_truth_doublet"))
            if label is None:
                invalid_labels += 1
            else:
                predicted.append(label)
            if label_truth is None:
                invalid_truth += 1
            else:
                truth.append(label_truth)

        metadata: dict[str, object] = {}
        metadata_path = run.artifact_paths.get("result_metadata.json")
        if metadata_path and Path(metadata_path).is_file():
            try:
                metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                failures.append("result_metadata_invalid")
        is_scientific = metadata.get("execution_purpose") == "scientific_pilot"
        is_preview = metadata.get("execution_purpose") == "representative_preview"

        sanity_checks.update(
            {
                "scores_finite_and_in_range": invalid_scores == 0,
                "predicted_labels_boolean": invalid_labels == 0,
                "ground_truth_labels_boolean": (
                    "not_applicable" if is_preview else invalid_truth == 0
                ),
            }
        )
        if invalid_scores:
            failures.append("score_non_finite_or_out_of_range")
        if invalid_labels:
            failures.append("predicted_label_type_invalid")
        if invalid_truth and not is_preview:
            failures.append("ground_truth_label_type_invalid")
        metadata_checks = {
            "scrublet_actually_executed": metadata.get("scrublet_actually_executed") is True,
        }
        if is_preview:
            metadata_checks.update(
                {
                    "user_data_provenance_retained": metadata.get("user_data_used") is True,
                    "qualification_mode_false": metadata.get("qualification_mode") is False,
                    "preview_only": metadata.get("preview_only") is True,
                    "scientific_claim_forbidden": metadata.get("scientific_claim_allowed") is False,
                    "non_synthetic": metadata.get("synthetic_fixture") is False,
                    "non_public_dataset": metadata.get("public_dataset") is False,
                }
            )
        elif is_scientific:
            metadata_checks.update(
                {
                    "user_data_not_used": metadata.get("user_data_used") is False,
                    "qualification_mode": metadata.get("qualification_mode") is True,
                    "public_dataset": metadata.get("public_dataset") is True,
                    "accession_allowlisted": metadata.get("accession") == "GSE108313",
                    "non_synthetic": metadata.get("synthetic_fixture") is False,
                }
            )
        else:
            metadata_checks.update(
                {
                    "user_data_not_used": metadata.get("user_data_used") is False,
                    "qualification_mode": metadata.get("qualification_mode") is True,
                    "synthetic_fixture": metadata.get("synthetic_fixture") is True,
                }
            )
        sanity_checks["metadata_checks"] = metadata_checks
        if not all(metadata_checks.values()):
            failures.append("qualification_metadata_invalid")

        if not is_preview and len(predicted) == len(truth) == expected_cells:
            tp = sum(call and actual for call, actual in zip(predicted, truth))
            fp = sum(call and not actual for call, actual in zip(predicted, truth))
            fn = sum(not call and actual for call, actual in zip(predicted, truth))
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            prefix = "scientific_pilot" if is_scientific else "synthetic_engineering"
            task_metrics.update(
                {
                    "predicted_doublet_call_rate": sum(predicted) / expected_cells,
                    f"{prefix}_ground_truth_rate": sum(truth) / expected_cells,
                    f"{prefix}_auprc": _average_precision(truth, scores),
                    f"{prefix}_precision": precision,
                    f"{prefix}_recall": recall,
                    f"{prefix}_f1": f1,
                }
            )

        resource_metrics = {
            "runtime_seconds": run.runtime_seconds,
            "runtime_observed": run.runtime_seconds >= 0.0,
            "peak_memory_mb": run.peak_memory_mb,
            "memory_observed": run.peak_memory_mb is not None,
            "memory_enforcement": run.memory_enforcement,
        }
        if run.peak_memory_mb is None:
            failures.append("memory_observation_missing")
        if is_preview:
            preview_plot = run.artifact_paths.get("doublet_score_histogram.png")
            preview_plot_valid = bool(
                preview_plot
                and Path(preview_plot).is_file()
                and run.artifact_hashes.get("doublet_score_histogram.png")
                == _sha256(Path(preview_plot))
            )
            artifact_checks["preview_histogram_present_and_hashed"] = preview_plot_valid
            if not preview_plot_valid:
                failures.append("preview_histogram_missing_or_invalid")
            task_metrics["preview_predicted_doublet_call_rate"] = (
                sum(predicted) / expected_cells if len(predicted) == expected_cells else None
            )
            warnings.append(
                "preview engineering checks do not establish full-data or biological performance"
            )
        elif is_scientific:
            warnings.append(
                "scientific pilot metrics are dataset-specific and not a universal performance claim"
            )
        else:
            warnings.append(
                "synthetic engineering metrics do not establish biological performance"
            )
        unique_failures = sorted(set(failures))
        return ValidationResult(
            validation_id=f"validation-{run.run_id}",
            run_id=run.run_id,
            passed=not unique_failures,
            artifact_checks=artifact_checks,
            task_metrics=task_metrics,
            sanity_checks=sanity_checks,
            resource_metrics=resource_metrics,
            warnings=warnings,
            failures=unique_failures,
            metric_authority=(
                "preview_engineering_metric"
                if is_preview
                else (
                    "scientific_pilot_metric"
                    if is_scientific
                    else "synthetic_engineering_metric"
                )
            ),
            validation_version=(
                "doublet-preview-validator-v1"
                if is_preview
                else "doublet-validator-v1"
            ),
        )


def _parse_bool(value: object) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _average_precision(truth: list[bool], scores: list[float]) -> float:
    positives = sum(truth)
    if positives == 0:
        return 0.0
    ranked = sorted(zip(scores, truth), key=lambda item: item[0], reverse=True)
    true_seen = 0
    precision_sum = 0.0
    for rank, (_, actual) in enumerate(ranked, start=1):
        if actual:
            true_seen += 1
            precision_sum += true_seen / rank
    return precision_sum / positives


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
