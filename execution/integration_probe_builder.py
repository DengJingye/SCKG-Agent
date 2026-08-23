from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd

from core.execution_models import IntegrationProbeSpec


class IntegrationProbeBuilder:
    """Build deterministic, balanced engineering probes for batch integration."""

    def build(
        self,
        *,
        output_dir: Path,
        split_role: str,
        random_seed: int,
        profile_id: str = "phase5-synthetic-integration",
        fixture_id: str = "phase5_batch_integration_synthetic",
        cells_per_batch_label: int = 30,
        n_features: int = 12,
        allowed_output_root: Path | None = None,
    ) -> IntegrationProbeSpec:
        if split_role not in {"development", "evaluation"}:
            raise ValueError("integration probe split_role must be development or evaluation")
        if cells_per_batch_label < 8 or n_features < 3:
            raise ValueError("integration probe is too small")
        output_dir = Path(output_dir).resolve()
        root = Path(allowed_output_root or output_dir).resolve()
        _require_within(output_dir, root)
        output_dir.mkdir(parents=True, exist_ok=False)

        rng = np.random.default_rng(random_seed)
        batches = ["batch_1", "batch_2", "batch_3"]
        labels = ["cell_type_a", "cell_type_b", "cell_type_c"]
        biological_centers = np.zeros((len(labels), n_features), dtype=np.float64)
        for index in range(len(labels)):
            biological_centers[index, index * 2 : index * 2 + 2] = 4.0
        batch_shifts = rng.normal(0.0, 0.25, size=(len(batches), n_features))
        batch_shifts[:, -3:] += np.asarray(
            [[-3.0, 0.0, 1.5], [0.0, 3.0, -1.5], [3.0, -3.0, 0.0]]
        )

        embeddings: list[np.ndarray] = []
        obs_rows: list[dict[str, str]] = []
        obs_names: list[str] = []
        for batch_index, batch in enumerate(batches):
            for label_index, label in enumerate(labels):
                values = (
                    biological_centers[label_index]
                    + batch_shifts[batch_index]
                    + rng.normal(0.0, 0.7, size=(cells_per_batch_label, n_features))
                )
                embeddings.append(values)
                for local_index in range(cells_per_batch_label):
                    obs_names.append(
                        f"{split_role}-{batch_index}-{label_index}-{local_index:03d}"
                    )
                    obs_rows.append({"batch": batch, "cell_type": label})
        x_pca = np.vstack(embeddings)
        obs = pd.DataFrame(obs_rows, index=pd.Index(obs_names, name="cell_id"))
        adata = ad.AnnData(X=x_pca.copy(), obs=obs)
        adata.obsm["X_pca"] = x_pca
        adata.uns["sckg_probe"] = {
            "fixture_id": fixture_id,
            "split_role": split_role,
            "random_seed": random_seed,
            "metric_authority": "synthetic_engineering_metric",
        }

        artifact_path = output_dir / "integration_probe.h5ad"
        adata.write_h5ad(artifact_path)
        probe_hash = _sha256(artifact_path)
        obs_hash = _text_hash(obs_names)
        source_hash = _text_hash(
            [fixture_id, split_role, str(random_seed), str(cells_per_batch_label), str(n_features)]
        )
        metadata = {
            "fixture_id": fixture_id,
            "split_role": split_role,
            "random_seed": random_seed,
            "n_cells": adata.n_obs,
            "n_features": n_features,
            "n_batches": len(batches),
            "n_biology_labels": len(labels),
            "batch_key": "batch",
            "label_key": "cell_type",
            "selected_obs_indices_hash": obs_hash,
            "probe_hash": probe_hash,
            "source_input_hash": source_hash,
            "scientific_claim_allowed": False,
        }
        metadata_path = output_dir / "probe_manifest.json"
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return IntegrationProbeSpec(
            probe_id=f"phase5-{split_role}-{random_seed}",
            profile_id=profile_id,
            source_fixture_id=fixture_id,
            split_role=split_role,
            random_seed=random_seed,
            n_cells=adata.n_obs,
            n_features=n_features,
            n_batches=len(batches),
            n_biology_labels=len(labels),
            selected_obs_indices_hash=obs_hash,
            probe_artifact_path=str(artifact_path),
            probe_hash=probe_hash,
            metadata_path=str(metadata_path),
            source_input_hash=source_hash,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text_hash(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("probe output escapes controlled root") from exc
