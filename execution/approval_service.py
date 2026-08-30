from __future__ import annotations

import hashlib
import json
import re
import uuid
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from core.execution_models import (
    ApprovalScope,
    AuthorizationBindingDecision,
    AuthorizationPrincipal,
    AuthorizationResource,
    ScopedAuthorizationBinding,
    StrictModel,
)

__all__ = [
    "ApprovalScope",
    "ApprovalService",
    "AuthorizationBindingDecision",
    "AuthorizationValidation",
    "ScopedAuthorizationBinding",
    "compare_scoped_authorization_bindings",
    "DataAccessGrant",
    "ExecutionApproval",
    "parameter_hash",
]
from core.settings import PROJECT_ROOT


SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
ValidationCode = Literal[
    "valid",
    "missing",
    "expired",
    "revoked",
    "scope_mismatch",
    "owner_mismatch",
    "consumed",
    "operation_mismatch",
]


class DataAccessGrant(StrictModel):
    grant_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    permissions: list[Literal["profile", "plan"]] = Field(
        default_factory=lambda: ["profile", "plan"]
    )
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def validate_time_window(self) -> "DataAccessGrant":
        if self.expires_at <= self.granted_at:
            raise ValueError("grant expiration must follow grant time")
        return self

    def authorization_binding(
        self, *, operation: Literal["profile", "plan"]
    ) -> ScopedAuthorizationBinding:
        return _data_access_binding(
            user_id=self.user_id,
            artifact_id=self.artifact_id,
            permissions=self.permissions,
            operation=operation,
        )


class ExecutionApproval(StrictModel):
    approval_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    scope: ApprovalScope
    request_fingerprint: str = Field(min_length=64, max_length=64)
    approved_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    max_uses: int = Field(default=1, ge=1, le=18)
    uses_consumed: int = Field(default=0, ge=0)
    consumed_request_ids: list[str] = Field(default_factory=list)
    last_consumed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_binding(self) -> "ExecutionApproval":
        if self.request_fingerprint != self.scope.fingerprint:
            raise ValueError("approval fingerprint does not match scope")
        if self.expires_at <= self.approved_at:
            raise ValueError("approval expiration must follow approval time")
        if self.uses_consumed > self.max_uses:
            raise ValueError("approval uses exceed max_uses")
        if len(set(self.consumed_request_ids)) != len(self.consumed_request_ids):
            raise ValueError("approval request ids must be unique")
        if self.uses_consumed != len(self.consumed_request_ids):
            raise ValueError("approval use count must match consumed request ids")
        return self

    @property
    def authorization_binding(self) -> ScopedAuthorizationBinding:
        return self.scope.authorization_binding


class AuthorizationValidation(StrictModel):
    allowed: bool
    code: ValidationCode
    reasons: list[str] = Field(default_factory=list)


