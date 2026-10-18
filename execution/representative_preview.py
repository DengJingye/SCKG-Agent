from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from core.research_workspace_models import DataAssetProfile, RepresentativePreviewManifest


class RepresentativePreviewBuilder:
    """Materialize a deterministic user-data preview without modifying the source."""

    def build(
        self,
        *,
        source_path: Path,
        profile: DataAssetProfile,
        output_dir: Path,
        allowed_output_root: Path,
        max_cells: int = 500,
        random_seed: int = 20260812,
        stratify_key: str | None = None,
    ) -> RepresentativePreviewManifest:
        if profile.preview_capability != "supported" or not profile.selected_count_source:
            raise ValueError("data profile is not eligible for representative preview")
        if max_cells <= 0:
            raise ValueError("max_cells must be positive")
        source_path = Path(source_path).resolve(strict=True)
        output_root = Path(allowed_output_root).resolve()
        output_dir = Path(output_dir).resolve()
        _require_within(output_dir, output_root, "preview output")
        if output_dir.exists():
            raise FileExistsError("preview output directory already exists")
        output_dir.mkdir(parents=True)

        source_hash_before = _sha256(source_path)
        if source_hash_before != profile.source_hash:
            raise ValueError("source hash differs from data profile")

        import anndata as ad

        adata = ad.read_h5ad(source_path, backed="r")
        try:
            resolved_stratify_key = _resolve_stratify_key(
                adata.obs, requested=stratify_key, candidates=profile.batch_candidates
            )
            selected, source_counts, preview_counts, policy = _select_indices(
                obs=adata.obs,
                max_cells=max_cells,
                random_seed=random_seed,
                stratify_key=resolved_stratify_key,
            )
            preview = adata[selected, :].to_memory()
        finally:
            if getattr(adata, "file", None) is not None:
                adata.file.close()

        _set_count_matrix(preview, profile.selected_count_source)
        preview.uns["sckg_preview"] = {
            "preview_only": True,
            "scientific_claim_allowed": False,
            "source_artifact_id": profile.artifact_id,
            "source_hash": profile.source_hash,
            "profile_id": profile.profile_id,
            "selected_count_source": profile.selected_count_source,
            "policy": policy,
            "random_seed": random_seed,
            "stratify_key": resolved_stratify_key,
        }
        preview_id = "preview-" + _digest_json(
            {
                "source_hash": profile.source_hash,
                "profile_id": profile.profile_id,
                "selected_indices": selected.tolist(),
                "random_seed": random_seed,
            }
        )[:16]
        preview.uns["sckg_fixture"] = {
            "fixture_id": preview_id,
            "synthetic": False,
            "public_dataset": False,
            "user_data": True,
            "maintainer_approved": False,
            "qualification_mode": False,
            "representative_preview": True,
        }
        preview_path = output_dir / "representative_preview.h5ad"
        preview.write_h5ad(preview_path)
        source_hash_after = _sha256(source_path)
        preview_hash = _sha256(preview_path)
        indices_hash = _digest_json(selected.tolist())
        ids_hash = _digest_json([str(item) for item in preview.obs_names])
        manifest = RepresentativePreviewManifest(
            preview_id=preview_id,
            artifact_id=profile.artifact_id,
            owner_user_id=profile.owner_user_id,
            profile_id=profile.profile_id,
            source_hash=profile.source_hash,
            preview_hash=preview_hash,
            selected_obs_indices_hash=indices_hash,
            selected_obs_ids_hash=ids_hash,
            preview_path_redacted=f".../{preview_path.name}",
            n_source_cells=profile.n_cells,
            n_preview_cells=int(preview.n_obs),
            n_genes=int(preview.n_vars),
            random_seed=random_seed,
            policy=policy,
            stratify_key=resolved_stratify_key,
            source_strata_counts=source_counts,
            preview_strata_counts=preview_counts,
            selected_count_source=profile.selected_count_source,
            source_unchanged=source_hash_before == source_hash_after,
            limitations=[
                "Preview validates data shape, code, environment, and artifact contracts only.",
                "Preview results are not full-data scientific conclusions or final parameter validation.",
                "Rare states not represented by the stratification key may still be under-sampled.",
            ],
        )
        (output_dir / "preview_manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return manifest


def _resolve_stratify_key(
    obs: pd.DataFrame, *, requested: str | None, candidates: list[str]
) -> str | None:
    if requested is not None:
        if requested not in obs.columns:
            raise ValueError(f"stratify key not found: {requested}")
        return requested
    return next((item for item in candidates if item in obs.columns), None)


def _select_indices(
    *, obs: pd.DataFrame, max_cells: int, random_seed: int, stratify_key: str | None
) -> tuple[np.ndarray, dict[str, int], dict[str, int], str]:
    n_cells = len(obs)
    if n_cells <= max_cells:
        indices = np.arange(n_cells, dtype=np.int64)
        counts = _strata_counts(obs, stratify_key, indices)
        return indices, counts, counts, "all_cells"
    rng = np.random.default_rng(random_seed)
    if stratify_key is None:
        selected = np.sort(rng.choice(n_cells, size=max_cells, replace=False))
        return selected, {}, {}, "stratified_v1"

    labels = obs[stratify_key].astype("string").fillna("<missing>").to_numpy()
    groups = {
        label: np.flatnonzero(labels == label) for label in sorted(set(labels.tolist()))
    }
    allocation = _allocate_strata(groups, max_cells)
    selected_parts = [
        rng.choice(groups[label], size=count, replace=False)
        for label, count in allocation.items()
        if count > 0
    ]
    selected = np.sort(np.concatenate(selected_parts).astype(np.int64))
    return (
        selected,
        {str(label): int(len(indices)) for label, indices in groups.items()},
        _strata_counts(obs, stratify_key, selected),
        "stratified_v1",
    )


def _allocate_strata(groups: dict[str, np.ndarray], budget: int) -> dict[str, int]:
    if len(groups) > budget:
        raise ValueError("preview budget is smaller than the number of strata")
    total = sum(len(item) for item in groups.values())
    allocation = {label: 1 for label in groups}
    remaining = budget - len(groups)
    if remaining <= 0:
        return allocation
    exact = {
        label: remaining * len(indices) / total for label, indices in groups.items()
    }
    for label, value in exact.items():
        allocation[label] += min(int(np.floor(value)), len(groups[label]) - 1)
    assigned = sum(allocation.values())
    order = sorted(
        groups,
        key=lambda label: (exact[label] - np.floor(exact[label]), label),
        reverse=True,
    )
    while assigned < budget:
        progressed = False
        for label in order:
            if allocation[label] < len(groups[label]):
                allocation[label] += 1
                assigned += 1
                progressed = True
                if assigned == budget:
                    break
        if not progressed:
            break
    return allocation


def _strata_counts(
    obs: pd.DataFrame, stratify_key: str | None, indices: np.ndarray
) -> dict[str, int]:
    if stratify_key is None:
        return {}
    labels = obs.iloc[indices][stratify_key].astype("string").fillna("<missing>")
    return {str(key): int(value) for key, value in labels.value_counts().sort_index().items()}


def _set_count_matrix(adata, matrix_id: str) -> None:
    if matrix_id == "X":
        matrix = adata.X
    elif matrix_id == "raw.X":
        if adata.raw is None:
            raise ValueError("raw.X was selected but is absent from preview")
        matrix = adata.raw.X
    elif matrix_id.startswith("layers/"):
        layer = matrix_id.split("/", 1)[1]
        if layer not in adata.layers:
            raise ValueError(f"selected count layer is absent: {layer}")
        matrix = adata.layers[layer]
    else:
        raise ValueError(f"unsupported count source: {matrix_id}")
    adata.X = matrix.copy() if hasattr(matrix, "copy") else matrix
    values = np.asarray(adata.X.data if sparse.issparse(adata.X) else adata.X).reshape(-1)
    if not values.size or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("preview count matrix is empty, negative, or non-finite")
    if not np.allclose(values, np.rint(values), atol=1e-8):
        raise ValueError("preview count matrix is not integer-valued")


def _require_within(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes allowed root") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
