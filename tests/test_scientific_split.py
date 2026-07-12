import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from execution.scientific_dataset import GSE108313Dataset


def test_scientific_split_is_deterministic_stratified_and_non_overlapping(tmp_path):
    labels = ["singlet"] * 12 + ["doublet"] * 8
    identities = ["A"] * 6 + ["B"] * 6 + ["A+B"] * 4 + ["A+C"] * 4
    obs = pd.DataFrame(
        {
            "gold_label": labels,
            "hto_identity": identities,
            "ground_truth_doublet": [label == "doublet" for label in labels],
        },
        index=[f"cell-{index:02d}" for index in range(20)],
    )
    adata = ad.AnnData(
        X=sparse.csr_matrix(np.ones((20, 4), dtype=np.int32)),
        obs=obs,
        var=pd.DataFrame(index=[f"g{index}" for index in range(4)]),
    )
    source = tmp_path / "labeled.h5ad"
    adata.write_h5ad(source)
    dataset = GSE108313Dataset()
    first = dataset.split(
        labeled_h5ad=source,
        output_dir=tmp_path / "first",
        split_seed=123,
    )
    second = dataset.split(
        labeled_h5ad=source,
        output_dir=tmp_path / "second",
        split_seed=123,
    )

    first_dev = ad.read_h5ad(first.development.path)
    first_eval = ad.read_h5ad(first.evaluation.path)
    second_dev = ad.read_h5ad(second.development.path)
    assert set(first_dev.obs_names).isdisjoint(first_eval.obs_names)
    assert set(first_dev.obs_names) == set(second_dev.obs_names)
    assert first.barcode_overlap_count == 0
    assert first.manifest_hash == second.manifest_hash
    assert first.development.barcode_hash == second.development.barcode_hash
    assert first.development.singlet_count > 0
    assert first.development.doublet_count > 0
    assert first.evaluation.singlet_count > 0
    assert first.evaluation.doublet_count > 0
