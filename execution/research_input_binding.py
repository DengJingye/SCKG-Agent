"""Local upload transport and conversation-scoped UI state, not scientific routing."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import os

from execution.data_registry import DataRegistry

MAX_UPLOAD_BYTES = int(os.environ.get("SCKG_RESEARCH_UPLOAD_MAX_MB", "1024")) * 1024 * 1024
MAX_EXPANDED_BYTES = int(os.environ.get("SCKG_RESEARCH_EXPANDED_MAX_MB", "4096")) * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def validate_h5ad(path: Path) -> tuple[int, int]:
    """Bound expansion and reject external links before backed AnnData inspection."""
    import h5py
    import anndata as ad

    total = 0
    seen = set()
    with h5py.File(path, "r") as handle:
        def walk(group):
            nonlocal total
            address = h5py.h5o.get_info(group.id).addr
            if address in seen:
                return
            seen.add(address)
            if len(seen) > 100000:
                raise ValueError("h5ad object budget exceeded")
            for name in group:
                if not isinstance(group.get(name, getlink=True), h5py.HardLink):
                    raise ValueError("h5ad external/soft links are not permitted")
                obj = group[name]
                if isinstance(obj, h5py.Group):
                    walk(obj)
                else:
                    if obj.is_virtual or obj.external:
                        raise ValueError("h5ad external storage is not permitted")
                    total += obj.size * max(obj.dtype.itemsize, 8)
                    if total > MAX_EXPANDED_BYTES:
                        raise ValueError("h5ad expanded size budget exceeded")
        walk(handle)
    data = ad.read_h5ad(path, backed="r")
    try:
        if min(data.shape) <= 0 or not data.obs_names.is_unique or not data.var_names.is_unique:
            raise ValueError("AnnData requires nonempty, unique cell and gene identities")
        return tuple(data.shape)
    finally:
        data.file.close()


def register_upload(registry: DataRegistry, *, user_id: str, filename: str, content: bytes):
    """Copy only explicit uploads below an existing approved root, never a supplied path."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", user_id) or user_id in {".", ".."}:
        raise ValueError("invalid user identity")
    name = filename.replace("\\", "/").split("/")[-1]
    if not name.lower().endswith(".h5ad"):
        raise ValueError("only .h5ad uploads are supported")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(f"上传文件须非空且不超过部署上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB；较大文件可使用本地关联，无需上传复制。")
    sha = hashlib.sha256(content).hexdigest()
    root = registry.approved_input_roots[0]
    folder = root / "research-uploads" / user_id
    for part in (root / "research-uploads", folder):
        if part.is_symlink():
            raise ValueError("symlink upload directory forbidden")
        part.mkdir(exist_ok=True, mode=0o700)
    path = folder / f"{sha}.h5ad"
    if path.is_symlink():
        raise ValueError("symlink upload forbidden")
    if not path.exists():
        with tempfile.NamedTemporaryFile(dir=folder, suffix=".h5ad") as temporary:
            temporary.write(content)
            temporary.flush()
            shape = validate_h5ad(Path(temporary.name))
            # Exclusive creation: never overwrite any existing input.
            try:
                with path.open("xb") as output:
                    output.write(content)
                path.chmod(0o600)
            except FileExistsError:
                if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                    raise ValueError("upload content-address collision")
    else:
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError("stored upload integrity mismatch")
        shape = validate_h5ad(path)
    record = registry.register(user_id=user_id, path=path)
    # Content-addressed storage is private; preserve the human filename across
    # process restarts and explicit registered-artifact selection.
    metadata = path.with_suffix(".upload.json")
    if not metadata.exists():
        try:
            with metadata.open("x", encoding="utf-8") as output:
                json.dump({"original_filename": name, "sha256": sha}, output, ensure_ascii=False)
            metadata.chmod(0o600)
        except FileExistsError:
            pass
    return {"artifact_id": record.artifact_id, "sha256": record.sha256,
            "original_filename": name, "source": "user_upload", "shape": list(shape),
            "owner_user_id": user_id}


def uploaded_display_name(path: Path) -> str:
    if path.name == "scanpy_core_synthetic_v1.h5ad":
        return "sample.h5ad"
    metadata = path.with_suffix(".upload.json")
    if metadata.is_file() and not metadata.is_symlink():
        value = json.loads(metadata.read_text())
        if value.get("sha256") == path.stem:
            return Path(value["original_filename"]).name
    return path.name


