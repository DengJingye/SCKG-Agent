from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

import anndata as ad
import numpy as np

from core.execution_models import ExecutionRun, ValidationResult


class ValidationPrimitive(Protocol):
    primitive_id: str

    def validate(self, run: ExecutionRun) -> tuple[bool, dict[str, Any], str | None]: ...


class ScientificValidator(Protocol):
    validator_id: str

    def validate(self, run: ExecutionRun) -> tuple[list[str], dict[str, Any], list[str]]: ...


class RequiredArtifactsPrimitive:
    primitive_id = "required_artifact"

    def __init__(self, required: set[str]) -> None:
        self.required = set(required)

    def validate(self, run: ExecutionRun) -> tuple[bool, dict[str, Any], str | None]:
        missing = sorted(self.required - set(run.artifact_paths))
        return not missing, {"missing": missing}, "required_artifact_missing" if missing else None


class ArtifactHashPrimitive:
    primitive_id = "hash"

    def validate(self, run: ExecutionRun) -> tuple[bool, dict[str, Any], str | None]:
        mismatches = []
        for name, path_text in run.artifact_paths.items():
            path = Path(path_text)
            if not path.is_file() or run.artifact_hashes.get(name) != _sha256(path):
                mismatches.append(name)
        return not mismatches, {"mismatches": mismatches}, "artifact_hash_mismatch" if mismatches else None


class ExecutionSuccessPrimitive:
    primitive_id = "execution_success"

    def validate(self, run: ExecutionRun) -> tuple[bool, dict[str, Any], str | None]:
        passed = run.status == "succeeded" and run.exit_code == 0
        return passed, {"status": run.status, "exit_code": run.exit_code}, "execution_not_successful" if not passed else None


class ScanpyCoreScientificValidator:
    validator_id = "scanpy_core_scientific_v1"

    def validate(self, run: ExecutionRun) -> tuple[list[str], dict[str, Any], list[str]]:
        failures: list[str] = []
        warnings: list[str] = []
        checks: dict[str, Any] = {}
        output_path = run.artifact_paths.get("scanpy_core_output.h5ad")
        ledger_path = run.artifact_paths.get("representation_ledger.json")
        if not output_path or not ledger_path:
            return ["scanpy_core_artifact_missing"], checks, warnings
        try:
            adata = ad.read_h5ad(output_path)
            ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
            lineage = list(ledger.get("lineage") or [])
            lineage_by_output = {item.get("produces"): item for item in lineage}
            required_outputs = {
                "qc_metrics",
                "filtered_counts",
                "library_size_normalized",
                "log1p_normalized",
                "hvg_selection",
                "pca",
                "neighbor_graph",
                "umap",
                "cluster_labels",
                "marker_result",
            }
            lineage_hashes_valid = True
            ledger_root = Path(ledger_path).parent
            for item in lineage:
                artifact = ledger_root / str(item.get("artifact") or "")
                lineage_hashes_valid = lineage_hashes_valid and bool(
                    artifact.is_file()
                    and item.get("artifact_hash") == _sha256(artifact)
                    and len(str(item.get("parameter_hash") or "")) == 64
                    and item.get("provenance")
                )
            checks.update(
                {
                    "finite_pca": "X_pca" in adata.obsm and bool(np.isfinite(adata.obsm["X_pca"]).all()),
                    "finite_umap": "X_umap" in adata.obsm and bool(np.isfinite(adata.obsm["X_umap"]).all()),
                    "neighbor_graph_present": "connectivities" in adata.obsp,
                    "cluster_labels_present": "leiden" in adata.obs,
                    "marker_result_present": "rank_genes_groups" in adata.uns,
                    "full_gene_log_preserved": "log1p" in adata.layers,
                    "marker_source": ledger.get("marker_source"),
                    "input_hash_matches": ledger.get("input_hash") == run.input_hash,
                    "cell_hash_matches": ledger.get("cell_index_hash") == _hash_names(adata.obs_names),
                    "lineage_complete": required_outputs <= set(lineage_by_output),
                    "lineage_hashes_valid": lineage_hashes_valid,
                    "umap_consumes_neighbor_graph": lineage_by_output.get("umap", {}).get("consumes") == ["neighbor_graph"],
                    "leiden_consumes_neighbor_graph": lineage_by_output.get("cluster_labels", {}).get("consumes") == ["neighbor_graph"],
                    "marker_consumes_full_gene_log": "full_gene_unscaled_log1p" in lineage_by_output.get("marker_result", {}).get("consumes", []),
                }
            )
            if not all(value for key, value in checks.items() if key != "marker_source"):
                failures.append("scanpy_scientific_state_invalid")
            if checks["marker_source"] != "full_gene_unscaled_log1p":
                failures.append("marker_source_illegal")
            if "scaled_hvg" in adata.layers and adata.layers["scaled_hvg"].shape[1] == adata.n_vars:
                warnings.append("scaled_hvg_stored_as_full_gene_layer")
        except Exception as exc:
            failures.append(f"scanpy_validation_exception:{type(exc).__name__}:{exc}")
        return failures, checks, warnings


class CapabilityValidationPipeline:
    def __init__(self, *, primitives: list[ValidationPrimitive], scientific_validator: ScientificValidator) -> None:
        self.primitives = list(primitives)
        self.scientific_validator = scientific_validator

    def validate(self, run: ExecutionRun) -> ValidationResult:
        failures: list[str] = []
        artifact_checks: dict[str, Any] = {}
        for primitive in self.primitives:
            passed, detail, failure = primitive.validate(run)
            artifact_checks[primitive.primitive_id] = {"passed": passed, **detail}
            if failure:
                failures.append(failure)
        scientific_failures, scientific_checks, warnings = self.scientific_validator.validate(run)
        failures.extend(scientific_failures)
        failures = sorted(set(failures))
        return ValidationResult(
            validation_id=f"capability-validation-{run.run_id}",
            run_id=run.run_id,
            passed=not failures,
            artifact_checks=artifact_checks,
            sanity_checks=scientific_checks,
            resource_metrics={"runtime_seconds": run.runtime_seconds, "peak_memory_mb": run.peak_memory_mb},
            warnings=warnings,
            failures=failures,
            eligible_for_candidate_aggregation=not failures,
            repairable=False,
            validation_version="capability-validation-pipeline-v1",
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_names(names) -> str:
    return hashlib.sha256("\n".join(map(str, names)).encode("utf-8")).hexdigest()
