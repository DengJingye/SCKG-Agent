from __future__ import annotations

import json

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from execution.annotation_scientific_dataset import (
    Zheng68KDatasetService,
    build_label_mapping,
    load_label_mapping,
)
from tests.annotation_helpers import GENES, build_reference


def test_zheng68k_validation_and_split_are_frozen_and_disjoint(tmp_path):
    dataset_path = _write_dataset(tmp_path / "zheng68k.h5ad")
    reference = build_reference(tmp_path / "reference")
    mapping = build_label_mapping(
        mapping_id="zheng68k-to-sckg-v1",
        version="1.0",
        mapping={
            "B cells": "B_cell",
            "T cells": "T_cell",
            "NK cells": "NK_cell",
            "Monocytes": "Monocyte",
        },
    )
    service = Zheng68KDatasetService()
    manifest = service.validate(
        dataset_path=dataset_path,
        label_key="source_cell_type",
        source_url="https://example.invalid/zheng68k",
        license_name="test fixture only",
    )
    split = service.split(
        dataset_manifest=manifest,
        label_mapping=mapping,
        reference=reference,
        output_dir=tmp_path / "split",
        split_seed=77,
    )

    development = ad.read_h5ad(split.development.path)
    evaluation = ad.read_h5ad(split.evaluation.path)
    assert split.cell_overlap_count == 0
    assert set(development.obs_names).isdisjoint(evaluation.obs_names)
    assert set(development.obs["ground_truth_cell_type"]) == {
        "B_cell",
        "T_cell",
        "NK_cell",
        "Monocyte",
    }
    assert split.development.reference_digest == reference.sha256
    assert split.evaluation.label_mapping_digest == mapping.mapping_digest
    assert bool(development.uns["sckg_fixture"]["user_data"]) is False


def test_label_mapping_digest_and_ai_boundary_are_enforced(tmp_path):
    mapping = build_label_mapping(
        mapping_id="mapping-v1",
        version="1",
        mapping={"B cells": "B_cell", "T cells": "T_cell"},
    )
    path = tmp_path / "mapping.json"
    path.write_text(mapping.model_dump_json(indent=2) + "\n", encoding="utf-8")
    assert load_label_mapping(path).mapping_digest == mapping.mapping_digest

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["mapping"]["T cells"] = "B_cell"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_label_mapping(path)

    ai_mapping = mapping.model_copy(update={"ai_generated": True})
    path.write_text(ai_mapping.model_dump_json(indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch|AI-generated"):
        load_label_mapping(path)


def _write_dataset(path):
    labels = np.repeat(["B cells", "T cells", "NK cells", "Monocytes"], 12)
    rng = np.random.default_rng(42)
    counts = sparse.csr_matrix(rng.poisson(2.0, size=(len(labels), len(GENES))))
    totals = np.asarray(counts.sum(axis=1)).reshape(-1)
    normalized = counts.multiply((10_000.0 / totals)[:, None])
    normalized.data = np.log1p(normalized.data)
    adata = ad.AnnData(
        X=normalized.tocsr(),
        obs=pd.DataFrame(
            {"source_cell_type": labels},
            index=[f"barcode-{index:04d}" for index in range(len(labels))],
        ),
        var=pd.DataFrame(index=GENES),
    )
    adata.layers["counts"] = counts
    adata.uns["sckg_dataset"] = {
        "accession": "Zheng68K",
        "frozen": True,
        "user_data": False,
    }
    adata.write_h5ad(path)
    return path
