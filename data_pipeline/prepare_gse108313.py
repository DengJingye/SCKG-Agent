#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from core.execution_models import ScientificDatasetManifest
from core.settings import PROJECT_ROOT


ACCESSION = "GSE108313"
DOI = "10.1186/s13059-018-1603-1"
DATASET_ROOT = PROJECT_ROOT / ".sckg_exec" / "datasets" / ACCESSION
RNA_NAME = "GSM2895282_Hashtag-RNA.umi.txt.gz"
HTO_NAME = "GSM2895283_Hashtag-HTO-count.csv.gz"
PREPARATION_VERSION = "gse108313-v2-batch-hto-only"
EXPECTED_HTO_NAMES = [f"Batch{letter}" for letter in "ABCDEFGH"]
SOURCE_URLS = {
    "rna_matrix": (
        "https://www.ncbi.nlm.nih.gov/geo/download/?acc=GSM2895282&format=file&file="
        "GSM2895282%5FHashtag%2DRNA%2Eumi%2Etxt%2Egz"
    ),
    "hto_counts": (
        "https://www.ncbi.nlm.nih.gov/geo/download/?acc=GSM2895283&format=file&file="
        "GSM2895283%5FHashtag%2DHTO%2Dcount%2Ecsv%2Egz"
    ),
}


