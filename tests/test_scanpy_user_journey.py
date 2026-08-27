from __future__ import annotations

import json
from pathlib import Path

from execution.scanpy_synthetic_fixture import generate_scanpy_core_synthetic_fixture
from execution.scanpy_user_journey import run_scanpy_synthetic_user_journey


def test_complete_scanpy_synthetic_user_journey(tmp_path):
    fixture, _, manifest = generate_scanpy_core_synthetic_fixture(
        tmp_path / "fixture"
    )
    result = run_scanpy_synthetic_user_journey(
        journey_id="post-s6-test",
        fixture_path=fixture,
        fixture_manifest=manifest,
        work_root=tmp_path / "journey",
        package_root=tmp_path / "packages",
    )

    assert result.source_unchanged is True
    assert result.execution_policy == "disabled"
    assert result.execution_request_count_before_qualification == 0
    assert result.package_complete is True
    assert result.package_hashes_valid is True
    assert {route.scale_enabled for route in result.routes} == {False, True}
    assert all(route.run_status == "succeeded" for route in result.routes)
    assert all(route.validation_passed for route in result.routes)
    assert all(route.output_cells < route.input_cells for route in result.routes)
    assert all(route.marker_source == "full_gene_unscaled_log1p" for route in result.routes)
    assert all(route.annotation_confirmation_required for route in result.routes)
    assert not any(route.final_annotation_present for route in result.routes)
    assert all(len(route.plot_paths) == 4 for route in result.routes)
    assert all(route.marker_candidate_count > 0 for route in result.routes)
    assert next(route for route in result.routes if route.scale_enabled).pca_source == "scaled_hvg"
    assert next(route for route in result.routes if not route.scale_enabled).pca_source == "log_hvg"
    for route in result.routes:
        assert "08_neighbors" in route.lineage_steps
        assert "09_umap" in route.lineage_steps
        assert "10_leiden" in route.lineage_steps
        assert "11_markers" in route.lineage_steps
        assert route.lineage_hashes_valid is True
        assert Path(route.notebook_path).is_file()

    package_manifest = json.loads(
        (Path(result.package_path) / "reproducibility_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert package_manifest["reproducibility_level"] == "Level 2"
    assert package_manifest["user_data_copied"] is False
