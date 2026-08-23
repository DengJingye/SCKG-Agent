from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, f1_score

from core.execution_models import (
    AnnotationReferenceManifest,
    AnnotationValidationResult,
    ExecutionRun,
    ToolContract,
)


REQUIRED_ARTIFACTS = {
    "predicted_labels.tsv",
    "annotation_scores.tsv",
    "parameters.json",
    "result_metadata.json",
}


class AnnotationValidator:
    """Shared schema, identity, reference and engineering-metric validation."""

    def validate(
        self,
        run: ExecutionRun,
        *,
        expected_cells: int,
        expected_input_path: str,
        contract: ToolContract,
        reference: AnnotationReferenceManifest,
    ) -> AnnotationValidationResult:
        failures: list[str] = []
        warnings: list[str] = []
        checks: dict[str, object] = {}
        metrics: dict[str, float] = {}
        if run.status != "succeeded" or run.exit_code != 0:
            failures.append("execution_not_successful")
        present = REQUIRED_ARTIFACTS <= set(run.artifact_paths)
        checks["required_artifacts_present"] = present
        if not present:
            failures.append("missing_required_artifact")

        for name, path_text in run.artifact_paths.items():
            path = Path(path_text)
            expected_hash = run.artifact_hashes.get(name)
            if expected_hash is None or not path.is_file() or _sha256(path) != expected_hash:
                failures.append("artifact_hash_mismatch")
                break
        checks["artifact_hashes_valid"] = "artifact_hash_mismatch" not in failures

        if present and not failures:
            try:
                source = ad.read_h5ad(expected_input_path)
                labels = pd.read_csv(
                    run.artifact_paths["predicted_labels.tsv"],
                    sep="\t",
                    dtype={"cell_id": str, "predicted_label": str},
                )
                scores = pd.read_csv(
                    run.artifact_paths["annotation_scores.tsv"],
                    sep="\t",
                    dtype={"cell_id": str},
                )
                snapshot = json.loads(
                    Path(run.artifact_paths["parameters.json"]).read_text(
                        encoding="utf-8"
                    )
                )
                metadata = json.loads(
                    Path(run.artifact_paths["result_metadata.json"]).read_text(
                        encoding="utf-8"
                    )
                )
                _validate_schema(
                    source=source,
                    labels=labels,
                    scores=scores,
                    expected_cells=expected_cells,
                    failures=failures,
                )
                if metadata.get("input_hash") != run.input_hash:
                    failures.append("input_hash_mismatch")
                if metadata.get("tool_name") != contract.tool_name:
                    failures.append("tool_metadata_mismatch")
                if metadata.get("tool_version") != contract.tool_version:
                    failures.append("tool_version_mismatch")
                if metadata.get("reference_id") != reference.reference_id:
                    failures.append("reference_id_mismatch")
                if metadata.get("reference_digest") != reference.sha256:
                    failures.append("reference_digest_mismatch")
                if metadata.get("runtime_network_used") is not False:
                    failures.append("runtime_network_boundary_violation")
                if snapshot.get("parameters") != run.parameters:
                    failures.append("parameter_snapshot_mismatch")
                if snapshot.get("reference_digest") != reference.sha256:
                    failures.append("parameter_reference_digest_mismatch")
                if not failures:
                    unknown = labels["unknown"].map(_as_bool).to_numpy(dtype=bool)
                    metrics["reject_rate"] = float(np.mean(unknown))
                    if "ground_truth_cell_type" in source.obs:
                        truth = source.obs["ground_truth_cell_type"].astype(str).to_numpy()
                        predicted = labels["predicted_label"].astype(str).to_numpy()
                        metrics.update(
                            {
                                "macro_f1": float(
                                    f1_score(
                                        truth,
                                        predicted,
                                        average="macro",
                                        zero_division=0,
                                    )
                                ),
                                "balanced_accuracy": float(
                                    balanced_accuracy_score(truth, predicted)
                                ),
                                "label_coverage": float(np.mean(~unknown)),
                            }
                        )
                    else:
                        warnings.append("ground_truth_labels_unavailable")
                checks.update(
                    {
                        "cell_count_matches": len(labels) == expected_cells,
                        "cell_order_matches": labels["cell_id"].tolist()
                        == source.obs_names.astype(str).tolist(),
                        "score_cell_order_matches": scores["cell_id"].tolist()
                        == source.obs_names.astype(str).tolist(),
                        "labels_nonempty": bool(
                            labels["predicted_label"].astype(str).str.len().gt(0).all()
                        ),
                        "scores_finite": bool(
                            np.isfinite(
                                scores.drop(columns=["cell_id"]).to_numpy(dtype=float)
                            ).all()
                        ),
                    }
                )
            except Exception as exc:
                failures.append(f"validation_exception:{type(exc).__name__}:{exc}")

        passed = not failures
        return AnnotationValidationResult(
            validation_id=f"annotation-validation-{run.run_id}",
            run_id=run.run_id,
            passed=passed,
            artifact_checks=checks,
            task_metrics=metrics,
            sanity_checks={
                "reference_digest_bound": reference.sha256,
                "raw_scores_compared_across_tools": False,
            },
            resource_metrics={
                "runtime_seconds": run.runtime_seconds,
                "peak_memory_mb": run.peak_memory_mb,
            },
            warnings=warnings,
            failures=sorted(set(failures)),
            eligible_for_candidate_aggregation=passed,
            repairable=False,
            metric_authority=(
                "scientific_pilot_metric"
                if run.execution_purpose == "scientific_pilot"
                else "synthetic_engineering_metric"
            ),
        )


def _validate_schema(
    *,
    source,
    labels: pd.DataFrame,
    scores: pd.DataFrame,
    expected_cells: int,
    failures: list[str],
) -> None:
    if not {"cell_id", "predicted_label", "unknown"} <= set(labels):
        failures.append("label_artifact_schema_invalid")
        return
    if "cell_id" not in scores or len(scores.columns) < 2:
        failures.append("score_artifact_schema_invalid")
        return
    if len(labels) != expected_cells or len(scores) != expected_cells:
        failures.append("cell_count_mismatch")
    expected_order = source.obs_names.astype(str).tolist()
    if labels["cell_id"].tolist() != expected_order:
        failures.append("cell_order_mismatch")
    if scores["cell_id"].tolist() != expected_order:
        failures.append("score_cell_order_mismatch")
    if labels["cell_id"].duplicated().any():
        failures.append("duplicate_cell_id")
    if labels["predicted_label"].isna().any() or labels["predicted_label"].eq("").any():
        failures.append("invalid_predicted_label")
    values = scores.drop(columns=["cell_id"]).to_numpy(dtype=float)
    if not values.size or not np.isfinite(values).all():
        failures.append("score_non_finite")


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ValueError(f"invalid unknown label value: {value}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
