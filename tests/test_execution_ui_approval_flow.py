from __future__ import annotations

import time

import pytest

from tests.execution_ui_helpers import (
    approval_confirmations,
    build_ui_harness,
    prepare_context,
)


def test_explicit_approval_parameter_invalidation_consumption_and_replay(tmp_path):
    harness = build_ui_harness(tmp_path)
    grant, context = prepare_context(harness)
    with pytest.raises(PermissionError, match="confirmations"):
        harness.service.create_plan_approval(
            context=context,
            data_grant_id=grant.grant_id,
            confirmations={name: False for name in approval_confirmations()},
            confirmation_text=harness.service.confirmation_text(context),
        )
    approval = harness.service.create_plan_approval(
        context=context,
        data_grant_id=grant.grant_id,
        confirmations=approval_confirmations(),
        confirmation_text=harness.service.confirmation_text(context),
        max_uses=2,
    )
    approved = harness.service.prepare(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        request_id="ui-request",
        query="run approved local doublet detection",
        parameters={},
        tool_name="Scrublet",
        tool_version="0.2.3",
    )
    assert approved.button_enabled is True

    changed = harness.service.prepare(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        request_id="ui-request",
        query="run approved local doublet detection",
        parameters={"expected_doublet_rate": 0.12},
        tool_name="Scrublet",
        tool_version="0.2.3",
    )
    assert changed.button_enabled is False
    assert "approval_scope_or_fingerprint_mismatch" in changed.button_blockers

    for index in range(2):
        harness.approvals.consume_execution_approval(
            approval.approval_id,
            expected_scope=context.approval_scope,
            request_id=f"consumption-{index}",
        )
    consumed = harness.service.prepare(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        request_id="ui-request",
        query="run approved local doublet detection",
        parameters={},
        tool_name="Scrublet",
        tool_version="0.2.3",
    )
    assert consumed.button_enabled is False
    assert "execution_approval_fully_consumed" in consumed.button_blockers
    with pytest.raises(PermissionError, match="replay"):
        harness.approvals.consume_execution_approval(
            approval.approval_id,
            expected_scope=context.approval_scope,
            request_id="consumption-1",
        )


def test_ui_cancel_delegates_to_user_workspace_backend(tmp_path):
    harness = build_ui_harness(tmp_path)
    grant, context = prepare_context(harness)
    approval = harness.service.create_plan_approval(
        context=context,
        data_grant_id=grant.grant_id,
        confirmations=approval_confirmations(),
        confirmation_text=harness.service.confirmation_text(context),
        max_uses=2,
    )
    approved = harness.service.prepare(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        request_id="ui-request",
        query="run approved local doublet detection",
        parameters={},
        tool_name="Scrublet",
        tool_version="0.2.3",
    )
    harness.service.local_user_service = _BlockingLocalService(harness.workspace)
    job = harness.service.start_execution(
        context=approved,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        request_id="ui-request",
        query="run approved local doublet detection",
        parameters={},
        package_id="ui-cancel-package",
        requested_runs=2,
    )
    assert harness.service.cancel_job(
        user_id="user-a", job_id=job.job_id, wait_seconds=2.0
    )
    deadline = time.monotonic() + 2.0
    status = harness.service.poll_job(user_id="user-a", job_id=job.job_id)
    while status.state not in {"failed", "completed"} and time.monotonic() < deadline:
        time.sleep(0.05)
        status = harness.service.poll_job(user_id="user-a", job_id=job.job_id)
    record = harness.workspace.get_record(
        resource_type="run", user_id="user-a", resource_id="ui-request-run-1"
    )
    assert record.status == "cancelled"
    assert status.state == "failed"
    with pytest.raises(KeyError):
        harness.workspace.get_record(
            resource_type="run", user_id="user-a", resource_id="ui-request-run-2"
        )
    with pytest.raises(PermissionError, match="cross-user"):
        harness.service.poll_job(user_id="user-b", job_id=job.job_id)


class _BlockingLocalService:
    def __init__(self, workspace):
        self.workspace = workspace

    def execute_approved_plan(self, **kwargs):
        run_id = f"{kwargs['request_id']}-run-1"
        self.workspace.reserve_run(user_id=kwargs["user_id"], run_id=run_id)
        self.workspace.mark_run_running(user_id=kwargs["user_id"], run_id=run_id)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.workspace.cancellation_reason(
                user_id=kwargs["user_id"], run_id=run_id
            ):
                self.workspace.mark_run_terminal(
                    user_id=kwargs["user_id"], run_id=run_id, status="cancelled"
                )
                raise RuntimeError("cancelled_by_local_user")
            time.sleep(0.02)
        raise RuntimeError("test cancellation timeout")
