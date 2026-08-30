import json
from pathlib import Path

import pytest

from core.execution_models import ExecutionBudget, RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from core.trace_context import TraceCollector, TracePersistenceError
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator, OrchestratorState
from execution.experiment_runner import build_configuration
from tests.fixtures.anndata_factory import write_phase1_fixtures
from tests.phase4_helpers import DeterministicFailureExperimentRunner


def test_repairable_invalid_components_completes_with_lineage(tmp_path):
    result = _run(tmp_path, "invalid_n_prin_comps")

    assert result.final_state == OrchestratorState.COMPLETED
    assert result.state_history == [
        "CREATED",
        "PROFILED",
        "PLANNED",
        "WAITING_APPROVAL",
        "RUNNING",
        "VALIDATING",
        "REPAIR_PENDING",
        "RUNNING",
        "VALIDATING",
        "AGGREGATING",
        "DECIDING",
        "PACKAGING",
        "COMPLETED",
    ]
    assert len(result.repair_actions) == 2
    assert sum(item.repairable for item in result.validation_results) == 2
    assert all(action.parent_run_id != action.new_run_id for action in result.repair_actions)
    assert result.budget.initial_runs_used == 2
    assert result.budget.repair_runs_used == 2
    assert result.decision_result.recommended_candidate_id is not None
    assert result.package_result.complete and result.package_result.manifest_hashes_valid
    package = Path(result.package_result.package_path)
    repair_history = json.loads((package / "repair_history.json").read_text())
    assert len(repair_history["actions"]) == 2
    assert all(Path(run.stderr_path).exists() for run in result.execution_runs)
    trace_rows = [json.loads(line) for line in Path(result.trace_path).read_text().splitlines()]
    package_trace_rows = [
        json.loads(line)
        for line in (package / "orchestrator_trace.jsonl").read_text().splitlines()
    ]
    assert package_trace_rows[-1]["state_after"] == "COMPLETED"
    repaired_rows = [row for row in trace_rows if row.get("parent_run_id")]
    assert len(repaired_rows) == 2
    assert all(row["run_id"] != row["parent_run_id"] for row in repaired_rows)
    assert not any(
        left == "PLANNED" and right == "COMPLETED"
        for left, right in zip(result.state_history, result.state_history[1:])
    )


def test_timeout_reduces_probe_and_transient_retries_once(tmp_path):
    timeout = _run(tmp_path / "timeout", "timeout")
    assert timeout.final_state == OrchestratorState.COMPLETED
    assert {item.repair_type for item in timeout.repair_actions} == {"reduce_probe_size"}

    transient = _run(tmp_path / "transient", "transient")
    assert transient.final_state == OrchestratorState.COMPLETED
    assert len(transient.repair_actions) == 2
    assert {item.repair_type for item in transient.repair_actions} == {
        "retry_same_request_once"
    }


def test_hash_mismatch_blocks_without_illegal_rerun(tmp_path):
    result = _run(tmp_path, "hash_mismatch")
    assert result.final_state == OrchestratorState.BLOCKED
    assert result.repair_actions == []
    assert result.budget.repair_runs_used == 0
    assert len(result.execution_runs) == 2
    assert "artifact_hash_mismatch" in result.blockers
    assert result.package_result.complete


def test_repair_budget_exhaustion_keeps_failed_candidate(tmp_path):
    budget = ExecutionBudget(
        max_initial_runs=2,
        reserved_repair_runs=1,
        reserved_validation_reruns=0,
        max_total_runs=3,
    )
    result = _run(tmp_path, "invalid_n_prin_comps", execution_budget=budget)
    assert result.final_state == OrchestratorState.BLOCKED
    assert result.budget.repair_runs_used == 1
    assert len(result.execution_runs) == 3
    assert any(candidate.failed_run_ids for candidate in result.candidate_evaluations)


def test_one_failed_candidate_does_not_block_successful_candidate(tmp_path):
    result = _run(tmp_path, "partial", two_candidates=True)
    assert result.final_state == OrchestratorState.COMPLETED
    assert result.decision_result.recommended_candidate_id is not None
    assert any(candidate.failed_run_ids for candidate in result.candidate_evaluations)
    assert any(candidate.successful_run_ids for candidate in result.candidate_evaluations)


