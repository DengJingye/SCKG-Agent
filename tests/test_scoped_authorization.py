from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.execution_models import ApprovalScope
from execution.approval_service import (
    ApprovalService,
    compare_scoped_authorization_bindings,
    parameter_hash,
)
from execution.execution_policy import ExecutionPolicy, ExecutionPolicyMode


NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _scope(**updates) -> ApprovalScope:
    values = {
        "user_id": "alice",
        "artifact_id": "artifact-a",
        "plan_id": "plan-a",
        "tool_name": "Scrublet",
        "tool_version": "0.2.3",
        "contract_version": "contract-v1",
        "environment_id": "scRNAseq",
        "parameter_hash": parameter_hash({"expected_doublet_rate": 0.1}),
    }
    values.update(updates)
    return ApprovalScope(**values)


def test_scoped_binding_exposes_current_principal_operation_resource_and_scope():
    binding = _scope().authorization_binding

    assert binding.schema_version == "sckg-scoped-authorization-v0"
    assert binding.principal.model_dump(mode="json") == {
        "principal_type": "local_user",
        "principal_id": "alice",
    }
    assert binding.operation == "execution.run"
    assert binding.resource.model_dump(mode="json") == {
        "resource_type": "artifact",
        "resource_id": "artifact-a",
        "owner_principal_id": "alice",
    }
    assert binding.scope_fingerprint == _scope().fingerprint

    mismatches = {
        "principal": _scope(user_id="bob").authorization_binding,
        "resource": _scope(artifact_id="artifact-b").authorization_binding,
        "scope": _scope(plan_id="plan-b").authorization_binding,
        "operation": binding.model_copy(update={"operation": "data.plan"}),
    }
    for dimension, expected in mismatches.items():
        decision = compare_scoped_authorization_bindings(
            actual=binding,
            expected=expected,
        )
        assert decision.allowed is False
        assert decision.mismatch_dimension == dimension


def test_data_grant_enforces_operation_without_changing_default_policy(tmp_path):
    approvals = ApprovalService(root=tmp_path / "approvals")
    profile_only = approvals.grant_data_access(
        user_id="alice",
        artifact_id="artifact-a",
        permissions=["profile"],
        now=NOW,
    )

    assert approvals.validate_data_access(
        profile_only.grant_id,
        user_id="alice",
        artifact_id="artifact-a",
        operation="profile",
        now=NOW,
    ).allowed
    plan = approvals.validate_data_access(
        profile_only.grant_id,
        user_id="alice",
        artifact_id="artifact-a",
        operation="plan",
        now=NOW,
    )
    assert plan.allowed is False
    assert plan.code == "operation_mismatch"
    assert plan.reasons == ["data_access_operation_not_granted"]
    assert approvals.validate_data_access(
        profile_only.grant_id,
        user_id="alice",
        artifact_id="artifact-a",
        operation="execute",  # type: ignore[arg-type]
        now=NOW,
    ).reasons == ["unsupported_data_access_operation"]
    with pytest.raises(PermissionError, match="valid data access grant"):
        approvals.create_execution_approval(
            scope=_scope(), data_grant_id=profile_only.grant_id, now=NOW
        )
    assert ExecutionPolicy().mode == ExecutionPolicyMode.DISABLED


def test_execution_binding_blocks_cross_user_resource_drift_scope_drift_and_replay(
    tmp_path,
):
    approvals = ApprovalService(root=tmp_path / "approvals")
    grant = approvals.grant_data_access(
        user_id="alice", artifact_id="artifact-a", now=NOW
    )
    approval = approvals.create_execution_approval(
        scope=_scope(),
        data_grant_id=grant.grant_id,
        max_uses=2,
        now=NOW,
    )

    assert approvals.get_execution_approval(
        approval.approval_id
    ).authorization_binding == _scope().authorization_binding
    for changed in (
        _scope(user_id="bob"),
        _scope(artifact_id="artifact-b"),
        _scope(plan_id="plan-b"),
    ):
        decision = approvals.validate_execution_approval(
            approval.approval_id,
            expected_scope=changed,
            now=NOW,
        )
        assert decision.allowed is False
        assert decision.code == "scope_mismatch"

    consumed = approvals.consume_execution_approval(
        approval.approval_id,
        expected_scope=_scope(),
        request_id="request-a",
        now=NOW,
    )
    assert consumed.uses_consumed == 1
    with pytest.raises(PermissionError, match="replay"):
        approvals.consume_execution_approval(
            approval.approval_id,
            expected_scope=_scope(),
            request_id="request-a",
            now=NOW,
        )
