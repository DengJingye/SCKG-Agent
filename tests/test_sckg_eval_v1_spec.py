from __future__ import annotations

import json
from pathlib import Path

from eval.build_sckg_eval_v1_spec import (
    MATRIX_PATH,
    OUTPUT,
    ROOT,
    SPEC_PATH,
    evidence_map,
    metric_registry,
    split_taxonomy,
    suites,
)


def _json(name: str) -> dict:
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def test_all_nine_suites_exist_and_no_global_score_is_defined() -> None:
    manifest = _json("suite_manifest.json")
    suite_ids = [row["suite_id"] for row in manifest["suites"]]

    assert suite_ids == [
        "KG-Eval",
        "Ingestion-Eval",
        "Retrieval-Eval",
        "Agent-Eval",
        "Planner-Eval",
        "Justification-Eval",
        "E2E-Eval",
        "Trace-Eval",
        "Regression-Eval",
    ]
    assert manifest["suite_count"] == 9
    assert manifest["global_score_defined"] is False
    assert manifest["new_large_experiment_run"] is False
    assert all(row["status"] for row in manifest["suites"])
    assert all(row["global_score_eligible"] is False for row in manifest["suites"])
    by_id = {row["suite_id"]: row for row in manifest["suites"]}
    assert by_id["Planner-Eval"]["test_case_schema"] == [
        "case_id",
        "input_artifact",
        "current_representation_records",
        "representation_status",
        "identity_hashes",
        "target_state",
        "gold_reuse",
        "gold_recompute",
        "gold_block",
        "required_actions",
        "forbidden_actions",
    ]
    assert by_id["Trace-Eval"]["status"] == "SPEC_DEFINED_BENCHMARK_NOT_RUN"
    assert len(by_id["Trace-Eval"]["future_failure_types"]) == 10


def test_metric_registry_has_unique_complete_entries() -> None:
    registry = _json("metric_registry.json")
    rows = registry["metrics"]
    ids = [row["metric_id"] for row in rows]
    required = {
        "metric_id",
        "suite",
        "name",
        "definition",
        "numerator",
        "denominator",
        "unit",
        "higher_or_lower_better",
        "valid_scope",
        "invalid_interpretations",
        "aggregation_unit",
        "status",
    }

    assert registry["metric_count"] == len(rows) == len(ids) == len(set(ids))
    assert all(required <= row.keys() for row in rows)
    assert all(row["definition"] for row in rows)
    assert all(row["aggregation_unit"] for row in rows)
    assert all(row["invalid_interpretations"] for row in rows)
    assert {row["suite"] for row in rows} == {
        row["suite_id"] for row in _json("suite_manifest.json")["suites"]
    }


def test_exported_spec_recomputes_from_registry_definitions() -> None:
    metrics = metric_registry()
    assert metrics == _json("metric_registry.json")["metrics"]
    assert suites(metrics) == _json("suite_manifest.json")["suites"]
    assert split_taxonomy() == _json("split_taxonomy.json")


def test_every_mapped_artifact_exists_and_paths_are_repository_relative() -> None:
    exported = _json("existing_evidence_map.json")
    records = exported["records"]

    assert records == evidence_map()
    assert exported["record_count"] == 19
    assert exported["mapped_existing_evaluation_count"] == 17
    assert exported["planned_not_run_count"] == 2
    assert all(not Path(row["artifact_path"]).is_absolute() for row in records)
    assert all((ROOT / row["artifact_path"]).exists() for row in records)
    assert all(row["artifact_tracking"] in {"TRACKED", "UNTRACKED_WORKSPACE"} for row in records)
    assert "/Users/" not in json.dumps(records)


def test_quarantined_disclosure_is_not_current_and_historical_run_is_preserved() -> None:
    records = _json("existing_evidence_map.json")["records"]
    by_id = {row["evidence_id"]: row for row in records}

    disclosed = by_id["independent_retrieval_validation_v1_disclosed_cases"]
    historical = by_id["independent_retrieval_validation_v1_historical"]
    assert disclosed["status"] == "QUARANTINED"
    assert "CURRENT" not in disclosed["result_type"]
    assert historical["status"] == "FROZEN_HISTORICAL"
    assert historical["split"] == "SEALED"


def test_development_and_regression_results_have_interpretation_boundaries() -> None:
    records = _json("existing_evidence_map.json")["records"]

    assert all(
        "independent" not in row["result_type"].casefold()
        for row in records
        if row["status"] in {"DEVELOPMENT_RESULT", "PILOT", "PARTIAL"}
    )
    regression_metrics = [
        row for row in _json("metric_registry.json")["metrics"]
        if row["suite"] == "Regression-Eval"
    ]
    assert all(
        any("scientific accuracy" in value.casefold() for value in row["invalid_interpretations"])
        for row in regression_metrics
    )


def test_formal_justification_before_after_numbers_are_exactly_mapped() -> None:
    by_id = {
        row["evidence_id"]: row
        for row in _json("existing_evidence_map.json")["records"]
    }
    before = by_id["justification_fidelity_v1_1"]["verified_result"]
    after = by_id["decision_local_projection_v1_2"]["verified_result"]

    assert before == {
        "precision": "5/17",
        "extra_nondecision_evidence": 12,
        "recall": "5/5",
        "behavior_invariance": "4/4",
    }
    assert after == {
        "precision": "5/5",
        "extra_nondecision_evidence": 0,
        "recall": "5/5",
        "behavior_invariance": "4/4",
    }


def test_e2e_blocked_terminal_is_not_mislabeled_success() -> None:
    record = next(
        row for row in _json("existing_evidence_map.json")["records"]
        if row["evidence_id"] == "pbmc3k_replay_v2"
    )

    assert record["verified_result"]["status"] == "FAIL"
    assert record["verified_result"]["full_scientific_task_completed"] is False
    assert "BLOCKED" in record["interpretation"]


def test_machine_readable_integrity_audit_passes_all_required_checks() -> None:
    audit = _json("integrity.json")

    assert audit["status"] == "PASS"
    assert all(audit["checks"].values())
    assert audit["protected_unchanged"] is True
    assert audit["details"] == {
        "absolute_paths": [],
        "dev_or_pilot_mislabeled_independent": [],
        "missing_artifacts": [],
        "quarantined_marked_current": [],
        "regression_metrics_missing_scientific_accuracy_boundary": [],
    }


def test_human_readable_spec_and_matrix_cover_each_suite() -> None:
    spec = SPEC_PATH.read_text(encoding="utf-8")
    matrix = MATRIX_PATH.read_text(encoding="utf-8")
    suite_ids = [row["suite_id"] for row in _json("suite_manifest.json")["suites"]]

    assert all(f"## {suite_id}" in spec for suite_id in suite_ids)
    assert all(f"| {suite_id} |" in matrix for suite_id in suite_ids)
    assert "5/17 to 5/5" in spec
    assert "BLOCKED scientific terminal is not SUCCESS" in spec
    assert "global score" in matrix
