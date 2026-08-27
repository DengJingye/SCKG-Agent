import anndata as ad
import numpy as np
import pandas as pd

from execution.scanpy_pbmc3k_pilot import (
    PBMC3K_ACCESSION,
    PBMC3K_EXPECTED,
    build_pbmc_marker_candidates,
)


def test_pbmc3k_sources_are_exact_and_roles_are_distinct():
    assert PBMC3K_ACCESSION == "Scanpy-PBMC3K"
    assert set(PBMC3K_EXPECTED) == {"pbmc3k_raw.h5ad", "pbmc3k.h5ad"}
    assert {item["role"] for item in PBMC3K_EXPECTED.values()} == {
        "raw_counts_full_workflow",
        "processed_resume_skip",
    }
    assert all(len(item["sha256"]) == 64 for item in PBMC3K_EXPECTED.values())


def test_pbmc_marker_candidates_require_observed_curated_markers():
    adata = ad.AnnData(
        X=np.ones((4, 4)),
        obs=pd.DataFrame(index=[f"cell-{index}" for index in range(4)]),
        var=pd.DataFrame(index=["CD3D", "IL7R", "MS4A1", "LYZ"]),
    )
    adata.uns["rank_genes_groups"] = {
        "names": np.rec.fromarrays(
            [
                np.asarray(["CD3D", "IL7R", "X", "Y"], dtype=object),
                np.asarray(["MS4A1", "CD79A", "X", "Y"], dtype=object),
            ],
            names=["0", "1"],
        )
    }

    candidates = build_pbmc_marker_candidates(adata)

    assert [(item.cluster_id, item.candidate_label) for item in candidates] == [
        ("0", "T cell"),
        ("1", "B cell"),
    ]
    assert all(
        item.evidence_source_ids == ["scanpy-official-pbmc3k-marker-panel-v1"]
        for item in candidates
    )


def test_pbmc_marker_candidates_preserve_unresolved_clusters():
    adata = ad.AnnData(
        X=np.ones((2, 3)),
        obs=pd.DataFrame(index=["cell-0", "cell-1"]),
        var=pd.DataFrame(index=["MKI67", "TYMS", "ZWINT"]),
    )
    adata.uns["rank_genes_groups"] = {
        "names": np.rec.fromarrays(
            [np.asarray(["MKI67", "TYMS", "ZWINT"], dtype=object)],
            names=["8"],
        )
    }

    candidate = build_pbmc_marker_candidates(adata)[0]

    assert candidate.cluster_id == "8"
    assert candidate.candidate_label == "Unresolved"
    assert candidate.status == "unknown"
