from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
from typing import Any

import numpy as np
from scipy import sparse

from core.execution_models import MatrixState
from core.research_workspace_models import DataAssetMatrixSummary, DataAssetProfile


class AnnDataBackedAdapter:
    """Read AnnData metadata and bounded matrix samples without loading full X."""

    def __init__(self, *, max_sampled_rows: int = 32, max_sampled_columns: int = 256):
        if max_sampled_rows <= 0 or max_sampled_columns <= 0:
            raise ValueError("sample bounds must be positive")
        self.max_sampled_rows = max_sampled_rows
        self.max_sampled_columns = max_sampled_columns

    def profile(
        self,
        *,
        path: Path,
        artifact_id: str,
        owner_user_id: str,
        source_hash: str | None = None,
    ) -> DataAssetProfile:
        path = Path(path).resolve(strict=True)
        if path.suffix.casefold() != ".h5ad" or not path.is_file():
            raise ValueError("AnnDataBackedAdapter requires an existing .h5ad file")
        import anndata as ad

        digest = source_hash or _sha256(path)
        warnings: list[str] = []
        blocking: list[str] = []
        adata = ad.read_h5ad(path, backed="r")
        try:
            matrices: list[DataAssetMatrixSummary] = [
                self._profile_matrix("X", adata.X)
            ]
            if adata.raw is not None:
                matrices.append(self._profile_matrix("raw.X", adata.raw.X))
            for layer_name in sorted(adata.layers.keys()):
                matrices.append(
                    self._profile_matrix(
                        f"layers/{layer_name}", adata.layers[layer_name]
                    )
                )
            selected = _select_count_source(matrices)
            if selected is None:
                blocking.append("count_source_unresolved")
            if adata.n_obs == 0 or adata.n_vars == 0:
                blocking.append("empty_anndata")
            if not adata.obs_names.is_unique:
                warnings.append("duplicate_obs_names")
            if not adata.var_names.is_unique:
                warnings.append("duplicate_var_names")
            obs_keys = sorted(str(item) for item in adata.obs.columns)
            batch_candidates = [
                key
                for key in obs_keys
                if any(token in key.casefold() for token in ("batch", "sample", "donor"))
            ]
            dtype = np.dtype(adata.X.dtype)
            estimated_dense = int(adata.n_obs * adata.n_vars * dtype.itemsize)
            return DataAssetProfile(
                profile_id=f"asset-profile-{digest[:16]}",
                artifact_id=artifact_id,
                owner_user_id=owner_user_id,
                redacted_path=f".../{path.name}",
                source_hash=digest,
                file_size_bytes=path.stat().st_size,
                estimated_dense_memory_bytes=estimated_dense,
                n_cells=int(adata.n_obs),
                n_genes=int(adata.n_vars),
                matrices=matrices,
                selected_count_source=selected,
                obs_keys=obs_keys,
                var_keys=sorted(str(item) for item in adata.var.columns),
                obsm_keys=sorted(str(item) for item in adata.obsm.keys()),
                obsp_keys=sorted(str(item) for item in adata.obsp.keys()),
                layer_keys=sorted(str(item) for item in adata.layers.keys()),
                batch_candidates=batch_candidates,
                warnings=sorted(set(warnings)),
                blocking_errors=sorted(set(blocking)),
                preview_capability="blocked" if blocking else "supported",
                reader_version=importlib.metadata.version("anndata"),
            )
        finally:
            if getattr(adata, "file", None) is not None:
                adata.file.close()

    def _profile_matrix(self, matrix_id: str, matrix: Any) -> DataAssetMatrixSummary:
        shape = (int(matrix.shape[0]), int(matrix.shape[1]))
        if not shape[0] or not shape[1]:
            return DataAssetMatrixSummary(
                matrix_id=matrix_id,
                shape=shape,
                dtype=str(matrix.dtype),
                is_sparse=_is_sparse_backed(matrix),
                sample_method="metadata_only",
            )
        row_indices = np.linspace(
            0, shape[0] - 1, num=min(shape[0], self.max_sampled_rows), dtype=np.int64
        )
        column_indices = np.linspace(
            0, shape[1] - 1, num=min(shape[1], self.max_sampled_columns), dtype=np.int64
        )
        sampled_rows: list[np.ndarray] = []
        for row_index in row_indices:
            row = matrix[int(row_index), :]
            if sparse.issparse(row):
                row = row.toarray()
            values = np.asarray(row).reshape(-1)
            sampled_rows.append(values[column_indices])
        values = np.concatenate(sampled_rows).astype(np.float64, copy=False)
        finite = np.isfinite(values)
        finite_values = values[finite]
        nonzero = finite_values[np.abs(finite_values) > 1e-12]
        nonfinite_fraction = float(np.mean(~finite))
        negative_fraction = (
            float(np.mean(finite_values < 0)) if finite_values.size else None
        )
        integer_fraction = (
            float(np.mean(np.isclose(nonzero, np.rint(nonzero), atol=1e-8)))
            if nonzero.size
            else None
        )
        inferred = _infer_state(
            finite_values, integer_fraction, negative_fraction, nonfinite_fraction
        )
        return DataAssetMatrixSummary(
            matrix_id=matrix_id,
            shape=shape,
            dtype=str(matrix.dtype),
            is_sparse=_is_sparse_backed(matrix),
            inferred_state=inferred,
            sampled_value_count=int(values.size),
            sample_method="bounded_backed_rows",
            min_value=float(finite_values.min()) if finite_values.size else None,
            max_value=float(finite_values.max()) if finite_values.size else None,
            nonzero_integer_fraction=integer_fraction,
            negative_fraction=negative_fraction,
            nonfinite_fraction=nonfinite_fraction,
        )


def _infer_state(
    values: np.ndarray,
    integer_fraction: float | None,
    negative_fraction: float | None,
    nonfinite_fraction: float,
) -> MatrixState:
    if not values.size or nonfinite_fraction > 0:
        return MatrixState.UNKNOWN
    if (negative_fraction or 0) > 0.001:
        return MatrixState.SCALED
    if integer_fraction is not None and integer_fraction >= 0.995:
        return MatrixState.RAW_COUNTS
    if values.min() >= -1e-8 and values.max() <= 50:
        return MatrixState.LOG_NORMALIZED
    return MatrixState.UNKNOWN


def _select_count_source(matrices: list[DataAssetMatrixSummary]) -> str | None:
    by_id = {item.matrix_id: item for item in matrices}
    for matrix_id in ("layers/counts", "X", "raw.X"):
        item = by_id.get(matrix_id)
        if item is not None and item.inferred_state == MatrixState.RAW_COUNTS:
            return matrix_id
    return None


def _is_sparse_backed(matrix: Any) -> bool:
    return bool(sparse.issparse(matrix) or "sparse" in type(matrix).__name__.casefold())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
