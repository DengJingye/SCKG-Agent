from copy import deepcopy
import hashlib

import numpy as np
import pytest
import anndata as ad
import h5py

from execution.data_registry import DataRegistry
from execution.research_input_binding import (
    register_upload, authorize_uploaded_binding, switch_conversation,
    invalidate_delivery, planning_context, digest, publish_delivery,
)


def upload_bytes(tmp_path, value=1):
    path = tmp_path / f"source-{value}.h5ad"
    data = ad.AnnData(np.full((3, 4), value, dtype=float))
    data.write_h5ad(path)
    return path.read_bytes()


def registry(tmp_path):
    root = tmp_path / "approved"
    root.mkdir(exist_ok=True)
    return DataRegistry(approved_input_roots=[root], registry_root=tmp_path / "registry")


def test_safe_upload_identity_and_original_unchanged(tmp_path):
    reg = registry(tmp_path)
    content = upload_bytes(tmp_path)
    result = register_upload(reg, user_id="alice", filename="../../my.h5ad", content=content)
    assert result["shape"] == [3, 4]
    assert result["original_filename"] == "my.h5ad"
    assert result["sha256"] == hashlib.sha256(content).hexdigest()
    path = reg.resolve_path(result["artifact_id"], user_id="alice")
    assert path.parent.name == "alice" and path.read_bytes() == content
    assert (tmp_path / "source-1.h5ad").read_bytes() == content
    with pytest.raises(PermissionError):
        reg.resolve_path(result["artifact_id"], user_id="bob")


def test_same_name_different_content_and_repeat_identity(tmp_path):
    reg = registry(tmp_path)
    a = register_upload(reg, user_id="alice", filename="same.h5ad", content=upload_bytes(tmp_path))
    b = register_upload(reg, user_id="alice", filename="same.h5ad", content=upload_bytes(tmp_path, 2))
    assert a["artifact_id"] != b["artifact_id"] and a["sha256"] != b["sha256"]
    assert register_upload(reg, user_id="alice", filename="same.h5ad", content=upload_bytes(tmp_path))["artifact_id"] == a["artifact_id"]


@pytest.mark.parametrize("name,content,user", [("x.txt", b"x", "a"), ("x.h5ad", b"broken", "a"), ("x.h5ad", b"", "a"), ("x.h5ad", b"x", "..")])
def test_reject_invalid_upload(tmp_path, name, content, user):
    with pytest.raises((ValueError, OSError)):
        register_upload(registry(tmp_path), user_id=user, filename=name, content=content)


def test_upload_external_link_rejected(tmp_path):
    path = tmp_path / "link.h5ad"
    with h5py.File(path, "w") as f:
        f["escape"] = h5py.ExternalLink("secret.h5", "/X")
    with pytest.raises(ValueError, match="links"):
        register_upload(registry(tmp_path), user_id="a", filename="x.h5ad", content=path.read_bytes())


def test_restart_reauthorizes_only_content_addressed_upload(tmp_path):
    reg = registry(tmp_path)
    binding = register_upload(reg, user_id="alice", filename="x.h5ad", content=upload_bytes(tmp_path))
    restored = registry(tmp_path)
    assert authorize_uploaded_binding(restored, binding, user_id="alice").artifact_id == binding["artifact_id"]
    with pytest.raises(ValueError, match="hash mismatch"):
        authorize_uploaded_binding(restored, {**binding, "sha256": "0" * 64}, user_id="alice")


def test_original_name_survives_registry_restart(tmp_path):
    from execution.research_input_binding import uploaded_display_name
    reg = registry(tmp_path)
    result = register_upload(reg, user_id="alice", filename="my experiment.h5ad", content=upload_bytes(tmp_path))
    restored = registry(tmp_path)
    authorize_uploaded_binding(restored, result, user_id="alice")
    assert uploaded_display_name(restored.resolve_path(result["artifact_id"], user_id="alice")) == "my experiment.h5ad"


def test_explicit_sample_selection_and_restart_preserve_identity(tmp_path):
    from execution.research_input_binding import register_sample
    reg = registry(tmp_path)
    assert reg.list_for_user(user_id="alice") == []
    sample = register_sample(reg, user_id="alice")
    assert sample["shape"] == [180, 240]
    assert sample["source"] == "explicit_demo"
    assert register_sample(reg, user_id="alice") == sample
    assert authorize_uploaded_binding(registry(tmp_path), sample, user_id="alice").sha256 == sample["sha256"]


def test_conversation_isolation_a_b_a_and_no_demo_default():
    state = {"workspace_artifact_id": "legacy-synthetic", "capability_workspace_jupyter_url": "raw-url"}
    switch_conversation(state, "A")
    assert "workspace_artifact_id" not in state and "capability_workspace_jupyter_url" not in state
    state.update(workspace_artifact_id="raw", capability_workspace_result={"plan": "raw"})
    switch_conversation(state, "B")
    assert "workspace_artifact_id" not in state and "capability_workspace_result" not in state
    state.update(workspace_artifact_id="processed", capability_workspace_result={"plan": "processed"})
    switch_conversation(state, "A")
    assert state["workspace_artifact_id"] == "raw"
    assert state["capability_workspace_result"]["plan"] == "raw"


