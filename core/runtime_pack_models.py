from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, computed_field, field_validator, model_validator

from core.execution_models import StrictModel


SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RuntimePackState(str, Enum):
    MISSING = "missing"
    WAITING_APPROVAL = "waiting_environment_approval"
    INSTALLING = "installing"
    VERIFYING = "verifying"
    READY = "ready"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class RuntimePackSource(str, Enum):
    NONE = "none"
    MANAGED = "managed_pack"
    LEGACY_CONDA = "legacy_conda_environment"


class RuntimeNetworkPolicy(str, Enum):
    NETWORK_NOT_OS_ISOLATED = "network_not_os_isolated"
    NETWORK_DISABLED = "network_disabled"


class RuntimeLockFile(StrictModel):
    path: str = Field(min_length=1)
    kind: Literal["conda_explicit", "pip_requirements", "r_source_requirements"]
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("runtime lock path must be relative and cannot traverse")
        return value


class RuntimePackTool(StrictModel):
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    environment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    wrapper_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")


class RuntimePackManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    pack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: str = Field(min_length=1)
    task_family: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1)
    platform: Literal["osx-arm64", "linux-64"]
    architecture: Literal["arm64", "x86_64"]
    supported_tools: list[RuntimePackTool] = Field(min_length=1)
    lock_files: list[RuntimeLockFile] = Field(min_length=1)
    package_sources: list[str] = Field(min_length=1)
    licenses: list[str] = Field(min_length=1)
    allowed_install_hosts: list[str] = Field(default_factory=list)
    estimated_download_size_bytes: int = Field(ge=0)
    estimated_installed_size_bytes: int = Field(gt=0)
    network_required_for_install: bool = True
    runtime_network_policy: RuntimeNetworkPolicy = (
        RuntimeNetworkPolicy.NETWORK_NOT_OS_ISOLATED
    )
    qualification_status: Literal[
        "manifest_only", "import_qualified", "integration_passed"
    ]
    removable: bool = True
    legacy_environment_name: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    python_entrypoint: str | None = None
    rscript_entrypoint: str | None = None
    import_smoke_modules: list[str] = Field(default_factory=list)
    r_smoke_packages: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("python_entrypoint", "rscript_entrypoint")
    @classmethod
    def require_safe_entrypoint(cls, value: str | None) -> str | None:
        if value is None:
            return value
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("runtime entrypoint must be relative and cannot traverse")
        return value

    @field_validator("import_smoke_modules", "r_smoke_packages")
    @classmethod
    def require_safe_package_names(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._" for char in value):
                raise ValueError("runtime smoke package names must be identifiers")
        return values

    @model_validator(mode="after")
    def validate_network_and_entrypoints(self) -> "RuntimePackManifest":
        if self.network_required_for_install and not self.allowed_install_hosts:
            raise ValueError("networked pack installation requires allowed hosts")
        if self.import_smoke_modules and not self.python_entrypoint:
            raise ValueError("Python smoke modules require a Python entrypoint")
        if self.r_smoke_packages and not self.rscript_entrypoint:
            raise ValueError("R smoke packages require an Rscript entrypoint")
        environment_ids = [item.environment_id for item in self.supported_tools]
        if len(set(environment_ids)) != 1:
            raise ValueError("one runtime pack manifest must map to one environment id")
        return self

    @computed_field
    @property
    def manifest_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"manifest_digest"})
        return _canonical_hash(payload)

    @property
    def environment_id(self) -> str:
        return self.supported_tools[0].environment_id


class EnvironmentProvisioningPlan(StrictModel):
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    pack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    pack_version: str
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    platform: str
    state: RuntimePackState
    install_path_redacted: str
    estimated_download_size_bytes: int = Field(ge=0)
    estimated_installed_size_bytes: int = Field(gt=0)
    disk_free_bytes: int = Field(ge=0)
    disk_quota_bytes: int = Field(gt=0)
    allowed_install_hosts: list[str] = Field(default_factory=list)
    runtime_network_policy: RuntimeNetworkPolicy
    command_preview: list[list[str]] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    approval_required: bool = True
    created_at: datetime


class EnvironmentProvisioningApproval(StrictModel):
    approval_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    pack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    approved_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    consumed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifetime(self) -> "EnvironmentProvisioningApproval":
        if self.expires_at <= self.approved_at:
            raise ValueError("environment approval expiration must follow approval")
        return self


