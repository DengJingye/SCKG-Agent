from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Optional

from core.execution_models import ExecutionRun, ToolContract, ValidationResult
from core.tool_contract_registry import ToolContractRegistry


REQUIRED_ARTIFACTS = {
    "doublet_results.tsv",
    "parameters.json",
    "result_metadata.json",
}


class ScDblFinderValidator:
    """Validate scDblFinder artifacts using the shared ValidationResult schema."""

    def __init__(self, contract: Optional[ToolContract] = None) -> None:
        self.contract = contract

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

        mismatches = []
        for name, path_text in run.artifact_paths.items():
            path = Path(path_text)
            if not path.is_file() or run.artifact_hashes.get(name) != _sha256(path):
                mismatches.append(name)
        artifact_checks["artifact_hashes_valid"] = not mismatches
        artifact_checks["hash_mismatches"] = sorted(mismatches)
        if mismatches:
            failures.append("artifact_hash_mismatch")

        input_path, expected_input_hash = _controlled_input_reference(run)
        input_hash_valid = bool(
            input_path
            and input_path.is_file()
            and _sha256(input_path) == run.input_hash == expected_input_hash
        )
        artifact_checks["input_hash_valid"] = input_hash_valid
        if not input_hash_valid:
            failures.append("input_hash_mismatch")

        expected_ids: list[str] = []
        truth: list[bool] = []
        if input_path and input_path.is_file():
            try:
                import anndata as ad

                adata = ad.read_h5ad(input_path, backed="r")
                expected_ids = [str(item) for item in adata.obs_names]
                if "ground_truth_doublet" in adata.obs:
                    truth = [bool(item) for item in adata.obs["ground_truth_doublet"]]
                adata.file.close()
            except Exception as exc:
                failures.append(f"input_read_failed:{type(exc).__name__}")

        rows: list[dict[str, str]] = []
        result_path = run.artifact_paths.get("doublet_results.tsv")
        if result_path and Path(result_path).is_file():
            with Path(result_path).open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
        observed_ids = [row.get("cell_id", "") for row in rows]
        order_matches = (
            len(rows) == expected_cells
            and len(expected_ids) == expected_cells
            and observed_ids == expected_ids
        )
        sanity_checks["cell_id_count"] = len(observed_ids)
        sanity_checks["cell_id_order_matches"] = order_matches
        if not order_matches:
            failures.append("cell_id_order_mismatch")

        scores: list[float] = []
        predicted: list[bool] = []
        invalid_scores = 0
        invalid_labels = 0
        for row in rows:
            try:
                score = float(row.get("doublet_score", "nan"))
                if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                    invalid_scores += 1
                scores.append(score)
            except (TypeError, ValueError):
                invalid_scores += 1
            label = _parse_bool(row.get("predicted_doublet"))
            if label is None:
                invalid_labels += 1
            else:
                predicted.append(label)
        sanity_checks["scores_finite_and_in_range"] = invalid_scores == 0
        sanity_checks["predicted_labels_boolean"] = invalid_labels == 0
        if invalid_scores:
            failures.append("score_non_finite_or_out_of_range")
        if invalid_labels:
            failures.append("predicted_label_type_invalid")

        parameters = _read_json(run.artifact_paths.get("parameters.json"))
        parameters_match = parameters == run.parameters
        if self.contract is not None:
            try:
                validated = ToolContractRegistry().validate_parameters(
                    self.contract, parameters
                )
                parameters_match = parameters_match and validated == run.parameters
            except ValueError:
                parameters_match = False
        sanity_checks["parameters_match_contract_and_run"] = parameters_match
        if not parameters_match:
            failures.append("parameter_snapshot_mismatch")

        metadata = _read_json(run.artifact_paths.get("result_metadata.json"))
        is_scientific = run.execution_purpose == "scientific_pilot"
        metadata_checks = {
            "scdblfinder_actually_executed": metadata.get(
                "scdblfinder_actually_executed"
            )
            is True,
            "qualification_mode": metadata.get("qualification_mode") is True,
            "user_data_not_used": metadata.get("user_data_used") is False,
            "input_hash_matches": metadata.get("input_hash") == run.input_hash,
        }
        if is_scientific:
            metadata_checks.update(
                {
                    "public_dataset": metadata.get("public_dataset") is True,
                    "accession_allowlisted": metadata.get("accession")
                    == "GSE108313",
                    "non_synthetic": metadata.get("synthetic_fixture") is False,
                }
            )
        else:
            metadata_checks["synthetic_fixture"] = (
                metadata.get("synthetic_fixture") is True
            )
        if self.contract is not None and self.contract.tool_version != "not_installed":
            metadata_checks["tool_version_matches"] = (
                metadata.get("scdblfinder_version") == self.contract.tool_version
            )
        sanity_checks["metadata_checks"] = metadata_checks
        if not all(metadata_checks.values()):
            failures.append("qualification_metadata_invalid")

        if len(scores) == len(predicted) == len(truth) == expected_cells:
            tp = sum(call and actual for call, actual in zip(predicted, truth))
            fp = sum(call and not actual for call, actual in zip(predicted, truth))
            fn = sum(not call and actual for call, actual in zip(predicted, truth))
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            prefix = (
                "scientific_pilot" if is_scientific else "synthetic_engineering"
            )
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
        warnings.append(
            "scientific pilot metrics are dataset-specific and not a universal performance claim"
            if is_scientific
            else "synthetic engineering metrics do not establish biological performance"
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
            eligible_for_candidate_aggregation=not unique_failures,
            metric_authority=(
                "scientific_pilot_metric"
                if is_scientific
                else "synthetic_engineering_metric"
            ),
            validation_version="scdblfinder-validator-v1",
        )


def _controlled_input_reference(run: ExecutionRun) -> tuple[Optional[Path], str]:
    worker_request = Path(run.stdout_path).parent / "worker_request.json"
    payload = _read_json(str(worker_request))
    input_text = payload.get("input_path")
    return (Path(input_text) if isinstance(input_text, str) else None), str(
        payload.get("expected_input_hash", "")
    )


def _read_json(path_text: Optional[str]) -> dict:
    if not path_text:
        return {}
    path = Path(path_text)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_bool(value: object) -> Optional[bool]:
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
