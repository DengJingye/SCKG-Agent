from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
from sklearn.model_selection import train_test_split

from core.execution_models import (
    IntegrationDatasetManifest,
    IntegrationSplitArtifact,
    IntegrationSplitManifest,
)


def build_integration_scientific_split(
    *,
    dataset: IntegrationDatasetManifest,
    output_dir: Path,
    split_seed: int = 20260718,
    cells_per_split: int = 3000,
) -> IntegrationSplitManifest:
    source = ad.read_h5ad(dataset.processed_h5ad_path)
    if source.obs_names.duplicated().any():
        raise ValueError("scientific dataset cell identifiers are not unique")
    strata = (
        source.obs["batch"].astype(str) + "|" + source.obs["cell_type"].astype(str)
    )
    counts = strata.value_counts()
    rare = set(counts[counts < 4].index)
    if rare:
        strata = strata.where(~strata.isin(rare), source.obs["batch"].astype(str) + "|rare")
    if cells_per_split * 2 > source.n_obs:
        raise ValueError("requested integration split exceeds dataset size")
    indices = np.arange(source.n_obs)
    development_indices, evaluation_indices = train_test_split(
        indices,
        train_size=cells_per_split,
        test_size=cells_per_split,
        random_state=split_seed,
        stratify=strata,
    )
    development_indices = np.sort(development_indices)
    evaluation_indices = np.sort(evaluation_indices)
    if set(development_indices) & set(evaluation_indices):
        raise RuntimeError("scientific development/evaluation split overlaps")

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    development = _write_split(
        source=source,
        indices=development_indices,
        path=output_dir / "development.h5ad",
        role="development",
        seed=split_seed,
        accession=dataset.accession,
    )
    evaluation = _write_split(
        source=source,
        indices=evaluation_indices,
        path=output_dir / "evaluation.h5ad",
        role="evaluation",
        seed=split_seed,
        accession=dataset.accession,
    )
    payload = {
        "accession": dataset.accession,
        "split_seed": split_seed,
        "stratification_fields": ["batch", "cell_type"],
        "development": development.model_dump(mode="json"),
        "evaluation": evaluation.model_dump(mode="json"),
        "cell_overlap_count": 0,
    }
    manifest = IntegrationSplitManifest(
        **payload,
        manifest_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    )
    (output_dir / "split_manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _write_split(*, source, indices, path: Path, role: str, seed: int, accession: str):
    split = source[indices].copy()
    split.uns["sckg_scientific_split"] = {
        "role": role,
        "seed": seed,
        "metric_authority": "scientific_pilot_metric",
        "parameters_may_be_tuned": role == "development",
    }
    split.write_h5ad(path)
    cell_ids = split.obs_names.astype(str).tolist()
    return IntegrationSplitArtifact(
        artifact_id=f"scib-pancreas-{role}",
        fixture_id=f"scib_pancreas_{role}",
        accession=accession,
        split_role=role,
        path=str(path),
        probe_hash=_sha256(path),
        cell_id_hash=hashlib.sha256("\n".join(cell_ids).encode("utf-8")).hexdigest(),
        n_cells=split.n_obs,
        n_batches=int(split.obs["batch"].nunique()),
        n_labels=int(split.obs["cell_type"].nunique()),
        split_seed=seed,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