def test_invalidation_archives_result_and_drops_jupyter():
    state = {"capability_workspace_result": {"notebook": "old"},
             "capability_workspace_jupyter_url": "old", "capability_workspace_context_digest": "old",
             "capability_workspace_artifact_id": "new"}
    invalidate_delivery(state)
    assert state["binding_delivery_history"][0]["capability_workspace_result"] == {"notebook": "old"}
    assert "capability_workspace_jupyter_url" not in state
    assert state["capability_workspace_artifact_id"] == "new"


@pytest.mark.parametrize("field,value", [("artifact_id", "b"), ("sha256", "2")])
def test_content_identity_changes_context(field, value):
    binding = {"artifact_id": "a", "sha256": "1"}
    a = digest(planning_context({}, binding, "batch"))
    binding[field] = value
    assert digest(planning_context({}, binding, "batch")) != a


@pytest.mark.parametrize("field,value", [("source_query", "new"), ("target_representations", ["umap"]),
    ("preferred_method_ids", ["pca"]), ("parameter_overrides", {"pca": {"n_comps": 20}}),
    ("handoff_id", "new"), ("enable_batch_integration", True)])
def test_task_and_parameters_invalidate_context(field, value):
    payload = {"conversation_id": "A"}
    first = digest(planning_context(payload, {"artifact_id": "a"}, None))
    payload[field] = value
    assert digest(planning_context(payload, {"artifact_id": "a"}, None)) != first


def test_late_results_cannot_publish():
    state = {"capability_workspace_context_digest": "new"}
    assert not publish_delivery(state, expected_context="old", result={"plan": "old"})
    assert "capability_workspace_result" not in state
    assert publish_delivery(state, expected_context="new", result={"plan": "new"})


def test_transport_preserves_supported_constraints():
    payload = {"conversation_id": "a", "target_representations": ["umap"],
               "preferred_method_ids": ["scanpy_core.pca_log_hvg"],
               "parameter_overrides": {"scanpy_core.neighbors": {"n_neighbors": 20}},
               "enable_batch_integration": True}
    before = deepcopy(payload)
    context = planning_context(payload, {"artifact_id": "a", "sha256": "b"}, "donor")
    for key in payload:
        assert context[key] == payload[key]
    assert context["batch_key"] == "donor" and payload == before


def test_widget_events_and_execution_grants_are_never_restored():
    state = {}
    switch_conversation(state, "a")
    state.update(capability_workspace_prepare=True, capability_workspace_download_binding=True,
                 workspace_grant_id="old-grant", workspace_preview_approval_id="old-approval",
                 capability_workspace_result={"plan": "a"})
    switch_conversation(state, "b")
    switch_conversation(state, "a")
    assert state["capability_workspace_result"] == {"plan": "a"}
    assert "capability_workspace_prepare" not in state
    assert "capability_workspace_download_binding" not in state
    assert "workspace_grant_id" not in state
    assert "workspace_preview_approval_id" not in state


def test_upload_resource_budget_and_symlink(tmp_path, monkeypatch):
    import execution.research_input_binding as mod
    reg = registry(tmp_path)
    monkeypatch.setattr(mod, "MAX_UPLOAD_BYTES", 2)
    with pytest.raises(ValueError, match="MiB"):
        register_upload(reg, user_id="a", filename="x.h5ad", content=b"123")
    monkeypatch.setattr(mod, "MAX_UPLOAD_BYTES", 200000)
    content = upload_bytes(tmp_path)
    folder = reg.approved_input_roots[0] / "research-uploads"
    folder.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        register_upload(reg, user_id="a", filename="x.h5ad", content=content)


def app_function(name, namespace):
    """Exercise exact app transport functions without starting Streamlit or Seed fixtures."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
    return namespace[name]


def test_actual_ui_handoff_keeps_request_binding_and_constraints():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    ns = {"Dict": dict, "Any": object, "datetime": datetime, "timezone": timezone,
          "st": SimpleNamespace(session_state=SimpleNamespace(session_id="a")),
          "_research_input_binding": lambda: {"artifact_id": "later-file", "sha256": "later"}}
    fn = app_function("_workspace_handoff_payload", ns)
    state = {"ui_input_binding": {"artifact_id": "request-file", "sha256": "frozen"},
             "workspace_handoff": {"status": "available", "notebook_strategy": "capability_renderer",
                 "pack_id": "scanpy_core", "pack_version": "1.0.0", "target_representations": ["umap"],
                 "preferred_method_ids": ["scanpy_core.pca_log_hvg"],
                 "parameter_overrides": {"pca": {"n_comps": 20}}, "enable_batch_integration": True}}
    result = fn(state, source_query="PLAN without scale")
    assert result["input_binding"] == state["ui_input_binding"]
    for field in ("target_representations", "preferred_method_ids", "parameter_overrides", "enable_batch_integration"):
        assert result[field] == state["workspace_handoff"][field]
    assert result["source_query"] == "PLAN without scale"


def test_multiple_uploads_require_explicit_choice_and_disable_unbound_submission():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    assert 'options=[None, *range(len(data_files))]' in text
    assert 'disabled=bool(st.session_state.get("workspace_input_pending"))' in text
    assert 'options=["", *labels]' in text
