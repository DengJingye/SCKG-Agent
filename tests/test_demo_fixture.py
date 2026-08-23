from __future__ import annotations

import hashlib

import anndata as ad
import numpy as np

from execution.demo_fixture import (
    SCRUBLET_PREVIEW_DEMO_SHAPE,
    SCRUBLET_PREVIEW_DEMO_VERSION,
    ensure_scrublet_preview_demo,
)


def test_scrublet_preview_demo_is_deterministic_and_source_bound(tmp_path):
    path = tmp_path / "scrublet_preview_demo.h5ad"
    first = ensure_scrublet_preview_demo(path)
    first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
    second = ensure_scrublet_preview_demo(path)

    assert second == first
    assert hashlib.sha256(second.read_bytes()).hexdigest() == first_hash
    data = ad.read_h5ad(path)
    assert data.shape == SCRUBLET_PREVIEW_DEMO_SHAPE
    assert "counts" in data.layers
    assert np.all(data.layers["counts"].data >= 0)
    assert np.allclose(
        data.layers["counts"].data,
        np.rint(data.layers["counts"].data),
    )
    assert data.uns["sckg_demo"]["version"] == SCRUBLET_PREVIEW_DEMO_VERSION
    assert bool(data.uns["sckg_demo"]["synthetic"]) is True
    assert bool(data.uns["sckg_demo"]["scientific_claim_allowed"]) is False


def test_scrublet_preview_demo_replaces_an_unrelated_file(tmp_path):
    path = tmp_path / "scrublet_preview_demo.h5ad"
    path.write_text("not an h5ad", encoding="utf-8")

    ensure_scrublet_preview_demo(path)

    data = ad.read_h5ad(path, backed="r")
    try:
        assert data.shape == SCRUBLET_PREVIEW_DEMO_SHAPE
        assert data.uns["sckg_demo"]["fixture"] == "scrublet_preview"
    finally:
        data.file.close()
