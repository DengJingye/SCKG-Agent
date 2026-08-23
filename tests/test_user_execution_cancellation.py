from __future__ import annotations

import sys
import time
import os
import re

import pytest
from pathlib import Path

from core.deterministic_router import RouterDecision, RouterRoute
from core.execution_models import (
    ExecutionRequest,
    ExperimentBatchResult,
    ExperimentRunRecord,
    QualificationArtifact,
    RestrictedUserExecutionContext,
)
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalScope, parameter_hash
from execution.candidate_aggregator import CandidateAggregator
from execution.environment_registry import EnvironmentRegistry
from execution.execution_policy import ExecutionPair, ExecutionPolicy, ExecutionPolicyMode
from execution.experiment_runner import build_configuration
from execution.local_controlled_executor import LocalControlledExecutor
from execution.probe_builder import ProbeBuilder
from execution.user_workspace import UserWorkspaceService
from execution.validators.doublet import DoubletValidator
from execution.wrapper_registry import WrapperDefinition, WrapperRegistry
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_local_user_cancellation_terminates_process_tree_and_preserves_logs(tmp_path):
    source = write_phase1_fixtures(tmp_path / "inputs")["raw_x"]
    probe = ProbeBuilder().build(
        source_path=source,
        output_dir=tmp_path / "inputs" / "probe",
        profile_id="profile-cancel",
        fixture_id="phase1_raw_counts_x",
        max_cells=20,
    )
    artifact = QualificationArtifact(
        artifact_id="cancel-artifact",
        fixture_id="phase1_raw_counts_x",
        path=probe.probe_artifact_path,
        sha256=probe.probe_hash,
        synthetic=True,
        user_data=False,
        allowlisted=True,
        expected_cells=probe.n_probe_cells,
    )
    environments = EnvironmentRegistry()
    environment = environments.get("scRNAseq").model_copy(
        update={"enabled_for_execution": True}
    )
    contract_registry = ToolContractRegistry(environment_registry=environments)
    base_contract = contract_registry.load("Scrublet", "0.2.3")
    contract = base_contract.model_copy(
        update={"wrapper_id": "test_cancel_wrapper", "enabled_for_execution": True}
    )
    parameters = contract_registry.validate_parameters(contract, {})
    scope = ApprovalScope(
        user_id="user-a",
        artifact_id=artifact.artifact_id,
        plan_id="plan-cancel",
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        contract_version=contract.contract_version,
        environment_id=environment.environment_id,
        parameter_hash=parameter_hash(parameters),
    )
    pair = ExecutionPair(
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        wrapper_id=contract.wrapper_id,
        environment_id=environment.environment_id,
    )
    policy = ExecutionPolicy(
        mode=ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS,
        local_user_pairs=[pair],
    )
    workspace = UserWorkspaceService(root=tmp_path / "users")
    workspace.reserve_run(user_id="user-a", run_id="cancel-run")
    workspace.mark_run_running(user_id="user-a", run_id="cancel-run")
    request = ExecutionRequest(
        request_id="cancel-request",
        run_id="cancel-run",
        trace_id="cancel-trace",
        plan_id=scope.plan_id,
        step_id="cancel-test",
        wrapper_id=contract.wrapper_id,
        environment_id=environment.environment_id,
        input_artifact_id=artifact.artifact_id,
        parameters=parameters,
        timeout_seconds=30,
        actor={"actor_id": "user-a", "role": "user"},
        qualification={
            "mode": False,
            "purpose": "synthetic_qualification",
            "fixture_id": artifact.fixture_id,
        },
        execution_mode="restricted_local_user",
        user_execution=RestrictedUserExecutionContext(
            user_id="user-a",
            artifact_id=artifact.artifact_id,
            approval_id="approval-cancel",
            allowance_id="allowance-cancel",
            request_fingerprint=scope.fingerprint,
            contract_version=contract.contract_version,
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            environment_id=environment.environment_id,
            parameter_hash=scope.parameter_hash,
            approval_consumption_index=1,
            approval_max_uses=1,
        ),
    )
    wrapper_registry = WrapperRegistry(
        [
            WrapperDefinition(
                wrapper_id=contract.wrapper_id,
                environment_id=environment.environment_id,
                tool_name=contract.tool_name,
                tool_version=contract.tool_version,
                module="tests.fixtures.cancellation_wrapper",
                python_executable=Path(sys.executable),
            )
        ]
    )
    executor = LocalControlledExecutor(
        run_root=tmp_path / "users" / "user-a" / "runs",
        approved_input_root=tmp_path / "inputs",
        wrapper_registry=wrapper_registry,
        contract_registry=contract_registry,
        environment_registry=_FixedEnvironmentRegistry(environment),
        execution_policy=policy,
    )
    started = time.monotonic()
    cancellation_sent = False

    def cancellation_checker():
        nonlocal cancellation_sent
        if not cancellation_sent and time.monotonic() - started > 1.0:
            workspace.request_cancellation(user_id="user-a", run_id="cancel-run")
            cancellation_sent = True
        return workspace.cancellation_reason(user_id="user-a", run_id="cancel-run")

    run = executor.execute(
        request=request,
        artifact=artifact,
        contract=contract,
        router_decision=RouterDecision(
            route=RouterRoute.RESTRICTED_USER_EXECUTION,
            execution_allowed=True,
        ),
        cancellation_checker=cancellation_checker,
    )
    workspace.mark_run_terminal(user_id="user-a", run_id=run.run_id, status=run.status)

    assert cancellation_sent is True
    assert run.status == "cancelled"
    assert run.process_cleanup.cancellation_triggered is True
    assert run.process_cleanup.cancellation_reason == "cancelled_by_local_user"
    assert run.process_cleanup.residual_processes == []
    assert Path(run.stdout_path).is_file()
    assert Path(run.stderr_path).is_file()
    assert run.exit_code is not None
    child_pid = int(re.search(r"child_pid=(\d+)", Path(run.stdout_path).read_text()).group(1))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    validation = DoubletValidator().validate(run, expected_cells=artifact.expected_cells)
    configuration = build_configuration(
        configuration_id="cancelled-config",
        parameters=parameters,
        provenance={},
        source="contract_default",
        contract=contract,
    )
    batch = ExperimentBatchResult(
        experiment_id="cancelled-experiment",
        split_role="development",
        probe_hash=artifact.sha256,
        configurations=[configuration],
        execution_runs=[run],
        validation_results=[validation],
        run_records=[
            ExperimentRunRecord(
                run_id=run.run_id,
                configuration_id=configuration.configuration_id,
                configuration_hash=configuration.configuration_hash,
                seed=0,
                split_role="development",
                probe_hash=artifact.sha256,
                parameters=run.parameters,
                parameter_provenance=run.parameter_provenance,
                run_status=run.status,
                validation_id=validation.validation_id,
                validation_passed=validation.passed,
                runtime_seconds=run.runtime_seconds,
                peak_memory_mb=run.peak_memory_mb,
            )
        ],
        requested_run_count=1,
        completed_run_count=1,
    )
    candidate = CandidateAggregator().aggregate(batch=batch, contract=contract)[0]
    assert validation.passed is False
    assert candidate.successful_run_ids == []
    assert candidate.failed_run_ids == [run.run_id]
    assert candidate.eligible_for_decision is False


class _FixedEnvironmentRegistry:
    def __init__(self, environment):
        self.environment = environment

    def contains(self, environment_id: str) -> bool:
        return environment_id == self.environment.environment_id

    def get(self, environment_id: str):
        if not self.contains(environment_id):
            raise KeyError(environment_id)
        return self.environment
