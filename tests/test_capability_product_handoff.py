from __future__ import annotations

import json
from pathlib import Path

import anndata as ad
import numpy as np

from agent.research_chat_service import ResearchChatService, _capability_workspace_handoff
from core.capability_workspace_models import CapabilityWorkspaceRequest
from core.research_agent_models import AgentMode
from engine.capability_workspace_service import CapabilityWorkspaceService
from execution.capability_notebook import GenericNotebookCompiler, NotebookRendererRegistry
from execution.data_registry import DataRegistry
from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer


def test_capability_handoff_is_generic_and_carries_pack_targets():
    handoff = _capability_workspace_handoff(
        context_pack={
            "capability_context": [
                {
                    "pack_id": "scanpy_core",
                    "pack_version": "1.0.0",
                    "task_family": "scanpy_core_workflow",
                    "readiness": ["discovered", "planning_ready", "notebook_ready"],
                    "suggested_workspace_targets": ["annotation_candidates", "umap"],
                    "blockers": [],
                }
            ]
        },
        mode=AgentMode.PLAN,
        task="scanpy_core_workflow",
        plan_id="plan-from-chat",
    )

    assert handoff == {
        "status": "available",
        "task_family": "scanpy_core_workflow",
        "plan_id": "plan-from-chat",
        "notebook_strategy": "capability_renderer",
        "stepwise_preview_available": True,
        "pack_id": "scanpy_core",
        "pack_version": "1.0.0",
        "target_representations": ["annotation_candidates", "umap"],
        "preferred_method_ids": [],
        "blockers": [],
    }
    assert _capability_workspace_handoff(
        context_pack={"capability_context": []},
        mode=AgentMode.ASK,
        task="",
        plan_id=None,
    ) is None


def test_scanpy_handoff_preserves_explicit_scale_preference():
    context = {
        "capability_context": [
            {
                "pack_id": "scanpy_core",
                "pack_version": "1.0.0",
                "task_family": "scanpy_core_workflow",
                "readiness": ["planning_ready", "notebook_ready"],
                "suggested_workspace_targets": ["marker_result", "umap"],
            }
        ]
    }

    with_scale = _capability_workspace_handoff(
        context_pack=context,
        mode=AgentMode.PLAN,
        task="scanpy_core_workflow",
        plan_id="scale-plan",
        query="请生成完整 workflow，不要跳过 Scale。",
    )
    assert with_scale["preferred_method_ids"] == [
        "scanpy_core.scale_hvg",
        "scanpy_core.pca_scaled",
    ]

    without_scale = _capability_workspace_handoff(
        context_pack=context,
        mode=AgentMode.PLAN,
        task="scanpy_core_workflow",
        plan_id="no-scale-plan",
        query="Please skip Scale for this workflow.",
    )
    assert without_scale["preferred_method_ids"] == ["scanpy_core.pca_log_hvg"]
    assert _capability_workspace_handoff(
        context_pack={
            "capability_context": [
                {
                    "pack_id": "scanpy_core",
                    "pack_version": "1.0.0",
                    "capability_id": "scanpy_core.normalize",
                    "task_family": "scanpy_core_workflow",
                    "readiness": ["planning_ready"],
                    "suggested_workspace_targets": ["umap"],
                }
            ]
        },
        mode=AgentMode.PLAN,
        task="doublet_detection",
        plan_id="doublet-plan",
    ) is None


def test_capability_workspace_returns_profile_and_jupyter_trusted_notebook(tmp_path):
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    h5ad = input_root / "small.h5ad"
    counts = np.asarray(
        [[4, 0, 2, 1], [3, 1, 0, 2], [0, 5, 3, 1], [1, 4, 2, 0]],
        dtype=np.int32,
    )
    adata = ad.AnnData(counts)
    adata.obs_names = [f"cell-{index}" for index in range(adata.n_obs)]
    adata.var_names = [f"gene-{index}" for index in range(adata.n_vars)]
    adata.layers["counts"] = counts.copy()
    adata.write_h5ad(h5ad)
    registry = DataRegistry(
        approved_input_roots=[input_root], registry_root=tmp_path / "registry"
    )
    artifact = registry.register(user_id="alice", path=h5ad)
    result = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=GenericNotebookCompiler(
            NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])
        ),
    ).prepare(
        CapabilityWorkspaceRequest(
            request_id="product-handoff",
            user_id="alice",
            artifact_id=artifact.artifact_id,
            pack_id="scanpy_core",
            pack_version="1.0.0",
            mode="PLAN",
            requirement_id="product-handoff-requirement",
            target_representations=["marker_result", "umap"],
        ),
        notebook_path=tmp_path / "workspace" / "scanpy.ipynb",
    )

    assert result.status == "planned"
    assert result.execution_request_count == 0
    assert result.data_profile is not None
    assert result.data_profile.n_cells == 4
    notebook = json.loads(Path(result.notebook_artifact["path"]).read_text())
    assert notebook["metadata"]["sckg"]["trusted_code_source"] == "maintainer_step_template"
    assert notebook["metadata"]["sckg"]["execution_request_count"] == 0
    assert notebook["metadata"]["kernelspec"] == {
        "name": "sckg-doublet-python",
        "display_name": "scKG Doublet Python",
        "language": "python",
    }
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert "import scanpy as sc" in code_cells[0]["source"]
    assert f"INPUT_PATH = Path({json.dumps(str(h5ad.resolve()))})" in code_cells[0]["source"]
    assert "adata = sc.read_h5ad(INPUT_PATH)" in code_cells[0]["source"]
    assert "calculate_qc_metrics" in code_cells[1]["source"]
    assert "if 0 < int(value) <= adata.n_vars" in code_cells[1]["source"]
    assert "percent_top=qc_percent_top or None" in code_cells[1]["source"]
    all_code = "\n".join(cell["source"] for cell in code_cells)
    assert "sckg_save_and_display" in all_code
    assert "sc.pl.umap" in all_code
    assert "sc.pl.violin" in all_code
    assert "ranked_marker_genes.png" in all_code
    calls: dict[str, object] = {}

    class FakePreprocessing:
        @staticmethod
        def calculate_qc_metrics(adata, *, percent_top, inplace):
            calls.update(percent_top=percent_top, inplace=inplace, n_vars=adata.n_vars)

    class FakeScanpy:
        pp = FakePreprocessing()

    class SmallAnnData:
        n_vars = 4

    exec(
        code_cells[1]["source"],
        {"sc": FakeScanpy(), "adata": SmallAnnData()},
    )
    assert calls == {"percent_top": None, "inplace": True, "n_vars": 4}


def test_stepwise_ui_uses_capability_handoff_without_a_second_page():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )
    assert '== "capability_renderer"' in source
    assert "_render_capability_stepwise_workspace" in source
    assert "CapabilityWorkspaceService" in source
    assert 'current_view = "capability_workspace"' not in source
    assert '[data-testid="stAppDeployButton"]' in source
    assert "capability_workspace_artifact_id = artifact.artifact_id" in source


def test_real_scanpy_workflow_question_reaches_capability_stepwise_handoff():
    result = ResearchChatService(dense_default_enabled=False).run(
        "请为我的 scRNA-seq h5ad 生成 Scanpy Core QC 到聚类和 marker 的 workflow"
    )

    handoff = result["workspace_handoff"]
    assert result["error_message"] is None
    assert handoff["status"] == "available"
    assert handoff["notebook_strategy"] == "capability_renderer"
    assert handoff["pack_id"] == "scanpy_core"
    assert handoff["target_representations"] == ["annotation_candidates", "umap"]
