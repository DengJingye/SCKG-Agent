import anndata as ad
import numpy as np
import pandas as pd

from core.execution_models import IntegrationDatasetManifest
from execution.integration_scientific_dataset import build_integration_scientific_split


def test_scientific_split_is_stratified_disjoint_and_deterministic(tmp_path):
    rng = np.random.default_rng(7)
    obs = pd.DataFrame(
        {
            "batch": np.repeat(["a", "b", "c"], 60),
            "cell_type": np.tile(np.repeat(["x", "y", "z"], 20), 3),
        },
        index=[f"cell-{index}" for index in range(180)],
    )
    adata = ad.AnnData(X=rng.normal(size=(180, 6)), obs=obs)
    adata.obsm["X_pca"] = np.asarray(adata.X)
    path = tmp_path / "source.h5ad"
    adata.write_h5ad(path)
    manifest = IntegrationDatasetManifest(
        dataset_id="test-pancreas",
        accession="scIB-pancreas",
        title="test",
        source_url="https://example.test/source.h5ad",
        license="CC BY 4.0",
        downloaded_at="2026-07-16T00:00:00Z",
        source_file_path=str(path),
        source_file_sha256="a" * 64,
        processed_h5ad_path=str(path),
        processed_h5ad_sha256="b" * 64,
        n_cells=180,
        n_genes=6,
        batch_key="batch",
        label_key="cell_type",
        n_batches=3,
        n_labels=3,
    )
    split = build_integration_scientific_split(
        dataset=manifest,
        output_dir=tmp_path / "split",
        cells_per_split=60,
    )

    assert split.cell_overlap_count == 0
    assert split.development.probe_hash != split.evaluation.probe_hash
    assert split.development.cell_id_hash != split.evaluation.cell_id_hash
    assert split.development.n_batches == split.evaluation.n_batches == 3
