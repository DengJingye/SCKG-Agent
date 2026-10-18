from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

import numpy as np
from scipy import sparse

if TYPE_CHECKING:
    from core.execution_models import DataProfile


PROFILE_VERSION = "anndata-profiler-v1.1-batch-integration"
MAX_SAMPLED_VALUES = 100_000
RAW_INTEGER_FRACTION = 0.995


class AnnDataProfiler:
    """Deterministically inspect AnnData metadata and matrix states without mutation."""

    def __init__(self, *, max_sampled_values: int = MAX_SAMPLED_VALUES) -> None:
        if max_sampled_values <= 0:
            raise ValueError("max_sampled_values must be positive")
        self.max_sampled_values = max_sampled_values

    def profile(
        self,
        file_path: str | Path,
        *,
        batch_key: Optional[str] = None,
        label_key: Optional[str] = None,
        explicit_count_source: Optional[str] = None,
        max_cells: Optional[int] = None,
    ) -> "DataProfile":
        from core.execution_models import DataProfile

        return DataProfile.model_validate(
            self.profile_payload(
                file_path,
                batch_key=batch_key,
                label_key=label_key,
                explicit_count_source=explicit_count_source,
                max_cells=max_cells,
            )
        )

    def profile_payload(
        self,
        file_path: str | Path,
        *,
        batch_key: Optional[str] = None,
        label_key: Optional[str] = None,
        explicit_count_source: Optional[str] = None,
        max_cells: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a JSON-compatible worker payload without requiring Pydantic."""

        path = Path(file_path).expanduser()
        redacted = _redacted_path(path)
        if path.suffix.casefold() != ".h5ad":
            return _blocked_payload(
                path,
                redacted=redacted,
                blocking_errors=["invalid_file_extension", "count_source_unresolved"],
            )
        if not path.exists():
            return _blocked_payload(
                path,
                redacted=redacted,
                blocking_errors=["input_file_missing", "count_source_unresolved"],
            )
        if not path.is_file():
            return _blocked_payload(
                path,
                redacted=redacted,
                blocking_errors=["input_path_not_file", "count_source_unresolved"],
            )

        file_hash = _sha256_file(path)
        file_size = path.stat().st_size
        try:
            import anndata as ad

            adata = ad.read_h5ad(path)
        except Exception as exc:
            return _blocked_payload(
                path,
                redacted=redacted,
                file_hash=file_hash,
                file_size_bytes=file_size,
                blocking_errors=[
                    f"anndata_read_failed:{type(exc).__name__}",
                    "count_source_unresolved",
                ],
            )

        matrix_profiles: list[Dict[str, Any]] = []
        matrix_profiles.append(self._profile_matrix("X", adata.X))
        if adata.raw is not None:
            matrix_profiles.append(self._profile_matrix("raw.X", adata.raw.X))
        for layer_name in sorted(adata.layers.keys()):
            matrix_profiles.append(
                self._profile_matrix(f"layers/{layer_name}", adata.layers[layer_name])
            )

        selected, selection_method, selection_evidence, selection_warnings = _select_count_source(
            matrix_profiles,
            explicit_count_source=explicit_count_source,
        )
        warnings = list(selection_warnings)
        blocking_errors: list[str] = []
        if adata.n_obs == 0 or adata.n_vars == 0:
            blocking_errors.append("empty_anndata")
        if selected is None:
            blocking_errors.append("count_source_unresolved")
            for profile in matrix_profiles:
                for reason in profile["blocking_reasons"]:
                    blocking_errors.append(f"{profile['matrix_id']}:{reason}")
        else:
            for profile in matrix_profiles:
                if profile["matrix_id"] != selected and profile["blocking_reasons"]:
                    warnings.append(
                        f"non_selected_matrix_issue:{profile['matrix_id']}:"
                        + ",".join(profile["blocking_reasons"])
                    )

        obs_keys = sorted(str(key) for key in adata.obs.columns)
        var_keys = sorted(str(key) for key in adata.var.columns)
        obsm_keys = sorted(str(key) for key in adata.obsm.keys())
        obsp_keys = sorted(str(key) for key in adata.obsp.keys())
        if not adata.obs_names.is_unique:
            warnings.append("duplicate_obs_names")
        if not adata.var_names.is_unique:
            warnings.append("duplicate_var_names")

        resolved_batch_key = batch_key if batch_key in adata.obs.columns else None
        batch_count: Optional[int] = None
        batch_missing_count = 0
        batch_min_cells: Optional[int] = None
        batch_max_cells: Optional[int] = None
        batch_imbalance_ratio: Optional[float] = None
        if batch_key:
            if resolved_batch_key is None:
                warnings.append(f"batch_key_not_found:{batch_key}")
            else:
                batch_values = adata.obs[batch_key]
                batch_count = int(batch_values.nunique(dropna=True))
                batch_missing_count = int(batch_values.isna().sum())
                batch_sizes = batch_values.value_counts(dropna=True)
                if not batch_sizes.empty:
                    batch_min_cells = int(batch_sizes.min())
                    batch_max_cells = int(batch_sizes.max())
                    if batch_min_cells > 0:
                        batch_imbalance_ratio = float(batch_max_cells / batch_min_cells)
        else:
            warnings.append("batch_key_not_provided")

        resolved_label_key = label_key if label_key in adata.obs.columns else None
        label_count: Optional[int] = None
        label_missing_count = 0
        if label_key and resolved_label_key is None:
            warnings.append(f"label_key_not_found:{label_key}")
        elif resolved_label_key is not None:
            label_values = adata.obs[resolved_label_key]
            label_count = int(label_values.nunique(dropna=True))
            label_missing_count = int(label_values.isna().sum())
        if max_cells is not None and adata.n_obs > max_cells:
            warnings.append(f"cell_count_exceeds_budget:{adata.n_obs}>{max_cells}")

        pca_n_components: Optional[int] = None
        pca_finite: Optional[bool] = None
        if "X_pca" in adata.obsm:
            pca = np.asarray(adata.obsm["X_pca"])
            pca_n_components = int(pca.shape[1]) if pca.ndim == 2 else 0
            pca_finite = bool(pca.ndim == 2 and pca.shape[0] == adata.n_obs and np.isfinite(pca).all())

        payload = {
            "profile_id": f"profile_{file_hash[:16]}",
            "file_path_redacted": redacted,
            "file_hash": file_hash,
            "file_size_bytes": file_size,
            "object_type": "AnnData",
            "n_cells": int(adata.n_obs),
            "n_genes": int(adata.n_vars),
            "raw_exists": adata.raw is not None,
            "layers": sorted(str(key) for key in adata.layers.keys()),
            "obsm_keys": obsm_keys,
            "obsp_keys": obsp_keys,
            "obs_keys": obs_keys,
            "var_keys": var_keys,
            "batch_key": resolved_batch_key,
            "batch_count": batch_count,
            "batch_missing_count": batch_missing_count,
            "batch_min_cells": batch_min_cells,
            "batch_max_cells": batch_max_cells,
            "batch_imbalance_ratio": batch_imbalance_ratio,
            "label_key": resolved_label_key,
            "label_count": label_count,
            "label_missing_count": label_missing_count,
            "has_pca": "X_pca" in adata.obsm,
            "pca_n_components": pca_n_components,
            "pca_finite": pca_finite,
            "has_neighbors": any(key in adata.obsp for key in ("connectivities", "distances")),
            "has_clustering": any(key in adata.obs for key in ("leiden", "louvain")),
            "matrix_profiles": matrix_profiles,
            "selected_count_source": selected,
            "count_source_selection": {
                "method": selection_method,
                "evidence": selection_evidence,
            },
            "warnings": sorted(set(warnings)),
            "blocking_errors": sorted(set(blocking_errors)),
            "profile_version": PROFILE_VERSION,
        }
        return payload

    def _profile_matrix(self, matrix_id: str, matrix: Any) -> Dict[str, Any]:
        sampled = _sample_matrix(matrix, self.max_sampled_values)
        sample_values = sampled["values"]
        finite_mask = np.isfinite(sample_values)
        finite_values = sample_values[finite_mask]
        nonzero_values = finite_values[np.abs(finite_values) > 1e-12]
        sample_size = int(sample_values.size)
        nan_fraction = _fraction(np.isnan(sample_values))
        inf_fraction = _fraction(np.isinf(sample_values))
        negative_fraction = _fraction(finite_values < 0)
        integer_fraction = (
            float(np.mean(np.isclose(nonzero_values, np.rint(nonzero_values), atol=1e-8)))
            if nonzero_values.size
            else None
        )
        min_value = float(np.min(finite_values)) if finite_values.size else None
        max_value = float(np.max(finite_values)) if finite_values.size else None
        p99 = float(np.quantile(finite_values, 0.99)) if finite_values.size else None
        state, confidence, state_reasons = _infer_matrix_state(
            finite_values=finite_values,
            nonzero_values=nonzero_values,
            integer_fraction=integer_fraction,
            min_value=min_value,
            max_value=max_value,
            negative_fraction=negative_fraction,
            nan_fraction=nan_fraction,
            inf_fraction=inf_fraction,
            p99=p99,
        )
        blocking_reasons: list[str] = []
        if matrix.shape[0] == 0 or matrix.shape[1] == 0:
            blocking_reasons.append("empty_matrix")
        if nan_fraction and nan_fraction > 0:
            blocking_reasons.append("contains_nan")
        if inf_fraction and inf_fraction > 0:
            blocking_reasons.append("contains_inf")
        if state != "raw_counts":
            blocking_reasons.append("not_validated_raw_counts")

        evidence = [
            {
                "state_name": "nonzero_integer_fraction",
                "value": integer_fraction,
                "method": sampled["method"],
                "sample_size": sample_size,
                "thresholds": {"raw_counts": RAW_INTEGER_FRACTION},
                "warnings": state_reasons,
            },
            {
                "state_name": "negative_fraction",
                "value": negative_fraction,
                "method": sampled["method"],
                "sample_size": sample_size,
                "thresholds": {"scaled_like": 0.001},
                "warnings": [],
            },
            {
                "state_name": "finite_value_check",
                "value": {
                    "nan_fraction": nan_fraction,
                    "inf_fraction": inf_fraction,
                    "p99": p99,
                },
                "method": sampled["method"],
                "sample_size": sample_size,
                "thresholds": {"required_nan_fraction": 0.0, "required_inf_fraction": 0.0},
                "warnings": [],
            },
        ]
        return {
            "matrix_id": matrix_id,
            "shape": [int(matrix.shape[0]), int(matrix.shape[1])],
            "dtype": str(matrix.dtype),
            "is_sparse": bool(sparse.issparse(matrix)),
            "min_value": min_value,
            "max_value": max_value,
            "negative_fraction": negative_fraction,
            "nonzero_integer_fraction": integer_fraction,
            "nan_fraction": nan_fraction,
            "inf_fraction": inf_fraction,
            "inferred_state": state,
            "inference_confidence": confidence,
            "state_evidence": evidence,
            "eligible_tasks": ["doublet_detection"] if state == "raw_counts" and not blocking_reasons else [],
            "blocking_reasons": blocking_reasons,
        }


def _infer_matrix_state(
    *,
    finite_values: np.ndarray,
    nonzero_values: np.ndarray,
    integer_fraction: Optional[float],
    min_value: Optional[float],
    max_value: Optional[float],
    negative_fraction: Optional[float],
    nan_fraction: Optional[float],
    inf_fraction: Optional[float],
    p99: Optional[float],
) -> tuple[str, str, list[str]]:
    reasons: list[str] = []
    if not finite_values.size or not nonzero_values.size:
        return "unknown", "low", ["no_finite_nonzero_values"]
    if (nan_fraction or 0.0) > 0 or (inf_fraction or 0.0) > 0:
        return "unknown", "high", ["non_finite_values_present"]
    if (negative_fraction or 0.0) > 0.001 or (min_value is not None and min_value < -1e-8):
        return "scaled", "high", ["negative_values_present"]
    if (
        min_value is not None
        and min_value >= -1e-8
        and integer_fraction is not None
        and integer_fraction >= RAW_INTEGER_FRACTION
    ):
        return "raw_counts", "high", ["nonnegative_integer_values"]
    if (
        min_value is not None
        and min_value >= -1e-8
        and integer_fraction is not None
        and integer_fraction < 0.95
        and max_value is not None
        and max_value <= 50.0
        and p99 is not None
        and p99 <= 30.0
    ):
        return "log_normalized", "medium", ["nonnegative_fractional_compressed_range"]
    reasons.append("state_rules_inconclusive")
    return "unknown", "low", reasons


def _select_count_source(
    profiles: list[Dict[str, Any]],
    *,
    explicit_count_source: Optional[str],
) -> tuple[Optional[str], str, list[str], list[str]]:
    by_id = {profile["matrix_id"]: profile for profile in profiles}
    warnings: list[str] = []
    if explicit_count_source:
        normalized = _normalize_matrix_id(explicit_count_source)
        profile = by_id.get(normalized)
        if profile and profile["inferred_state"] == "raw_counts" and not _has_fatal_matrix_issue(profile):
            return normalized, "explicit_user", [f"validated explicit count source: {normalized}"], warnings
        warnings.append(f"explicit_count_source_invalid:{normalized}")
        return None, "unresolved", [f"explicit count source failed validation: {normalized}"], warnings

    counts_layer = by_id.get("layers/counts")
    if counts_layer is not None:
        if counts_layer["inferred_state"] == "raw_counts" and not _has_fatal_matrix_issue(counts_layer):
            return (
                "layers/counts",
                "explicit_layer_name",
                ["layers/counts is explicitly named and validated as non-negative integer counts"],
                warnings,
            )
        warnings.append("named_counts_layer_failed_validation")

    for matrix_id in ("X", "raw.X"):
        profile = by_id.get(matrix_id)
        if profile and profile["inferred_state"] == "raw_counts" and not _has_fatal_matrix_issue(profile):
            return (
                matrix_id,
                "deterministic_rule",
                [f"{matrix_id} validated as a non-negative integer count matrix"],
                warnings,
            )

    other_candidates = [
        profile["matrix_id"]
        for profile in profiles
        if profile["matrix_id"] not in {"X", "raw.X", "layers/counts"}
        and profile["inferred_state"] == "raw_counts"
        and not _has_fatal_matrix_issue(profile)
    ]
    if other_candidates:
        warnings.append("unselected_raw_like_layers:" + ",".join(sorted(other_candidates)))
    return None, "unresolved", ["no authoritative count source passed deterministic selection"], warnings


def _has_fatal_matrix_issue(profile: Dict[str, Any]) -> bool:
    fatal = {"empty_matrix", "contains_nan", "contains_inf"}
    return bool(fatal.intersection(profile.get("blocking_reasons") or []))


def _sample_matrix(matrix: Any, max_values: int) -> Dict[str, Any]:
    if sparse.issparse(matrix):
        values = np.asarray(matrix.data, dtype=np.float64)
        method = "deterministic_even_sample_of_sparse_stored_values"
    else:
        values = np.asarray(matrix).reshape(-1).astype(np.float64, copy=False)
        method = "deterministic_even_sample_of_dense_values"
    if values.size > max_values:
        indices = np.linspace(0, values.size - 1, num=max_values, dtype=np.int64)
        values = values[indices]
    return {"values": values, "method": method}


def _fraction(mask: np.ndarray) -> Optional[float]:
    if mask.size == 0:
        return None
    return float(np.mean(mask))


def _normalize_matrix_id(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("layers[") and cleaned.endswith("]"):
        layer = cleaned[len("layers[") : -1].strip("'\"")
        return f"layers/{layer}"
    return cleaned


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _redacted_path(path: Path) -> str:
    return f".../{path.name}" if path.name else ".../unknown"


def _blocked_payload(
    path: Path,
    *,
    redacted: str,
    blocking_errors: list[str],
    file_hash: str = "",
    file_size_bytes: int = 0,
) -> Dict[str, Any]:
    seed = file_hash or hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return {
        "profile_id": f"profile_{seed[:16]}",
        "file_path_redacted": redacted,
        "file_hash": file_hash,
        "file_size_bytes": file_size_bytes,
        "object_type": "unknown",
        "n_cells": 0,
        "n_genes": 0,
        "raw_exists": False,
        "layers": [],
        "obsm_keys": [],
        "obsp_keys": [],
        "obs_keys": [],
        "var_keys": [],
        "batch_key": None,
        "batch_count": None,
        "batch_missing_count": 0,
        "batch_min_cells": None,
        "batch_max_cells": None,
        "batch_imbalance_ratio": None,
        "label_key": None,
        "label_count": None,
        "label_missing_count": 0,
        "has_pca": False,
        "pca_n_components": None,
        "pca_finite": None,
        "has_neighbors": False,
        "has_clustering": False,
        "matrix_profiles": [],
        "selected_count_source": None,
        "count_source_selection": {
            "method": "unresolved",
            "evidence": ["input could not be profiled"],
        },
        "warnings": [],
        "blocking_errors": sorted(set(blocking_errors)),
        "profile_version": PROFILE_VERSION,
    }