def test_all_candidates_failed_blocks(tmp_path):
    result = _run(tmp_path, "all_fail")
    assert result.final_state == OrchestratorState.BLOCKED
    assert result.decision_result.recommended_candidate_id is None
    assert "all_candidates_failed" in result.blockers


def test_non_maintainer_cannot_enter_execution(tmp_path):
    with pytest.raises(PermissionError, match="qualification_requires_maintainer"):
        _run(tmp_path, "invalid_n_prin_comps", actor_role="user")


def test_canonical_controlled_trace_links_existing_records_and_parent_lineage(tmp_path):
    parent_trace_id = "trace_11111111111111111111111111111111"
    result = _run(
        tmp_path,
        "invalid_n_prin_comps",
        lineage={
            "parent_trace_id": parent_trace_id,
            "handoff_id": "controlled-handoff:test",
            "parent_request_id": "stepwise-request:test",
            "original_plan_id": "cap-plan-origin-test",
        },
    )
    row = json.loads((tmp_path / "canonical-traces.jsonl").read_text())

    assert result.canonical_trace_id == row["trace_id"]
    assert row["trace_kind"] == "CONTROLLED_EXECUTION"
    assert row["parent_trace_id"] == parent_trace_id
    assert row["handoff_id"] == "controlled-handoff:test"
    assert row["parent_request_id"] == "stepwise-request:test"
    assert row["original_plan_id"] == "cap-plan-origin-test"
    assert len([span for span in row["spans"] if span["parent_span_id"] is None]) == 1
    assert [span["stage"] for span in row["spans"]] == [
        "REQUEST",
        "RUNTIME_BIND",
        "STATE_INSPECTION",
        "PLANNING",
        "POLICY",
        "APPROVAL",
        "EXECUTION",
        "VALIDATION",
        "REPAIR",
        "APPROVAL",
        "EXECUTION",
        "VALIDATION",
        "DECISION",
        "PACKAGE",
    ]
    refs = [
        ref
        for span in row["spans"]
        for ref in span["input_refs"] + span["output_refs"]
    ]
    record_types = {ref["record_type"] for ref in refs}
    assert {
        "workflow_plan",
        "execution_run",
        "validation_record",
        "repair_proposal",
        "repair_action",
        "decision_record",
        "orchestration_record",
        "reproducibility_package",
    }.issubset(record_types)
    runtime_trace_ids = {run.trace_id for run in result.execution_runs}
    assert runtime_trace_ids == {
        link["target_id"]
        for link in row["links"]
        if link["link_type"] == "LEGACY_TRACE"
    }


def test_success_without_repair_emits_no_repair_or_extra_approval_span(tmp_path):
    result = _run(tmp_path, "success")
    row = json.loads((tmp_path / "canonical-traces.jsonl").read_text())

    assert result.final_state == OrchestratorState.COMPLETED
    assert row["status"] == "SUCCESS"
    assert [span["stage"] for span in row["spans"]] == [
        "REQUEST",
        "RUNTIME_BIND",
        "STATE_INSPECTION",
        "PLANNING",
        "POLICY",
        "APPROVAL",
        "EXECUTION",
        "VALIDATION",
        "DECISION",
        "PACKAGE",
    ]


def test_non_maintainer_trace_blocks_before_execution_and_preserves_exception(tmp_path):
    with pytest.raises(PermissionError, match="qualification_requires_maintainer"):
        _run(tmp_path, "success", actor_role="user")

    row = json.loads((tmp_path / "canonical-traces.jsonl").read_text())
    assert row["status"] == "FAILED"
    assert "EXECUTION" not in [span["stage"] for span in row["spans"]]
    policy = next(span for span in row["spans"] if span["stage"] == "POLICY")
    assert policy["status"] == "BLOCKED"
    assert policy["decision_evidence"][0]["reason_code"] == (
        "qualification_requires_maintainer"
    )


