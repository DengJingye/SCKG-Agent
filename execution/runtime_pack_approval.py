from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.runtime_pack_models import (
    EnvironmentApprovalValidation,
    EnvironmentProvisioningApproval,
    EnvironmentProvisioningPlan,
)


class RuntimePackApprovalService:
    """One-time consent store for a specific pack manifest and install plan."""

    def __init__(self, *, root: Path) -> None:
        self.root = Path(root).resolve()
        self.plan_root = self.root / "plans"
        self.approval_root = self.root / "approvals"
        self.audit_path = self.root / "audit.jsonl"
        self.plan_root.mkdir(parents=True, exist_ok=True)
        self.approval_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save_plan(self, plan: EnvironmentProvisioningPlan) -> None:
        self._write(self.plan_root / f"{plan.plan_id}.json", plan)
        self._audit("environment_plan_created", plan.plan_id, plan.user_id, plan.pack_id)

    def get_plan(self, plan_id: str) -> EnvironmentProvisioningPlan:
        path = self.plan_root / f"{plan_id}.json"
        if not path.is_file():
            raise KeyError("environment provisioning plan not found")
        return EnvironmentProvisioningPlan.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    @staticmethod
    def confirmation_text(plan: EnvironmentProvisioningPlan) -> str:
        return f"INSTALL {plan.manifest_digest[:12]}"

    def approve(
        self,
        *,
        plan_id: str,
        user_id: str,
        confirmation_text: str,
        ttl: timedelta = timedelta(minutes=30),
        now: datetime | None = None,
    ) -> EnvironmentProvisioningApproval:
        plan = self.get_plan(plan_id)
        if plan.user_id != user_id:
            raise PermissionError("environment plan owner mismatch")
        if plan.blockers:
            raise PermissionError("blocked environment plan cannot be approved")
        if confirmation_text.strip() != self.confirmation_text(plan):
            raise PermissionError("environment approval confirmation text mismatch")
        current = now or datetime.now(timezone.utc)
        approval = EnvironmentProvisioningApproval(
            approval_id=f"env-approval-{uuid.uuid4().hex}",
            plan_id=plan.plan_id,
            user_id=user_id,
            pack_id=plan.pack_id,
            manifest_digest=plan.manifest_digest,
            approved_at=current,
            expires_at=current + ttl,
        )
        self._write(self.approval_root / f"{approval.approval_id}.json", approval)
        self._audit(
            "environment_install_approved",
            approval.approval_id,
            user_id,
            plan.pack_id,
        )
        return approval

    def validate(
        self,
        *,
        approval_id: str | None,
        plan: EnvironmentProvisioningPlan,
        now: datetime | None = None,
    ) -> EnvironmentApprovalValidation:
        if not approval_id:
            return EnvironmentApprovalValidation(
                allowed=False, reasons=["environment_approval_missing"]
            )
        try:
            approval = self._load_approval(approval_id)
        except KeyError:
            return EnvironmentApprovalValidation(
                allowed=False, reasons=["environment_approval_not_found"]
            )
        reasons: list[str] = []
        current = now or datetime.now(timezone.utc)
        if approval.revoked_at is not None:
            reasons.append("environment_approval_revoked")
        if current >= approval.expires_at:
            reasons.append("environment_approval_expired")
        if approval.consumed_at is not None:
            reasons.append("environment_approval_consumed")
        if approval.plan_id != plan.plan_id or approval.user_id != plan.user_id:
            reasons.append("environment_approval_plan_or_owner_mismatch")
        if approval.pack_id != plan.pack_id:
            reasons.append("environment_approval_pack_mismatch")
        if approval.manifest_digest != plan.manifest_digest:
            reasons.append("environment_manifest_changed_after_approval")
        return EnvironmentApprovalValidation(
            allowed=not reasons, reasons=sorted(set(reasons))
        )

    def consume(
        self,
        *,
        approval_id: str,
        plan: EnvironmentProvisioningPlan,
        now: datetime | None = None,
    ) -> EnvironmentProvisioningApproval:
        with self._lock:
            validation = self.validate(approval_id=approval_id, plan=plan, now=now)
            if not validation.allowed:
                raise PermissionError(";".join(validation.reasons))
            approval = self._load_approval(approval_id).model_copy(
                update={"consumed_at": now or datetime.now(timezone.utc)}
            )
            self._write(
                self.approval_root / f"{approval.approval_id}.json", approval
            )
            self._audit(
                "environment_approval_consumed",
                approval.approval_id,
                approval.user_id,
                approval.pack_id,
            )
            return approval

    def revoke(
        self, approval_id: str, *, now: datetime | None = None
    ) -> EnvironmentProvisioningApproval:
        approval = self._load_approval(approval_id).model_copy(
            update={"revoked_at": now or datetime.now(timezone.utc)}
        )
        self._write(self.approval_root / f"{approval_id}.json", approval)
        self._audit(
            "environment_approval_revoked",
            approval.approval_id,
            approval.user_id,
            approval.pack_id,
        )
        return approval

    def _load_approval(self, approval_id: str) -> EnvironmentProvisioningApproval:
        path = self.approval_root / f"{approval_id}.json"
        if not path.is_file():
            raise KeyError("environment provisioning approval not found")
        return EnvironmentProvisioningApproval.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    @staticmethod
    def _write(path: Path, model) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _audit(self, event: str, record_id: str, user_id: str, pack_id: str) -> None:
        payload = {
            "event": event,
            "record_id": record_id,
            "user_id": user_id,
            "pack_id": pack_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
