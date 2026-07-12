from datetime import datetime, timezone

from core.execution_models import (
    ExecutionRun,
    ExperimentBatchResult,
    ExperimentRunRecord,
    ValidationResult,
)
from core.tool_contract_registry import ToolContractRegistry
from execution.candidate_aggregator import CandidateAggregator
from execution.experiment_runner import build_configuration


def test_candidate_aggregation_handles_partial_failure_and_duplicates():
    contract = ToolContractRegistry().load("scrublet", "0.2.3")
    configuration = _configuration(contract, "config-a")
    runs = [
        _run("run-1", contract, configuration, "succeeded"),
        _run("run-2", contract, configuration, "succeeded"),
        _run("run-3", contract, configuration, "failed"),
    ]
    batch = _batch(
        configuration,
        runs + [runs[0]],
        [
            _validation("run-1", True, 0.7),
            _validation("run-2", True, 0.8),
            _validation("run-3", False, None),
        ],
    )
    candidate = CandidateAggregator().aggregate(batch=batch, contract=contract)[0]

    assert candidate.successful_run_ids == ["run-1", "run-2"]
    assert candidate.failed_run_ids == ["run-3"]
    assert candidate.duplicate_run_ids == ["run-1"]
    assert candidate.execution_success_rate == 2 / 3
    assert candidate.metric_summaries["synthetic_engineering_f1"].mean == 0.75
    assert candidate.seed_stability["successful_seed_count"] == 2
    assert candidate.eligible_for_decision is True


def test_candidate_aggregation_blocks_all_failed_missing_artifact_and_hash_mismatch():
    contract = ToolContractRegistry().load("scrublet", "0.2.3")
    configuration = _configuration(contract, "config-b")
    all_failed = _batch(
        configuration,
        [_run("failed-1", contract, configuration, "failed"), _run("failed-2", contract, configuration, "failed")],
        [_validation("failed-1", False, None), _validation("failed-2", False, None)],
    )
    failed_candidate = CandidateAggregator().aggregate(
        batch=all_failed, contract=contract
    )[0]
    assert failed_candidate.eligible_for_decision is False
    assert failed_candidate.execution_success_rate == 0.0

    missing_artifact = _batch(
        configuration,
        [_run("missing-1", contract, configuration, "succeeded"), _run("missing-2", contract, configuration, "succeeded")],
        [
            _validation("missing-1", True, 0.9, artifacts=False),
            _validation("missing-2", True, 0.9, artifacts=False),
        ],
    )
    missing_candidate = CandidateAggregator().aggregate(
        batch=missing_artifact, contract=contract
    )[0]
    assert missing_candidate.successful_run_ids == []
    assert missing_candidate.eligible_for_decision is False

    mismatched_run = _run("mismatch-1", contract, configuration, "succeeded")
    mismatched_run = mismatched_run.model_copy(
        update={"parameters": {**mismatched_run.parameters, "expected_doublet_rate": 0.2}}
    )
    mismatch = _batch(
        configuration,
        [mismatched_run, _run("mismatch-2", contract, configuration, "succeeded")],
        [_validation("mismatch-1", True, 0.9), _validation("mismatch-2", True, 0.9)],
    )
    mismatch_candidate = CandidateAggregator().aggregate(batch=mismatch, contract=contract)[0]
    assert mismatch_candidate.eligible_for_decision is False
    assert any("configuration_hash_mismatch" in item for item in mismatch_candidate.limitations)


def test_single_validation_never_becomes_decision_eligible():
    contract = ToolContractRegistry().load("scrublet", "0.2.3")
    configuration = _configuration(contract, "single")
    batch = _batch(
        configuration,
        [_run("only-run", contract, configuration, "succeeded")],
        [_validation("only-run", True, 1.0)],
    )
    candidate = CandidateAggregator().aggregate(batch=batch, contract=contract)[0]
    assert candidate.eligible_for_decision is False
    assert "fewer_than_two_successful_seeds" in candidate.limitations


def _configuration(contract, configuration_id):
    return build_configuration(
        configuration_id=configuration_id,
        parameters={"min_gene_variability_pctl": 0.0, "n_prin_comps": 10, "use_approx_neighbors": False, "min_counts": 1, "min_cells": 1},
        provenance={},
        source="development_probe_search",
        contract=contract,
    )


def _run(run_id, contract, configuration, status):
    now = datetime.now(timezone.utc)
    return ExecutionRun(
        request_id=f"request-{run_id}", run_id=run_id, trace_id="trace", plan_id="plan", step_id="step",
        wrapper_id=contract.wrapper_id, tool_name=contract.tool_name, tool_version=contract.tool_version,
        environment_id=contract.environment_id, command_argv_redacted=["python", "-m", "wrapper"],
        parameters=configuration.parameters, parameter_provenance=configuration.parameter_provenance,
        input_hash="a" * 64, start_time=now, end_time=now, runtime_seconds=1.0,
        peak_memory_mb=100.0, exit_code=0 if status == "succeeded" else 1,
        stdout_path="stdout", stderr_path="stderr", status=status, fixture_id="fixture",
    )


def _validation(run_id, passed, f1, artifacts=True):
    return ValidationResult(
        validation_id=f"validation-{run_id}", run_id=run_id, passed=passed,
        artifact_checks={"required_artifacts_present": artifacts},
        task_metrics={} if f1 is None else {"synthetic_engineering_f1": f1},
        failures=[] if passed else ["failed"],
    )


def _batch(configuration, runs, validations):
    records = [
        ExperimentRunRecord(
            run_id=run.run_id, configuration_id=configuration.configuration_id,
            configuration_hash=configuration.configuration_hash, seed=index,
            split_role="development", probe_hash="b" * 64, parameters=run.parameters,
            parameter_provenance=run.parameter_provenance, run_status=run.status,
            validation_id=f"validation-{run.run_id}",
            validation_passed=next((v.passed for v in validations if v.run_id == run.run_id), False),
            runtime_seconds=run.runtime_seconds, peak_memory_mb=run.peak_memory_mb,
        )
        for index, run in enumerate(dict.fromkeys(run.run_id for run in runs) and {run.run_id: run for run in runs}.values())
    ]
    return ExperimentBatchResult(
        experiment_id="batch", split_role="development", probe_hash="b" * 64,
        configurations=[configuration], execution_runs=runs, validation_results=validations,
        run_records=records, requested_run_count=len(records), completed_run_count=len(runs),
    )