def test_controlled_trace_privacy_and_persistence_failure_isolation(tmp_path, monkeypatch):
    privacy_root = tmp_path / "privacy"
    result = _run(
        privacy_root,
        "success",
        request_id="controlled-request:privacy",
        query="raw prompt must remain in the business requirement only",
    )
    persisted = (privacy_root / "canonical-traces.jsonl").read_text()
    assert "raw prompt must remain" not in persisted
    assert str(privacy_root) not in persisted
    assert "stdout.log" not in persisted
    assert "stderr.log" not in persisted
    assert "test-only-wrapper" not in persisted
    assert result.package_result.complete

    failure_root = tmp_path / "persistence-failure"
    collector = TraceCollector(failure_root / "canonical-traces.jsonl")

    def fail_append(_encoded):
        raise TracePersistenceError("trace append failed")

    monkeypatch.setattr(collector, "_append_encoded", fail_append)
    completed = _run(
        failure_root,
        "success",
        trace_collector=collector,
    )
    assert completed.final_state == OrchestratorState.COMPLETED
    assert completed.package_result.complete
    assert not (failure_root / "canonical-traces.jsonl").exists()

    with pytest.raises(PermissionError, match="qualification_requires_maintainer"):
        _run(
            tmp_path / "business-failure",
            "success",
            actor_role="user",
            trace_collector=collector,
        )


def _run(
    tmp_path,
    scenario,
    *,
    execution_budget=None,
    two_candidates=False,
    actor_role="maintainer",
    trace_collector=None,
    lineage=None,
    request_id=None,
    query="qualify bounded Scrublet repair",
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixtures = write_phase1_fixtures(tmp_path / "fixtures")
    environments = EnvironmentRegistry()
    registry = ToolContractRegistry(environment_registry=environments)
    contract = registry.load("scrublet", "0.2.3")
    if scenario in {"invalid_n_prin_comps", "hash_mismatch"}:
        parameters = {
            "min_counts": 1,
            "min_cells": 1,
            "min_gene_variability_pctl": 0.0,
            "n_prin_comps": 100,
            "use_approx_neighbors": False,
        }
    else:
        parameters = {
            "min_counts": 1,
            "min_cells": 1,
            "min_gene_variability_pctl": 0.0,
            "n_prin_comps": 10,
            "use_approx_neighbors": False,
        }
    configs = [
        build_configuration(
            configuration_id="fail" if two_candidates else "candidate",
            parameters=parameters,
            provenance={},
            source="development_probe_search",
            contract=contract,
        )
    ]
    if two_candidates:
        configs.append(
            build_configuration(
                configuration_id="success",
                parameters={**parameters, "expected_doublet_rate": 0.12},
                provenance={},
                source="development_probe_search",
                contract=contract,
            )
        )
    runner = DeterministicFailureExperimentRunner(tmp_path / "runner", scenario)
    orchestrator = ExecutionOrchestrator(
        run_root=tmp_path / "runs",
        approved_input_root=tmp_path / "probes",
        package_root=tmp_path / "packages",
        trace_root=tmp_path / "traces",
        environment_registry=environments,
        contract_registry=registry,
        experiment_runner=runner,
        trace_collector=(
            trace_collector
            or TraceCollector(tmp_path / "canonical-traces.jsonl")
        ),
    )
    requirement = RequirementSpec(
        request_id=request_id or f"phase4-{scenario}",
        query=query,
        input_path=str(fixtures["raw_x"]),
        input_object_type="AnnData",
        data_access_authorized=True,
        resource_budget={"max_cells": 12, "max_runtime_seconds": 120},
    )
    return orchestrator.run(
        orchestration_id=f"orchestration-{scenario}",
        requirement=requirement,
        configurations=configs,
        seeds=[101, 102],
        fixture_id="phase1_raw_counts_x",
        package_id=f"package-{scenario}",
        execution_budget=execution_budget,
        probe_max_cells=12,
        pairing_strategy="mixed",
        cluster_key="batch",
        actor_role=actor_role,
        **dict(lineage or {}),
    )
