"""Bound-data embedding requests use the existing planner, without external LLM."""
import hashlib
import json

import anndata as ad
import numpy as np
import pytest

from agent.research_chat_service import ResearchChatService
from core.research_agent_models import ResearchAgentRequest
from core.trace_context import TraceCollector
from engine.capability_workspace_service import CapabilityWorkspaceService
from tests.test_capability_workspace_service import _registered_fixture, _request
from tests.test_research_chat_service import _service


@pytest.mark.parametrize("query,targets", [
    ("帮我画一下这份数据的umap图", ["umap"]),
    ("请绘制 UMAP", ["umap"]),
    ("plot UMAP for this dataset", ["umap"]),
    ("帮我画一下这份数据的PCA图", ["pca"]),
    ("帮我做 PCA 和 UMAP 分析", ["pca", "umap"]),
])
def test_bound_embedding_request_reaches_handoff(tmp_path, query, targets):
    registry, artifact, _ = _registered_fixture(tmp_path)
    service = _service(tmp_path)
    service._data_registry = registry
    response = service.run_request(ResearchAgentRequest(
        request_id="embedding-request", user_id="local-user", query=query,
        artifact_id=artifact.artifact_id,
    ))
    assert response.state.domain == "SINGLE_CELL"
    assert response.state.mode == "PLAN"
    assert response.workspace_handoff.status == "available"
    assert response.workspace_handoff.target_representations == targets
    assert response.workspace_handoff.pack_id == "scanpy_core"
    assert response.execution_handoff.execution_request_count == 0
    traces = [json.loads(row) for row in (tmp_path / "traces.jsonl").read_text().splitlines()]
    stages = [span["stage"] for span in traces[-1]["spans"]]
    assert "HANDOFF" in stages and "EXECUTION" not in stages


@pytest.mark.parametrize("query", [
    "UMAP是什么？", "帮我解释UMAP图", "如何绘制UMAP？",
    "不要画UMAP", "don't plot UMAP", "帮我比较PCA和UMAP",
])
def test_embedding_information_and_negation_do_not_schedule(tmp_path, query):
    registry, artifact, _ = _registered_fixture(tmp_path)
    service = _service(tmp_path)
    service._data_registry = registry
    response = service.run_request(ResearchAgentRequest(
        request_id="embedding-ask", user_id="local-user", query=query,
        artifact_id=artifact.artifact_id,
    ))
    assert response.state.mode == "ASK"
    assert response.workspace_handoff.status == "not_applicable"
    assert response.execution_handoff.execution_request_count == 0


@pytest.mark.parametrize("artifact_kind", ["missing", "other_owner", "unbound"])
def test_umap_does_not_invent_a_bound_input(tmp_path, artifact_kind):
    registry, artifact, _ = _registered_fixture(tmp_path)
    service = _service(tmp_path)
    service._data_registry = registry
    request = ResearchAgentRequest(request_id="no-input", query="帮我画UMAP图",
        user_id="other-user" if artifact_kind == "other_owner" else "local-user",
        artifact_id=None if artifact_kind == "unbound" else
        "missing" if artifact_kind == "missing" else artifact.artifact_id)
    assert service._bound_operator_task(request) is None


@pytest.mark.parametrize("reuse", [False, True])
def test_real_research_to_workspace_umap_notebook(tmp_path, reuse):
    registry, artifact, compiler = _registered_fixture(tmp_path)
    if reuse:
        data = ad.read_h5ad(registry.resolve_path(artifact.artifact_id, user_id="local-user"))
        data.obsm["X_umap"] = np.random.default_rng(19).normal(size=(data.n_obs, 2))
        path = registry.approved_input_roots[0] / "with-umap.h5ad"
        data.write_h5ad(path)
        artifact = registry.register(user_id="local-user", path=path)
    path = registry.resolve_path(artifact.artifact_id, user_id="local-user")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    # Real production Research retrieval/tool service, offline; no mocked planner.
    service = ResearchChatService(data_registry=registry, dense_default_enabled=False,
        trace_collector=TraceCollector(tmp_path / "research-trace.jsonl"))
    response = service.run_request(ResearchAgentRequest(
        request_id="real-umap", user_id="local-user", query="帮我画一下这份数据的umap图",
        artifact_id=artifact.artifact_id))
    assert response.workspace_handoff.status == "available"
    assert response.workspace_handoff.target_representations == ["umap"]
    handoff = response.workspace_handoff
    result = CapabilityWorkspaceService(data_registry=registry, notebook_compiler=compiler,
        trace_collector=TraceCollector(tmp_path / "workspace-trace.jsonl")).prepare(
        _request(artifact.artifact_id, pack_id=handoff.pack_id, pack_version=handoff.pack_version,
                 target_representations=handoff.target_representations),
        notebook_path=tmp_path / "umap.ipynb")
    operations = [step.operation for step in result.workflow_plan.steps]
    assert not any(any(term in op for term in ("leiden", "annotation", "rank_markers")) for op in operations)
    assert (operations == []) if reuse else ("scanpy_core.umap" in operations)
    notebook = json.loads((tmp_path / "umap.ipynb").read_text())
    code = [c["source"] for c in notebook["cells"] if c["cell_type"] == "code"]
    assert len(code) >= 2
    assert any("umap" in c.lower() and "sckg_save_and_display" in c for c in code)
    for cell in code:
        compile(cell, "umap-notebook-cell", "exec")
    assert result.execution_request_count == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
