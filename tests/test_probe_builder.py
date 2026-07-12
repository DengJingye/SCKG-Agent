from pathlib import Path

import anndata as ad
import numpy as np
import pytest

from execution.probe_builder import ProbeBuilder
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_probe_builder_is_deterministic_and_preserves_source(tmp_path):
    fixtures = write_phase1_fixtures(tmp_path / "fixtures")
    source_before = fixtures["raw_x"].read_bytes()
    builder = ProbeBuilder()
    first = builder.build(
        source_path=fixtures["raw_x"],
        output_dir=tmp_path / "probes" / "first",
        profile_id="profile-1",
        fixture_id="phase1_raw_counts_x",
        allowed_output_root=tmp_path / "probes",
    )
    second = builder.build(
        source_path=fixtures["raw_x"],
        output_dir=tmp_path / "probes" / "second",
        profile_id="profile-1",
        fixture_id="phase1_raw_counts_x",
        allowed_output_root=tmp_path / "probes",
    )

    first_data = ad.read_h5ad(first.probe_artifact_path)
    second_data = ad.read_h5ad(second.probe_artifact_path)
    np.testing.assert_array_equal(first_data.X.toarray(), second_data.X.toarray())
    assert first.selected_obs_indices_hash == second.selected_obs_indices_hash
    assert first_data.obs["ground_truth_doublet"].sum() == first.n_synthetic_doublets
    assert first_data.uns["sckg_fixture"]["qualification_mode"]
    assert not first_data.uns["sckg_fixture"]["user_data"]
    assert fixtures["raw_x"].read_bytes() == source_before
    assert first.source_unchanged is True
    assert first.scientific_claim_allowed is False


def test_probe_builder_rejects_uncontrolled_output_and_non_synthetic_source(tmp_path):
    fixtures = write_phase1_fixtures(tmp_path / "fixtures")
    with pytest.raises(ValueError, match="escapes"):
        ProbeBuilder().build(
            source_path=fixtures["raw_x"],
            output_dir=tmp_path / "outside",
            profile_id="profile-1",
            fixture_id="phase1_raw_counts_x",
            allowed_output_root=tmp_path / "allowed",
        )


def test_development_and_evaluation_probes_are_independent_and_cover_pairing_modes(tmp_path):
    fixtures = write_phase1_fixtures(tmp_path / "fixtures")
    builder = ProbeBuilder()
    development = builder.build(
        source_path=fixtures["raw_x"],
        output_dir=tmp_path / "probes" / "development",
        profile_id="profile-1",
        fixture_id="phase1_raw_counts_x",
        random_seed=101,
        split_role="development",
        pairing_strategy="mixed",
        cluster_key="batch",
        allowed_output_root=tmp_path / "probes",
    )
    evaluation = builder.build(
        source_path=fixtures["raw_x"],
        output_dir=tmp_path / "probes" / "evaluation",
        profile_id="profile-1",
        fixture_id="phase1_raw_counts_x",
        random_seed=202,
        split_role="evaluation",
        pairing_strategy="between_cluster",
        cluster_key="batch",
        allowed_output_root=tmp_path / "probes",
    )
    within = builder.build(
        source_path=fixtures["raw_x"],
        output_dir=tmp_path / "probes" / "within",
        profile_id="profile-1",
        fixture_id="phase1_raw_counts_x",
        random_seed=303,
        split_role="development",
        pairing_strategy="within_cluster",
        cluster_key="batch",
        allowed_output_root=tmp_path / "probes",
    )

    assert development.random_seed != evaluation.random_seed
    assert development.probe_hash != evaluation.probe_hash
    assert development.ground_truth_hash != evaluation.ground_truth_hash
    assert development.selected_obs_indices_hash != evaluation.selected_obs_indices_hash
    dev_classes = set(
        ad.read_h5ad(development.probe_artifact_path)
        .obs["synthetic_pairing_class"]
        .dropna()
    )
    eval_classes = set(
        ad.read_h5ad(evaluation.probe_artifact_path)
        .obs["synthetic_pairing_class"]
        .dropna()
    )
    within_classes = set(
        ad.read_h5ad(within.probe_artifact_path)
        .obs["synthetic_pairing_class"]
        .dropna()
    )
    assert {"homotypic", "heterotypic"}.issubset(dev_classes)
    assert eval_classes == {"heterotypic"}
    assert within_classes == {"homotypic"}

    data = ad.read_h5ad(fixtures["raw_x"])
    data.uns["sckg_fixture"]["synthetic"] = False
    data.write_h5ad(fixtures["raw_x"])
    with pytest.raises(ValueError, match="synthetic"):
        ProbeBuilder().build(
            source_path=fixtures["raw_x"],
            output_dir=tmp_path / "allowed" / "probe",
            profile_id="profile-1",
            fixture_id="phase1_raw_counts_x",
            allowed_output_root=tmp_path / "allowed",
        )
