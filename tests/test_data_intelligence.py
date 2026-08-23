from pathlib import Path

import pytest

from engine.data_intelligence import AnnDataBackedAdapter
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_backed_profile_selects_counts_without_materializing_full_matrix(tmp_path):
    fixtures = write_phase1_fixtures(tmp_path / "fixtures")
    profile = AnnDataBackedAdapter(
        max_sampled_rows=4, max_sampled_columns=7
    ).profile(
        path=fixtures["counts_layer"],
        artifact_id="pbmc",
        owner_user_id="alice",
    )

    assert profile.storage_mode == "backed_read_only"
    assert profile.full_matrix_materialized is False
    assert profile.selected_count_source == "layers/counts"
    assert profile.preview_capability == "supported"
    assert max(item.sampled_value_count for item in profile.matrices) <= 28
    assert profile.redacted_path == ".../log1p_x_counts_layer.h5ad"
    assert "batch" in profile.batch_candidates


def test_backed_profile_blocks_scaled_input_and_rejects_non_h5ad(tmp_path):
    fixtures = write_phase1_fixtures(tmp_path / "fixtures")
    profile = AnnDataBackedAdapter().profile(
        path=fixtures["scaled"], artifact_id="scaled", owner_user_id="alice"
    )
    assert profile.preview_capability == "blocked"
    assert "count_source_unresolved" in profile.blocking_errors

    text = tmp_path / "input.txt"
    text.write_text("not h5ad", encoding="utf-8")
    with pytest.raises(ValueError, match="h5ad"):
        AnnDataBackedAdapter().profile(
            path=text, artifact_id="text", owner_user_id="alice"
        )
