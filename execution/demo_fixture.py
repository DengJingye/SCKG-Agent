from __future__ import annotations

from pathlib import Path


SCRUBLET_PREVIEW_DEMO_FILENAME = "scrublet_preview_demo.h5ad"
SCRUBLET_PREVIEW_DEMO_VERSION = "1.0"
SCRUBLET_PREVIEW_DEMO_SEED = 20260814
SCRUBLET_PREVIEW_DEMO_SHAPE = (240, 500)


def ensure_scrublet_preview_demo(path: Path) -> Path:
    """Create or reuse the deterministic, synthetic Scrublet Preview fixture."""

    import anndata as ad
    import numpy as np
    import pandas as pd
    from scipy import sparse

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink():
            raise ValueError("demo fixture path must not be a symlink")
        try:
            existing = ad.read_h5ad(target, backed="r")
            try:
                marker = dict(existing.uns.get("sckg_demo", {}))
                valid = (
                    existing.shape == SCRUBLET_PREVIEW_DEMO_SHAPE
                    and "counts" in existing.layers
                    and marker.get("fixture") == "scrublet_preview"
                    and marker.get("version") == SCRUBLET_PREVIEW_DEMO_VERSION
                    and marker.get("synthetic") is True
                )
            finally:
                existing.file.close()
            if valid:
                return target
        except (OSError, ValueError, KeyError):
            pass

    rng = np.random.default_rng(SCRUBLET_PREVIEW_DEMO_SEED)
    n_cells, n_genes = SCRUBLET_PREVIEW_DEMO_SHAPE
    gene_rates = rng.gamma(shape=1.8, scale=1.2, size=n_genes)
    cell_depth = rng.lognormal(mean=0.0, sigma=0.3, size=n_cells)
    counts = rng.poisson(cell_depth[:, None] * gene_rates[None, :]).astype(
        np.int32
    )
    obs = pd.DataFrame(
        {
            "batch": ["batch_a"] * (n_cells // 2)
            + ["batch_b"] * (n_cells - n_cells // 2),
            "fixture_label": ["synthetic_singlet"] * n_cells,
        },
        index=[f"demo_cell_{index:04d}" for index in range(n_cells)],
    )
    var = pd.DataFrame(
        index=[f"demo_gene_{index:04d}" for index in range(n_genes)]
    )
    data = ad.AnnData(
        X=sparse.csr_matrix(np.log1p(counts).astype(np.float32)),
        obs=obs,
        var=var,
    )
    data.layers["counts"] = sparse.csr_matrix(counts)
    data.uns["sckg_demo"] = {
        "fixture": "scrublet_preview",
        "version": SCRUBLET_PREVIEW_DEMO_VERSION,
        "seed": SCRUBLET_PREVIEW_DEMO_SEED,
        "synthetic": True,
        "scientific_claim_allowed": False,
    }

    temporary = target.with_name(f".{target.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        data.write_h5ad(temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
