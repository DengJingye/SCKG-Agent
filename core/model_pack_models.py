from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from core.execution_models import StrictModel


SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ModelPackStrictModel(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        protected_namespaces=(),
    )


class ModelPackState(str, Enum):
    MISSING = "missing"
    WAITING_APPROVAL = "waiting_approval"
    INSTALLING = "installing"
    VERIFYING = "verifying"
    READY = "ready"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class ModelPackManifest(ModelPackStrictModel):
    schema_version: Literal["1.0"] = "1.0"
    pack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: str
    purpose: Literal["dense_retrieval"]
    model_id: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    license: str
    platform: Literal["osx-arm64"]
    embedding_dimension: int = Field(gt=0)
    max_sequence_length: int = Field(gt=0)
    python_dependencies: list[str] = Field(min_length=1)
    allowed_install_hosts: list[str] = Field(min_length=1)
    estimated_download_size_bytes: int = Field(gt=0)
    estimated_installed_size_bytes: int = Field(gt=0)
    minimum_free_space_bytes: int = Field(gt=0)
    removable: bool = True
    notes: list[str] = Field(default_factory=list)

    @property
    def manifest_digest(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


class ModelPackInstallPlan(ModelPackStrictModel):
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    pack_id: str
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    state: ModelPackState
    install_root_redacted: str
    disk_free_bytes: int = Field(ge=0)
    minimum_free_space_bytes: int = Field(gt=0)
    estimated_download_size_bytes: int = Field(gt=0)
    estimated_installed_size_bytes: int = Field(gt=0)
    model_id: str
    revision: str
    allowed_install_hosts: list[str]
    command_preview: list[list[str]]
    blockers: list[str] = Field(default_factory=list)
    created_at: datetime


class ModelPackApproval(ModelPackStrictModel):
    approval_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    pack_id: str
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    approved_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifetime(self) -> "ModelPackApproval":
        if self.expires_at <= self.approved_at:
            raise ValueError("model pack approval must expire after approval")
        return self


class ModelPackProbe(ModelPackStrictModel):
    pack_id: str
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    state: ModelPackState
    install_root_redacted: str
    environment_ready: bool
    snapshot_ready: bool
    disk_free_bytes: int = Field(ge=0)
    installed_size_bytes: int = Field(ge=0)
    model_id: str
    revision: str
    snapshot_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    warnings: list[str] = Field(default_factory=list)


class ModelPackInstallationRecord(ModelPackStrictModel):
    record_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    pack_id: str
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    state: ModelPackState
    started_at: datetime
    completed_at: datetime | None = None
    environment_ready: bool = False
    snapshot_ready: bool = False
    smoke_passed: bool = False
    snapshot_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    installed_size_bytes: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0)
    error_code: str | None = None
    error_message: str | None = None
