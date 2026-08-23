from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from core.model_pack_models import (
    ModelPackApproval,
    ModelPackInstallationRecord,
    ModelPackInstallPlan,
    ModelPackManifest,
    ModelPackProbe,
    ModelPackState,
)
from core.settings import PROJECT_ROOT


DEFAULT_MANIFEST = (
    PROJECT_ROOT / "model_packs/manifests/retrieval-bge-m3.json"
)


def default_sckg_home() -> Path:
    configured = os.environ.get("SCKG_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".sckg"


class ModelPackManager:
    """Install a maintainer-pinned local model without touching the control plane."""

    def __init__(
        self,
        *,
        manifest_path: Path = DEFAULT_MANIFEST,
        home: Path | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.manifest = ModelPackManifest.model_validate_json(
            self.manifest_path.read_text(encoding="utf-8")
        )
        self.home = (home or default_sckg_home()).expanduser().resolve()
        self.pack_root = self.home / "model_packs" / self.manifest.pack_id
        self.environment_root = self.pack_root / "environment"
        self.snapshot_root = self.pack_root / "snapshot"
        self.registry_root = self.home / "registry" / "model_packs"
        self.command_runner = command_runner

    @property
    def python_executable(self) -> Path:
        return self.environment_root / "bin" / "python"

    @property
    def metadata_path(self) -> Path:
        return self.pack_root / "metadata.json"

    def probe(self) -> ModelPackProbe:
        disk_free = shutil.disk_usage(self.home.parent if not self.home.exists() else self.home).free
        metadata = _read_json(self.metadata_path)
        environment_ready = self.python_executable.is_file()
        snapshot_ready = (self.snapshot_root / "config.json").is_file()
        digest = metadata.get("snapshot_digest")
        ready = (
            environment_ready
            and snapshot_ready
            and metadata.get("manifest_digest") == self.manifest.manifest_digest
            and metadata.get("revision") == self.manifest.revision
            and isinstance(digest, str)
        )
        warnings: list[str] = []
        if platform.machine() != "arm64" or sys.platform != "darwin":
            state = ModelPackState.UNSUPPORTED
            warnings.append("model_pack_platform_unsupported")
        else:
            state = ModelPackState.READY if ready else ModelPackState.MISSING
            if metadata and not ready:
                warnings.append("model_pack_metadata_or_assets_stale")
        return ModelPackProbe(
            pack_id=self.manifest.pack_id,
            manifest_digest=self.manifest.manifest_digest,
            state=state,
            install_root_redacted=self.redact_path(self.pack_root),
            environment_ready=environment_ready,
            snapshot_ready=snapshot_ready,
            disk_free_bytes=disk_free,
            installed_size_bytes=_directory_size(self.pack_root),
            model_id=self.manifest.model_id,
            revision=self.manifest.revision,
            snapshot_digest=digest if isinstance(digest, str) else None,
            warnings=warnings,
        )

    def create_plan(self) -> ModelPackInstallPlan:
        probe = self.probe()
        blockers = list(probe.warnings)
        if probe.state == ModelPackState.READY:
            blockers.append("model_pack_already_ready")
        if probe.disk_free_bytes < self.manifest.minimum_free_space_bytes:
            blockers.append("model_pack_insufficient_disk")
        command_preview = [
            ["python", "-m", "venv", "<SCKG_HOME>/model_packs/retrieval-bge-m3/environment"],
            ["<pack-python>", "-m", "pip", "install", *self.manifest.python_dependencies],
            [
                "<pack-python>",
                "scripts/download_bge_m3_model.py",
                "--revision",
                self.manifest.revision,
                "--output",
                "<SCKG_HOME>/model_packs/retrieval-bge-m3/snapshot",
            ],
        ]
        return ModelPackInstallPlan(
            plan_id=f"model-plan-{uuid.uuid4().hex}",
            pack_id=self.manifest.pack_id,
            manifest_digest=self.manifest.manifest_digest,
            state=ModelPackState.WAITING_APPROVAL,
            install_root_redacted=self.redact_path(self.pack_root),
            disk_free_bytes=probe.disk_free_bytes,
            minimum_free_space_bytes=self.manifest.minimum_free_space_bytes,
            estimated_download_size_bytes=self.manifest.estimated_download_size_bytes,
            estimated_installed_size_bytes=self.manifest.estimated_installed_size_bytes,
            model_id=self.manifest.model_id,
            revision=self.manifest.revision,
            allowed_install_hosts=self.manifest.allowed_install_hosts,
            command_preview=command_preview,
            blockers=sorted(set(blockers)),
            created_at=datetime.now(timezone.utc),
        )

    def approve(self, plan: ModelPackInstallPlan) -> ModelPackApproval:
        if plan.blockers:
            raise ValueError(f"model pack plan is blocked: {','.join(plan.blockers)}")
        now = datetime.now(timezone.utc)
        return ModelPackApproval(
            approval_id=f"model-approval-{uuid.uuid4().hex}",
            plan_id=plan.plan_id,
            pack_id=plan.pack_id,
            manifest_digest=plan.manifest_digest,
            approved_at=now,
            expires_at=now + timedelta(minutes=30),
        )

    def install(
        self,
        plan: ModelPackInstallPlan,
        approval: ModelPackApproval,
    ) -> ModelPackInstallationRecord:
        self._validate_approval(plan, approval)
        started = datetime.now(timezone.utc)
        started_clock = time.monotonic()
        record_id = f"model-install-{uuid.uuid4().hex}"
        try:
            self.pack_root.mkdir(parents=True, exist_ok=True)
            if not self.python_executable.is_file():
                self._run([sys.executable, "-m", "venv", str(self.environment_root)])
            self._run(
                [
                    str(self.python_executable),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    *self.manifest.python_dependencies,
                ]
            )
            self._run(
                [
                    str(self.python_executable),
                    str(PROJECT_ROOT / "scripts/download_bge_m3_model.py"),
                    "--model-id",
                    self.manifest.model_id,
                    "--revision",
                    self.manifest.revision,
                    "--output",
                    str(self.snapshot_root),
                ]
            )
            snapshot_digest = _tree_digest(self.snapshot_root)
            self._run(
                [
                    str(self.python_executable),
                    str(PROJECT_ROOT / "execution/model_workers/bge_m3_worker.py"),
                    "--model-path",
                    str(self.snapshot_root),
                    "--smoke",
                ],
                offline=True,
            )
            metadata = {
                "schema_version": "model-pack-install-v1",
                "pack_id": self.manifest.pack_id,
                "manifest_digest": self.manifest.manifest_digest,
                "model_id": self.manifest.model_id,
                "revision": self.manifest.revision,
                "snapshot_digest": snapshot_digest,
                "installed_at": datetime.now(timezone.utc).isoformat(),
                "rebuild_command": "python scripts/manage_bge_m3_pack.py install --approve",
            }
            self.metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            approval.consumed_at = datetime.now(timezone.utc)
            record = ModelPackInstallationRecord(
                record_id=record_id,
                pack_id=self.manifest.pack_id,
                manifest_digest=self.manifest.manifest_digest,
                state=ModelPackState.READY,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                environment_ready=True,
                snapshot_ready=True,
                smoke_passed=True,
                snapshot_digest=snapshot_digest,
                installed_size_bytes=_directory_size(self.pack_root),
                elapsed_ms=(time.monotonic() - started_clock) * 1000,
            )
        except Exception as exc:
            record = ModelPackInstallationRecord(
                record_id=record_id,
                pack_id=self.manifest.pack_id,
                manifest_digest=self.manifest.manifest_digest,
                state=ModelPackState.FAILED,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                environment_ready=self.python_executable.is_file(),
                snapshot_ready=(self.snapshot_root / "config.json").is_file(),
                smoke_passed=False,
                installed_size_bytes=_directory_size(self.pack_root),
                elapsed_ms=(time.monotonic() - started_clock) * 1000,
                error_code=type(exc).__name__,
                error_message=str(exc)[:800],
            )
        self._write_record(record)
        return record

    def remove(self) -> None:
        if self.pack_root.is_symlink():
            raise ValueError("model pack root cannot be a symlink")
        if self.pack_root.exists():
            shutil.rmtree(self.pack_root)

    def redact_path(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.home)
            return f"<SCKG_HOME>/{relative.as_posix()}"
        except ValueError:
            return "<outside-sckg-home>"

    def _validate_approval(
        self, plan: ModelPackInstallPlan, approval: ModelPackApproval
    ) -> None:
        now = datetime.now(timezone.utc)
        reasons = []
        if approval.plan_id != plan.plan_id:
            reasons.append("model_pack_approval_plan_mismatch")
        if approval.manifest_digest != self.manifest.manifest_digest:
            reasons.append("model_pack_approval_manifest_mismatch")
        if approval.pack_id != self.manifest.pack_id:
            reasons.append("model_pack_approval_pack_mismatch")
        if approval.expires_at <= now:
            reasons.append("model_pack_approval_expired")
        if approval.revoked_at is not None:
            reasons.append("model_pack_approval_revoked")
        if approval.consumed_at is not None:
            reasons.append("model_pack_approval_replayed")
        if reasons:
            raise PermissionError(",".join(reasons))

    def _run(self, argv: list[str], *, offline: bool = False) -> None:
        env = os.environ.copy()
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env["HF_HOME"] = str(self.pack_root / "cache")
        if offline:
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
        completed = self.command_runner(
            argv,
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "")[-1200:]
            raise RuntimeError(f"model pack command failed ({completed.returncode}): {stderr}")

    def _write_record(self, record: ModelPackInstallationRecord) -> None:
        record_root = self.registry_root / "records"
        record_root.mkdir(parents=True, exist_ok=True)
        (record_root / f"{record.record_id}.json").write_text(
            json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()
