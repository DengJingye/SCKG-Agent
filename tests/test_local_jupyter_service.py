from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.trace_context import TraceCollector
from execution.local_jupyter_service import LocalJupyterService


class _Process:
    pid = 424242

    def poll(self):
        return None


def _trusted_notebook(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cells": [],
                "metadata": {
                    "sckg": {
                        "trusted_code_source": "maintainer_step_template"
                    }
                },
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_jupyter_uses_localhost_fixed_argv_and_existing_runtime(tmp_path):
    workspace = tmp_path / "workspace"
    notebook = workspace / "alice" / "analysis_preview.ipynb"
    digest = _trusted_notebook(notebook)
    server_python = _executable(tmp_path / "control" / "python")
    runtime_python = _executable(tmp_path / "runtime" / "python")
    calls = []

    def launch(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Process()

    service = LocalJupyterService(
        allowed_workspace_root=workspace,
        state_root=tmp_path / "state",
        server_python=server_python,
        process_launcher=launch,
        readiness_probe=lambda _url: True,
        port_allocator=lambda: 18888,
        token_factory=lambda: "fixed-token",
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )
    session = service.start(
        owner_user_id="alice",
        notebook_path=notebook,
        expected_sha256=digest,
        runtime_python=runtime_python,
        runtime_pack_id="doublet-python",
    )

    argv, kwargs = calls[0]
    assert argv[:3] == [str(server_python.resolve()), "-m", "jupyterlab"]
    assert "--LabApp.core_mode=True" in argv
    assert "--LabApp.news_url=" in argv
    assert "--ServerApp.ip=127.0.0.1" in argv
    assert "--ServerApp.port=18888" in argv
    assert "--FileContentsManager.allow_hidden=True" in argv
    assert all("install" not in value.casefold() for value in argv)
    assert kwargs["shell"] is False
    assert kwargs["env"]["JUPYTERLAB_WORKSPACES_DIR"] == str(
        tmp_path / "state" / "sessions" / session.session_id / "lab-workspaces"
    )
    assert session.launch_url.startswith("http://127.0.0.1:18888/lab/tree/")
    kernel = json.loads(
        (
            tmp_path
            / "state"
            / "jupyter-data"
            / "kernels"
            / "sckg-doublet-python"
            / "kernel.json"
        ).read_text(encoding="utf-8")
    )
    assert kernel["argv"][0] == str(runtime_python.resolve())
    assert kernel["metadata"]["sckg_runtime_pack"] == "doublet-python"
    session_manifest = (
        tmp_path / "state" / "sessions" / session.session_id / "session.json"
    ).read_text(encoding="utf-8")
    assert "fixed-token" not in session_manifest
    assert str(notebook.parent) not in session_manifest
    with pytest.raises(PermissionError, match="cross-user"):
        service.get(session_id=session.session_id, owner_user_id="bob")


def test_jupyter_blocks_escape_hash_change_and_untrusted_notebook(tmp_path):
    workspace = tmp_path / "workspace"
    server_python = _executable(tmp_path / "control" / "python")
    runtime_python = _executable(tmp_path / "runtime" / "python")
    service = LocalJupyterService(
        allowed_workspace_root=workspace,
        state_root=tmp_path / "state",
        server_python=server_python,
        process_launcher=lambda *args, **kwargs: _Process(),
        readiness_probe=lambda _url: True,
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )
    outside = tmp_path / "outside.ipynb"
    outside_digest = _trusted_notebook(outside)
    with pytest.raises(ValueError, match="escapes"):
        service.start(
            owner_user_id="alice",
            notebook_path=outside,
            expected_sha256=outside_digest,
            runtime_python=runtime_python,
            runtime_pack_id="doublet-python",
        )

    notebook = workspace / "analysis_preview.ipynb"
    _trusted_notebook(notebook)
    with pytest.raises(ValueError, match="hash changed"):
        service.start(
            owner_user_id="alice",
            notebook_path=notebook,
            expected_sha256="0" * 64,
            runtime_python=runtime_python,
            runtime_pack_id="doublet-python",
        )
    payload = json.loads(notebook.read_text(encoding="utf-8"))
    payload["metadata"]["sckg"]["trusted_code_source"] = "user"
    notebook.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="maintainer-generated"):
        service.start(
            owner_user_id="alice",
            notebook_path=notebook,
            expected_sha256=hashlib.sha256(notebook.read_bytes()).hexdigest(),
            runtime_python=runtime_python,
            runtime_pack_id="doublet-python",
        )


def test_slow_start_is_not_killed_at_old_fifteen_second_limit(tmp_path, monkeypatch):
    import execution.local_jupyter_service as module
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    notebook = tmp_path / "workspace" / "slow.ipynb"
    digest = _trusted_notebook(notebook)
    service = LocalJupyterService(
        allowed_workspace_root=notebook.parent, state_root=tmp_path / "state",
        server_python=_executable(tmp_path / "server" / "python"),
        process_launcher=lambda *a, **k: _Process(),
        readiness_probe=lambda url: clock[0] >= 20,
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )
    session = service.start(owner_user_id="alice", notebook_path=notebook,
                            expected_sha256=digest, runtime_python=service.server_python,
                            runtime_pack_id="doublet-python")
    assert session.running and 20 <= clock[0] < 60


def test_timeout_remains_bounded_and_does_not_leak_token(tmp_path, monkeypatch):
    import execution.local_jupyter_service as module
    clock = [0.0]
    terminated = []
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(module, "_terminate_process", lambda process: terminated.append(process))
    notebook = tmp_path / "workspace" / "blocked.ipynb"
    digest = _trusted_notebook(notebook)
    service = LocalJupyterService(
        allowed_workspace_root=notebook.parent, state_root=tmp_path / "state",
        server_python=_executable(tmp_path / "server" / "python"),
        process_launcher=lambda *a, **k: _Process(), readiness_probe=lambda url: False,
        token_factory=lambda: "do-not-disclose-this-token",
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )
    with pytest.raises(TimeoutError) as error:
        service.start(owner_user_id="alice", notebook_path=notebook,
                      expected_sha256=digest, runtime_python=service.server_python,
                      runtime_pack_id="doublet-python", timeout_seconds=1)
    assert "within 1s" in str(error.value) and "jupyter.log" in str(error.value)
    assert "do-not-disclose" not in str(error.value)
    assert len(terminated) == 1
    assert not list((tmp_path / "state").rglob("session.json"))
