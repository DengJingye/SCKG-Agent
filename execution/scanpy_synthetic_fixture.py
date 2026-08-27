from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from pydantic import Field
from scipy import sparse

from core.execution_models import StrictModel


SCANPY_SYNTHETIC_FIXTURE_VERSION = "1.0.0"
SCANPY_SYNTHETIC_FIXTURE_SEED = 20260824
SCANPY_SYNTHETIC_N_CELLS = 180
SCANPY_SYNTHETIC_N_GENES = 240


class ScanpySyntheticFixtureManifest(StrictModel):
    schema_version: str = "sckg-scanpy-synthetic-fixture-v1"
    fixture_id: str
    fixture_version: str
    seed: int
    h5ad_filename: str
    h5ad_sha256: str = Field(min_length=64, max_length=64)
    file_size_bytes: int = Field(gt=0)
    shape: list[int] = Field(min_length=2, max_length=2)
    groups: list[str] = Field(min_length=3)
    batches: list[str] = Field(min_length=2)
    marker_genes: dict[str, list[str]]
    mitochondrial_genes: list[str]
    batch_shift_genes: list[str]
    low_quality_cell_ids: list[str]
    obs_fields: list[str]
    var_fields: list[str]
    count_model: str
    purpose: str
    scientific_claim_allowed: bool = False
    user_data: bool = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScanpyIntermediateFixtureRecord(StrictModel):
    state_id: str
    h5ad_filename: str
    h5ad_sha256: str = Field(min_length=64, max_length=64)
    file_size_bytes: int = Field(gt=0)
    shape: list[int] = Field(min_length=2, max_length=2)
    expected_representations: list[str]


class ScanpyIntermediateFixtureManifest(StrictModel):
    schema_version: str = "sckg-scanpy-intermediate-fixtures-v1"
    source_fixture_id: str
    source_h5ad_sha256: str = Field(min_length=64, max_length=64)
    seed: int
    states: list[ScanpyIntermediateFixtureRecord] = Field(min_length=3)
    purpose: str
    scientific_claim_allowed: bool = False
    user_data: bool = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def generate_scanpy_core_synthetic_fixture(
    output_dir: str | Path,
    *,
    seed: int = SCANPY_SYNTHETIC_FIXTURE_SEED,
    overwrite: bool = False,
) -> tuple[Path, Path, ScanpySyntheticFixtureManifest]:
    """Create a small structured UMI-count fixture and its provenance manifest."""

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    h5ad_path = root / "scanpy_core_synthetic_v1.h5ad"
    manifest_path = root / "fixture_manifest.json"
    if not overwrite and (h5ad_path.exists() or manifest_path.exists()):
        raise FileExistsError("versioned synthetic fixture already exists")

    adata, design = _build_structured_counts(seed)
    temporary = h5ad_path.with_suffix(".h5ad.tmp")
    adata.write_h5ad(temporary, compression="gzip")
    temporary.replace(h5ad_path)
    manifest = ScanpySyntheticFixtureManifest(
        fixture_id="scanpy-core-structured-synthetic-v1",
        fixture_version=SCANPY_SYNTHETIC_FIXTURE_VERSION,
        seed=seed,
        h5ad_filename=h5ad_path.name,
        h5ad_sha256=_sha256(h5ad_path),
        file_size_bytes=h5ad_path.stat().st_size,
        shape=[adata.n_obs, adata.n_vars],
        groups=design["groups"],
        batches=design["batches"],
        marker_genes=design["marker_genes"],
        mitochondrial_genes=design["mitochondrial_genes"],
        batch_shift_genes=design["batch_shift_genes"],
        low_quality_cell_ids=design["low_quality_cell_ids"],
        obs_fields=list(adata.obs.columns),
        var_fields=list(adata.var.columns),
        count_model="gamma-poisson-like discrete UMI counts with planted group, library-size, QC and batch effects",
        purpose=(
            "Engineering validation of profiling, representation transitions, clustering, "
            "marker recovery, annotation candidate review and reproducibility."
        ),
    )
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return h5ad_path, manifest_path, manifest


