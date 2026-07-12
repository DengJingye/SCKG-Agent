from __future__ import annotations

import hashlib

import pytest

from engine.data_profiler import AnnDataProfiler
from tests.fixtures.anndata_factory import write_phase1_fixtures


@pytest.fixture()
def phase1_anndata_files(tmp_path):
    return write_phase1_fixtures(tmp_path)


def _matrix(profile, matrix_id):
    return next(item for item in profile.matrix_profiles if item.matrix_id == matrix_id)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_raw_counts_in_x_are_selected_without_mutation(phase1_anndata_files):
    path = phase1_anndata_files["raw_x"]
    before = _sha256(path)
    profiler = AnnDataProfiler()

    first = profiler.profile(path, batch_key="batch")
    second = profiler.profile(path, batch_key="batch")

    assert first.selected_count_source == "X"
    assert _matrix(first, "X").inferred_state == "raw_counts"
    assert first.count_source_selection.method == "deterministic_rule"
    assert first.batch_count == 2
    assert first.blocking_errors == []
    assert first.model_dump() == second.model_dump()
    assert _sha256(path) == before


def test_counts_layer_has_priority_over_log1p_x(phase1_anndata_files):
    profile = AnnDataProfiler().profile(phase1_anndata_files["counts_layer"])

    assert _matrix(profile, "X").inferred_state == "log_normalized"
    assert _matrix(profile, "layers/counts").inferred_state == "raw_counts"
    assert profile.selected_count_source == "layers/counts"
    assert profile.count_source_selection.method == "explicit_layer_name"
    assert profile.blocking_errors == []


def test_scaled_x_without_counts_is_blocking(phase1_anndata_files):
    profile = AnnDataProfiler().profile(phase1_anndata_files["scaled"])

    assert _matrix(profile, "X").inferred_state == "scaled"
    assert profile.selected_count_source is None
    assert profile.count_source_selection.method == "unresolved"
    assert "count_source_unresolved" in profile.blocking_errors


def test_raw_x_is_preserved_and_selected_when_x_is_log1p(phase1_anndata_files):
    profile = AnnDataProfiler().profile(phase1_anndata_files["raw_x_distinct"])

    assert _matrix(profile, "X").inferred_state == "log_normalized"
    assert _matrix(profile, "raw.X").inferred_state == "raw_counts"
    assert profile.selected_count_source == "raw.X"
    assert profile.raw_exists is True


@pytest.mark.parametrize(
    ("fixture_name", "expected_error"),
    [
        ("corrupt", "anndata_read_failed"),
        ("nan", "count_source_unresolved"),
        ("inf", "count_source_unresolved"),
        ("empty", "empty_anndata"),
    ],
)
def test_invalid_inputs_return_blocking_profiles(
    phase1_anndata_files,
    fixture_name,
    expected_error,
):
    profile = AnnDataProfiler().profile(phase1_anndata_files[fixture_name])

    assert profile.is_blocked
    assert any(item.startswith(expected_error) for item in profile.blocking_errors)
    assert profile.selected_count_source is None


def test_missing_input_is_blocking(tmp_path):
    profile = AnnDataProfiler().profile(tmp_path / "missing.h5ad")

    assert profile.object_type == "unknown"
    assert "input_file_missing" in profile.blocking_errors
    assert "count_source_unresolved" in profile.blocking_errors


def test_duplicate_names_are_reported_as_warnings(phase1_anndata_files):
    profile = AnnDataProfiler().profile(phase1_anndata_files["duplicate_names"])

    assert "duplicate_obs_names" in profile.warnings
    assert "duplicate_var_names" in profile.warnings
    assert profile.selected_count_source == "X"


def test_cell_budget_excess_is_reported_without_changing_count_selection(phase1_anndata_files):
    profile = AnnDataProfiler().profile(phase1_anndata_files["raw_x"], max_cells=10)

    assert "cell_count_exceeds_budget:48>10" in profile.warnings
    assert profile.selected_count_source == "X"
    assert profile.blocking_errors == []
