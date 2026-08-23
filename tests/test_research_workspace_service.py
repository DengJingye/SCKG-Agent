import io
import zipfile
from pathlib import Path

import pytest

from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.research_workspace_service import ResearchWorkspaceService
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_workspace_requires_grant_and_preserves_ownership(tmp_path):
    input_root = tmp_path / "inputs"
    source = write_phase1_fixtures(input_root)["counts_layer"]
    registry = DataRegistry(
        approved_input_roots=[input_root], registry_root=tmp_path / "registry"
    )
    artifact = registry.register(user_id="alice", path=source, artifact_id="pbmc")
    approvals = ApprovalService(root=tmp_path / "approvals")
    service = ResearchWorkspaceService(
        data_registry=registry,
        approval_service=approvals,
        workspace_root=tmp_path / "workspace",
    )

    with pytest.raises(PermissionError, match="data_access_grant_missing"):
        service.profile(user_id="alice", artifact_id="pbmc", data_grant_id="")
    grant = approvals.grant_data_access(user_id="alice", artifact_id="pbmc")
    profile = service.profile(
        user_id="alice", artifact_id="pbmc", data_grant_id=grant.grant_id
    )
    preview = service.build_preview(
        user_id="alice",
        artifact_id="pbmc",
        profile=profile,
        data_grant_id=grant.grant_id,
        max_cells=18,
    )
    bundle = service.compile_notebook(
        user_id="alice",
        artifact_id="pbmc",
        profile=profile,
        preview=preview,
        data_grant_id=grant.grant_id,
        task_context={
            "conversation_id": "conversation-1",
            "source_query": "请逐步运行 Scrublet Preview",
            "task_family": "doublet_detection",
            "tool_name": "Scrublet",
        },
    )
    assert service.notebook_path(
        user_id="alice", artifact_id="pbmc", bundle=bundle
    ).is_file()
    assert artifact.sha256 == profile.source_hash
    assert bundle.task_context["conversation_id"] == "conversation-1"
    assert bundle.task_context["tool_name"] == "Scrublet"
    archive_bytes = service.notebook_bundle_bytes(
        user_id="alice", artifact_id="pbmc", bundle=bundle
    )
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert {
            "analysis_preview.ipynb",
            "representative_preview.h5ad",
            "parameters.json",
            "step_contract.json",
            "notebook_manifest.json",
            "README.txt",
        }.issubset(archive.namelist())
    preview_path = service.preview_path(
        user_id="alice", artifact_id="pbmc", preview=preview
    )
    import anndata as ad

    preview_adata = ad.read_h5ad(preview_path)
    assert preview_adata.uns["sckg_fixture"] == {
        "fixture_id": preview.preview_id,
        "maintainer_approved": False,
        "public_dataset": False,
        "qualification_mode": False,
        "representative_preview": True,
        "synthetic": False,
        "user_data": True,
    }

    with pytest.raises(PermissionError):
        service.notebook_path(user_id="bob", artifact_id="pbmc", bundle=bundle)
    unsafe_bundle = bundle.model_copy(update={"owner_user_id": "../alice"})
    with pytest.raises(ValueError, match="unsafe research workspace identifier"):
        service.notebook_path(
            user_id="../alice", artifact_id="pbmc", bundle=unsafe_bundle
        )
    approvals.revoke_data_access(grant.grant_id)
    with pytest.raises(PermissionError, match="authorization_revoked"):
        service.build_preview(
            user_id="alice",
            artifact_id="pbmc",
            profile=profile,
            data_grant_id=grant.grant_id,
        )
