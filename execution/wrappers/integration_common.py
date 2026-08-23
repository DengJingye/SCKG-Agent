from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import anndata as ad
import numpy as np


def load_request(argv: list[str] | None) -> tuple[dict[str, Any], Path, Path]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args(argv)
    run_dir = Path.cwd().resolve()
    request_path = (run_dir / args.request_json).resolve(strict=True)
    require_within(request_path, run_dir)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    required = {
        "expected_cells",
        "expected_input_hash",
        "execution_seed",
        "fixture_id",
        "input_path",
        "parameters",
        "public_dataset",
        "purpose",
    }
    missing = sorted(required - set(request))
    if missing:
        raise ValueError("worker request missing fields: " + ", ".join(missing))
    artifacts_dir = (run_dir / "artifacts").resolve()
    require_within(artifacts_dir, run_dir)
    artifacts_dir.mkdir(exist_ok=True)
    return request, run_dir, artifacts_dir


def load_embedding_input(request: dict[str, Any]):
    input_path = Path(request["input_path"]).resolve(strict=True)
    if input_path.suffix.casefold() != ".h5ad":
        raise ValueError("integration wrapper only accepts .h5ad")
    if sha256(input_path) != request["expected_input_hash"]:
        raise ValueError("input hash mismatch")
    adata = ad.read_h5ad(input_path)
    if adata.n_obs != int(request["expected_cells"]):
        raise ValueError("input cell count mismatch")
    if not adata.obs_names.is_unique:
        raise ValueError("cell identifiers must be unique")
    if "batch" not in adata.obs:
        raise ValueError("missing batch key")
    if adata.obs["batch"].isna().any() or adata.obs["batch"].nunique() < 2:
        raise ValueError("batch labels must contain at least two non-empty batches")
    if "X_pca" not in adata.obsm:
        raise ValueError("missing PCA representation")
    embedding = np.asarray(adata.obsm["X_pca"], dtype=np.float64)
    if embedding.ndim != 2 or embedding.shape[0] != adata.n_obs or embedding.shape[1] < 2:
        raise ValueError("invalid PCA representation shape")
    if not np.isfinite(embedding).all():
        raise ValueError("non-finite PCA representation")
    return adata, embedding


def write_outputs(
    *,
    artifacts_dir: Path,
    adata,
    embedding: np.ndarray,
    request: dict[str, Any],
    tool_name: str,
    tool_distribution: str,
    tool_version: str,
) -> dict[str, Any]:
    embedding = np.asarray(embedding, dtype=np.float64)
    if embedding.shape[0] != adata.n_obs and embedding.shape[1] == adata.n_obs:
        embedding = embedding.T
    if embedding.shape[0] != adata.n_obs or embedding.ndim != 2:
        raise ValueError("integrated embedding cell dimension mismatch")
    if not np.isfinite(embedding).all():
        raise ValueError("integrated embedding contains non-finite values")

    result_path = artifacts_dir / "integrated_embedding.tsv"
    pc_names = [f"integrated_{index + 1}" for index in range(embedding.shape[1])]
    fields = ["cell_id", "batch", "cell_type", *pc_names]
    with result_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        labels = (
            adata.obs["cell_type"].astype(str).tolist()
            if "cell_type" in adata.obs
            else [""] * adata.n_obs
        )
        for cell_id, batch, label, values in zip(
            adata.obs_names.astype(str),
            adata.obs["batch"].astype(str),
            labels,
            embedding,
        ):
            writer.writerow(
                {
                    "cell_id": cell_id,
                    "batch": batch,
                    "cell_type": label,
                    **{name: repr(float(value)) for name, value in zip(pc_names, values)},
                }
            )

    parameter_snapshot = {
        "parameters": request["parameters"],
        "execution_seed": int(request["execution_seed"]),
    }
    (artifacts_dir / "parameters.json").write_text(
        json.dumps(parameter_snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metadata = {
        "fixture_id": request["fixture_id"],
        "input_hash": request["expected_input_hash"],
        "input_cell_order_hash": text_hash(adata.obs_names.astype(str).tolist()),
        "output_cell_order_hash": text_hash(adata.obs_names.astype(str).tolist()),
        "n_cells": adata.n_obs,
        "n_dimensions": embedding.shape[1],
        "batch_key": "batch",
        "label_key": "cell_type" if "cell_type" in adata.obs else None,
        "tool_name": tool_name,
        "tool_version": importlib.metadata.version(tool_distribution),
        "contract_tool_version": tool_version,
        "execution_seed": int(request["execution_seed"]),
        "execution_purpose": request["purpose"],
        "public_dataset": bool(request["public_dataset"]),
        "user_data_used": False,
        "tool_actually_executed": True,
    }
    (artifacts_dir / "result_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text_hash(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes controlled run directory") from exc
