from __future__ import annotations

import json

import pytest

from core.trace_context import TraceCollector, TracePersistenceError
from engine.capability_workspace_service import CapabilityWorkspaceService
from execution.local_jupyter_service import LocalJupyterService
from tests.test_capability_workspace_service import _registered_fixture, _request
from tests.test_local_jupyter_service import _Process, _executable, _trusted_notebook


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _stages(row):
    return [span["stage"] for span in row["spans"]]


def test_research_stepwise_jupyter_child_trace_topology_and_privacy(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    collector = TraceCollector(trace_path)
    registry, artifact, compiler = _registered_fixture(tmp_path)
    workspace_root = tmp_path / "workspace"
    notebook_path = workspace_root / "alice" / "scanpy.ipynb"
    research_trace_id = "trace_11111111111111111111111111111111"
    handoff_id = "research-handoff:stepwise-test"
    research_request_id = "research-request:stepwise-test"
    original_plan_id = "plan_stepwise_origin"
    prepared = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=compiler,
        trace_collector=collector,
    ).prepare(
        _request(
            artifact.artifact_id,
            request_id="workspace-stepwise-request",
            origin_trace_id=research_trace_id,
            handoff_id=handoff_id,
            parent_request_id=research_request_id,
            original_plan_id=original_plan_id,
        ),
        notebook_path=notebook_path,
    )

    server_python = _executable(tmp_path / "control" / "python")
    runtime_python = _executable(tmp_path / "runtime" / "python")
    jupyter = LocalJupyterService(
        allowed_workspace_root=workspace_root,
        state_root=tmp_path / "jupyter-state",
        server_python=server_python,
        process_launcher=lambda *args, **kwargs: _Process(),
        readiness_probe=lambda _url: True,
        port_allocator=lambda: 18888,
        token_factory=lambda: "fixed-jupyter-token-123456",
        trace_collector=collector,
    )
    session = jupyter.start(
        owner_user_id="alice",
        notebook_path=notebook_path,
        expected_sha256=prepared.notebook_artifact["sha256"],
        runtime_python=runtime_python,
        runtime_pack_id="doublet-python",
        request_id="jupyter-launch:stepwise-test",
        parent_trace_id=prepared.canonical_trace_id,
        handoff_id=handoff_id,
        parent_request_id=prepared.request_id,
        original_plan_id=prepared.workflow_plan.plan_id,
    )

    rows = _rows(trace_path)
    assert len(rows) == 2
    workspace_row, jupyter_row = rows
    assert prepared.canonical_trace_id == workspace_row["trace_id"]
    assert session.canonical_trace_id == jupyter_row["trace_id"]
    assert workspace_row["trace_kind"] == "STEPWISE"
    assert workspace_row["parent_trace_id"] == research_trace_id
    assert workspace_row["handoff_id"] == handoff_id
    assert workspace_row["parent_request_id"] == research_request_id
    assert workspace_row["original_plan_id"] == original_plan_id
    assert _stages(workspace_row) == [
        "REQUEST",
        "STATE_INSPECTION",
        "PLANNING",
        "NOTEBOOK_COMPILE",
    ]
    assert jupyter_row["trace_kind"] == "STEPWISE"
    assert jupyter_row["parent_trace_id"] == prepared.canonical_trace_id
    assert jupyter_row["parent_request_id"] == prepared.request_id
    assert _stages(jupyter_row) == ["REQUEST", "RUNTIME_BIND"]
    assert all(
        len([span for span in row["spans"] if span["parent_span_id"] is None]) == 1
        for row in rows
    )
    persisted = trace_path.read_text(encoding="utf-8")
    assert str(notebook_path) not in persisted
    assert str(runtime_python) not in persisted
    assert "fixed-jupyter-token-123456" not in persisted
    assert session.launch_url not in persisted
    assert "Editable shadow notebook" not in persisted
    assert prepared.execution_request_count == 0


def test_ask_workspace_does_not_emit_false_semantic_spans(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    registry, artifact, compiler = _registered_fixture(tmp_path)
    result = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=compiler,
        trace_collector=TraceCollector(trace_path),
    ).prepare(
        _request(
            artifact.artifact_id,
            request_id="workspace-ask-only",
            mode="ASK",
        ),
        notebook_path=tmp_path / "unused.ipynb",
    )

    assert result.status == "discovered"
    assert _stages(_rows(trace_path)[0]) == ["REQUEST"]
    assert not (tmp_path / "unused.ipynb").exists()


def test_stepwise_trace_persistence_failure_does_not_change_business_result(
    tmp_path,
    monkeypatch,
):
    collector = TraceCollector(tmp_path / "traces.jsonl")

    def fail_append(_encoded):
        raise TracePersistenceError("trace append failed")

    monkeypatch.setattr(collector, "_append_encoded", fail_append)
    registry, artifact, compiler = _registered_fixture(tmp_path)
    result = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=compiler,
        trace_collector=collector,
    ).prepare(
        _request(artifact.artifact_id, request_id="workspace-persistence-failure"),
        notebook_path=tmp_path / "workspace" / "scanpy.ipynb",
    )

    assert result.status == "planned"
    assert result.notebook_artifact["sha256"]
    assert not (tmp_path / "traces.jsonl").exists()


def test_jupyter_trace_persistence_failure_does_not_change_business_result(
    tmp_path,
    monkeypatch,
):
    collector = TraceCollector(tmp_path / "traces.jsonl")

    def fail_append(_encoded):
        raise TracePersistenceError("trace append failed")

    monkeypatch.setattr(collector, "_append_encoded", fail_append)
    workspace = tmp_path / "workspace"
    notebook = workspace / "alice" / "analysis.ipynb"
    digest = _trusted_notebook(notebook)
    service = LocalJupyterService(
        allowed_workspace_root=workspace,
        state_root=tmp_path / "state",
        server_python=_executable(tmp_path / "control" / "python"),
        process_launcher=lambda *args, **kwargs: _Process(),
        readiness_probe=lambda _url: True,
        port_allocator=lambda: 18889,
        trace_collector=collector,
    )

    session = service.start(
        owner_user_id="alice",
        notebook_path=notebook,
        expected_sha256=digest,
        runtime_python=_executable(tmp_path / "runtime" / "python"),
        runtime_pack_id="doublet-python",
        request_id="jupyter-launch:persistence-failure",
    )

    assert session.launch_url.startswith("http://127.0.0.1:18889/")
    assert not (tmp_path / "traces.jsonl").exists()


def test_jupyter_business_exception_remains_primary_and_trace_is_failed(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    workspace = tmp_path / "workspace"
    outside_notebook = tmp_path / "outside.ipynb"
    outside_digest = _trusted_notebook(outside_notebook)
    server_python = _executable(tmp_path / "control" / "python")
    runtime_python = _executable(tmp_path / "runtime" / "python")
    service = LocalJupyterService(
        allowed_workspace_root=workspace,
        state_root=tmp_path / "state",
        server_python=server_python,
        process_launcher=lambda *args, **kwargs: _Process(),
        readiness_probe=lambda _url: True,
        trace_collector=TraceCollector(trace_path),
    )

    with pytest.raises(ValueError, match="escapes"):
        service.start(
            owner_user_id="alice",
            notebook_path=outside_notebook,
            expected_sha256=outside_digest,
            runtime_python=runtime_python,
            runtime_pack_id="doublet-python",
            request_id="jupyter-launch:business-failure",
        )

    row = _rows(trace_path)[0]
    assert row["status"] == "FAILED"
    assert _stages(row) == ["REQUEST", "RUNTIME_BIND"]
    assert row["spans"][1]["error_code"] == "runtime_bind_failed"
