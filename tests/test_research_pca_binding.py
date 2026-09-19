"""Bound-data routing regressions; no Seed generators and no external LLM."""
import json

import pytest

from agent.research_chat_service import _pca_analysis_request, _capability_workspace_handoff
from core.research_agent_models import ResearchAgentRequest, AgentMode
from tests.test_research_chat_service import _service
from tests.test_research_input_binding import registry, register_upload, upload_bytes


@pytest.mark.parametrize("query", ["帮我做一下 pca分析", "请计算PCA", "帮我做主成分分析", "please run PCA"])
def test_owned_anndata_pca_reaches_planning_handoff_without_llm(tmp_path, query):
    reg = registry(tmp_path)
    binding = register_upload(reg, user_id="alice", filename="my.h5ad", content=upload_bytes(tmp_path))
    service = _service(tmp_path)
    service._data_registry = reg
    response = service.run_request(ResearchAgentRequest(
        request_id="pca-bound", user_id="alice", query=query, artifact_id=binding["artifact_id"],
    ))
    assert response.state.domain == "SINGLE_CELL"
    assert response.state.mode == "PLAN"
    assert response.workspace_handoff.status == "available"
    assert response.workspace_handoff.target_representations == ["pca"]
    assert response.workspace_handoff.pack_id == "scanpy_core"
    assert response.execution_handoff.execution_request_count == 0
    rows = [json.loads(line) for line in (tmp_path / "traces.jsonl").read_text().splitlines()]
    stages = [span["stage"] for span in rows[-1]["spans"]]
    assert "HANDOFF" in stages and "EXECUTION" not in stages


@pytest.mark.parametrize("query", ["PCA是什么？", "PCA需要什么输入", "PCA怎么做", "不要做PCA", "what does PCA require?", "帮我解释一下PCA分析", "帮我比较PCA和UMAP"])
def test_pca_information_or_negation_is_not_analysis_request(query):
    assert not _pca_analysis_request(query)


@pytest.mark.parametrize("user,artifact", [("bob", "owned"), ("alice", "missing"), ("alice", None)])
def test_non_owned_or_missing_artifact_is_not_a_data_anchor(tmp_path, user, artifact):
    reg = registry(tmp_path)
    binding = register_upload(reg, user_id="alice", filename="my.h5ad", content=upload_bytes(tmp_path))
    service = _service(tmp_path)
    service._data_registry = reg
    request = ResearchAgentRequest(request_id="no-anchor", user_id=user, query="帮我做一下pca分析",
        artifact_id=binding["artifact_id"] if artifact == "owned" else artifact)
    assert service._bound_operator_task(request) is None


def test_bound_data_does_not_make_finance_a_single_cell_task(tmp_path):
    reg = registry(tmp_path)
    binding = register_upload(reg, user_id="alice", filename="my.h5ad", content=upload_bytes(tmp_path))
    service = _service(tmp_path)
    service._data_registry = reg
    assert service._bound_operator_task(ResearchAgentRequest(request_id="finance", user_id="alice",
        query="帮我做股票PCA分析", artifact_id=binding["artifact_id"])) is None


def test_bound_pca_explanation_stays_ask(tmp_path):
    reg = registry(tmp_path)
    binding = register_upload(reg, user_id="alice", filename="my.h5ad", content=upload_bytes(tmp_path))
    service = _service(tmp_path)
    service._data_registry = reg
    response = service.run_request(ResearchAgentRequest(request_id="pca-ask", user_id="alice",
        query="PCA需要什么输入？", artifact_id=binding["artifact_id"]))
    assert response.state.mode == "ASK"
    assert response.workspace_handoff.status == "not_applicable"
    assert response.execution_handoff.execution_request_count == 0


def test_explicit_run_cannot_gain_execution_permission_from_data_binding(tmp_path):
    reg = registry(tmp_path)
    binding = register_upload(reg, user_id="alice", filename="my.h5ad", content=upload_bytes(tmp_path))
    service = _service(tmp_path)
    service._data_registry = reg
    response = service.run_request(ResearchAgentRequest(request_id="pca-run", user_id="alice",
        mode=AgentMode.RUN, query="现在执行PCA", artifact_id=binding["artifact_id"]))
    assert response.state.mode == "RUN"
    assert response.execution_handoff.execution_request_count == 0
    assert response.execution_handoff.status != "completed"


def test_pca_target_uses_actual_workspace_and_preserves_input(tmp_path):
    from tests.test_capability_workspace_service import _registered_fixture, _request
    from engine.capability_workspace_service import CapabilityWorkspaceService
    from core.trace_context import TraceCollector
    import hashlib
    registry_, artifact, compiler = _registered_fixture(tmp_path)
    path = registry_.resolve_path(artifact.artifact_id, user_id="local-user")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = CapabilityWorkspaceService(data_registry=registry_, notebook_compiler=compiler,
        trace_collector=TraceCollector(tmp_path / "trace.jsonl")).prepare(
            _request(artifact.artifact_id, target_representations=["pca"]), notebook_path=tmp_path / "pca.ipynb")
    operations = [step.operation for step in result.workflow_plan.steps]
    assert any("pca" in name for name in operations)
    assert not any(any(term in name for term in ("neighbors", "leiden", "umap", "annotation")) for name in operations)
    assert result.execution_request_count == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_reused_pca_notebook_is_inspectable_not_an_empty_title(tmp_path):
    import hashlib
    import anndata as ad
    import numpy as np
    from tests.test_capability_workspace_service import _registered_fixture, _request
    from engine.capability_workspace_service import CapabilityWorkspaceService
    from core.trace_context import TraceCollector
    reg, source, compiler = _registered_fixture(tmp_path)
    data = ad.read_h5ad(reg.resolve_path(source.artifact_id, user_id="local-user"))
    # Explicit synthetic representation fixture, not biological annotation gold.
    data.obsm["X_pca"] = np.random.default_rng(12).normal(size=(data.n_obs, 50))
    data.uns["pca"] = {"variance_ratio": np.linspace(.03, .001, 50)}
    path = reg.approved_input_roots[0] / "existing-pca.h5ad"
    data.write_h5ad(path)
    artifact = reg.register(user_id="local-user", path=path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    notebook_path = tmp_path / "reuse.ipynb"
    result = CapabilityWorkspaceService(data_registry=reg, notebook_compiler=compiler,
        trace_collector=TraceCollector(tmp_path / "trace.jsonl")).prepare(
            _request(artifact.artifact_id, target_representations=["pca"]), notebook_path=notebook_path)
    assert result.workflow_plan.steps == []
    notebook = json.loads(notebook_path.read_text())
    code = [cell["source"] for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert len(code) == 2
    assert notebook["metadata"]["language_info"]["name"] == "python"
    assert notebook["metadata"]["kernelspec"]["name"] == "sckg-doublet-python"
    for source_code in code:
        compile(source_code, "reuse-fixture-cell", "exec")
        assert "sc.pp.pca(" not in source_code and "sc.tl.pca(" not in source_code
    assert "existing_pca_scatter.png" in code[-1]
    assert "existing_pca_variance.png" in code[-1]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
