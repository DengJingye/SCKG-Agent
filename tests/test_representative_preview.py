from pathlib import Path

import anndata as ad
import pytest

from engine.data_intelligence import AnnDataBackedAdapter
from execution.representative_preview import RepresentativePreviewBuilder
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_preview_is_deterministic_stratified_and_preserves_source(tmp_path):
    source = write_phase1_fixtures(tmp_path / "fixtures")["counts_layer"]
    source_before = source.read_bytes()
    profile = AnnDataBackedAdapter().profile(
        path=source, artifact_id="pbmc", owner_user_id="alice"
    )
    builder = RepresentativePreviewBuilder()
    first = builder.build(
        source_path=source,
        profile=profile,
        output_dir=tmp_path / "previews" / "first",
        allowed_output_root=tmp_path / "previews",
        max_cells=20,
        random_seed=77,
        stratify_key="batch",
    )
    second = builder.build(
        source_path=source,
        profile=profile,
        output_dir=tmp_path / "previews" / "second",
        allowed_output_root=tmp_path / "previews",
        max_cells=20,
        random_seed=77,
        stratify_key="batch",
    )

    assert first.selected_obs_indices_hash == second.selected_obs_indices_hash
    assert first.selected_obs_ids_hash == second.selected_obs_ids_hash
    assert first.preview_strata_counts == {"batch_a": 10, "batch_b": 10}
    assert first.source_unchanged is True
    assert first.scientific_claim_allowed is False
    assert source.read_bytes() == source_before
    preview = ad.read_h5ad(
        tmp_path / "previews" / "first" / "representative_preview.h5ad"
    )
    assert preview.n_obs == 20
    assert bool(preview.uns["sckg_preview"]["preview_only"]) is True
    assert preview.uns["sckg_preview"]["selected_count_source"] == "layers/counts"


def test_preview_blocks_output_escape_and_ineligible_profile(tmp_path):
    source = write_phase1_fixtures(tmp_path / "fixtures")["scaled"]
    profile = AnnDataBackedAdapter().profile(
        path=source, artifact_id="scaled", owner_user_id="alice"
    )
    with pytest.raises(ValueError, match="not eligible"):
        RepresentativePreviewBuilder().build(
            source_path=source,
            profile=profile,
            output_dir=tmp_path / "outside",
            allowed_output_root=tmp_path / "allowed",
        )
