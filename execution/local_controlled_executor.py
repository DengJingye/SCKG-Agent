from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psutil

from core.deterministic_router import RouterDecision
from core.execution_models import (
    ExecutionRequest,
    ExecutionRun,
    ProcessCleanup,
    QualificationArtifact,
    ToolContract,
)
from core.settings import PROJECT_ROOT
from core.tool_contract_registry import ToolContractRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.wrapper_registry import WrapperRegistry
from execution.approval_service import ApprovalScope, parameter_hash
from execution.execution_policy import ExecutionPolicy


DEFAULT_RUN_ROOT = PROJECT_ROOT / ".sckg_exec" / "runs"


class LocalControlledExecutor:
    """Application-level process controls for qualification wrappers.

    This is deliberately not a sandbox. It enforces the Phase 3A allowlist,
    fixed paths, structured requests, runtime observation, and process cleanup.
    """

    def __init__(
        self,
        *,
        run_root: Path = DEFAULT_RUN_ROOT,
        approved_input_root: Path,
        wrapper_registry: WrapperRegistry | None = None,
        contract_registry: ToolContractRegistry | None = None,
        environment_registry: EnvironmentRegistry | None = None,
        execution_policy: ExecutionPolicy | None = None,
    ) -> None:
        self.run_root = Path(run_root).resolve()
        self.approved_input_root = Path(approved_input_root).resolve()
        self.wrapper_registry = wrapper_registry or WrapperRegistry()
        self.environment_registry = environment_registry or EnvironmentRegistry()
        self.contract_registry = contract_registry or ToolContractRegistry(
            environment_registry=self.environment_registry
        )
        self.execution_policy = execution_policy or ExecutionPolicy()

    def execute(
        self,
        *,
        request: ExecutionRequest,
        artifact: QualificationArtifact,
        contract: ToolContract,
        router_decision: RouterDecision,
        cancellation_checker: Callable[[], str | None] | None = None,
    ) -> ExecutionRun:
        started = datetime.now(timezone.utc)
        preflight_error = self._preflight(
            request=request,
            artifact=artifact,
            contract=contract,
            router_decision=router_decision,
        )
        if preflight_error is not None:
            return self._blocked(request, artifact, contract, started, *preflight_error)

        wrapper = self.wrapper_registry.get(request.wrapper_id)
        parameters = self.contract_registry.validate_parameters(contract, request.parameters)
        input_path = Path(artifact.path).resolve(strict=True)
        run_dir = self.run_root / request.run_id
        try:
            _require_within(run_dir.resolve(), self.run_root, "run directory")
            if run_dir.exists():
                return self._blocked(
                    request,
                    artifact,
                    contract,
                    started,
                    "run_directory_exists",
                    f"run directory already exists: {run_dir}",
                )
            run_dir.mkdir(parents=True)
            artifacts_dir = run_dir / "artifacts"
            artifacts_dir.mkdir()
        except (OSError, ValueError) as exc:
            return self._blocked(
                request, artifact, contract, started, "run_directory_invalid", str(exc)
            )

        request_path = run_dir / "request.json"
        worker_request_path = run_dir / "worker_request.json"
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        request_path.write_text(
            request.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        worker_request = {
            "accession": artifact.accession,
            "expected_cells": artifact.expected_cells,
            "expected_input_hash": artifact.sha256,
            "fixture_id": artifact.fixture_id,
            "input_path": str(input_path),
            "execution_seed": request.execution_seed,
            "parameters": parameters,
            "public_dataset": artifact.public_dataset,
            "purpose": request.qualification.purpose,
        }
        worker_request_path.write_text(
            json.dumps(worker_request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        try:
            argv = wrapper.command(worker_request_path.name)
            wrapper_environment = wrapper.worker_environment()
        except (FileNotFoundError, KeyError, RuntimeError) as exc:
            return self._blocked(
                request,
                artifact,
                contract,
                started,
                "runtime_pack_not_ready",
                str(exc),
            )
        cleanup = ProcessCleanup()
        peak_memory_mb = 0.0
        process: subprocess.Popen[str] | None = None
        exit_code: int | None = None
        error_type: str | None = None
        error_message: str | None = None
        status = "failed"
        monotonic_start = time.monotonic()
        env = self._worker_environment(run_dir, wrapper_environment)
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_handle:
                process = subprocess.Popen(
                    argv,
                    cwd=run_dir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    shell=False,
                    start_new_session=True,
                    text=True,
                )
                while process.poll() is None:
                    peak_memory_mb = max(peak_memory_mb, _process_tree_rss_mb(process.pid))
                    cancellation_reason = (
                        cancellation_checker() if cancellation_checker is not None else None
                    )
                    if cancellation_reason:
                        cleanup = _terminate_process_tree(
                            process,
                            cancellation_triggered=True,
                            cancellation_reason=cancellation_reason,
                        )
                        status = "cancelled"
                        error_type = "cancelled"
                        error_message = cancellation_reason
                        break
                    if time.monotonic() - monotonic_start > request.timeout_seconds:
                        cleanup = _terminate_process_tree(process, timeout_triggered=True)
                        status = "timeout"
                        error_type = "timeout"
                        error_message = f"wrapper exceeded {request.timeout_seconds}s timeout"
                        break
                    time.sleep(0.05)
                exit_code = process.poll()
                peak_memory_mb = max(peak_memory_mb, _process_tree_rss_mb(process.pid))
                if status not in {"timeout", "cancelled"}:
                    status = "succeeded" if exit_code == 0 else "failed"
                    if exit_code != 0:
                        error_type = "wrapper_exit_nonzero"
                        error_message = f"wrapper exited with code {exit_code}"
        except Exception as exc:  # executor failures must be preserved as run records
            if process is not None and process.poll() is None:
                cleanup = _terminate_process_tree(process)
                exit_code = process.poll()
            error_type = type(exc).__name__
            error_message = str(exc)
            status = "failed"

        artifact_paths: dict[str, str] = {}
        artifact_hashes: dict[str, str] = {}
        try:
            artifact_paths, artifact_hashes = _collect_artifacts(artifacts_dir, run_dir)
        except ValueError as exc:
            status = "failed"
            error_type = "output_path_escape"
            error_message = str(exc)

        ended = datetime.now(timezone.utc)
        run = ExecutionRun(
            request_id=request.request_id,
            run_id=request.run_id,
            trace_id=request.trace_id,
            plan_id=request.plan_id,
            step_id=request.step_id,
            wrapper_id=request.wrapper_id,
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            environment_id=request.environment_id,
            command_argv_redacted=[Path(argv[0]).name, "-m", wrapper.module, "--request-json", worker_request_path.name],
            parameters=parameters,
            execution_seed=request.execution_seed,
            parameter_provenance=request.parameter_provenance,
            input_hash=artifact.sha256,
            start_time=started,
            end_time=ended,
            runtime_seconds=max(0.0, time.monotonic() - monotonic_start),
            peak_memory_mb=round(peak_memory_mb, 3),
            exit_code=exit_code,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            artifact_paths=artifact_paths,
            artifact_hashes=artifact_hashes,
            status=status,
            error_type=error_type,
            error_message=error_message,
            process_cleanup=cleanup,
            qualification_mode=request.qualification.mode,
            fixture_id=artifact.fixture_id,
            synthetic_fixture=artifact.synthetic,
            public_dataset=artifact.public_dataset,
            user_data_used=artifact.user_data,
            execution_purpose=request.qualification.purpose,
            owner_user_id=(
                request.user_execution.user_id if request.user_execution else None
            ),
            approval_id=(
                request.user_execution.approval_id if request.user_execution else None
            ),
        )
        (run_dir / "execution_run.json").write_text(
            run.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return run

    def _preflight(
        self,
        *,
        request: ExecutionRequest,
        artifact: QualificationArtifact,
        contract: ToolContract,
        router_decision: RouterDecision,
    ) -> tuple[str, str] | None:
        if request.execution_mode == "restricted_local_user":
            return self._preflight_restricted_user(
                request=request,
                artifact=artifact,
                contract=contract,
                router_decision=router_decision,
            )
        if not (
            router_decision.execution_allowed
            and router_decision.qualification_only
            and router_decision.route == "QUALIFICATION_EXECUTION"
        ):
            return "qualification_route_blocked", "; ".join(router_decision.reasons)
        if request.actor.role != "maintainer" or not request.qualification.authorized:
            return "unauthorized_execution", "maintainer qualification authorization required"
        if not request.qualification.mode:
            return "qualification_mode_required", "qualification.mode must be true"
        if not (request.qualification.fixture_allowlisted and artifact.allowlisted):
            return "fixture_not_allowlisted", "fixture must be allowlisted"
        if artifact.user_data:
            return "user_data_forbidden", "user data is forbidden in qualification execution"
        if request.qualification.purpose == "synthetic_qualification":
            if not artifact.synthetic:
                return "synthetic_fixture_required", "synthetic qualification requires synthetic data"
        elif request.qualification.purpose == "scientific_pilot":
            if artifact.synthetic or not artifact.public_dataset:
                return "public_scientific_dataset_required", "scientific pilot requires public real data"
            if artifact.accession not in {"GSE108313", "scIB-pancreas", "Zheng68K"}:
                return "scientific_dataset_not_allowlisted", str(artifact.accession)
        elif request.qualification.purpose == "representative_preview":
            return (
                "representative_preview_requires_restricted_user_route",
                "representative Preview execution cannot use qualification authorization",
            )
        if artifact.fixture_id != request.qualification.fixture_id:
            return "fixture_id_mismatch", "request and artifact fixture ids differ"
        if request.wrapper_id != contract.wrapper_id:
            return "wrapper_contract_mismatch", "request wrapper differs from contract"
        if not self.wrapper_registry.contains(request.wrapper_id):
            return "unknown_wrapper", f"wrapper is not allowlisted: {request.wrapper_id}"
        wrapper = self.wrapper_registry.get(request.wrapper_id)
        if not wrapper.is_runtime_ready():
            return "runtime_pack_not_ready", "required runtime pack is missing or unverified"
        if wrapper.environment_id != request.environment_id:
            return "wrapper_environment_mismatch", "wrapper and request environments differ"
        if not self.environment_registry.contains(request.environment_id):
            return "unknown_environment", request.environment_id
        environment = self.environment_registry.get(request.environment_id)
        if request.environment_id != contract.environment_id:
            return "environment_contract_mismatch", "environment differs from contract"
        runtime_key = contract.tool_name.casefold()
        if environment.package_versions.get(runtime_key) != contract.tool_version:
            return (
                "runtime_version_mismatch",
                f"registered {contract.tool_name} version differs from contract",
            )
        max_timeout = int(contract.resource_requirements.get("qualification_timeout_seconds", 0))
        if request.timeout_seconds > max_timeout:
            return "qualification_budget_exceeded", "timeout exceeds contract qualification budget"
        try:
            self.contract_registry.validate_parameters(contract, request.parameters)
        except ValueError as exc:
            return "invalid_parameter", str(exc)
        try:
            path = Path(artifact.path)
            if path.is_symlink():
                return "symlink_input_forbidden", "qualification input cannot be a symlink"
            resolved = path.resolve(strict=True)
            _require_within(resolved, self.approved_input_root, "input artifact")
            if not resolved.is_file():
                return "input_not_file", str(resolved)
            if _sha256(resolved) != artifact.sha256:
                return "input_hash_mismatch", "qualification input hash differs from artifact"
        except (OSError, ValueError) as exc:
            return "input_path_invalid", str(exc)
        return None

    def _preflight_restricted_user(
        self,
        *,
        request: ExecutionRequest,
        artifact: QualificationArtifact,
        contract: ToolContract,
        router_decision: RouterDecision,
    ) -> tuple[str, str] | None:
        context = request.user_execution
        if not (
            router_decision.execution_allowed
            and router_decision.route == "RESTRICTED_USER_EXECUTION"
            and not router_decision.qualification_only
        ):
            return "restricted_user_route_blocked", "; ".join(router_decision.reasons)
        if request.actor.role != "user" or context is None:
            return "unauthorized_execution", "restricted local user context required"
        if not context.approval_consumed:
            return "approval_not_consumed", "approval must be consumed before execution"
        if context.user_id != request.actor.actor_id:
            return "user_context_mismatch", "actor and approval user differ"
        if context.artifact_id != request.input_artifact_id:
            return "artifact_scope_mismatch", "approval artifact differs from request"
        if context.tool_name != contract.tool_name or context.tool_version != contract.tool_version:
            return "tool_scope_mismatch", "approval tool differs from contract"
        if context.contract_version != contract.contract_version:
            return "contract_scope_mismatch", "approval contract version changed"
        if context.environment_id != request.environment_id:
            return "environment_scope_mismatch", "approval environment changed"
        try:
            parameters = self.contract_registry.validate_parameters(
                contract, request.parameters
            )
        except ValueError as exc:
            return "invalid_parameter", str(exc)
        if context.parameter_hash != parameter_hash(parameters):
            return "parameter_scope_mismatch", "approval parameter hash changed"
        scope = ApprovalScope(
            user_id=context.user_id,
            artifact_id=context.artifact_id,
            plan_id=request.plan_id,
            tool_name=context.tool_name,
            tool_version=context.tool_version,
            contract_version=context.contract_version,
            environment_id=context.environment_id,
            parameter_hash=context.parameter_hash,
        )
        if scope.fingerprint != context.request_fingerprint:
            return "approval_fingerprint_mismatch", "approval fingerprint changed"
        if request.wrapper_id != contract.wrapper_id:
            return "wrapper_contract_mismatch", "request wrapper differs from contract"
        if not self.wrapper_registry.contains(request.wrapper_id):
            return "unknown_wrapper", f"wrapper is not allowlisted: {request.wrapper_id}"
        wrapper = self.wrapper_registry.get(request.wrapper_id)
        if wrapper.environment_id != request.environment_id:
            return "wrapper_environment_mismatch", "wrapper and request environments differ"
        if not self.environment_registry.contains(request.environment_id):
            return "unknown_environment", request.environment_id
        environment = self.environment_registry.get(request.environment_id)
        policy = self.execution_policy.authorize(
            actor_role=request.actor.role,
            access_origin=context.access_origin,
            user_allowlisted=True,
            contract=contract,
            environment=environment,
        )
        if not policy.allowed:
            return "execution_policy_blocked", ";".join(policy.reasons)
        runtime_key = contract.tool_name.casefold()
        if environment.package_versions.get(runtime_key) != contract.tool_version:
            return "runtime_version_mismatch", "runtime and contract versions differ"
        max_timeout = int(contract.resource_requirements.get("qualification_timeout_seconds", 0))
        if request.timeout_seconds > max_timeout:
            return "user_execution_budget_exceeded", "timeout exceeds contract boundary"
        if not artifact.allowlisted:
            return "artifact_not_allowlisted", "registered artifact is not approved"
        try:
            path = Path(artifact.path)
            if path.is_symlink():
                return "symlink_input_forbidden", "user input cannot be a symlink"
            resolved = path.resolve(strict=True)
            _require_within(resolved, self.approved_input_root, "input artifact")
            if not resolved.is_file() or _sha256(resolved) != artifact.sha256:
                return "input_hash_mismatch", "registered user artifact changed"
        except (OSError, ValueError) as exc:
            return "input_path_invalid", str(exc)
        return None

    def _worker_environment(
        self, run_dir: Path, runtime_environment: dict[str, str] | None = None
    ) -> dict[str, str]:
        env = {
            "HOME": str(run_dir),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(PROJECT_ROOT),
        }
        for name in ("MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME"):
            cache_dir = self.run_root.parent / ".qualification_cache" / name.casefold()
            cache_dir.mkdir(parents=True, exist_ok=True)
            env[name] = str(cache_dir)
        env.update(runtime_environment or {})
        return env

    def _blocked(
        self,
        request: ExecutionRequest,
        artifact: QualificationArtifact,
        contract: ToolContract,
        started: datetime,
        error_type: str,
        error_message: str,
    ) -> ExecutionRun:
        ended = datetime.now(timezone.utc)
        nominal = self.run_root / request.run_id
        return ExecutionRun(
            request_id=request.request_id,
            run_id=request.run_id,
            trace_id=request.trace_id,
            plan_id=request.plan_id,
            step_id=request.step_id,
            wrapper_id=request.wrapper_id,
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            environment_id=request.environment_id,
            command_argv_redacted=[],
            parameters=request.parameters,
            execution_seed=request.execution_seed,
            parameter_provenance=request.parameter_provenance,
            input_hash=artifact.sha256,
            start_time=started,
            end_time=ended,
            runtime_seconds=max(0.0, (ended - started).total_seconds()),
            stdout_path=str(nominal / "stdout.log"),
            stderr_path=str(nominal / "stderr.log"),
            status="blocked",
            error_type=error_type,
            error_message=error_message,
            qualification_mode=request.qualification.mode,
            fixture_id=artifact.fixture_id,
            synthetic_fixture=artifact.synthetic,
            public_dataset=artifact.public_dataset,
            user_data_used=artifact.user_data,
            execution_purpose=request.qualification.purpose,
            owner_user_id=(
                request.user_execution.user_id if request.user_execution else None
            ),
            approval_id=(
                request.user_execution.approval_id if request.user_execution else None
            ),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_within(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes controlled root") from exc


def _process_tree_rss_mb(pid: int) -> float:
    try:
        parent = psutil.Process(pid)
        try:
            processes = [parent, *parent.children(recursive=True)]
        except (psutil.Error, PermissionError):
            processes = [parent]
        return sum(process.memory_info().rss for process in processes if process.is_running()) / 2**20
    except (psutil.Error, ProcessLookupError, PermissionError):
        return 0.0


def _terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    timeout_triggered: bool = False,
    cancellation_triggered: bool = False,
    cancellation_reason: str | None = None,
) -> ProcessCleanup:
    children: list[psutil.Process] = []
    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except (psutil.Error, PermissionError):
        pass
    known_pids = {item.pid for item in children}
    try:
        candidates = psutil.process_iter(["pid"])
        for candidate in candidates:
            if candidate.pid == process.pid:
                continue
            try:
                if os.getpgid(candidate.pid) == process.pid and candidate.pid not in known_pids:
                    children.append(candidate)
                    known_pids.add(candidate.pid)
            except (OSError, psutil.Error, PermissionError):
                continue
    except (psutil.Error, PermissionError):
        pass
    try:
        os.killpg(process.pid, signal.SIGTERM)
        terminate_sent = True
    except (ProcessLookupError, PermissionError):
        terminate_sent = False
    _, alive = psutil.wait_procs(children, timeout=1.0)
    kill_sent = False
    if process.poll() is None or alive:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            kill_sent = True
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass
    residual = []
    for child in children:
        try:
            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                residual.append(child.pid)
        except (psutil.Error, PermissionError):
            continue
    return ProcessCleanup(
        timeout_triggered=timeout_triggered,
        terminate_sent=terminate_sent,
        kill_sent=kill_sent,
        child_processes_seen=len(children),
        residual_processes=residual,
        cancellation_triggered=cancellation_triggered,
        cancellation_reason=cancellation_reason,
    )


def _collect_artifacts(artifacts_dir: Path, run_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    paths: dict[str, str] = {}
    hashes: dict[str, str] = {}
    if not artifacts_dir.exists():
        return paths, hashes
    for path in sorted(artifacts_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"artifact symlink forbidden: {path.name}")
        if not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        _require_within(resolved, run_dir, "output artifact")
        relative = str(resolved.relative_to(artifacts_dir.resolve()))
        paths[relative] = str(resolved)
        hashes[relative] = _sha256(resolved)
    return paths, hashes
