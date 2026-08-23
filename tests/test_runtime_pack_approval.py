from datetime import datetime, timedelta, timezone

import pytest

from execution.runtime_pack_approval import RuntimePackApprovalService
from execution.runtime_pack_manager import RuntimePackManager
from tests.runtime_pack_helpers import build_test_registry


def test_environment_approval_is_exact_expiring_revocable_and_one_time(tmp_path):
    registry = build_test_registry(tmp_path)
    approvals = RuntimePackApprovalService(root=tmp_path / "approvals")
    manager = RuntimePackManager(
        registry=registry,
        home=tmp_path / "home",
        approval_service=approvals,
        disk_safety_margin_bytes=0,
    )
    plan = manager.create_plan(pack_id="test-pack", user_id="user-a")
    assert not plan.blockers
    with pytest.raises(PermissionError, match="confirmation"):
        approvals.approve(
            plan_id=plan.plan_id,
            user_id="user-a",
            confirmation_text="INSTALL something-else",
        )
    now = datetime.now(timezone.utc)
    approval = approvals.approve(
        plan_id=plan.plan_id,
        user_id="user-a",
        confirmation_text=approvals.confirmation_text(plan),
        now=now,
    )
    assert approvals.validate(approval_id=approval.approval_id, plan=plan).allowed
    consumed = approvals.consume(approval_id=approval.approval_id, plan=plan)
    assert consumed.consumed_at is not None
    assert "environment_approval_consumed" in approvals.validate(
        approval_id=approval.approval_id, plan=plan
    ).reasons

    second = approvals.approve(
        plan_id=plan.plan_id,
        user_id="user-a",
        confirmation_text=approvals.confirmation_text(plan),
        ttl=timedelta(seconds=1),
        now=now,
    )
    assert "environment_approval_expired" in approvals.validate(
        approval_id=second.approval_id,
        plan=plan,
        now=now + timedelta(seconds=2),
    ).reasons
    third = approvals.approve(
        plan_id=plan.plan_id,
        user_id="user-a",
        confirmation_text=approvals.confirmation_text(plan),
    )
    approvals.revoke(third.approval_id)
    assert "environment_approval_revoked" in approvals.validate(
        approval_id=third.approval_id, plan=plan
    ).reasons
