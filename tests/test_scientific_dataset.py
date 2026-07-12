import anndata as ad
import csv
import gzip
import numpy as np
import pandas as pd
from scipy import sparse

from execution.scientific_dataset import GSE108313Dataset, classify_hto_counts
from data_pipeline.prepare_gse108313 import _read_hto_counts


def test_hto_label_mapping_and_exclusions():
    counts = np.asarray(
        [
            [90, 5, 3, 2],
            [45, 45, 5, 5],
            [55, 19, 13, 13],
            [0, 0, 0, 0],
        ]
    )
    labels = classify_hto_counts(counts, ["A", "B", "C", "D"])

    assert labels["gold_label"].tolist() == [
        "singlet",
        "doublet",
        "excluded",
        "excluded",
    ]
    assert labels["exclusion_reason"].tolist() == ["", "", "ambiguous", "negative"]
    assert labels.loc[0, "hto_identity"] == "A"
    assert labels.loc[1, "hto_identity"] == "A+B"


def test_dataset_alignment_filter_and_limitations(tmp_path):
    obs = pd.DataFrame(index=["c1", "c2", "c3", "c4"])
    adata = ad.AnnData(
        X=sparse.csr_matrix(np.asarray([[1, 2], [3, 1], [1, 1], [2, 2]])),
        obs=obs,
        var=pd.DataFrame(index=["g1", "g2"]),
    )
    adata.layers["counts"] = adata.X.copy()
    adata.obsm["HTO_counts"] = np.asarray(
        [[90, 5, 3, 2], [45, 45, 5, 5], [55, 19, 13, 13], [0, 0, 0, 0]]
    )
    adata.uns["hto_names"] = ["A", "B", "C", "D"]
    source = tmp_path / "prepared.h5ad"
    adata.write_h5ad(source)
    output, report = GSE108313Dataset().label_and_filter(
        input_h5ad=source,
        output_h5ad=tmp_path / "labeled.h5ad",
        exclusion_path=tmp_path / "excluded.tsv",
        report_path=tmp_path / "labels.json",
    )

    filtered = ad.read_h5ad(output)
    assert list(filtered.obs_names) == ["c1", "c2"]
    assert filtered.obs["ground_truth_doublet"].tolist() == [False, True]
    assert report.singlet_count == 1
    assert report.doublet_count == 1
    assert report.excluded_count == 2
    assert report.cross_sample_doublets_only is True
    assert any("Same-donor" in item for item in report.limitations)
    assert filtered.uns["sckg_fixture"]["accession"] == "GSE108313"


def test_geo_hto_mapping_summary_rows_are_not_treated_as_tags(tmp_path):
    path = tmp_path / "hto.csv.gz"
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["", "cell-1", "cell-2"])
        for index, name in enumerate([f"Batch{letter}" for letter in "ABCDEFGH"]):
            writer.writerow([f"{name}-barcode", index + 1, index + 2])
        writer.writerow(["bad_struct", 100, 100])
        writer.writerow(["no_match", 200, 200])
        writer.writerow(["total_reads", 1000, 1000])
    barcodes, names, matrix = _read_hto_counts(path)

    assert barcodes == ["cell-1", "cell-2"]
    assert names == [f"Batch{letter}" for letter in "ABCDEFGH"]
    assert matrix.shape == (2, 8)
