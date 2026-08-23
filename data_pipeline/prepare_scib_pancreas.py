#!/usr/bin/env python
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.execution_models import IntegrationDatasetManifest


ACCESSION = "scIB-pancreas"
SOURCE_URL = (
    "https://openproblems-data.s3.amazonaws.com/resources/datasets/"
    "openproblems_v1/pancreas/log_cp10k/dataset.h5ad"
)
EXPECTED_SIZE = 1_356_334_299
DATASET_ROOT = PROJECT_ROOT / ".sckg_exec" / "datasets" / ACCESSION


def prepare_scib_pancreas(
    *, dataset_root: Path = DATASET_ROOT
) -> IntegrationDatasetManifest:
    dataset_root = Path(dataset_root).resolve()
    raw_dir = dataset_root / "raw"
    processed_dir = dataset_root / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    source_path = raw_dir / "openproblems_scib_pancreas.h5ad"
    _download(SOURCE_URL, source_path, expected_size=EXPECTED_SIZE)

    source = ad.read_h5ad(source_path, backed="r")
    try:
        if source.n_obs != 16_382:
            raise ValueError(f"unexpected pancreas cell count: {source.n_obs}")
        if "X_pca" not in source.obsm:
            raise ValueError("scIB pancreas source has no X_pca")
        batch_key = "batch" if "batch" in source.obs else "tech"
        label_key = "cell_type" if "cell_type" in source.obs else "celltype"
        if batch_key not in source.obs or label_key not in source.obs:
            raise ValueError("scIB pancreas source lacks independent batch/cell-type labels")
        obs = pd.DataFrame(
            {
                "batch": source.obs[batch_key].astype(str).to_numpy(),
                "cell_type": source.obs[label_key].astype(str).to_numpy(),
            },
            index=pd.Index(source.obs_names.astype(str), name="cell_id"),
        )
        if obs.isna().any().any() or obs["batch"].nunique() < 2 or obs["cell_type"].nunique() < 2:
            raise ValueError("scIB pancreas labels are missing or degenerate")
        x_pca = np.asarray(source.obsm["X_pca"], dtype=np.float32)
        n_genes = source.n_vars
    finally:
        source.file.close()

    if not np.isfinite(x_pca).all() or x_pca.shape[0] != len(obs):
        raise ValueError("scIB pancreas PCA representation is invalid")
    processed = ad.AnnData(X=x_pca.copy(), obs=obs)
    processed.obsm["X_pca"] = x_pca
    processed.uns["dataset"] = {
        "accession": ACCESSION,
        "source_url": SOURCE_URL,
        "license": "CC BY 4.0",
        "source_n_genes": n_genes,
        "representation": "source X_pca",
        "user_data": False,
    }
    processed_path = processed_dir / "scib_pancreas_pca.h5ad"
    processed.write_h5ad(processed_path)
    manifest = IntegrationDatasetManifest(
        dataset_id="scIB-pancreas",
        accession=ACCESSION,
        title="Human pancreas cells from the scIB benchmarks",
        source_url=SOURCE_URL,
        license="CC BY 4.0",
        downloaded_at=datetime.now(timezone.utc).isoformat(),
        source_file_path=str(source_path),
        source_file_sha256=_sha256(source_path),
        processed_h5ad_path=str(processed_path),
        processed_h5ad_sha256=_sha256(processed_path),
        n_cells=processed.n_obs,
        n_genes=n_genes,
        batch_key="batch",
        label_key="cell_type",
        n_batches=int(processed.obs["batch"].nunique()),
        n_labels=int(processed.obs["cell_type"].nunique()),
    )
    (dataset_root / "dataset_manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _download(url: str, destination: Path, *, expected_size: int) -> None:
    if destination.is_file():
        if destination.stat().st_size == expected_size:
            return
        raise ValueError("cached pancreas source has unexpected size")
    partial = destination.with_suffix(destination.suffix + ".partial")
    resume_at = partial.stat().st_size if partial.exists() else 0
    if resume_at > expected_size:
        raise ValueError("partial pancreas download exceeds expected size")
    if resume_at < expected_size:
        _download_ranges(
            url=url,
            partial=partial,
            start=resume_at,
            stop=expected_size,
            workers=4,
        )
    if partial.stat().st_size != expected_size:
        raise ValueError(
            f"downloaded pancreas source size mismatch: {partial.stat().st_size}"
        )
    partial.replace(destination)


def _download_ranges(
    *, url: str, partial: Path, start: int, stop: int, workers: int
) -> None:
    remaining = stop - start
    chunk_size = (remaining + workers - 1) // workers
    ranges = []
    for index in range(workers):
        range_start = start + index * chunk_size
        range_stop = min(stop, range_start + chunk_size)
        if range_start < range_stop:
            ranges.append((index, range_start, range_stop - 1))

    def fetch(item):
        index, range_start, range_end = item
        path = partial.with_name(f"{partial.name}.range-{index:02d}")
        expected = range_end - range_start + 1
        if path.is_file() and path.stat().st_size == expected:
            return index, path
        path.unlink(missing_ok=True)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "scKG-Agent/2.5 Phase5 scientific pilot",
                "Range": f"bytes={range_start}-{range_end}",
            },
        )
        with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as out:
            if response.status != 206:
                raise ValueError("pancreas source did not honor HTTP range request")
            shutil.copyfileobj(response, out, length=8 * 1024 * 1024)
        if path.stat().st_size != expected:
            raise ValueError(f"pancreas range {index} size mismatch")
        return index, path

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        completed = sorted(pool.map(fetch, ranges))
    with partial.open("ab") as output:
        for _, path in completed:
            with path.open("rb") as source:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
            path.unlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    args = parser.parse_args()
    manifest = prepare_scib_pancreas(dataset_root=args.dataset_root)
    print(manifest.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