class ApprovalService:
    def __init__(
        self,
        *,
        root: Path = PROJECT_ROOT / ".sckg_exec" / "registry" / "approvals",
    ) -> None:
        self.root = Path(root).resolve()
        self.grant_root = self.root / "grants"
        self.approval_root = self.root / "execution"
        self.audit_log = self.root / "audit.jsonl"
        self.grant_root.mkdir(parents=True, exist_ok=True)
        self.approval_root.mkdir(parents=True, exist_ok=True)
        self._consumption_lock = threading.Lock()

    def grant_data_access(
        self,
        *,
        user_id: str,
        artifact_id: str,
        permissions: list[Literal["profile", "plan"]] | None = None,
        ttl: timedelta = timedelta(hours=1),
        now: datetime | None = None,
    ) -> DataAccessGrant:
        current = now or datetime.now(timezone.utc)
        grant = DataAccessGrant(
            grant_id=f"grant-{uuid.uuid4().hex}",
            user_id=user_id,
            artifact_id=artifact_id,
            permissions=(
                permissions if permissions is not None else ["profile", "plan"]
            ),
            granted_at=current,
            expires_at=current + ttl,
        )
        self._write_model(self.grant_root / f"{grant.grant_id}.json", grant)
        self._audit("data_access_granted", grant.grant_id, user_id, artifact_id)
        return grant

    def validate_data_access(
        self,
        grant_id: str | None,
        *,
        user_id: str,
        artifact_id: str,
        operation: Literal["profile", "plan"] = "plan",
        now: datetime | None = None,
    ) -> AuthorizationValidation:
        if operation not in {"profile", "plan"}:
            return AuthorizationValidation(
                allowed=False,
                code="operation_mismatch",
                reasons=["unsupported_data_access_operation"],
            )
        if not grant_id:
            return AuthorizationValidation(
                allowed=False, code="missing", reasons=["data_access_grant_missing"]
            )
        try:
            grant = self._load_grant(grant_id)
        except KeyError:
            return AuthorizationValidation(
                allowed=False, code="missing", reasons=["data_access_grant_not_found"]
            )
        expected_binding = _data_access_binding(
            user_id=user_id,
            artifact_id=artifact_id,
            permissions=grant.permissions,
            operation=operation,
        )
        binding_decision = compare_scoped_authorization_bindings(
            actual=grant.authorization_binding(operation=operation),
            expected=expected_binding,
        )
        if not binding_decision.allowed:
            return AuthorizationValidation(
                allowed=False,
                code="owner_mismatch",
                reasons=["data_access_scope_mismatch"],
            )
        if operation not in grant.permissions:
            return AuthorizationValidation(
                allowed=False,
                code="operation_mismatch",
                reasons=["data_access_operation_not_granted"],
            )
        return _validate_lifetime(grant.revoked_at, grant.expires_at, now)

    def create_execution_approval(
        self,
        *,
        scope: ApprovalScope,
        data_grant_id: str,
        ttl: timedelta = timedelta(minutes=30),
        max_uses: int = 1,
        now: datetime | None = None,
    ) -> ExecutionApproval:
        access = self.validate_data_access(
            data_grant_id,
            user_id=scope.user_id,
            artifact_id=scope.artifact_id,
            operation="plan",
            now=now,
        )
        if not access.allowed:
            raise PermissionError("valid data access grant required for execution approval")
        current = now or datetime.now(timezone.utc)
        approval = ExecutionApproval(
            approval_id=f"approval-{uuid.uuid4().hex}",
            scope=scope,
            request_fingerprint=scope.fingerprint,
            approved_at=current,
            expires_at=current + ttl,
            max_uses=max_uses,
        )
        self._write_model(
            self.approval_root / f"{approval.approval_id}.json", approval
        )
        self._audit(
            "execution_approved",
            approval.approval_id,
            scope.user_id,
            scope.artifact_id,
            fingerprint=approval.request_fingerprint,
        )
        return approval

    def validate_execution_approval(
        self,
        approval_id: str | None,
        *,
        expected_scope: ApprovalScope,
        now: datetime | None = None,
    ) -> AuthorizationValidation:
        if not approval_id:
            return AuthorizationValidation(
                allowed=False,
                code="missing",
                reasons=["execution_approval_missing"],
            )
        try:
            approval = self._load_approval(approval_id)
        except KeyError:
            return AuthorizationValidation(
                allowed=False,
                code="missing",
                reasons=["execution_approval_not_found"],
            )
        lifetime = _validate_lifetime(approval.revoked_at, approval.expires_at, now)
        if not lifetime.allowed:
            return lifetime
        binding_decision = compare_scoped_authorization_bindings(
            actual=approval.authorization_binding,
            expected=expected_scope.authorization_binding,
        )
        if not binding_decision.allowed:
            return AuthorizationValidation(
                allowed=False,
                code="scope_mismatch",
                reasons=["approval_scope_or_fingerprint_mismatch"],
            )
        if approval.uses_consumed >= approval.max_uses:
            return AuthorizationValidation(
                allowed=False,
                code="consumed",
                reasons=["execution_approval_fully_consumed"],
            )
        return AuthorizationValidation(allowed=True, code="valid")

    def get_execution_approval(self, approval_id: str) -> ExecutionApproval:
        return self._load_approval(approval_id)

    def consume_execution_approval(
        self,
        approval_id: str,
        *,
        expected_scope: ApprovalScope,
        request_id: str,
        now: datetime | None = None,
    ) -> ExecutionApproval:
        if not request_id or SAFE_ID.fullmatch(request_id) is None:
            raise ValueError("unsafe approval consumption request id")
        with self._consumption_lock:
            approval = self._load_approval(approval_id)
            if request_id in approval.consumed_request_ids:
                raise PermissionError("approval replay detected")
            validation = self.validate_execution_approval(
                approval_id, expected_scope=expected_scope, now=now
            )
            if not validation.allowed:
                raise PermissionError(";".join(validation.reasons))
            current = now or datetime.now(timezone.utc)
            updated = approval.model_copy(
                update={
                    "uses_consumed": approval.uses_consumed + 1,
                    "consumed_request_ids": [
                        *approval.consumed_request_ids,
                        request_id,
                    ],
                    "last_consumed_at": current,
                }
            )
            self._write_model(
                self.approval_root / f"{approval_id}.json", updated
            )
            self._audit(
                "execution_approval_consumed",
                approval_id,
                updated.scope.user_id,
                updated.scope.artifact_id,
                fingerprint=updated.request_fingerprint,
            )
            return updated

    def revoke_data_access(
        self, grant_id: str, *, now: datetime | None = None
    ) -> DataAccessGrant:
        grant = self._load_grant(grant_id).model_copy(
            update={"revoked_at": now or datetime.now(timezone.utc)}
        )
        self._write_model(self.grant_root / f"{grant_id}.json", grant)
        self._audit("data_access_revoked", grant_id, grant.user_id, grant.artifact_id)
        return grant

    def revoke_execution_approval(
        self, approval_id: str, *, now: datetime | None = None
    ) -> ExecutionApproval:
        approval = self._load_approval(approval_id).model_copy(
            update={"revoked_at": now or datetime.now(timezone.utc)}
        )
        self._write_model(self.approval_root / f"{approval_id}.json", approval)
        self._audit(
            "execution_approval_revoked",
            approval_id,
            approval.scope.user_id,
            approval.scope.artifact_id,
        )
        return approval

    def _load_grant(self, grant_id: str) -> DataAccessGrant:
        path = self.grant_root / f"{grant_id}.json"
        if not path.is_file():
            raise KeyError(f"data access grant not found: {grant_id}")
        return DataAccessGrant.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_approval(self, approval_id: str) -> ExecutionApproval:
        path = self.approval_root / f"{approval_id}.json"
        if not path.is_file():
            raise KeyError(f"execution approval not found: {approval_id}")
        return ExecutionApproval.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_model(self, path: Path, model: StrictModel) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _audit(
        self,
        event: str,
        record_id: str,
        user_id: str,
        artifact_id: str,
        *,
        fingerprint: str | None = None,
    ) -> None:
        payload = {
            "event": event,
            "record_id": record_id,
            "user_id": user_id,
            "artifact_id": artifact_id,
            "fingerprint": fingerprint,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.audit_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def parameter_hash(parameters: dict) -> str:
    return _canonical_hash(parameters)


def compare_scoped_authorization_bindings(
    *,
    actual: ScopedAuthorizationBinding,
    expected: ScopedAuthorizationBinding,
) -> AuthorizationBindingDecision:
    if actual.principal != expected.principal:
        return AuthorizationBindingDecision(
            allowed=False, mismatch_dimension="principal"
        )
    if actual.operation != expected.operation:
        return AuthorizationBindingDecision(
            allowed=False, mismatch_dimension="operation"
        )
    if actual.resource != expected.resource:
        return AuthorizationBindingDecision(
            allowed=False, mismatch_dimension="resource"
        )
    if actual.scope_fingerprint != expected.scope_fingerprint:
        return AuthorizationBindingDecision(
            allowed=False, mismatch_dimension="scope"
        )
    return AuthorizationBindingDecision(allowed=True)


def _data_access_binding(
    *,
    user_id: str,
    artifact_id: str,
    permissions: list[Literal["profile", "plan"]],
    operation: Literal["profile", "plan"],
) -> ScopedAuthorizationBinding:
    return ScopedAuthorizationBinding(
        principal=AuthorizationPrincipal(principal_id=user_id),
        operation=f"data.{operation}",
        resource=AuthorizationResource(
            resource_id=artifact_id,
            owner_principal_id=user_id,
        ),
        scope_fingerprint=_canonical_hash(
            {
                "user_id": user_id,
                "artifact_id": artifact_id,
                "permissions": sorted(permissions),
            }
        ),
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_lifetime(
    revoked_at: datetime | None,
    expires_at: datetime,
    now: datetime | None,
) -> AuthorizationValidation:
    if revoked_at is not None:
        return AuthorizationValidation(
            allowed=False, code="revoked", reasons=["authorization_revoked"]
        )
    if (now or datetime.now(timezone.utc)) >= expires_at:
        return AuthorizationValidation(
            allowed=False, code="expired", reasons=["authorization_expired"]
        )
    return AuthorizationValidation(allowed=True, code="valid")