def prepare_gse108313(
    *,
    dataset_root: Path = DATASET_ROOT,
    min_counts: int = 500,
    min_genes: int = 200,
) -> ScientificDatasetManifest:
    dataset_root = Path(dataset_root)
    raw_dir = dataset_root / "raw"
    processed_dir = dataset_root / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    rna_path = raw_dir / RNA_NAME
    hto_path = raw_dir / HTO_NAME
    _download(SOURCE_URLS["rna_matrix"], rna_path)
    _download(SOURCE_URLS["hto_counts"], hto_path)
    h5ad_path = processed_dir / "GSE108313_pbmc_raw_counts_hto.h5ad"
    cached = _reuse_or_repair_cached_h5ad(h5ad_path, processed_dir)
    if cached is not None:
        return _write_manifest(
            dataset_root=dataset_root,
            processed_dir=processed_dir,
            rna_path=rna_path,
            hto_path=hto_path,
            h5ad_path=h5ad_path,
            adata=cached,
        )

    hto_barcodes, hto_names, hto_counts = _read_hto_counts(hto_path)
    hto_lookup = {barcode: index for index, barcode in enumerate(hto_barcodes)}
    with gzip.open(rna_path, "rb") as handle:
        header = handle.readline().decode("utf-8").rstrip("\r\n").split("\t")
    if not header or header[0] != "GENE":
        raise ValueError("unexpected GSE108313 RNA matrix header")
    rna_barcodes = header[1:]
    aligned_rna_positions = np.asarray(
        [index for index, barcode in enumerate(rna_barcodes) if barcode in hto_lookup],
        dtype=np.int64,
    )
    aligned_barcodes = [rna_barcodes[index] for index in aligned_rna_positions]
    aligned_hto_positions = np.asarray(
        [hto_lookup[barcode] for barcode in aligned_barcodes], dtype=np.int64
    )
    if not len(aligned_barcodes):
        raise ValueError("RNA and HTO files have no shared barcodes")

    totals, detected_genes, n_source_genes = _rna_qc_pass(
        rna_path, aligned_rna_positions, len(rna_barcodes)
    )
    quality_mask = (totals >= min_counts) & (detected_genes >= min_genes)
    retained_rna_positions = aligned_rna_positions[quality_mask]
    retained_barcodes = [
        barcode for barcode, keep in zip(aligned_barcodes, quality_mask) if keep
    ]
    retained_hto_positions = aligned_hto_positions[quality_mask]
    if not len(retained_barcodes):
        raise ValueError("RNA quality filtering removed every aligned barcode")

    matrix, genes = _build_sparse_matrix(
        rna_path,
        retained_rna_positions,
        len(rna_barcodes),
    )
    if len(genes) != n_source_genes:
        raise RuntimeError("RNA gene count changed between streaming passes")
    obs = pd.DataFrame(
        {
            "rna_total_counts": totals[quality_mask],
            "rna_detected_genes": detected_genes[quality_mask],
        },
        index=pd.Index(retained_barcodes, name="barcode"),
    )
    var = pd.DataFrame(
        {"original_gene_name": genes},
        index=pd.Index(genes, name="gene"),
    )
    adata = ad.AnnData(X=matrix, obs=obs, var=var)
    adata.var_names_make_unique()
    adata.layers["counts"] = adata.X.copy()
    adata.obsm["HTO_counts"] = hto_counts[retained_hto_positions].astype(np.int32)
    adata.uns["hto_names"] = hto_names
    adata.uns["dataset"] = {
        "accession": ACCESSION,
        "doi": DOI,
        "raw_counts_preserved": True,
        "rna_min_counts": min_counts,
        "rna_min_genes": min_genes,
        "aligned_before_quality_filter": len(aligned_barcodes),
        "quality_filtered_cells": len(retained_barcodes),
        "user_data": False,
        "preparation_version": PREPARATION_VERSION,
    }
    adata.write_h5ad(h5ad_path)
    _write_lines_gzip(processed_dir / "barcodes.tsv.gz", retained_barcodes)
    _write_lines_gzip(processed_dir / "genes.tsv.gz", list(adata.var_names))
    (processed_dir / "preprocessing.json").write_text(
        json.dumps(adata.uns["dataset"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return _write_manifest(
        dataset_root=dataset_root,
        processed_dir=processed_dir,
        rna_path=rna_path,
        hto_path=hto_path,
        h5ad_path=h5ad_path,
        adata=adata,
    )


def _write_manifest(
    *,
    dataset_root: Path,
    processed_dir: Path,
    rna_path: Path,
    hto_path: Path,
    h5ad_path: Path,
    adata: ad.AnnData,
) -> ScientificDatasetManifest:
    download_date = datetime.now(timezone.utc).date().isoformat()
    raw_files = [
        _file_record(rna_path, SOURCE_URLS["rna_matrix"], download_date),
        _file_record(hto_path, SOURCE_URLS["hto_counts"], download_date),
    ]
    processed_files = [
        _file_record(h5ad_path, "generated_from_geo_processed_files", download_date),
        _file_record(processed_dir / "barcodes.tsv.gz", "generated", download_date),
        _file_record(processed_dir / "genes.tsv.gz", "generated", download_date),
        _file_record(processed_dir / "preprocessing.json", "generated", download_date),
    ]
    manifest = ScientificDatasetManifest(
        title="Cell Hashing PBMC",
        source_urls=SOURCE_URLS,
        raw_files=raw_files,
        processed_files=processed_files,
        download_date=download_date,
        h5ad_path=str(h5ad_path),
        h5ad_sha256=_sha256(h5ad_path),
        n_cells=adata.n_obs,
        n_genes=adata.n_vars,
        raw_counts_preserved=True,
    )
    (dataset_root / "dataset_manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _reuse_or_repair_cached_h5ad(
    h5ad_path: Path, processed_dir: Path
) -> ad.AnnData | None:
    if not h5ad_path.is_file():
        return None
    adata = ad.read_h5ad(h5ad_path)
    names = [str(item) for item in adata.uns.get("hto_names", [])]
    if not set(EXPECTED_HTO_NAMES).issubset(names):
        return None
    positions = [names.index(name) for name in EXPECTED_HTO_NAMES]
    if names != EXPECTED_HTO_NAMES:
        adata.obsm["HTO_counts"] = np.asarray(adata.obsm["HTO_counts"])[:, positions]
        adata.uns["hto_names"] = EXPECTED_HTO_NAMES
    dataset = dict(adata.uns.get("dataset") or {})
    dataset["preparation_version"] = PREPARATION_VERSION
    dataset["hto_rows_retained"] = EXPECTED_HTO_NAMES
    dataset["hto_mapping_summary_rows_excluded"] = [
        "bad_struct",
        "no_match",
        "total_reads",
    ]
    adata.uns["dataset"] = dataset
    adata.write_h5ad(h5ad_path)
    _write_lines_gzip(processed_dir / "barcodes.tsv.gz", list(adata.obs_names))
    _write_lines_gzip(processed_dir / "genes.tsv.gz", list(adata.var_names))
    (processed_dir / "preprocessing.json").write_text(
        json.dumps(dataset, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return adata


def _download(url: str, destination: Path) -> None:
    if destination.is_file() and destination.stat().st_size > 0:
        return
    partial = destination.with_suffix(destination.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "scKG-Agent/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, length=1024 * 1024)
        partial.replace(destination)
    finally:
        if partial.exists():
            partial.unlink()


def _read_hto_counts(path: Path) -> tuple[list[str], list[str], np.ndarray]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        barcodes = header[1:]
        hto_names: list[str] = []
        rows: list[np.ndarray] = []
        for row in reader:
            name = row[0].split("-", 1)[0]
            if name not in EXPECTED_HTO_NAMES:
                continue
            hto_names.append(name)
            values = np.asarray(row[1:], dtype=np.int32)
            if len(values) != len(barcodes):
                raise ValueError("HTO row length mismatch")
            rows.append(values)
    matrix = np.vstack(rows).T
    if hto_names != EXPECTED_HTO_NAMES:
        raise ValueError(f"unexpected HTO batch rows: {hto_names}")
    return barcodes, hto_names, matrix


def _rna_qc_pass(
    path: Path, selected_positions: np.ndarray, expected_columns: int
) -> tuple[np.ndarray, np.ndarray, int]:
    totals = np.zeros(len(selected_positions), dtype=np.int64)
    detected = np.zeros(len(selected_positions), dtype=np.int32)
    gene_count = 0
    with gzip.open(path, "rb") as handle:
        handle.readline()
        for line in handle:
            _, separator, payload = line.partition(b"\t")
            if not separator:
                raise ValueError("malformed RNA matrix row")
            values = np.fromstring(payload, dtype=np.int32, sep="\t")
            if len(values) != expected_columns:
                raise ValueError("RNA matrix row length mismatch")
            selected = values[selected_positions]
            totals += selected
            detected += selected > 0
            gene_count += 1
    return totals, detected, gene_count


def _build_sparse_matrix(
    path: Path, selected_positions: np.ndarray, expected_columns: int
) -> tuple[sparse.csr_matrix, list[str]]:
    row_chunks: list[np.ndarray] = []
    column_chunks: list[np.ndarray] = []
    data_chunks: list[np.ndarray] = []
    genes: list[str] = []
    with gzip.open(path, "rb") as handle:
        handle.readline()
        for gene_index, line in enumerate(handle):
            gene_bytes, separator, payload = line.partition(b"\t")
            if not separator:
                raise ValueError("malformed RNA matrix row")
            values = np.fromstring(payload, dtype=np.int32, sep="\t")
            if len(values) != expected_columns:
                raise ValueError("RNA matrix row length mismatch")
            selected = values[selected_positions]
            nonzero = np.flatnonzero(selected)
            if len(nonzero):
                row_chunks.append(nonzero.astype(np.int32))
                column_chunks.append(np.full(len(nonzero), gene_index, dtype=np.int32))
                data_chunks.append(selected[nonzero].astype(np.int32))
            genes.append(gene_bytes.decode("utf-8"))
    rows = np.concatenate(row_chunks) if row_chunks else np.empty(0, dtype=np.int32)
    columns = (
        np.concatenate(column_chunks) if column_chunks else np.empty(0, dtype=np.int32)
    )
    data = np.concatenate(data_chunks) if data_chunks else np.empty(0, dtype=np.int32)
    matrix = sparse.coo_matrix(
        (data, (rows, columns)), shape=(len(selected_positions), len(genes))
    ).tocsr()
    return matrix, genes


def _write_lines_gzip(path: Path, values: list[str]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for value in values:
            handle.write(f"{value}\n")


def _file_record(path: Path, source: str, date: str) -> dict:
    return {
        "name": path.name,
        "path": str(path),
        "source": source,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "download_or_generation_date": date,
    }


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare GEO GSE108313 processed data")
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    args = parser.parse_args()
    manifest = prepare_gse108313(dataset_root=args.dataset_root)
    print(manifest.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
