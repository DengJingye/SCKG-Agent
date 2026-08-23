import pytest

from datetime import datetime, timezone

from core.execution_models import ExecutionRun, ValidationResult
from core.research_workspace_models import PreviewRunResult
from execution.interactive_step_runtime import InteractiveStepRuntime
from tests.test_preview_execution_service import _harness


def test_step_runtime_exposes_next_action_and_completed_path(tmp_path):
    service, approvals, grant, profile, preview, notebook = _harness(tmp_path)
    runtime = InteractiveStepRuntime(service.contract_registry)
    preparation = service.prepare(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=None,
        profile=profile,
        preview=preview,
        notebook=notebook,
    )
    before_approval = runtime.inspect(
        artifact_id="pbmc",
        profile=profile,
        preview=preview,
        notebook=notebook,
        approval_id=None,
        result=None,
        preparation=preparation,
    )
    assert before_approval.current_step_id == "approve_execution"
    assert before_approval.execution_request_count == 0

    approval = approvals.create_execution_approval(
        scope=preparation.approval_scope, data_grant_id=grant.grant_id
    )
    result = PreviewRunResult(
        user_id="alice",
        artifact_id="pbmc",
        preview_id=preview.preview_id,
        notebook_id=notebook.notebook_id,
        plan_id=preparation.plan_id,
        status="validated",
        execution_run=ExecutionRun(
            run_id="step-runtime-run",
            request_id="step-runtime-request",
            trace_id="trace-step-runtime",
            plan_id=preparation.plan_id,
            step_id="doublet.scrublet.preview",
            wrapper_id="scrublet_0_2_3",
            tool_name="Scrublet",
            tool_version="0.2.3",
            environment_id=preparation.environment_id,
            command_argv_redacted=["python", "-m", "scrublet"],
            parameters=dict(notebook.parameter_snapshot),
            input_hash=preview.preview_hash,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            stdout_path="stdout.log",
            stderr_path="stderr.log",
            exit_code=0,
            status="succeeded",
            runtime_seconds=1.0,
            fixture_id=preview.preview_id,
            synthetic_fixture=False,
            user_data_used=True,
            execution_purpose="representative_preview",
            owner_user_id="alice",
        ),
        validation_result=ValidationResult(
            validation_id="validation-step-runtime",
            run_id="step-runtime-run",
            passed=True,
            metric_authority="preview_engineering_metric",
            validation_version="step-runtime-test-v1",
        ),
    )
    completed = runtime.inspect(
        artifact_id="pbmc",
        profile=profile,
        preview=preview,
        notebook=notebook,
        approval_id=approval.approval_id,
        result=result,
    )
    assert completed.current_step_id is None
    assert all(
        item.status in {"CURRENT", "COMPLETED"} for item in completed.steps
    )


def test_parameter_patch_is_contract_validated_and_marks_downstream_stale(tmp_path):
    service, _, _, profile, preview, notebook = _harness(tmp_path)
    runtime = InteractiveStepRuntime(service.contract_registry)
    proposed = dict(notebook.parameter_snapshot)
    proposed["expected_doublet_rate"] = 0.09
    patch = runtime.propose_parameter_patch(
        notebook=notebook, proposed_parameters=proposed
    )

    assert patch.requires_rebuild is True
    assert patch.invalidates == ["notebook", "approval", "result"]
    assert patch.execution_request_count == 0
    assert [item.parameter_name for item in patch.changes] == [
        "expected_doublet_rate"
    ]
    snapshot = runtime.inspect(
        artifact_id="pbmc",
        profile=profile,
        preview=preview,
        notebook=notebook,
        approval_id="approval-old",
        result=None,
        parameter_patch=patch,
    )
    assert snapshot.parameter_patch_required is True
    assert snapshot.current_step_id == "compile_notebook"
    assert snapshot.steps[3].status == "STALE"
    assert snapshot.steps[4].status == "WAITING"

    proposed["n_prin_comps"] = 1000
    with pytest.raises(ValueError, match="above_maximum"):
        runtime.propose_parameter_patch(
            notebook=notebook, proposed_parameters=proposed
        )


def test_noop_parameter_patch_keeps_notebook_current(tmp_path):
    service, _, _, profile, preview, notebook = _harness(tmp_path)
    runtime = InteractiveStepRuntime(service.contract_registry)
    patch = runtime.propose_parameter_patch(
        notebook=notebook,
        proposed_parameters=dict(notebook.parameter_snapshot),
    )
    snapshot = runtime.inspect(
        artifact_id="pbmc",
        profile=profile,
        preview=preview,
        notebook=notebook,
        approval_id=None,
        result=None,
        parameter_patch=patch,
    )
    assert patch.requires_rebuild is False
    assert patch.changes == []
    assert snapshot.parameter_patch_required is False
    assert snapshot.current_step_id == "approve_execution"
