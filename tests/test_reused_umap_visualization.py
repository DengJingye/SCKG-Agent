"""Existing UMAP display bindings; no clustering or embedding computation."""
import hashlib
import json
from types import SimpleNamespace

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from core.capability_workspace_models import CapabilityWorkspaceRequest
from core.trace_context import TraceCollector
from engine.capability_workspace_service import CapabilityWorkspaceService
from execution.capability_notebook import GenericNotebookCompiler, NotebookRendererRegistry
from execution.data_registry import DataRegistry
from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer


TITLE = "Reusing existing UMAP; no recomputation"


def _record(key, **updates):
    return {"representation_id": "cluster_labels", "slot": f"obs/{key}",
            "status": "current", "validated": True, **updates}


def _inspection(records):
    cells = ScanpyCoreNotebookRenderer().bootstrap({
        "reused_target_representations": ["umap"],
        "representation_ledger": {"records": records},
    })
    return next(c["source"] for c in cells if c["id"] == "reused-umap-inspection")


def _run_inspection(source, data):
    calls = []
    saved = []
    # No tl/pp methods exist: recomputation would fail this generated-cell test.
    scanpy = SimpleNamespace(pl=SimpleNamespace(umap=lambda a, **kw: calls.append((a, kw))))
    before_obs = data.obs.copy(deep=True)
    before_umap = data.obsm["X_umap"].copy()
    exec(source, {"np": np, "adata": data, "sc": scanpy,
                  "plt": SimpleNamespace(gcf=lambda: "figure"),
                  "sckg_save_and_display": lambda fig, name: saved.append((fig, name))})
    pd.testing.assert_frame_equal(data.obs, before_obs)
    np.testing.assert_array_equal(data.obsm["X_umap"], before_umap)
    assert saved == [("figure", "existing_umap.png")]
    assert len(calls) == 1 and calls[0][0] is data
    return calls[0][1]


def _data(key):
    data = ad.AnnData(np.ones((4, 3)))
    data.obs[key] = pd.Categorical(["A", "A", "B", "B"])
    data.obsm["X_umap"] = np.arange(8, dtype=float).reshape(4, 2)
    return data


@pytest.mark.parametrize("key", ["louvain", "leiden", "clusters_custom_v2", "cluster/with'quote"])
def test_reused_umap_uses_inspector_slot_for_arbitrary_label_keys(key):
    data = _data(key)
    if key != "leiden":
        data.obs["leiden"] = pd.Categorical(["wrong"] * 4)
    kwargs = _run_inspection(_inspection([_record(key)]), data)
    assert kwargs["color"] == [key]
    assert kwargs["title"] == [TITLE]
    assert kwargs["show"] is False


@pytest.mark.parametrize("records", [
    [], [_record("louvain", status="stale")], [_record("louvain", validated=False)],
    [_record("louvain", representation_id="confirmed_annotation")],
    [_record("louvain", slot="uns/louvain")], [_record("absent_column")],
])
def test_missing_or_unusable_label_binding_is_explicit_not_guessed(records, capsys):
    kwargs = _run_inspection(_inspection(records), _data("louvain"))
    assert kwargs["color"] is None
    assert kwargs["title"] == TITLE
    assert "showing an unlabelled UMAP" in capsys.readouterr().out


def test_multiple_inspected_labels_are_distinct_panels_without_duplicate_keys():
    data = _data("clusters_a")
    data.obs["clusters_b"] = pd.Categorical(["X", "Y", "X", "Y"])
    records = [_record("clusters_a"), _record("clusters_a"), _record("clusters_b")]
    kwargs = _run_inspection(_inspection(records), data)
    assert kwargs["color"] == ["clusters_a", "clusters_b"]
    assert kwargs["title"] == [TITLE, TITLE]


@pytest.mark.parametrize("key", ["louvain", "leiden"])
def test_workspace_passes_actual_inspector_binding_to_reuse_only_notebook(tmp_path, key):
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    source = input_root / "processed.h5ad"
    _data(key).write_h5ad(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    registry = DataRegistry(approved_input_roots=[input_root], registry_root=tmp_path / "registry")
    artifact = registry.register(user_id="demo", path=source)
    notebook_path = tmp_path / "reuse.ipynb"
    result = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=GenericNotebookCompiler(NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])),
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    ).prepare(CapabilityWorkspaceRequest(
        request_id="umap-display", user_id="demo", artifact_id=artifact.artifact_id,
        pack_id="scanpy_core", pack_version="1.0.0", mode="PLAN",
        requirement_id="existing-umap", target_representations=["umap"],
    ), notebook_path=notebook_path)
    assert result.status == "planned"
    assert result.workflow_plan.steps == []
    assert result.execution_request_count == 0
    cluster = result.representation_ledger.current("cluster_labels")
    assert [r.slot for r in cluster] == [f"obs/{key}"]
    notebook = json.loads(notebook_path.read_text())
    code = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    assert len(code) == 2  # load and display only
    assert all(c["execution_count"] is None and not c["outputs"] for c in code)
    kwargs = _run_inspection(code[-1]["source"], ad.read_h5ad(source))
    assert kwargs["color"] == [key]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
