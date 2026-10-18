from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score

from core.execution_models import ExecutionRun, ToolContract, ValidationResult


REQUIRED_ARTIFACTS = {
    "integrated_embedding.tsv",
    "parameters.json",
    "result_metadata.json",
}


class IntegrationValidator:
    """Validate common integration artifacts and compute task-aware metrics."""

    def validate(
        self,
        run: ExecutionRun,
        *,
        expected_cells: int,
        expected_input_path: str,
        contract: ToolContract,
    ) -> ValidationResult:
        failures: list[str] = []
        warnings: list[str] = []
        artifact_checks: dict[str, object] = {}
        task_metrics: dict[str, float] = {}

        if run.status != "succeeded" or run.exit_code != 0:
            failures.append("execution_not_successful")
        present = REQUIRED_ARTIFACTS <= set(run.artifact_paths)
        artifact_checks["required_artifacts_present"] = present
        if not present:
            failures.append("missing_required_artifact")

        for name, path_text in run.artifact_paths.items():
            path = Path(path_text)
            expected_hash = run.artifact_hashes.get(name)
            if expected_hash is None or not path.is_file() or _sha256(path) != expected_hash:
                failures.append("artifact_hash_mismatch")
                break
        artifact_checks["artifact_hashes_valid"] = "artifact_hash_mismatch" not in failures

        if present and not failures:
            try:
                source = ad.read_h5ad(expected_input_path)
                table = pd.read_csv(
                    run.artifact_paths["integrated_embedding.tsv"], sep="\t", dtype={"cell_id": str}
                )
                metadata = json.loads(
                    Path(run.artifact_paths["result_metadata.json"]).read_text(encoding="utf-8")
                )
                snapshot = json.loads(
                    Path(run.artifact_paths["parameters.json"]).read_text(encoding="utf-8")
                )
                _validate_schema(
                    source=source,
                    table=table,
                    expected_cells=expected_cells,
                    failures=failures,
                )
                if metadata.get("input_hash") != run.input_hash:
                    failures.append("input_hash_mismatch")
                if metadata.get("tool_name") != contract.tool_name:
                    failures.append("tool_metadata_mismatch")
                if metadata.get("tool_version") != contract.tool_version:
                    failures.append("tool_version_mismatch")
                if snapshot.get("parameters") != run.parameters:
                    failures.append("parameter_snapshot_mismatch")
                if snapshot.get("execution_seed") != run.execution_seed:
                    failures.append("execution_seed_mismatch")
                if not failures:
                    embedding_columns = [
                        name for name in table.columns if name.startswith("integrated_")
                    ]
                    embedding = table[embedding_columns].to_numpy(dtype=float)
                    task_metrics = _integration_metrics(
                        embedding,
                        table["batch"].astype(str).to_numpy(),
                        table["cell_type"].astype(str).to_numpy(),
                    )
                    if task_metrics["biology_conservation_asw"] < 0.5:
                        warnings.append("biology_conservation_below_decision_floor")
                    artifact_checks.update(
                        {
                            "cell_count_matches": len(table) == expected_cells,
                            "cell_order_matches": table["cell_id"].tolist()
                            == source.obs_names.astype(str).tolist(),
                            "embedding_dimensions": len(embedding_columns),
                            "embedding_finite": bool(np.isfinite(embedding).all()),
                            "embedding_nonzero_variance": bool(
                                np.any(np.var(embedding, axis=0) > 1e-12)
                            ),
                        }
                    )
            except Exception as exc:
                failures.append(f"validation_exception:{type(exc).__name__}:{exc}")

        passed = not failures
        return ValidationResult(
            validation_id=f"integration-validation-{run.run_id}",
            run_id=run.run_id,
            passed=passed,
            artifact_checks=artifact_checks,
            task_metrics=task_metrics,
            sanity_checks={
                "biology_collapse_floor": 0.5,
                "biology_collapse_detected": bool(
                    task_metrics and task_metrics.get("biology_conservation_asw", 0.0) < 0.5
                ),
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
            validation_version="integration-validator-v1",
        )


def _validate_schema(*, source, table, expected_cells: int, failures: list[str]) -> None:
    required = {"cell_id", "batch", "cell_type"}
    embedding_columns = [name for name in table.columns if name.startswith("integrated_")]
    if not required <= set(table.columns) or len(embedding_columns) < 2:
        failures.append("artifact_schema_invalid")
        return
    if len(table) != expected_cells or len(table) != source.n_obs:
        failures.append("cell_count_mismatch")
    if table["cell_id"].duplicated().any():
        failures.append("duplicate_cell_id")
    if table["cell_id"].tolist() != source.obs_names.astype(str).tolist():
        failures.append("cell_order_mismatch")
    expected_batches = source.obs["batch"].astype(str).tolist()
    if table["batch"].astype(str).tolist() != expected_batches:
        failures.append("batch_label_mismatch")
    if "cell_type" in source.obs:
        expected_labels = source.obs["cell_type"].astype(str).tolist()
        if table["cell_type"].astype(str).tolist() != expected_labels:
            failures.append("biology_label_mismatch")
    values = table[embedding_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        failures.append("non_finite_embedding")
    elif not np.any(np.var(values, axis=0) > 1e-12):
        failures.append("collapsed_embedding")


def _integration_metrics(
    embedding: np.ndarray,
    batches: np.ndarray,
    labels: np.ndarray,
) -> dict[str, float]:
    biology_raw = float(silhouette_score(embedding, labels))
    biology = float(np.clip((biology_raw + 1.0) / 2.0, 0.0, 1.0))
    mixing_scores: list[float] = []
    for label in sorted(set(labels.tolist())):
        mask = labels == label
        subset_batches = batches[mask]
        batch_count = len(set(subset_batches.tolist()))
        if mask.sum() < 4 or batch_count < 2 or batch_count >= mask.sum():
            continue
        batch_raw = float(silhouette_score(embedding[mask], subset_batches))
        mixing_scores.append(float(np.clip(1.0 - abs(batch_raw), 0.0, 1.0)))
    if not mixing_scores:
        raise ValueError("batch mixing ASW requires labels spanning multiple batches")
    mixing = float(np.mean(mixing_scores))
    return {
        "batch_mixing_asw": mixing,
        "biology_conservation_asw": biology,
        "integration_harmonic_mean": (
            2.0 * mixing * biology / (mixing + biology) if mixing + biology else 0.0
        ),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