def register_sample(registry, *, user_id):
    """The small engineering demo is created only on an explicit user click."""
    from execution.scanpy_synthetic_fixture import generate_scanpy_core_synthetic_fixture
    folder = registry.approved_input_roots[0] / "capability-fixtures" / "scanpy_core" / "1.0.0"
    path = folder / "scanpy_core_synthetic_v1.h5ad"
    manifest = folder / "fixture_manifest.json"
    if not path.exists() and not manifest.exists():
        generate_scanpy_core_synthetic_fixture(folder)
    frozen = json.loads(manifest.read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != frozen["h5ad_sha256"]:
        raise ValueError("系统样例完整性检查未通过")
    record = registry.register(user_id=user_id, path=path)
    return {"artifact_id": record.artifact_id, "sha256": record.sha256,
            "original_filename": "sample.h5ad", "source": "explicit_demo", "shape": frozen["shape"],
            "owner_user_id": user_id}


def _managed_record_path(registry, record, user_id):
    """Only reconstruct application-owned paths, never guess a private local path."""
    root = registry.approved_input_roots[0]
    name = Path(record.redacted_path).name
    if name == f"{record.sha256}.h5ad":
        return root / "research-uploads" / user_id / name, "user_upload"
    if name == "scanpy_core_synthetic_v1.h5ad":
        return root / "capability-fixtures" / "scanpy_core" / "1.0.0" / name, "explicit_demo"
    return None, None


def registered_input_options(registry, *, user_id):
    """Hide unresolved history. Full integrity/AnnData validation happens on selection."""
    available, unavailable = [], []
    for record in registry.list_for_user(user_id=user_id):
        path, source = _managed_record_path(registry, record, user_id)
        try:
            if registry.path_authorized(record.artifact_id, user_id=user_id):
                if registry.current_hash(record.artifact_id, user_id=user_id) != record.sha256:
                    raise ValueError("changed")
                name = uploaded_display_name(path) if path else Path(record.redacted_path).name
            elif path and path.is_file() and not path.is_symlink() and path.stat().st_size == record.size_bytes:
                name = uploaded_display_name(path)
            else:
                raise ValueError("unresolved")
            available.append((record, name))
        except (OSError, ValueError, KeyError):
            unavailable.append(record.artifact_id)
    return available, unavailable


def select_registered_input(registry, *, artifact_id, user_id):
    """Explicit selection restores managed uploads, with owner/hash checks intact."""
    record = registry.get(artifact_id, user_id=user_id)
    _, source = _managed_record_path(registry, record, user_id)
    binding = {"artifact_id": record.artifact_id, "sha256": record.sha256,
               "owner_user_id": user_id, "source": source or "explicit_registered_selection"}
    authorize_uploaded_binding(registry, binding, user_id=user_id)
    path = registry.resolve_path(artifact_id, user_id=user_id)
    binding.update(original_filename=uploaded_display_name(path), shape=list(validate_h5ad(path)))
    return binding


def authorize_uploaded_binding(registry, binding, *, user_id):
    record = registry.get(binding["artifact_id"], user_id=user_id)
    if record.sha256 != binding["sha256"]:
        raise ValueError("input binding hash mismatch")
    if not registry.path_authorized(record.artifact_id, user_id=user_id):
        if binding.get("source") == "explicit_demo":
            restored = register_sample(registry, user_id=user_id)
            if restored["artifact_id"] != record.artifact_id or restored["sha256"] != record.sha256:
                raise ValueError("样例数据身份已变化，请重新选择")
            return record
        if binding.get("source") != "user_upload":
            raise ValueError("approved local input must be re-associated after restart")
        path = registry.approved_input_roots[0] / "research-uploads" / user_id / f"{record.sha256}.h5ad"
        if path.is_symlink():
            raise ValueError("symlink upload forbidden")
        checksum = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                checksum.update(block)
        if checksum.hexdigest() != record.sha256:
            raise ValueError("stored upload integrity mismatch")
        resolved = registry.register(user_id=user_id, path=path)
        if resolved.artifact_id != record.artifact_id:
            raise ValueError("upload registry identity mismatch")
    registry.resolve_path(record.artifact_id, user_id=user_id)
    return record


def switch_conversation(state, conversation_id):
    """Archive current displays, then restore ONLY this conversation's displays."""
    previous = state.get("binding_active_conversation")
    if previous == conversation_id:
        return
    def scoped(key):
        return key.startswith(("workspace_", "capability_workspace_", "research_run_",
                               "research_attach_")) or key in {"uploaded_context", "latest_state"}
    archive = dict(state.get("conversation_workspace_states", {}))
    # Streamlit button/file-uploader values cannot be assigned programmatically.
    # Archive owned data state only, not transient widget events or approvals.
    durable = {
        "workspace_task_handoff", "workspace_artifact_id", "workspace_profile",
        "workspace_preview", "workspace_notebook", "workspace_parameter_context",
        "workspace_parameter_draft", "workspace_stale_result", "uploaded_context",
        "capability_workspace_artifact_id", "capability_workspace_selected_artifact",
        "capability_workspace_batch_key", "capability_workspace_result",
        "capability_workspace_context_digest", "capability_workspace_result_context",
        "capability_workspace_request_binding", "capability_workspace_jupyter_url",
        "capability_workspace_jupyter_trace_id", "capability_workspace_jupyter_binding",
    }
    if previous:
        archive[previous] = {k: deepcopy(state[k]) for k in list(state) if k in durable}
    for key in list(state):
        if scoped(key):
            del state[key]
    state.update(deepcopy({k: v for k, v in archive.get(conversation_id, {}).items() if k in durable}))
    state["conversation_workspace_states"] = archive
    state["binding_active_conversation"] = conversation_id


def invalidate_delivery(state):
    """Keep old delivery as history; never display its notebook/approval as current."""
    keys = [k for k in list(state) if k.startswith("capability_workspace_") and
            k not in {"capability_workspace_artifact_id", "capability_workspace_selected_artifact",
                      "capability_workspace_local_path", "capability_workspace_batch_key"}]
    if keys:
        history = list(state.get("binding_delivery_history", []))
        history.append({k: deepcopy(state[k]) for k in keys})
        state["binding_delivery_history"] = history
    for key in keys:
        state.pop(key, None)


def planning_context(payload, binding, batch_key):
    """All planning-affecting supported transport values, without display timestamps."""
    fields = ("conversation_id", "handoff_id", "parent_request_id", "origin_trace_id",
              "original_plan_id", "source_query", "pack_id", "pack_version",
              "target_representations", "preferred_method_ids", "parameter_overrides",
              "enable_doublet_detection", "exclude_predicted_doublets", "doublet_selection_hash",
              "enable_batch_integration")
    return {**{k: payload.get(k) for k in fields}, "input_binding": binding,
            "batch_key": batch_key or None}


def publish_delivery(state, *, expected_context, result):
    if state.get("capability_workspace_context_digest") != expected_context:
        return False
    state["capability_workspace_result"] = result
    state["capability_workspace_result_context"] = expected_context
    return True