class RuntimeCapabilityProbe(StrictModel):
    pack_id: str
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    state: RuntimePackState
    source: RuntimePackSource = RuntimePackSource.NONE
    platform_supported: bool
    install_prefix_redacted: str
    environment_id: str
    executable_paths: dict[str, str] = Field(default_factory=dict)
    disk_free_bytes: int = Field(ge=0)
    logical_size_bytes: int = Field(ge=0)
    physical_size_bytes: int = Field(default=0, ge=0)
    last_used_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.state == RuntimePackState.READY


class PackInstallationRecord(StrictModel):
    record_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    pack_id: str
    pack_version: str
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    state: RuntimePackState
    source: RuntimePackSource
    install_prefix: str
    started_at: datetime
    completed_at: datetime | None = None
    lock_hashes_verified: bool = False
    smoke_passed: bool = False
    command_argv_redacted: list[list[str]] = Field(default_factory=list)
    stdout_path: str | None = None
    stderr_path: str | None = None
    exit_code: int | None = None
    installed_size_bytes: int = Field(default=0, ge=0)
    installed_physical_size_bytes: int = Field(default=0, ge=0)
    cache_size_before_bytes: int = Field(default=0, ge=0)
    cache_size_after_bytes: int = Field(default=0, ge=0)
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    error_code: str | None = None
    error_message: str | None = None


class EnvironmentApprovalValidation(StrictModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)


class ControlPlaneLockAsset(StrictModel):
    path: str = Field(min_length=1)
    kind: Literal["conda_explicit", "pip_requirements"]
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("control-plane lock path must be safe and relative")
        return value


class MicromambaBootstrapArtifact(StrictModel):
    version: str = Field(min_length=1)
    platform: Literal["osx-arm64"]
    url: str = Field(pattern=r"^https://")
    sha256: str = Field(pattern=SHA256_PATTERN)
    archive_size_bytes: int = Field(gt=0)


class ControlPlaneReleaseManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    product: str = Field(min_length=1)
    release_version: str = Field(min_length=1)
    release_status: Literal["release_candidate", "clean_machine_accepted"]
    platform: Literal["osx-arm64"]
    architecture: Literal["arm64"]
    micromamba: MicromambaBootstrapArtifact
    lock_files: list[ControlPlaneLockAsset] = Field(min_length=2)
    python_entrypoint: str = "bin/python"
    app_entrypoint: str = "app.py"
    default_home: str = "~/.sckg"
    allowed_install_hosts: list[str] = Field(min_length=1)
    max_core_release_size_bytes: int = Field(gt=0)
    max_first_launch_size_bytes: int = Field(gt=0)

    @field_validator("python_entrypoint", "app_entrypoint")
    @classmethod
    def require_safe_entrypoint(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("control-plane entrypoint must be safe and relative")
        return value


class RuntimePackInstallTelemetry(StrictModel):
    record_id: str
    pack_id: str
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    state: RuntimePackState
    elapsed_ms: float = Field(ge=0.0)
    cache_size_before_bytes: int = Field(ge=0)
    cache_size_after_bytes: int = Field(ge=0)
    cache_growth_bytes: int
    installed_logical_size_bytes: int = Field(ge=0)
    installed_physical_size_bytes: int = Field(ge=0)
    allowed_install_hosts: list[str] = Field(default_factory=list)
    smoke_passed: bool
    error_code: str | None = None


class RuntimePackAcceptanceItem(StrictModel):
    pack_id: str
    initial_state: RuntimePackState
    final_state: RuntimePackState
    installed_from_lock: bool
    remove_rebuild_passed: bool = False
    telemetry: list[RuntimePackInstallTelemetry] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class RuntimePackAcceptanceResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    acceptance_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    platform: str
    isolated_home_redacted: str
    legacy_fallback_disabled: bool
    core_cold_start_passed: bool
    pack_results: list[RuntimePackAcceptanceItem] = Field(default_factory=list)
    cache_relocation_passed: bool = False
    release_archive_passed: bool = False
    release_size_bytes: int = Field(default=0, ge=0)
    first_launch_size_bytes: int = Field(default=0, ge=0)
    privacy_issue_count: int = Field(default=0, ge=0)
    status: Literal["release_candidate", "clean_machine_accepted", "blocked"]
    blockers: list[str] = Field(default_factory=list)
    created_at: datetime


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