def load_scanpy_synthetic_manifest(path: str | Path) -> ScanpySyntheticFixtureManifest:
    return ScanpySyntheticFixtureManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def derive_scanpy_core_intermediate_fixtures(
    source_path: str | Path,
    source_manifest: ScanpySyntheticFixtureManifest,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> tuple[Path, ScanpyIntermediateFixtureManifest]:
    """Derive deterministic resumable states from the versioned synthetic counts."""

    import igraph as ig
    import leidenalg
    import umap
    from sklearn.decomposition import PCA
    from sklearn.neighbors import NearestNeighbors

    source = Path(source_path).expanduser().resolve(strict=True)
    if _sha256(source) != source_manifest.h5ad_sha256:
        raise ValueError("source fixture hash does not match its manifest")
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "intermediate_fixture_manifest.json"
    state_paths = {
        "log_normalized_ready": root / "scanpy_core_log_normalized_ready.h5ad",
        "pca_ready": root / "scanpy_core_pca_ready.h5ad",
        "cluster_ready": root / "scanpy_core_cluster_ready.h5ad",
    }
    if not overwrite and (
        manifest_path.exists() or any(path.exists() for path in state_paths.values())
    ):
        raise FileExistsError("versioned intermediate fixtures already exist")

    adata = ad.read_h5ad(source)
    counts = sparse.csr_matrix(adata.layers["counts"])
    total_counts = np.asarray(counts.sum(axis=1)).ravel()
    detected_genes = np.asarray((counts > 0).sum(axis=1)).ravel()
    mt_mask = adata.var_names.str.startswith("MT-")
    mitochondrial_counts = np.asarray(counts[:, mt_mask].sum(axis=1)).ravel()
    adata.var["mt"] = mt_mask
    adata.obs["total_counts"] = total_counts
    adata.obs["n_genes_by_counts"] = detected_genes
    adata.obs["pct_counts_mt"] = np.divide(
        mitochondrial_counts * 100.0,
        total_counts,
        out=np.zeros_like(total_counts, dtype=float),
        where=total_counts > 0,
    )
    keep_cells = (
        (np.asarray(adata.obs["n_genes_by_counts"]) >= 70)
        & (np.asarray(adata.obs["pct_counts_mt"]) <= 35.0)
    )
    adata = adata[keep_cells].copy()
    keep_genes = np.asarray((adata.layers["counts"] > 0).sum(axis=0)).ravel() >= 3
    adata = adata[:, keep_genes].copy()
    adata.layers["filtered_counts"] = adata.layers["counts"].copy()
    filtered_counts = sparse.csr_matrix(adata.layers["counts"])
    filtered_totals = np.asarray(filtered_counts.sum(axis=1)).ravel()
    normalization = np.divide(
        1e4,
        filtered_totals,
        out=np.zeros_like(filtered_totals, dtype=float),
        where=filtered_totals > 0,
    )
    normalized = sparse.diags(normalization) @ filtered_counts
    log1p = normalized.tocsr(copy=True)
    log1p.data = np.log1p(log1p.data)
    adata.X = log1p
    adata.layers["log1p"] = adata.X.copy()
    adata.uns["sckg_intermediate_state"] = {
        "state_id": "log_normalized_ready",
        "source_fixture_hash": source_manifest.h5ad_sha256,
        "seed": source_manifest.seed,
    }
    _write_h5ad_atomic(adata, state_paths["log_normalized_ready"])

    pca_ready = adata.copy()
    log_dense = np.asarray(pca_ready.X.toarray(), dtype=np.float64)
    gene_variance = np.var(log_dense, axis=0)
    hvg_count = min(90, pca_ready.n_vars)
    hvg_indices = np.argsort(gene_variance, kind="stable")[-hvg_count:]
    hvg = np.zeros(pca_ready.n_vars, dtype=bool)
    hvg[hvg_indices] = True
    pca_ready.var["highly_variable"] = hvg
    hvg_values = log_dense[:, hvg]
    standard_deviation = np.std(hvg_values, axis=0)
    standard_deviation[standard_deviation == 0] = 1.0
    scaled_hvg = np.clip(
        (hvg_values - np.mean(hvg_values, axis=0)) / standard_deviation,
        -10,
        10,
    )
    n_components = min(25, scaled_hvg.shape[0] - 1, scaled_hvg.shape[1] - 1)
    pca_model = PCA(n_components=n_components, random_state=source_manifest.seed)
    pca_ready.obsm["X_pca"] = pca_model.fit_transform(scaled_hvg).astype(np.float32)
    pca_ready.uns["pca"] = {
        "variance": pca_model.explained_variance_.astype(float),
        "variance_ratio": pca_model.explained_variance_ratio_.astype(float),
    }
    pca_ready.uns["sckg_intermediate_state"] = {
        "state_id": "pca_ready",
        "source_fixture_hash": source_manifest.h5ad_sha256,
        "pca_source": "scaled_hvg",
        "seed": source_manifest.seed,
    }
    _write_h5ad_atomic(pca_ready, state_paths["pca_ready"])

    cluster_ready = pca_ready.copy()
    n_neighbors = min(12, cluster_ready.n_obs - 1)
    neighbor_model = NearestNeighbors(n_neighbors=n_neighbors + 1)
    neighbor_model.fit(cluster_ready.obsm["X_pca"])
    distances, indices = neighbor_model.kneighbors(cluster_ready.obsm["X_pca"])
    rows = np.repeat(np.arange(cluster_ready.n_obs), n_neighbors)
    columns = indices[:, 1:].reshape(-1)
    distance_values = distances[:, 1:].reshape(-1)
    distance_graph = sparse.csr_matrix(
        (distance_values, (rows, columns)),
        shape=(cluster_ready.n_obs, cluster_ready.n_obs),
    ).maximum(
        sparse.csr_matrix(
            (distance_values, (columns, rows)),
            shape=(cluster_ready.n_obs, cluster_ready.n_obs),
        )
    )
    positive = distance_values[distance_values > 0]
    scale = float(np.median(positive)) if positive.size else 1.0
    weights = np.exp(-distance_values / max(scale, 1e-12))
    connectivity_graph = sparse.csr_matrix(
        (weights, (rows, columns)), shape=(cluster_ready.n_obs, cluster_ready.n_obs)
    ).maximum(
        sparse.csr_matrix(
            (weights, (columns, rows)), shape=(cluster_ready.n_obs, cluster_ready.n_obs)
        )
    )
    cluster_ready.obsp["distances"] = distance_graph
    cluster_ready.obsp["connectivities"] = connectivity_graph
    cluster_ready.obsm["X_umap"] = umap.UMAP(
        n_neighbors=n_neighbors,
        n_components=2,
        random_state=source_manifest.seed,
        transform_seed=source_manifest.seed,
    ).fit_transform(cluster_ready.obsm["X_pca"]).astype(np.float32)
    upper = sparse.triu(connectivity_graph, k=1).tocoo()
    graph = ig.Graph(
        n=cluster_ready.n_obs,
        edges=list(zip(upper.row.tolist(), upper.col.tolist())),
        directed=False,
    )
    partition = leidenalg.find_partition(
        graph,
        leidenalg.RBConfigurationVertexPartition,
        weights=upper.data.tolist(),
        resolution_parameter=0.55,
        seed=source_manifest.seed,
    )
    cluster_ready.obs["leiden"] = pd.Categorical(
        [str(value) for value in partition.membership]
    )
    cluster_ready.uns["neighbors"] = {
        "params": {
            "n_neighbors": n_neighbors,
            "method": "deterministic_sklearn_knn_fixture",
            "use_rep": "X_pca",
        }
    }
    cluster_ready.uns["sckg_intermediate_state"] = {
        "state_id": "cluster_ready",
        "source_fixture_hash": source_manifest.h5ad_sha256,
        "neighbor_source": "pca",
        "derivation": "sklearn_knn+umap_learn+leidenalg",
        "seed": source_manifest.seed,
    }
    _write_h5ad_atomic(cluster_ready, state_paths["cluster_ready"])

    expected = {
        "log_normalized_ready": [
            "raw_counts",
            "qc_metrics",
            "filtered_counts",
            "log1p_normalized",
        ],
        "pca_ready": [
            "raw_counts",
            "filtered_counts",
            "log1p_normalized",
            "hvg_selection",
            "pca",
        ],
        "cluster_ready": [
            "raw_counts",
            "filtered_counts",
            "log1p_normalized",
            "hvg_selection",
            "pca",
            "neighbor_graph",
            "umap",
            "cluster_labels",
        ],
    }
    records = [
        ScanpyIntermediateFixtureRecord(
            state_id=state_id,
            h5ad_filename=path.name,
            h5ad_sha256=_sha256(path),
            file_size_bytes=path.stat().st_size,
            shape=[ad.read_h5ad(path, backed="r").n_obs, ad.read_h5ad(path, backed="r").n_vars],
            expected_representations=expected[state_id],
        )
        for state_id, path in state_paths.items()
    ]
    manifest = ScanpyIntermediateFixtureManifest(
        source_fixture_id=source_manifest.fixture_id,
        source_h5ad_sha256=source_manifest.h5ad_sha256,
        seed=source_manifest.seed,
        states=records,
        purpose=(
            "Engineering validation of profile, reuse, skip, resume and stale-state "
            "handling. These fixtures are not scientific evidence."
        ),
    )
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path, manifest


def _build_structured_counts(seed: int) -> tuple[ad.AnnData, dict[str, object]]:
    rng = np.random.default_rng(seed)
    groups = ["group_a", "group_b", "group_c"]
    batches = ["batch_1", "batch_2"]
    cells_per_group = SCANPY_SYNTHETIC_N_CELLS // len(groups)
    group_labels = np.repeat(groups, cells_per_group)
    batch_labels = np.tile(np.repeat(batches, cells_per_group // 2), len(groups))
    permutation = rng.permutation(SCANPY_SYNTHETIC_N_CELLS)
    group_labels = group_labels[permutation]
    batch_labels = batch_labels[permutation]

    mitochondrial_genes = [f"MT-SYN{index:02d}" for index in range(8)]
    marker_genes = {
        group: [f"{group.upper()}_MARKER_{index:02d}" for index in range(12)]
        for group in groups
    }
    batch_shift_genes = [f"BATCH_SHIFT_{index:02d}" for index in range(12)]
    designed = (
        mitochondrial_genes
        + [gene for group in groups for gene in marker_genes[group]]
        + batch_shift_genes
    )
    background_genes = [
        f"GENE_{index:03d}"
        for index in range(SCANPY_SYNTHETIC_N_GENES - len(designed))
    ]
    gene_names = designed + background_genes

    base_expression = rng.gamma(shape=1.6, scale=0.55, size=SCANPY_SYNTHETIC_N_GENES)
    base_expression[: len(mitochondrial_genes)] = 0.35
    library_factors = rng.lognormal(mean=0.0, sigma=0.32, size=SCANPY_SYNTHETIC_N_CELLS)
    low_quality_indices = np.sort(rng.choice(SCANPY_SYNTHETIC_N_CELLS, size=9, replace=False))
    library_factors[low_quality_indices] *= 0.12
    rates = library_factors[:, None] * base_expression[None, :]

    marker_offset = len(mitochondrial_genes)
    for group_index, group in enumerate(groups):
        rows = group_labels == group
        start = marker_offset + group_index * len(marker_genes[group])
        stop = start + len(marker_genes[group])
        rates[rows, start:stop] += library_factors[rows, None] * 6.5

    batch_start = marker_offset + sum(len(value) for value in marker_genes.values())
    batch_rows = batch_labels == "batch_2"
    rates[batch_rows, batch_start : batch_start + len(batch_shift_genes)] *= 2.0
    rates[low_quality_indices, : len(mitochondrial_genes)] += 2.5
    counts = rng.poisson(np.maximum(rates, 0.0)).astype(np.int32)

    cell_ids = [f"synthetic_cell_{index:04d}" for index in range(SCANPY_SYNTHETIC_N_CELLS)]
    low_quality_ids = [cell_ids[index] for index in low_quality_indices]
    obs = pd.DataFrame(
        {
            "synthetic_group": pd.Categorical(group_labels, categories=groups),
            "batch": pd.Categorical(batch_labels, categories=batches),
            "expected_low_quality": np.isin(
                np.arange(SCANPY_SYNTHETIC_N_CELLS), low_quality_indices
            ),
            "library_size_factor": library_factors.astype(np.float32),
        },
        index=cell_ids,
    )
    marker_group = [""] * SCANPY_SYNTHETIC_N_GENES
    gene_role = ["background"] * SCANPY_SYNTHETIC_N_GENES
    for index in range(len(mitochondrial_genes)):
        gene_role[index] = "mitochondrial"
    for group_index, group in enumerate(groups):
        start = marker_offset + group_index * len(marker_genes[group])
        stop = start + len(marker_genes[group])
        for index in range(start, stop):
            marker_group[index] = group
            gene_role[index] = "planted_marker"
    for index in range(batch_start, batch_start + len(batch_shift_genes)):
        gene_role[index] = "batch_shift"
    var = pd.DataFrame(
        {
            "gene_role": pd.Categorical(gene_role),
            "marker_group": pd.Categorical(marker_group),
            "mitochondrial": [name.startswith("MT-") for name in gene_names],
        },
        index=gene_names,
    )
    adata = ad.AnnData(X=sparse.csr_matrix(counts), obs=obs, var=var)
    adata.layers["counts"] = sparse.csr_matrix(counts.copy())
    adata.uns["sckg_fixture"] = {
        "fixture_id": "scanpy-core-structured-synthetic-v1",
        "fixture_version": SCANPY_SYNTHETIC_FIXTURE_VERSION,
        "seed": int(seed),
        "synthetic": True,
        "maintainer_approved": True,
        "user_data": False,
        "scientific_claim_allowed": False,
        "marker_design": marker_genes,
    }
    return adata, {
        "groups": groups,
        "batches": batches,
        "marker_genes": marker_genes,
        "mitochondrial_genes": mitochondrial_genes,
        "batch_shift_genes": batch_shift_genes,
        "low_quality_cell_ids": low_quality_ids,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_h5ad_atomic(adata: ad.AnnData, path: Path) -> None:
    temporary = path.with_suffix(".h5ad.tmp")
    adata.write_h5ad(temporary, compression="gzip")
    temporary.replace(path)
