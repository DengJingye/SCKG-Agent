"""Engineering invariants for the DEV targeted regression harness."""
import json

from eval.benchmark_v3.dev_pilot import BASE, LANES, sha
from eval.benchmark_v3.dev_targeted_regression import CONTROLS, FIX_MAPPING, select_cases
from eval.benchmark_v3.dev_scoring import validate_receipts

OUTPUT = BASE / "dev_targeted_regression_20260921_v3"


def test_selection_is_mechanical_from_canonical_final_attribution():
    affected, rows, provenance = select_cases()
    assert affected == sorted(FIX_MAPPING)
    assert all(row["attribution"]["stage"] in {"validation-governance", "routing"} for row in rows)
    assert len({row["run_id"].rsplit("--", 2)[0] for row in rows}) == 5
    assert provenance["canonical_attribution"].endswith("failure_attribution.final.json")
    assert set(affected).isdisjoint(CONTROLS)
    assert "dev-W01" not in affected


def test_new_manifest_has_all_four_lanes_once_per_selected_scenario():
    output = OUTPUT
    if not (output / "manifest.json").exists():
        return
    manifest = json.loads((output / "manifest.json").read_text())
    schedule = manifest["schedule"]
    selected = set(FIX_MAPPING) | set(CONTROLS)
    assert len(schedule) == 28
    for case_id in selected:
        rows = [row for row in schedule if row["case_id"] == case_id]
        assert {row["lane"] for row in rows} == set(LANES)
        assert len(rows) == 4
        assert len({row["input_sha256"] for row in rows}) == 1


def test_rendered_inputs_are_byte_identical_to_previous_pilot():
    output = OUTPUT
    if not (output / "inputs.json").exists():
        return
    old = json.loads((BASE / "dev_pilot_20260921/inputs.json").read_text())
    new = json.loads((output / "inputs.json").read_text())
    assert set(new) == set(FIX_MAPPING) | set(CONTROLS)
    for case_id, value in new.items():
        assert value == old[case_id]
        expected = next(row["input_sha256"] for row in json.loads(
            (output / "manifest.json").read_text())["schedule"] if row["case_id"] == case_id)
        assert sha(value["rendered_query"].encode()) == expected


def test_live_receipts_when_available():
    output = OUTPUT
    receipts = list((output / "runs").glob("*/runtime_receipt.json")) if output.exists() else []
    if len(receipts) != 28:
        return
    result = validate_receipts(output, 28)
    assert result["pass"], result["errors"]
    assert all(row["status"] == "completed" for row in result["rows"])


def test_recorded_regression_gates_are_evidence_bound():
    path = OUTPUT / "regression_audit.json"
    if not path.exists():
        return
    result = json.loads(path.read_text())
    assert result["status"] == "COMPLETE_WITH_BLOCKERS"
    assert result["runs_completed"] == 28
    assert result["runs_not_run"] == 0
    assert result["user_fact_preserved"] is False
    assert result["targeted_clarification_preserved"] is False
    assert result["artifact_validation_routing_pass"] is True
    assert result["unauthorized_execution_count"] == 0
    assert result["control_regression_count"] == 1
    assert result["lane_isolation_pass"] is True
    assert result["runtime_receipt_pass"] is True
    assert result["ready_for_evaluation_freeze"] is False
    rejected = [
        row
        for row in result["targeted_clarification_audit"]
        if row["support_check"].get("reason") == "clarification_field_already_available"
    ]
    assert len(rejected) == 3
    assert len(result["artifact_validation_audit"]) == 4
    assert all(row["pass"] for row in result["artifact_validation_audit"])
    assert result["scientific_kg_aggregate"]["input_tokens_before"] == 141941
    assert result["scientific_kg_aggregate"]["input_tokens_after"] == 91272


def test_user_context_is_never_upgraded_to_scientific_evidence():
    if not (OUTPUT / "regression_audit.json").exists():
        return
    result = json.loads((OUTPUT / "regression_audit.json").read_text())
    assert result["user_fact_audit"]
    assert all(row["context_complete"] for row in result["user_fact_audit"])
    assert all(row["authority_safe"] for row in result["user_fact_audit"])
    assert all(row["final_claims_safe"] for row in result["user_fact_audit"])
    assert result["lost_user_fact_segments"]


def test_aborted_harness_attempts_are_retained_without_provider_calls():
    for name in ("dev_targeted_regression_20260921", "dev_targeted_regression_20260921_v2"):
        path = BASE / name
        if not (path / "ABORTED.json").exists():
            return
        aborted = json.loads((path / "ABORTED.json").read_text())
        assert aborted["status"] == "aborted_before_worker_initialization"
        assert aborted["provider_calls"] == 0
        assert aborted["runs_with_runtime_receipt"] == 0
        assert len(list((path / "process_logs").glob("*.json"))) == 28
        assert not list(path.glob("runs/*/runtime_receipt.json"))
