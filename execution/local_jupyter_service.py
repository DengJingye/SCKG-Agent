from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Callable

from core.trace_context import (
    TraceCollector,
    TraceContext,
    TraceCorrelationKind,
    TraceKind,
    TracePrivacyError,
    TraceStage,
    TraceStatus,
    TraceValidationError,
    trace_correlation_id,
)
from execution.local_notebook_launcher import KERNEL_NAME, write_kernel_spec


@dataclass(frozen=True)
class LocalJupyterSession:
    session_id: str
    canonical_trace_id: str
    notebook_name: str
    kernel_name: str
    runtime_pack_id: str
    server_pid: int
    port: int
    launch_url: str
    running: bool


@dataclass
class _ManagedSession:
    public: LocalJupyterSession
    process: object
    owner_user_id: str
    notebook_path: Path


_SESSIONS: dict[str, _ManagedSession] = {}
_SESSION_LOCK = threading.Lock()


class LocalJupyterService:
    """Launch a localhost-only JupyterLab for a trusted workspace notebook.

    This service starts a notebook editor; it never executes a cell and never
    installs a dependency. Scientific code runs only when the user explicitly
    executes a cell in the selected Runtime Pack kernel.
    """

    def __init__(
        self,
        *,
        allowed_workspace_root: Path,
        state_root: Path,
        server_python: Path | None = None,
        process_launcher: Callable[..., object] = subprocess.Popen,
        readiness_probe: Callable[[str], bool] | None = None,
        port_allocator: Callable[[], int] | None = None,
        token_factory: Callable[[], str] | None = None,
        trace_collector: TraceCollector | None = None,
    ) -> None:
        self.allowed_workspace_root = Path(allowed_workspace_root).resolve()
        self.state_root = Path(state_root).expanduser().resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.kernel_data_root = self.state_root / "jupyter-data"
        self.kernel_root = self.kernel_data_root / "kernels"
        self.session_root = self.state_root / "sessions"
        self.session_root.mkdir(parents=True, exist_ok=True)
        self._cleanup_orphaned_sessions()
        discovered = server_python or discover_jupyter_server_python()
        self.server_python = Path(discovered).resolve() if discovered else None
        self.process_launcher = process_launcher
        self.readiness_probe = readiness_probe or _server_ready
        self.port_allocator = port_allocator or _free_local_port
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._trace_collector = trace_collector or TraceCollector()

    @property
    def available(self) -> bool:
        return bool(
            self.server_python
            and self.server_python.is_file()
            and os.access(self.server_python, os.X_OK)
        )

    def start(
        self,
        *,
        owner_user_id: str,
        notebook_path: Path,
        expected_sha256: str,
        runtime_python: Path,
        runtime_pack_id: str,
        timeout_seconds: float = 60.0,
        request_id: str | None = None,
        parent_trace_id: str | None = None,
        handoff_id: str | None = None,
        parent_request_id: str | None = None,
        original_plan_id: str | None = None,
    ) -> LocalJupyterSession:
        trace = _new_jupyter_trace(
            owner_user_id=owner_user_id,
            request_id=request_id or f"jupyter-request:{uuid.uuid4().hex}",
            parent_trace_id=parent_trace_id,
            handoff_id=handoff_id,
            parent_request_id=parent_request_id,
            original_plan_id=original_plan_id,
        )
        with self._trace_collector.request_scope(trace):
            instrumentation = trace.instrumentation()
            with instrumentation.span(
                stage=TraceStage.RUNTIME_BIND,
                component="local_jupyter_service",
                operation="bind_notebook_runtime",
                input_refs=[
                    {
                        "record_type": "notebook_artifact",
                        "record_id": f"notebook:{expected_sha256}",
                        "relation": "binds",
                        "content_hash": expected_sha256,
                    },
                    {
                        "record_type": "runtime_pack",
                        "record_id": runtime_pack_id,
                        "relation": "selects",
                    },
                ],
                exception_error_code="runtime_bind_failed",
            ) as runtime_span:
                session, reused = self._start_session(
                    owner_user_id=owner_user_id,
                    notebook_path=notebook_path,
                    expected_sha256=expected_sha256,
                    runtime_python=runtime_python,
                    runtime_pack_id=runtime_pack_id,
                    timeout_seconds=timeout_seconds,
                    canonical_trace_id=trace.trace_id,
                )
                response = replace(session, canonical_trace_id=trace.trace_id)
                runtime_span.add_output_ref(
                    record_type="jupyter_session",
                    record_id=session.session_id,
                    relation="bound",
                )
                runtime_span.add_decision(
                    decision_type="runtime_binding",
                    outcome="reused" if reused else "started",
                    reason_code=(
                        "existing_session_reused" if reused else "runtime_pack_bound"
                    ),
                    rule_version="local_jupyter_v0",
                )
                runtime_span.succeed()
            instrumentation.set_request_outcome(TraceStatus.SUCCESS)
        return response

    def _start_session(
        self,
        *,
        owner_user_id: str,
        notebook_path: Path,
        expected_sha256: str,
        runtime_python: Path,
        runtime_pack_id: str,
        timeout_seconds: float,
        canonical_trace_id: str,
    ) -> tuple[LocalJupyterSession, bool]:
        if not self.available:
            raise FileNotFoundError(
                "local JupyterLab is unavailable; no dependency was installed"
            )
        notebook = _validate_notebook(
            notebook_path=notebook_path,
            expected_sha256=expected_sha256,
            allowed_workspace_root=self.allowed_workspace_root,
        )
        runtime = Path(runtime_python).resolve(strict=True)
        if not runtime.is_file() or not os.access(runtime, os.X_OK):
            raise FileNotFoundError("Runtime Pack Python is unavailable")
        write_kernel_spec(
            runtime_python=runtime,
            kernel_root=self.kernel_root,
            runtime_pack_id=runtime_pack_id,
        )

        session_key = hashlib.sha256(
            f"{owner_user_id}\0{notebook}\0{expected_sha256}\0{runtime}".encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        with _SESSION_LOCK:
            existing = _SESSIONS.get(session_key)
            if existing and _process_running(existing.process):
                return existing.public, True
            if existing:
                _SESSIONS.pop(session_key, None)

        port = self.port_allocator()
        token = self.token_factory()
        session_dir = self.session_root / session_key
        session_dir.mkdir(parents=True, exist_ok=True)
        log_path = session_dir / "jupyter.log"
        argv = [
            str(self.server_python),
            "-m",
            "jupyterlab",
            "--no-browser",
            "--LabApp.core_mode=True",
            "--LabApp.news_url=",
            "--ServerApp.open_browser=False",
            "--ServerApp.ip=127.0.0.1",
            f"--ServerApp.port={port}",
            "--ServerApp.port_retries=0",
            f"--ServerApp.root_dir={notebook.parent}",
            "--ServerApp.allow_remote_access=False",
            "--FileContentsManager.allow_hidden=True",
            f"--IdentityProvider.token={token}",
        ]
        environment = os.environ.copy()
        # A new server must not restore unrelated tabs/kernels from a previous
        # server's default JupyterLab workspace. Keep the editor workspace local
        # to this exact notebook/runtime binding; do not alter global settings.
        environment["JUPYTERLAB_WORKSPACES_DIR"] = str(session_dir / "lab-workspaces")
        prior_jupyter_path = environment.get("JUPYTER_PATH")
        environment["JUPYTER_PATH"] = (
            f"{self.kernel_data_root}{os.pathsep}{prior_jupyter_path}"
            if prior_jupyter_path
            else str(self.kernel_data_root)
        )
        with log_path.open("ab") as log_handle:
            process = self.process_launcher(
                argv,
                cwd=str(notebook.parent),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                shell=False,
                start_new_session=True,
            )
        pid = int(getattr(process, "pid", 0) or 0)
        if pid <= 0:
            raise RuntimeError("JupyterLab did not return a process id")
        status_url = (
            f"http://127.0.0.1:{port}/api/status?token="
            f"{urllib.parse.quote(token, safe='')}"
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not _process_running(process):
                break
            if self.readiness_probe(status_url):
                break
            time.sleep(0.1)
        else:
            _terminate_process(process)
            raise TimeoutError(
                f"local JupyterLab did not become ready within {timeout_seconds:g}s; "
                f"inspect sessions/{session_key}/jupyter.log (ExecutionPolicy is unrelated)"
            )
        if not _process_running(process) or not self.readiness_probe(status_url):
            _terminate_process(process)
            raise RuntimeError(
                f"local JupyterLab failed to start; inspect {log_path.name}"
            )

        relative_notebook = urllib.parse.quote(notebook.name)
        launch_url = (
            f"http://127.0.0.1:{port}/lab/tree/{relative_notebook}"
            f"?token={urllib.parse.quote(token, safe='')}"
        )
        public = LocalJupyterSession(
            session_id=session_key,
            canonical_trace_id=canonical_trace_id,
            notebook_name=notebook.name,
            kernel_name=KERNEL_NAME,
            runtime_pack_id=runtime_pack_id,
            server_pid=pid,
            port=port,
            launch_url=launch_url,
            running=True,
        )
        with _SESSION_LOCK:
            _SESSIONS[session_key] = _ManagedSession(
                public=public,
                process=process,
                owner_user_id=owner_user_id,
                notebook_path=notebook,
            )
        self._session_manifest_path(session_key).write_text(
            json.dumps(
                {
                    "session_id": session_key,
                    "canonical_trace_id": canonical_trace_id,
                    "owner_user_id": owner_user_id,
                    "notebook_name": notebook.name,
                    "pid": pid,
                    "workspace_root_digest": hashlib.sha256(
                        str(self.allowed_workspace_root).encode("utf-8")
                    ).hexdigest(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return public, False

    def get(
        self, *, session_id: str, owner_user_id: str
    ) -> LocalJupyterSession | None:
        with _SESSION_LOCK:
            managed = _SESSIONS.get(session_id)
        if managed is None:
            return None
        if managed.owner_user_id != owner_user_id:
            raise PermissionError("cross-user Jupyter session access is forbidden")
        if not _process_running(managed.process):
            with _SESSION_LOCK:
                _SESSIONS.pop(session_id, None)
            self._session_manifest_path(session_id).unlink(missing_ok=True)
            return None
        return managed.public

    def stop(self, *, session_id: str, owner_user_id: str) -> bool:
        with _SESSION_LOCK:
            managed = _SESSIONS.get(session_id)
        if managed is None:
            return False
        if managed.owner_user_id != owner_user_id:
            raise PermissionError("cross-user Jupyter session access is forbidden")
        _terminate_process(managed.process)
        with _SESSION_LOCK:
            _SESSIONS.pop(session_id, None)
        self._session_manifest_path(session_id).unlink(missing_ok=True)
        return True

    def _session_manifest_path(self, session_id: str) -> Path:
        return self.session_root / session_id / "session.json"

    def _cleanup_orphaned_sessions(self) -> None:
        for manifest_path in self.session_root.glob("*/session.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                pid = int(payload.get("pid", 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                manifest_path.unlink(missing_ok=True)
                continue
            if pid > 0 and _is_owned_jupyter_process(
                pid=pid, allowed_workspace_root=self.allowed_workspace_root
            ):
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                deadline = time.monotonic() + 3
                while _pid_exists(pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if _pid_exists(pid) and _is_owned_jupyter_process(
                    pid=pid, allowed_workspace_root=self.allowed_workspace_root
                ):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
            manifest_path.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def discover_jupyter_server_python() -> Path | None:
    candidates: list[Path] = []
    explicit = os.getenv("SCKG_JUPYTER_SERVER_PYTHON")
    if explicit:
        candidates.append(Path(explicit).expanduser())
    conda_executable = os.getenv("CONDA_EXE")
    if conda_executable:
        candidates.append(Path(conda_executable).expanduser().parent / "python")
    current = Path(sys.executable)
    candidates.append(current)
    for parent in current.parents:
        if parent.name == "envs":
            candidates.append(parent.parent / "bin" / "python")
            break
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved in seen or not os.access(resolved, os.X_OK):
            continue
        seen.add(resolved)
        check = subprocess.run(
            [str(resolved), "-c", "import jupyterlab"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        if check.returncode == 0:
            return resolved
    return None


def _validate_notebook(
    *, notebook_path: Path, expected_sha256: str, allowed_workspace_root: Path
) -> Path:
    notebook = Path(notebook_path)
    if notebook.is_symlink():
        raise ValueError("notebook path must not be a symlink")
    notebook = notebook.resolve(strict=True)
    _require_within(notebook, allowed_workspace_root)
    if notebook.suffix.casefold() != ".ipynb":
        raise ValueError("only .ipynb notebooks can be opened")
    if _sha256(notebook) != expected_sha256:
        raise ValueError("notebook hash changed")
    payload = json.loads(notebook.read_text(encoding="utf-8"))
    metadata = payload.get("metadata", {}).get("sckg", {})
    if metadata.get("trusted_code_source") != "maintainer_step_template":
        raise ValueError("notebook is not a maintainer-generated scKG notebook")
    return notebook


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _server_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _process_running(process: object) -> bool:
    poll = getattr(process, "poll", None)
    return callable(poll) and poll() is None


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _is_owned_jupyter_process(*, pid: int, allowed_workspace_root: Path) -> bool:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    command = completed.stdout.strip()
    return bool(
        completed.returncode == 0
        and "-m jupyterlab" in command
        and "--ServerApp.ip=127.0.0.1" in command
        and str(allowed_workspace_root) in command
    )


def _terminate_process(process: object) -> None:
    pid = int(getattr(process, "pid", 0) or 0)
    if pid > 0:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                terminate()
    wait = getattr(process, "wait", None)
    if callable(wait):
        try:
            wait(timeout=5)
        except (subprocess.TimeoutExpired, TypeError):
            if pid > 0:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("notebook escapes the owned workspace") from exc


def _new_jupyter_trace(
    *,
    owner_user_id: str,
    request_id: str,
    parent_trace_id: str | None,
    handoff_id: str | None,
    parent_request_id: str | None,
    original_plan_id: str | None,
) -> TraceContext:
    try:
        trace_request_id = trace_correlation_id(
            request_id,
            kind=TraceCorrelationKind.REQUEST,
        )
    except (TracePrivacyError, TraceValidationError):
        trace_request_id = f"request-ref:opaque:{uuid.uuid4().hex}"
    try:
        return TraceContext.new_request(
            trace_kind=TraceKind.STEPWISE,
            request_id=trace_request_id,
            parent_trace_id=parent_trace_id,
            handoff_id=handoff_id,
            parent_request_id=parent_request_id,
            original_plan_id=original_plan_id,
            principal_ref=owner_user_id,
        )
    except (TracePrivacyError, TraceValidationError):
        return TraceContext.new_request(
            trace_kind=TraceKind.STEPWISE,
            request_id=trace_request_id,
        )
