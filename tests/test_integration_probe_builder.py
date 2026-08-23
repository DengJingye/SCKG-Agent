import anndata as ad
import numpy as np

from execution.integration_probe_builder import IntegrationProbeBuilder


def test_integration_probes_are_balanced_independent_and_source_safe(tmp_path):
    root = tmp_path / "probes"
    root.mkdir()
    builder = IntegrationProbeBuilder()
    development = builder.build(
        output_dir=root / "development",
        allowed_output_root=root,
        split_role="development",
        random_seed=101,
    )
    evaluation = builder.build(
        output_dir=root / "evaluation",
        allowed_output_root=root,
        split_role="evaluation",
        random_seed=202,
    )
    dev = ad.read_h5ad(development.probe_artifact_path)

    assert development.probe_hash != evaluation.probe_hash
    assert development.selected_obs_indices_hash != evaluation.selected_obs_indices_hash
    assert dev.obs["batch"].value_counts().nunique() == 1
    assert dev.obs["cell_type"].value_counts().nunique() == 1
    assert dev.obs_names.str.startswith("development-").all()
    assert np.isfinite(dev.obsm["X_pca"]).all()
    assert development.source_unchanged is True
    assert development.scientific_claim_allowed is False
