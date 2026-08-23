from datetime import datetime, timezone

import pytest

from execution.approval_service import ApprovalScope, ApprovalService, parameter_hash


def test_execution_approval_has_bounded_consumption_and_replay_protection(tmp_path):
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    service = ApprovalService(root=tmp_path / "approvals")
    grant = service.grant_data_access(
        user_id="user-a", artifact_id="data-a", now=now
    )
    scope = ApprovalScope(
        user_id="user-a",
        artifact_id="data-a",
        plan_id="plan-a",
        tool_name="Scrublet",
        tool_version="0.2.3",
        contract_version="contract-v1",
        environment_id="scRNAseq",
        parameter_hash=parameter_hash({"expected_doublet_rate": 0.1}),
    )
    approval = service.create_execution_approval(
        scope=scope,
        data_grant_id=grant.grant_id,
        max_uses=2,
        now=now,
    )
    first = service.consume_execution_approval(
        approval.approval_id,
        expected_scope=scope,
        request_id="run-request-1",
        now=now,
    )
    assert first.uses_consumed == 1
    with pytest.raises(PermissionError, match="replay"):
        service.consume_execution_approval(
            approval.approval_id,
            expected_scope=scope,
            request_id="run-request-1",
            now=now,
        )
    second = service.consume_execution_approval(
        approval.approval_id,
        expected_scope=scope,
        request_id="run-request-2",
        now=now,
    )
    assert second.uses_consumed == second.max_uses == 2
    assert service.validate_execution_approval(
        approval.approval_id, expected_scope=scope, now=now
    ).code == "consumed"
    with pytest.raises(PermissionError, match="fully_consumed"):
        service.consume_execution_approval(
            approval.approval_id,
            expected_scope=scope,
            request_id="run-request-3",
            now=now,
        )

    changed = scope.model_copy(
        update={"parameter_hash": parameter_hash({"expected_doublet_rate": 0.12})}
    )
    assert service.validate_execution_approval(
        approval.approval_id, expected_scope=changed, now=now
    ).code == "scope_mismatch"
