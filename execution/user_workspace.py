from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from core.execution_models import StrictModel
from core.settings import PROJECT_ROOT


SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class RetentionPolicy(StrictModel):
    run_artifact_ttl: timedelta = timedelta(days=7)
    package_ttl: timedelta = timedelta(days=30)
    retain_minimal_audit: bool = True
    delete_original_input: Literal[False] = False


class UserResourceRecord(StrictModel):
    resource_type: Literal["run", "package"]
    resource_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    owner_user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    status: str
    created_at: datetime
    updated_at: datetime
    cancellation_requested_at: datetime | None = None
    artifacts_deleted_at: datetime | None = None


class UserWorkspaceService:
    def __init__(
        self,
        *,
        root: Path = PROJECT_ROOT / ".sckg_exec" / "users",
        retention_policy: RetentionPolicy | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention_policy = retention_policy or RetentionPolicy()
        self._records: dict[tuple[str, str], UserResourceRecord] = {}
        self._owners: dict[tuple[str, str], str] = {}
        self._load_audit()

    def create_run_directory(
        self,
        *,
        user_id: str,
        run_id: str,
        now: datetime | None = None,
    ) -> Path:
        return self._create("run", user_id, run_id, now, create_directory=True)

    def reserve_run(
        self, *, user_id: str, run_id: str, now: datetime | None = None
    ) -> Path:
        return self._create("run", user_id, run_id, now, create_directory=False)

    def create_package_directory(
        self,
        *,
        user_id: str,
        package_id: str,
        now: datetime | None = None,
    ) -> Path:
        return self._create("package", user_id, package_id, now, create_directory=True)

    def reserve_package(
        self, *, user_id: str, package_id: str, now: datetime | None = None
    ) -> Path:
        return self._create("package", user_id, package_id, now, create_directory=False)

    def get_run_directory(self, *, user_id: str, run_id: str) -> Path:
        return self._get("run", user_id, run_id)

    def get_package_directory(self, *, user_id: str, package_id: str) -> Path:
        return self._get("package", user_id, package_id)

    def write_package_manifest(
        self,
        *,
        user_id: str,
        package_id: str,
        artifact_id: str,
        input_hash: str,
        plan_id: str,
    ) -> Path:
        package_dir = self.get_package_directory(
            user_id=user_id, package_id=package_id
        )
        manifest = package_dir / "input_reference.json"
        manifest.write_text(
            json.dumps(
                {
                    "artifact_id": artifact_id,
                    "input_hash": input_hash,
                    "plan_id": plan_id,
                    "input_data_copied": False,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return manifest

    def mark_run_running(
        self, *, user_id: str, run_id: str, now: datetime | None = None
    ) -> UserResourceRecord:
        return self._update("run", user_id, run_id, "running", now=now)

    def request_cancellation(
        self, *, user_id: str, run_id: str, now: datetime | None = None
    ) -> UserResourceRecord:
        current = now or datetime.now(timezone.utc)
        current_record = self._require_owner("run", user_id, run_id)
        if current_record.status not in {"running", "cancellation_requested"}:
            raise ValueError("only a running process can be cancelled")
        record = current_record.model_copy(
            update={
                "status": "cancellation_requested",
                "updated_at": current,
                "cancellation_requested_at": current,
            }
        )
        self._store(record, "run_cancellation_requested")
        return record

    def get_record(
        self,
        *,
        resource_type: Literal["run", "package"],
        user_id: str,
        resource_id: str,
    ) -> UserResourceRecord:
        return self._require_owner(resource_type, user_id, resource_id)

    def cancellation_reason(self, *, user_id: str, run_id: str) -> str | None:
        record = self._require_owner("run", user_id, run_id)
        if record.status == "cancellation_requested":
            return "cancelled_by_local_user"
        return None

    def mark_run_terminal(
        self,
        *,
        user_id: str,
        run_id: str,
        status: Literal["succeeded", "failed", "timeout", "cancelled", "blocked"],
        now: datetime | None = None,
    ) -> UserResourceRecord:
        return self._update("run", user_id, run_id, status, now=now)

    def mark_completed(
        self,
        *,
        resource_type: Literal["run", "package"],
        user_id: str,
        resource_id: str,
        now: datetime | None = None,
    ) -> UserResourceRecord:
        return self._update(resource_type, user_id, resource_id, "completed", now=now)

    def delete_run_artifacts(
        self, *, user_id: str, run_id: str, now: datetime | None = None
    ) -> UserResourceRecord:
        record = self._require_owner("run", user_id, run_id)
        run_dir = self._resource_path("run", user_id, run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir)
        current = now or datetime.now(timezone.utc)
        updated = record.model_copy(
            update={
                "status": "artifacts_deleted",
                "updated_at": current,
                "artifacts_deleted_at": current,
            }
        )
        self._store(updated, "run_artifacts_deleted")
        return updated

    def apply_retention(self, *, now: datetime | None = None) -> list[str]:
        current = now or datetime.now(timezone.utc)
        deleted: list[str] = []
        for key, record in list(self._records.items()):
            if record.status not in {"completed", "failed", "cancelled"}:
                continue
            ttl = (
                self.retention_policy.run_artifact_ttl
                if record.resource_type == "run"
                else self.retention_policy.package_ttl
            )
            if current - record.updated_at < ttl:
                continue
            path = self._resource_path(
                record.resource_type, record.owner_user_id, record.resource_id
            )
            if path.exists():
                shutil.rmtree(path)
            updated = record.model_copy(
                update={
                    "status": "artifacts_deleted",
                    "updated_at": current,
                    "artifacts_deleted_at": current,
                }
            )
            self._store(updated, f"{record.resource_type}_retention_deleted")
            deleted.append(record.resource_id)
        return sorted(deleted)

    def _create(
        self,
        resource_type: Literal["run", "package"],
        user_id: str,
        resource_id: str,
        now: datetime | None,
        create_directory: bool,
    ) -> Path:
        _validate_id(user_id)
        _validate_id(resource_id)
        owner = self._owners.get((resource_type, resource_id))
        if owner is not None and owner != user_id:
            raise PermissionError("cross-user resource id reuse is forbidden")
        path = self._resource_path(resource_type, user_id, resource_id)
        if path.exists():
            raise FileExistsError(f"resource directory already exists: {resource_id}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if create_directory:
            path.mkdir()
        current = now or datetime.now(timezone.utc)
        record = UserResourceRecord(
            resource_type=resource_type,
            resource_id=resource_id,
            owner_user_id=user_id,
            status="created",
            created_at=current,
            updated_at=current,
        )
        self._owners[(resource_type, resource_id)] = user_id
        self._store(record, f"{resource_type}_created")
        return path

    def _get(
        self, resource_type: Literal["run", "package"], user_id: str, resource_id: str
    ) -> Path:
        self._require_owner(resource_type, user_id, resource_id)
        path = self._resource_path(resource_type, user_id, resource_id)
        if not path.exists():
            raise FileNotFoundError(f"resource artifacts no longer exist: {resource_id}")
        return path

    def _update(
        self,
        resource_type: Literal["run", "package"],
        user_id: str,
        resource_id: str,
        status: str,
        *,
        now: datetime | None,
    ) -> UserResourceRecord:
        record = self._require_owner(resource_type, user_id, resource_id).model_copy(
            update={"status": status, "updated_at": now or datetime.now(timezone.utc)}
        )
        self._store(record, f"{resource_type}_{status}")
        return record

    def _require_owner(
        self, resource_type: Literal["run", "package"], user_id: str, resource_id: str
    ) -> UserResourceRecord:
        owner = self._owners.get((resource_type, resource_id))
        if owner is None:
            raise KeyError(f"resource is not registered: {resource_id}")
        if owner != user_id:
            raise PermissionError("cross-user resource access is forbidden")
        return self._records[(resource_type, resource_id)]

    def _resource_path(
        self, resource_type: Literal["run", "package"], user_id: str, resource_id: str
    ) -> Path:
        directory = "runs" if resource_type == "run" else "packages"
        path = (self.root / user_id / directory / resource_id).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("user resource path escapes workspace root") from exc
        return path

    def _store(self, record: UserResourceRecord, event: str) -> None:
        key = (record.resource_type, record.resource_id)
        self._records[key] = record
        audit_dir = self.root / record.owner_user_id / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "event": event,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "owner_user_id": record.owner_user_id,
            "status": record.status,
            "recorded_at": record.updated_at.isoformat(),
        }
        with (audit_dir / "resources.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def _load_audit(self) -> None:
        for audit_path in sorted(self.root.glob("*/audit/resources.jsonl")):
            for line in audit_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                resource_type = payload.get("resource_type")
                resource_id = payload.get("resource_id")
                owner = payload.get("owner_user_id")
                if resource_type not in {"run", "package"}:
                    continue
                if not isinstance(resource_id, str) or not isinstance(owner, str):
                    continue
                recorded_at = datetime.fromisoformat(payload["recorded_at"])
                key = (resource_type, resource_id)
                previous = self._records.get(key)
                record = UserResourceRecord(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    owner_user_id=owner,
                    status=str(payload.get("status", "unknown")),
                    created_at=(previous.created_at if previous else recorded_at),
                    updated_at=recorded_at,
                    cancellation_requested_at=(
                        recorded_at
                        if payload.get("event") == "run_cancellation_requested"
                        else (
                            previous.cancellation_requested_at if previous else None
                        )
                    ),
                    artifacts_deleted_at=(
                        recorded_at
                        if str(payload.get("event", "")).endswith(
                            ("artifacts_deleted", "retention_deleted")
                        )
                        else (previous.artifacts_deleted_at if previous else None)
                    ),
                )
                self._owners[key] = owner
                self._records[key] = record


def _validate_id(value: str) -> None:
    if not value or SAFE_ID.fullmatch(value) is None:
        raise ValueError("unsafe user resource identifier")
