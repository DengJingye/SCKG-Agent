from datetime import datetime, timezone

import pytest

from core.deterministic_router import DeterministicRouter, RouterRoute
from core.execution_models import ExecutionBudget, ExecutionRun, ValidationResult
from core.tool_contract_registry import ToolContractRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.repair_policy import (
    RepairPolicy,
    RepairReason,
    RepairType,
    RunBudgetLedger,
    apply_repair_parameters,
)


def test_invalid_components_produces_auditable_parameter_repair(tmp_path):
    contract = ToolContractRegistry(environment_registry=EnvironmentRegistry()).load(
        "scrublet", "0.2.3"
    )
    run = _run(tmp_path, parameters={**contract.default_parameters, "n_prin_comps": 100})
    (tmp_path / "stderr.log").write_text("n_components must be smaller\n", encoding="utf-8")
    validation = _validation(run, ["execution_not_successful"])

    proposal = RepairPolicy().propose(
        run=run,
        validation=validation,
        contract=contract,
        expected_cells=15,
    )

    assert proposal is not None
    assert proposal.reason_code == RepairReason.INVALID_N_PRIN_COMPS
    assert proposal.repair_type == RepairType.REDUCE_N_PRIN_COMPS
    assert proposal.old_values == {"n_prin_comps": 100}
    assert proposal.new_values == {"n_prin_comps": 10}
    action = RepairPolicy().apply(
        proposal=proposal, new_run_id="repair-run", approved=True
    )
    assert action.parent_run_id == run.run_id
    assert action.new_run_id != action.parent_run_id
    assert apply_repair_parameters(run.parameters, proposal)["n_prin_comps"] == 10


@pytest.mark.parametrize(
    ("status", "error_type", "expected_reason", "expected_type"),
    [
        ("timeout", "timeout", RepairReason.TIMEOUT, RepairType.REDUCE_PROBE_SIZE),
        (
            "failed",
            "wrapper_exit_nonzero",
            RepairReason.TRANSIENT_PROCESS_FAILURE,
            RepairType.RETRY_SAME_REQUEST_ONCE,
        ),
    ],
)
def test_timeout_and_transient_failures_are_bounded(
    tmp_path, status, error_type, expected_reason, expected_type
):
    contract = ToolContractRegistry(environment_registry=EnvironmentRegistry()).load(
        "scrublet", "0.2.3"
    )
    run = _run(tmp_path, status=status, error_type=error_type)
    proposal = RepairPolicy().propose(
        run=run,
        validation=_validation(run, ["execution_not_successful"]),
        contract=contract,
        expected_cells=40,
    )
    assert proposal is not None
    assert proposal.reason_code == expected_reason
    assert proposal.repair_type == expected_type
    if expected_reason == RepairReason.TRANSIENT_PROCESS_FAILURE:
        assert (
            RepairPolicy().propose(
                run=run,
                validation=_validation(run, ["execution_not_successful"]),
                contract=contract,
                expected_cells=40,
                previous_repairs_for_parent=1,
            )
            is None
        )


def test_hash_mismatch_is_never_repaired(tmp_path):
    contract = ToolContractRegistry(environment_registry=EnvironmentRegistry()).load(
        "scrublet", "0.2.3"
    )
    run = _run(tmp_path)
    validation = _validation(run, ["artifact_hash_mismatch"])
    policy = RepairPolicy()
    assert policy.classify(run, validation) == RepairReason.HASH_MISMATCH
    assert policy.propose(
        run=run, validation=validation, contract=contract, expected_cells=40
    ) is None
    decision = DeterministicRouter().route_repair(
        validation=validation,
        proposal=None,
        repair_approved=None,
        budget_available=True,
    )
    assert decision.route == RouterRoute.BLOCKED


def test_repair_router_requires_approval_and_preserves_failed_route(tmp_path):
    contract = ToolContractRegistry(environment_registry=EnvironmentRegistry()).load(
        "scrublet", "0.2.3"
    )
    run = _run(tmp_path, status="timeout", error_type="timeout")
    validation = _validation(run, ["execution_not_successful"])
    proposal = RepairPolicy().propose(
        run=run, validation=validation, contract=contract, expected_cells=40
    )
    router = DeterministicRouter()
    assert router.route_repair(
        validation=validation,
        proposal=proposal,
        repair_approved=None,
        budget_available=True,
    ).route == RouterRoute.REPAIR_PENDING
    assert router.route_repair(
        validation=validation,
        proposal=proposal,
        repair_approved=True,
        budget_available=True,
    ).route == RouterRoute.QUALIFICATION_EXECUTION
    assert router.route_repair(
        validation=validation,
        proposal=proposal,
        repair_approved=False,
        budget_available=True,
    ).route == RouterRoute.AGGREGATE_FAILED


def test_run_budget_enforces_12_4_2_18():
    ledger = RunBudgetLedger(limits=ExecutionBudget())
    ledger = ledger.reserve_initial(12).reserve_repair(4).reserve_validation_rerun(2)
    assert ledger.total_runs_used == 18
    with pytest.raises(ValueError, match="repair_run_budget_exhausted"):
        ledger.reserve_repair()


def test_scdblfinder_repair_never_uses_scrublet_parameters(tmp_path):
    contract = ToolContractRegistry(environment_registry=EnvironmentRegistry()).load(
        "scDblFinder", "1.24.0"
    )
    run = _run(
        tmp_path,
        parameters={"dbr": 0.1, "clusters": False, "n_cores": 4, "random_state": 0},
    )
    (tmp_path / "stderr.log").write_text(
        "n_prin_comps n_components error\n", encoding="utf-8"
    )
    policy = RepairPolicy()
    assert policy.propose(
        run=run,
        validation=_validation(run, ["execution_not_successful"]),
        contract=contract,
        expected_cells=40,
    ) is None

    (tmp_path / "stderr.log").write_text("memory soft limit\n", encoding="utf-8")
    proposal = policy.propose(
        run=run,
        validation=_validation(run, ["memory_soft_limit"]),
        contract=contract,
        expected_cells=40,
    )
    assert proposal is not None
    assert proposal.repair_type == "reduce_worker_core_count"
    assert proposal.new_values == {"n_cores": 2}


def _run(tmp_path, *, parameters=None, status="failed", error_type="wrapper_exit_nonzero"):
    now = datetime.now(timezone.utc)
    return ExecutionRun(
        request_id="request-run-1",
        run_id="run-1",
        trace_id="trace-1",
        plan_id="plan-1",
        step_id="step-1",
        wrapper_id="scrublet_0_2_3",
        tool_name="Scrublet",
        tool_version="0.2.3",
        environment_id="scRNAseq",
        command_argv_redacted=["python", "-m", "wrapper"],
        parameters=parameters or {"n_prin_comps": 30},
        input_hash="a" * 64,
        start_time=now,
        end_time=now,
        runtime_seconds=1.0,
        peak_memory_mb=10.0,
        exit_code=1,
        stdout_path=str(tmp_path / "stdout.log"),
        stderr_path=str(tmp_path / "stderr.log"),
        status=status,
        error_type=error_type,
        fixture_id="fixture",
    )


def _validation(run, failures):
    return ValidationResult(
        validation_id=f"validation-{run.run_id}",
        run_id=run.run_id,
        passed=False,
        failures=failures,
    )
