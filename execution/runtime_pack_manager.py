from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import shutil
import subprocess
import threading
import time
import uuid
import urllib.request
import fcntl
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core.runtime_pack_models import (
    EnvironmentProvisioningPlan,
    PackInstallationRecord,
    RuntimeCapabilityProbe,
    RuntimePackManifest,
    RuntimePackSource,
    RuntimePackState,
)
from execution.runtime_pack_approval import RuntimePackApprovalService
from execution.runtime_pack_registry import RuntimePackRegistry


DEFAULT_DISK_QUOTA_BYTES = 6 * 1024**3
DISK_SAFETY_MARGIN_BYTES = 6 * 1024**3
_USAGE_WRITE_LOCK = threading.RLock()


class RuntimePackInstallationCancelled(RuntimeError):
    pass


def default_sckg_home() -> Path:
    configured = os.environ.get("SCKG_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".sckg"


class RuntimePackManager:
    """Provision maintainer-authored packs without accepting user commands or paths."""

    def __init__(
        self,
        *,
        registry: RuntimePackRegistry | None = None,
        home: Path | None = None,
        disk_quota_bytes: int = DEFAULT_DISK_QUOTA_BYTES,
        disk_safety_margin_bytes: int = DISK_SAFETY_MARGIN_BYTES,
        approval_service: RuntimePackApprovalService | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        allow_legacy_environments: bool = True,
    ) -> None:
        if disk_safety_margin_bytes < 0:
            raise ValueError("disk safety margin cannot be negative")
        self.registry = registry or RuntimePackRegistry()
        self.home = (home or default_sckg_home()).expanduser().resolve()
        self.pack_root = self.home / "runtime-packs"
        self.cache_root = self.home / "cache"
        self.record_root = self.home / "registry" / "runtime-packs" / "records"
        self.audit_path = self.home / "registry" / "runtime-packs" / "audit.jsonl"
        self.usage_path = self.home / "registry" / "runtime-packs" / "usage.json"
        self.disk_quota_bytes = disk_quota_bytes
        self.disk_safety_margin_bytes = disk_safety_margin_bytes
        self.approvals = approval_service or RuntimePackApprovalService(
            root=self.home / "registry" / "runtime-packs" / "approvals"
        )
        self.command_runner = command_runner
        self.allow_legacy_environments = allow_legacy_environments
        for path in (self.pack_root, self.cache_root, self.record_root):
            path.mkdir(parents=True, exist_ok=True)

    def probe(self, pack_id: str) -> RuntimeCapabilityProbe:
        manifest = self.registry.get(pack_id)
        platform_supported = (
            manifest.platform == self.registry.current_platform_tag()
        )
        disk_free = shutil.disk_usage(self.home).free
        warnings = self.registry.validate_assets(manifest)
        if not platform_supported:
            return RuntimeCapabilityProbe(
                pack_id=pack_id,
                manifest_digest=manifest.manifest_digest,
                state=RuntimePackState.UNSUPPORTED,
                platform_supported=False,
                install_prefix_redacted=self.redact_path(self._managed_prefix(manifest)),
                environment_id=manifest.environment_id,
                disk_free_bytes=disk_free,
                logical_size_bytes=0,
                physical_size_bytes=0,
                last_used_at=self._last_used_at(pack_id),
                warnings=[
                    *warnings,
                    f"unsupported_platform:{self.registry.current_platform_tag()}",
                ],
            )

        managed = self._managed_prefix(manifest)
        managed_entrypoints = self._entrypoints(manifest, managed)
        record = self._latest_record(pack_id)
        if (
            record is not None
            and record.state == RuntimePackState.READY
            and record.manifest_digest == manifest.manifest_digest
            and all(path.is_file() for path in managed_entrypoints.values())
        ):
            return self._ready_probe(
                manifest,
                RuntimePackSource.MANAGED,
                managed,
                managed_entrypoints,
                disk_free,
                warnings,
            )

        legacy = self._legacy_prefix(manifest) if self.allow_legacy_environments else None
        if legacy is not None:
            legacy_entrypoints = self._entrypoints(manifest, legacy)
            if legacy_entrypoints and all(path.is_file() for path in legacy_entrypoints.values()):
                return self._ready_probe(
                    manifest,
                    RuntimePackSource.LEGACY_CONDA,
                    legacy,
                    legacy_entrypoints,
                    disk_free,
                    [*warnings, "legacy_environment_compatibility_mode"],
                )

        state = (
            RuntimePackState.FAILED
            if record is not None and record.state == RuntimePackState.FAILED
            else RuntimePackState.MISSING
        )
        if record and record.error_code:
            warnings.append(f"last_install_failed:{record.error_code}")
        logical_size, physical_size = _directory_sizes(managed)
        return RuntimeCapabilityProbe(
            pack_id=pack_id,
            manifest_digest=manifest.manifest_digest,
            state=state,
            platform_supported=True,
            install_prefix_redacted=self.redact_path(managed),
            environment_id=manifest.environment_id,
            disk_free_bytes=disk_free,
            logical_size_bytes=logical_size,
            physical_size_bytes=physical_size,
            last_used_at=self._last_used_at(pack_id),
            warnings=sorted(set(warnings)),
        )

    def inventory(self) -> list[RuntimeCapabilityProbe]:
        return [self.probe(item.pack_id) for item in self.registry.load_all()]

    def create_plan(self, *, pack_id: str, user_id: str) -> EnvironmentProvisioningPlan:
        manifest = self.registry.get(pack_id)
        probe = self.probe(pack_id)
        blockers = list(self.registry.validate_assets(manifest))
        if not probe.platform_supported:
            blockers.append("runtime_pack_platform_unsupported")
        if probe.ready:
            blockers.append("runtime_pack_already_ready")
        total_installed = sum(
            item.logical_size_bytes
            for item in self.inventory()
            if item.source == RuntimePackSource.MANAGED
        )
        if (
            total_installed + manifest.estimated_installed_size_bytes
            > self.disk_quota_bytes
        ):
            blockers.append("runtime_pack_disk_quota_exceeded")
        if (
            probe.disk_free_bytes
            < manifest.estimated_installed_size_bytes
            + self.disk_safety_margin_bytes
        ):
            blockers.append("runtime_pack_insufficient_disk")
        manager = self._manager_executable()
        if manager is None:
            blockers.append("conda_or_micromamba_unavailable")
            command_preview: list[list[str]] = []
        else:
            command_preview = [
                [_redact_home(value) for value in command]
                for command in self._install_commands(manifest, manager)
            ]
        plan = EnvironmentProvisioningPlan(
            plan_id=f"env-plan-{uuid.uuid4().hex}",
            user_id=user_id,
            pack_id=manifest.pack_id,
            pack_version=manifest.version,
            manifest_digest=manifest.manifest_digest,
            platform=manifest.platform,
            state=RuntimePackState.WAITING_APPROVAL,
            install_path_redacted=self.redact_path(self._managed_prefix(manifest)),
            estimated_download_size_bytes=manifest.estimated_download_size_bytes,
            estimated_installed_size_bytes=manifest.estimated_installed_size_bytes,
            disk_free_bytes=probe.disk_free_bytes,
            disk_quota_bytes=self.disk_quota_bytes,
            allowed_install_hosts=manifest.allowed_install_hosts,
            runtime_network_policy=manifest.runtime_network_policy,
            command_preview=command_preview,
            blockers=sorted(set(blockers)),
            created_at=datetime.now(timezone.utc),
        )
        self.approvals.save_plan(plan)
        return plan

    def provision(
        self,
        *,
        plan_id: str,
        approval_id: str,
        timeout_seconds: int = 7200,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> PackInstallationRecord:
        plan = self.approvals.get_plan(plan_id)
        manifest = self.registry.get(plan.pack_id)
        if manifest.manifest_digest != plan.manifest_digest:
            raise PermissionError("runtime manifest changed after plan")
        if plan.blockers:
            raise PermissionError("blocked environment plan cannot install")
        self.approvals.consume(approval_id=approval_id, plan=plan)
        manager = self._manager_executable()
        if manager is None:
            raise RuntimeError("conda or micromamba is unavailable")
        prefix = self._managed_prefix(manifest)
        if prefix.exists():
            raise FileExistsError("managed runtime prefix already exists")
        started = datetime.now(timezone.utc)
        started_clock = time.perf_counter()
        cache_size_before = _directory_size(self.cache_root)
        record = PackInstallationRecord(
            record_id=f"pack-install-{uuid.uuid4().hex}",
            pack_id=manifest.pack_id,
            pack_version=manifest.version,
            manifest_digest=manifest.manifest_digest,
            state=RuntimePackState.INSTALLING,
            source=RuntimePackSource.MANAGED,
            install_prefix=str(prefix),
            started_at=started,
            command_argv_redacted=[
                [_redact_home(value) for value in command]
                for command in self._install_commands(manifest, manager)
            ],
        )
        self._write_record(record)
        self._audit("runtime_pack_install_started", record)
        stdout_path = self.record_root / f"{record.record_id}.stdout.log"
        stderr_path = self.record_root / f"{record.record_id}.stderr.log"
        exit_code: int | None = None
        try:
            if cancellation_check and cancellation_check():
                raise RuntimePackInstallationCancelled("runtime pack installation cancelled")
            reasons = self.registry.validate_assets(manifest)
            if reasons:
                raise RuntimeError(";".join(reasons))
            env = self._installer_environment()
            self._prepare_r_sources(manifest)
            with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr:
                for command in self._install_commands(manifest, manager):
                    completed = self._run_install_command(
                        command=command,
                        stdout=stdout,
                        stderr=stderr,
                        timeout_seconds=timeout_seconds,
                        env=env,
                        cancellation_check=cancellation_check,
                    )
                    exit_code = int(completed.returncode)
                    if exit_code != 0:
                        raise RuntimeError(f"runtime installer exited with {exit_code}")
            verifying_record = record.model_copy(
                update={
                    "state": RuntimePackState.VERIFYING,
                    "lock_hashes_verified": True,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "exit_code": exit_code,
                }
            )
            self._write_record(verifying_record)
            self._audit("runtime_pack_verification_started", verifying_record)
            self._run_smoke(manifest, prefix, timeout_seconds=min(300, timeout_seconds))
            completed_record = verifying_record.model_copy(
                update={
                    "state": RuntimePackState.READY,
                    "completed_at": datetime.now(timezone.utc),
                    "lock_hashes_verified": True,
                    "smoke_passed": True,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "exit_code": exit_code,
                    "installed_size_bytes": _directory_sizes(prefix)[0],
                    "installed_physical_size_bytes": _directory_sizes(prefix)[1],
                    "cache_size_before_bytes": cache_size_before,
                    "cache_size_after_bytes": _directory_size(self.cache_root),
                    "elapsed_ms": (time.perf_counter() - started_clock) * 1000.0,
                }
            )
        except Exception as exc:
            completed_record = record.model_copy(
                update={
                    "state": RuntimePackState.FAILED,
                    "completed_at": datetime.now(timezone.utc),
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "exit_code": exit_code,
                    "installed_size_bytes": _directory_sizes(prefix)[0],
                    "installed_physical_size_bytes": _directory_sizes(prefix)[1],
                    "cache_size_before_bytes": cache_size_before,
                    "cache_size_after_bytes": _directory_size(self.cache_root),
                    "elapsed_ms": (time.perf_counter() - started_clock) * 1000.0,
                    "error_code": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
        self._write_record(completed_record)
        self._audit("runtime_pack_install_finished", completed_record)
        return completed_record

    def _run_install_command(
        self,
        *,
        command: list[str],
        stdout,
        stderr,
        timeout_seconds: int,
        env: dict[str, str],
        cancellation_check: Callable[[], bool] | None,
    ) -> subprocess.CompletedProcess[str]:
        if cancellation_check is None or self.command_runner is not subprocess.run:
            if cancellation_check and cancellation_check():
                raise RuntimePackInstallationCancelled(
                    "runtime pack installation cancelled"
                )
            return self.command_runner(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                text=True,
                check=False,
                timeout=timeout_seconds,
                env=env,
            )

        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            text=True,
            env=env,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if cancellation_check():
                _terminate_process_group(process)
                raise RuntimePackInstallationCancelled(
                    "runtime pack installation cancelled"
                )
            if time.monotonic() >= deadline:
                _terminate_process_group(process)
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            time.sleep(0.1)
        return subprocess.CompletedProcess(command, int(process.returncode))

    def remove(self, *, pack_id: str, confirmation_text: str) -> bool:
        manifest = self.registry.get(pack_id)
        if not manifest.removable:
            raise PermissionError("runtime pack is not removable")
        if confirmation_text.strip() != f"REMOVE {pack_id}":
            raise PermissionError("runtime pack removal confirmation mismatch")
        prefix = self._managed_prefix(manifest)
        _require_within(prefix, self.pack_root)
        if not prefix.exists():
            return False
        shutil.rmtree(prefix)
        self._audit(
            "runtime_pack_removed",
            PackInstallationRecord(
                record_id=f"pack-remove-{uuid.uuid4().hex}",
                pack_id=manifest.pack_id,
                pack_version=manifest.version,
                manifest_digest=manifest.manifest_digest,
                state=RuntimePackState.MISSING,
                source=RuntimePackSource.MANAGED,
                install_prefix=str(prefix),
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            ),
        )
        return True

    def resolve_entrypoint(self, pack_id: str, kind: str) -> Path:
        manifest = self.registry.get(pack_id)
        probe = self.probe(pack_id)
        if not probe.ready:
            raise FileNotFoundError(f"runtime pack is not ready: {pack_id}")
        path_text = probe.executable_paths.get(kind)
        if not path_text:
            raise FileNotFoundError(f"runtime pack has no {kind} entrypoint: {pack_id}")
        path = Path(path_text).resolve(strict=True)
        self.mark_used(pack_id)
        return path

    def mark_used(self, pack_id: str, *, now: datetime | None = None) -> None:
        self.registry.get(pack_id)
        with _USAGE_WRITE_LOCK:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.usage_path.with_name(".usage.lock")
            with lock_path.open("a+", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    usage = self._load_usage()
                    usage[pack_id] = (now or datetime.now(timezone.utc)).isoformat()
                    temporary = self.usage_path.with_name(
                        f".{self.usage_path.name}.{uuid.uuid4().hex}.tmp"
                    )
                    temporary.write_text(
                        json.dumps(usage, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    temporary.replace(self.usage_path)
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def redact_path(self, path: Path) -> str:
        path = path.expanduser().resolve()
        try:
            return str(Path("~/.sckg") / path.relative_to(self.home))
        except ValueError:
            return f".../{path.name}"

    def _ready_probe(
        self,
        manifest: RuntimePackManifest,
        source: RuntimePackSource,
        prefix: Path,
        entrypoints: dict[str, Path],
        disk_free: int,
        warnings: list[str],
    ) -> RuntimeCapabilityProbe:
        logical_size, physical_size = _directory_sizes(prefix)
        return RuntimeCapabilityProbe(
            pack_id=manifest.pack_id,
            manifest_digest=manifest.manifest_digest,
            state=RuntimePackState.READY,
            source=source,
            platform_supported=True,
            install_prefix_redacted=self.redact_path(prefix),
            environment_id=manifest.environment_id,
            executable_paths={key: str(value) for key, value in entrypoints.items()},
            disk_free_bytes=disk_free,
            logical_size_bytes=logical_size,
            physical_size_bytes=physical_size,
            last_used_at=self._last_used_at(manifest.pack_id),
            warnings=sorted(set(warnings)),
        )

    def _managed_prefix(self, manifest: RuntimePackManifest) -> Path:
        prefix = (self.pack_root / manifest.pack_id / manifest.version).resolve()
        _require_within(prefix, self.pack_root)
        return prefix

    @staticmethod
    def _entrypoints(manifest: RuntimePackManifest, prefix: Path) -> dict[str, Path]:
        values: dict[str, Path] = {}
        if manifest.python_entrypoint:
            values["python"] = (prefix / manifest.python_entrypoint).resolve()
        if manifest.rscript_entrypoint:
            values["rscript"] = (prefix / manifest.rscript_entrypoint).resolve()
        return values

    @staticmethod
    def _legacy_prefix(manifest: RuntimePackManifest) -> Path | None:
        if not manifest.legacy_environment_name:
            return None
        conda_exe = os.environ.get("CONDA_EXE") or shutil.which("conda")
        if not conda_exe:
            return None
        return Path(conda_exe).resolve().parent.parent / "envs" / manifest.legacy_environment_name

    def _manager_executable(self) -> Path | None:
        candidates = [
            os.environ.get("SCKG_MICROMAMBA_EXE"),
            shutil.which("micromamba"),
            os.environ.get("CONDA_EXE"),
            shutil.which("conda"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).expanduser().is_file():
                return Path(candidate).expanduser().resolve()
        return None

    def _install_commands(
        self, manifest: RuntimePackManifest, manager: Path
    ) -> list[list[str]]:
        prefix = self._managed_prefix(manifest)
        commands: list[list[str]] = []
        conda_lock = next(
            (item for item in manifest.lock_files if item.kind == "conda_explicit"),
            None,
        )
        if conda_lock is None:
            raise ValueError("runtime pack requires a conda explicit lock")
        commands.append(
            [
                str(manager),
                "create",
                "--yes",
                "--prefix",
                str(prefix),
                "--file",
                str(self.registry.lock_path(conda_lock)),
            ]
        )
        pip_lock = next(
            (item for item in manifest.lock_files if item.kind == "pip_requirements"),
            None,
        )
        if pip_lock is not None:
            if not manifest.python_entrypoint:
                raise ValueError("pip lock requires a Python entrypoint")
            commands.append(
                [
                    str(prefix / manifest.python_entrypoint),
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--requirement",
                    str(self.registry.lock_path(pip_lock)),
                ]
            )
        r_source_lock = next(
            (
                item
                for item in manifest.lock_files
                if item.kind == "r_source_requirements"
            ),
            None,
        )
        if r_source_lock is not None:
            if not manifest.rscript_entrypoint:
                raise ValueError("R source lock requires an R entrypoint")
            payload = json.loads(
                self.registry.lock_path(r_source_lock).read_text(encoding="utf-8")
            )
            for package in payload.get("packages") or []:
                digest = str(package["sha256"])
                commands.append(
                    [
                        str(prefix / "bin" / "R"),
                        "CMD",
                        "INSTALL",
                        str(self.cache_root / "r-sources" / f"{digest}.tar.gz"),
                    ]
                )
        return commands

    def _prepare_r_sources(self, manifest: RuntimePackManifest) -> None:
        lock = next(
            (
                item
                for item in manifest.lock_files
                if item.kind == "r_source_requirements"
            ),
            None,
        )
        if lock is None:
            return
        payload = json.loads(
            self.registry.lock_path(lock).read_text(encoding="utf-8")
        )
        source_root = self.cache_root / "r-sources"
        source_root.mkdir(parents=True, exist_ok=True)
        for package in payload.get("packages") or []:
            url = str(package["url"])
            digest = str(package["sha256"])
            host = urlparse(url).hostname
            if not host or host.casefold() not in manifest.allowed_install_hosts:
                raise PermissionError("R source host is not allowlisted")
            destination = source_root / f"{digest}.tar.gz"
            if destination.is_file() and _sha256(destination) == digest:
                continue
            temporary = destination.with_suffix(".tmp")
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "scKG-RuntimePack/1.0"},
            )
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open(
                "wb"
            ) as handle:
                shutil.copyfileobj(response, handle)
            if _sha256(temporary) != digest:
                temporary.unlink(missing_ok=True)
                raise ValueError("R source digest mismatch")
            temporary.replace(destination)

    def _run_smoke(
        self, manifest: RuntimePackManifest, prefix: Path, *, timeout_seconds: int
    ) -> None:
        env = self._installer_environment()
        if manifest.import_smoke_modules:
            modules = ",".join(manifest.import_smoke_modules)
            code = "import importlib;[importlib.import_module(x) for x in " + repr(modules.split(",")) + "]"
            command = [str(prefix / str(manifest.python_entrypoint)), "-c", code]
            completed = self.command_runner(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                text=True,
                check=False,
                timeout=timeout_seconds,
                env=env,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "Python runtime pack smoke failed: "
                    + _diagnostic_tail(completed.stderr)
                )
        if manifest.r_smoke_packages:
            packages = ",".join(manifest.r_smoke_packages)
            code = ";".join(f"library({name})" for name in packages.split(","))
            completed = self.command_runner(
                [str(prefix / str(manifest.rscript_entrypoint)), "-e", code],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                text=True,
                check=False,
                timeout=timeout_seconds,
                env=env,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "R runtime pack smoke failed: "
                    + _diagnostic_tail(completed.stderr)
                )

    def _installer_environment(self) -> dict[str, str]:
        return {
            "HOME": str(self.home),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "CONDA_PKGS_DIRS": str(self.cache_root / "conda-pkgs"),
            "PIP_CACHE_DIR": str(self.cache_root / "pip"),
            "MAMBA_ROOT_PREFIX": str(self.home / "micromamba"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
            "PYTHONNOUSERSITE": "1",
        }

    def _latest_record(self, pack_id: str) -> PackInstallationRecord | None:
        records = [
            PackInstallationRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.record_root.glob(f"{pack_id}-*.json")
        ]
        if not records:
            return None
        return max(records, key=lambda item: item.started_at)

    def _load_usage(self) -> dict[str, str]:
        if not self.usage_path.is_file():
            return {}
        try:
            value = json.loads(self.usage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return value if isinstance(value, dict) else {}

    def _last_used_at(self, pack_id: str) -> datetime | None:
        value = self._load_usage().get(pack_id)
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _write_record(self, record: PackInstallationRecord) -> None:
        path = self.record_root / f"{record.pack_id}-{record.record_id}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _audit(self, event: str, record: PackInstallationRecord) -> None:
        payload = {
            "event": event,
            "record_id": record.record_id,
            "pack_id": record.pack_id,
            "manifest_digest": record.manifest_digest,
            "state": record.state,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _directory_size(path: Path) -> int:
    return _directory_sizes(path)[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _directory_sizes(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    logical = 0
    physical = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                stat = item.stat()
                logical += stat.st_size
                physical += getattr(stat, "st_blocks", 0) * 512
        except OSError:
            continue
    return logical, physical


def _require_within(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("runtime pack path escapes managed root") from exc


def _redact_home(value: str) -> str:
    home = str(Path.home())
    return value.replace(home, "~")


def _diagnostic_tail(value: str | None, *, limit: int = 500) -> str:
    text = (value or "no stderr").replace(str(Path.home()), "~")
    return text[-limit:]


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=2.0)
