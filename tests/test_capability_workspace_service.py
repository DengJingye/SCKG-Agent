from __future__ import annotations

import json

import anndata as ad
import numpy as np
import pandas as pd

from core.capability_workspace_models import CapabilityWorkspaceRequest
from core.trace_context import TraceCollector
from engine.capability_workspace_service import CapabilityWorkspaceService
from engine.data_profiler import AnnDataProfiler
from execution.capability_notebook import GenericNotebookCompiler, NotebookRendererRegistry
from execution.data_registry import DataRegistry
from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer


def _registered_fixture(tmp_path):
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    rng = np.random.default_rng(20260824)
    batches = np.repeat(["batch-a", "batch-b", "batch-c"], 30)
    counts = rng.poisson(1.4, size=(len(batches), 80)).astype(np.int32)
    counts[batches == "batch-a", :12] += 4
    counts[batches == "batch-b", 12:24] += 4
    counts[batches == "batch-c", 24:36] += 4
    adata = ad.AnnData(
        X=counts,
        obs=pd.DataFrame(
            {"batch": batches},
            index=[f"cell-{index:03d}" for index in range(len(batches))],
        ),
        var=pd.DataFrame(index=[f"gene-{index:03d}" for index in range(80)]),
    )
    adata.layers["counts"] = counts.copy()
    path = input_root / "scanpy-core-workspace.h5ad"
    adata.write_h5ad(path)
    registry = DataRegistry(
        approved_input_roots=[input_root],
        registry_root=tmp_path / "data-registry",
    )
    artifact = registry.register(user_id="local-user", path=path)
    compiler = GenericNotebookCompiler(
        NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])
    )
    return registry, artifact, compiler


def _request(artifact_id: str, **updates):
    values = {
        "request_id": "scanpy-workspace-request",
        "user_id": "local-user",
        "artifact_id": artifact_id,
        "pack_id": "scanpy_core",
        "pack_version": "1.0.0",
        "mode": "PLAN",
        "requirement_id": "scanpy-workspace-requirement",
        "target_representations": ["marker_result", "umap"],
    }
    values.update(updates)
    return CapabilityWorkspaceRequest(**values)


def test_workspace_minimal_scanpy_plan_is_registry_driven_and_never_executes(tmp_path):
    registry, artifact, compiler = _registered_fixture(tmp_path)
    result = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=compiler,
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    ).prepare(
        _request(artifact.artifact_id),
        notebook_path=tmp_path / "minimal.ipynb",
    )

    assert result.status == "planned"
    assert "planning_ready" in result.readiness
    assert result.execution_request_count == 0
    assert result.workflow_plan is not None
    assert result.workflow_plan.plan_status == "dry_run"
    assert result.workflow_plan.execution_eligible is False
    assert result.notebook_artifact["cell_count"] > 4
    assert result.composition.selected_action_bundle_refs == []
    nodes = {step.operation: step for step in result.workflow_plan.steps}
    assert nodes["scanpy_core.highly_variable_genes"].parameters == {
        "n_top_genes": 80
    }
    assert nodes["scanpy_core.pca_log_hvg"].parameters == {"n_comps": 50}
    assert nodes["scanpy_core.neighbors"].parameters == {"n_neighbors": 15}
    assert nodes["scanpy_core.neighbors"].parameter_provenance[0].source_id.startswith(
        "https://scanpy.readthedocs.io/"
    )
    notebook = json.loads((tmp_path / "minimal.ipynb").read_text(encoding="utf-8"))
    notebook_source = "\n".join(cell["source"] for cell in notebook["cells"])
    assert 'STEP_PARAMETERS = {"n_top_genes": 80}' in notebook_source
    assert 'STEP_PARAMETERS = {"n_neighbors": 15}' in notebook_source
    assert "Resolved parameters and provenance" in notebook_source


def test_workspace_composes_doublet_and_batch_actions_without_direct_imports(tmp_path):
    registry, artifact, compiler = _registered_fixture(tmp_path)
    result = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=compiler,
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    ).prepare(
        _request(
            artifact.artifact_id,
            request_id="scanpy-composed-request",
            batch_key="batch",
            enable_doublet_detection=True,
            enable_batch_integration=True,
        ),
        notebook_path=tmp_path / "composed.ipynb",
    )

    assert result.status == "planned"
    assert result.execution_request_count == 0
    assert result.composition.selected_action_bundle_refs == [
        "action:batch-integration",
        "action:doublet-detection",
    ]
    method_ids = result.composition.selected_method_ids
    assert "scanpy_core.doublet_detection_action" in method_ids
    assert "scanpy_core.batch_integration_action" in method_ids
    assert "scanpy_core.neighbors_integrated" in method_ids


def test_workspace_run_remains_blocked_by_global_policy_with_zero_requests(tmp_path):
    registry, artifact, compiler = _registered_fixture(tmp_path)
    result = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=compiler,
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    ).prepare(
        _request(
            artifact.artifact_id,
            request_id="scanpy-run-request",
            mode="RUN",
        ),
        notebook_path=tmp_path / "run-shadow.ipynb",
    )

    assert result.status == "blocked"
    assert result.execution_policy == "disabled"
    assert result.blockers == ["execution_policy_disabled"]
    assert result.execution_request_count == 0


def test_workspace_rebuilds_profile_across_model_reload_boundary(tmp_path):
    registry, artifact, compiler = _registered_fixture(tmp_path)

    class ReloadedModelProxy:
        def __init__(self, value):
            self.value = value

        def model_dump(self, *, mode):
            return self.value.model_dump(mode=mode)

    class ReloadBoundaryProfiler:
        def profile(self, *args, **kwargs):
            return ReloadedModelProxy(AnnDataProfiler().profile(*args, **kwargs))

    result = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=compiler,
        data_profiler=ReloadBoundaryProfiler(),
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    ).prepare(
        _request(artifact.artifact_id, request_id="model-reload-boundary"),
        notebook_path=tmp_path / "model-reload.ipynb",
    )

    assert result.status == "planned"
    assert result.data_profile is not None
    assert result.data_profile.n_cells == 90
