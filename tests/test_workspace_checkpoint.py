from pathlib import Path
import shutil

from execution.approval_service import parameter_hash
from execution.environment_registry import EnvironmentRegistry
from tests.test_preview_execution_service import _harness


def _run(tmp_path: Path):
    service, approvals, grant, profile, preview, notebook = _harness(tmp_path)
    preparation = service.prepare(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=None,
        profile=profile,
        preview=preview,
        notebook=notebook,
    )
    approval = approvals.create_execution_approval(
        scope=preparation.approval_scope,
        data_grant_id=grant.grant_id,
    )
    result = service.execute(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        profile=profile,
        preview=preview,
        notebook=notebook,
        request_id="checkpoint-run",
    )
    integrity = service.result_store.inspect_integrity(result)
    return service, approvals, grant, profile, preview, notebook, result, integrity


def test_completed_result_lineage_is_current_after_single_use_approval(tmp_path):
    service, _, _, _, _, _, result, integrity = _run(tmp_path)

    report = service.checkpoints.inspect_result(result=result, integrity=integrity)

    assert report.overall_status == "CURRENT"
    assert report.first_invalid_stage is None
    assert report.execution_request_count == 0
    assert [item.status for item in report.nodes] == ["CURRENT"] * 6


def test_source_change_propagates_stale_from_profile_without_execution(tmp_path):
    service, approvals, _, _, _, _, result, integrity = _run(tmp_path)
    source = service.data_registry.resolve_path("pbmc", user_id="alice")
    source.write_bytes(source.read_bytes() + b"source-drift")
    stored = approvals.get_execution_approval(result.execution_run.approval_id)
    consumed_before = stored.uses_consumed

    report = service.checkpoints.inspect_result(result=result, integrity=integrity)

    assert report.overall_status == "STALE"
    assert report.first_invalid_stage == "source"
    assert report.rebuild_from == "source"
    assert report.node("source").reasons == ["registered_source_hash_changed"]
    assert all(item.status == "STALE" for item in report.nodes)
    assert all(item.propagated for item in report.nodes[1:])
    assert approvals.get_execution_approval(
        result.execution_run.approval_id
    ).uses_consumed == consumed_before
    assert report.execution_request_count == 0


def test_preview_change_invalidates_preview_and_downstream_only(tmp_path):
    service, _, _, _, _, _, result, integrity = _run(tmp_path)
    preview_path = Path(
        next(
            path
            for path in (
                service.research_workspace.workspace_root
                / "alice/artifacts/pbmc/previews"
            ).glob("*/representative_preview.h5ad")
        )
    )
    preview_path.write_bytes(preview_path.read_bytes() + b"preview-drift")

    report = service.checkpoints.inspect_result(result=result, integrity=integrity)

    assert report.overall_status == "STALE"
    assert report.first_invalid_stage == "preview"
    assert report.node("source").status == "CURRENT"
    assert report.node("profile").status == "CURRENT"
    assert report.node("preview").status == "STALE"
    assert all(report.node(stage).status == "STALE" for stage in ("notebook", "approval", "result"))


def test_parameter_change_invalidates_notebook_and_downstream(tmp_path):
    service, _, _, _, _, notebook, result, integrity = _run(tmp_path)
    notebook_path = service.research_workspace.notebook_path(
        user_id="alice", artifact_id="pbmc", bundle=notebook
    )
    parameter_path = notebook_path.parent / "parameters.json"
    parameter_path.write_text('{"expected_doublet_rate": 0.2}\n', encoding="utf-8")

    report = service.checkpoints.inspect_result(result=result, integrity=integrity)

    assert report.overall_status == "STALE"
    assert report.first_invalid_stage == "notebook"
    assert report.node("notebook").reasons == ["notebook_or_parameter_hash_changed"]
    assert report.node("approval").status == "STALE"
    assert report.node("result").status == "STALE"
    assert parameter_hash({"expected_doublet_rate": 0.2}) != notebook.parameter_hash


def test_legacy_result_without_lineage_is_readable_but_stale(tmp_path):
    service, _, _, _, _, _, result, integrity = _run(tmp_path)
    legacy = result.model_copy(update={"lineage": None})

    report = service.checkpoints.inspect_result(result=legacy, integrity=integrity)

    assert report.overall_status == "STALE"
    assert report.rebuild_from == "source"
    assert "legacy" in report.user_action.casefold()
    assert report.execution_request_count == 0


def test_environment_change_invalidates_approval_and_result(tmp_path):
    service, _, _, _, _, _, result, integrity = _run(tmp_path)
    environment_root = tmp_path / "environment-drift"
    environment_root.mkdir()
    source_environment = service.environment_registry.root / "scRNAseq.json"
    environment_path = environment_root / "scRNAseq.json"
    shutil.copy2(source_environment, environment_path)
    environment_path.write_text(
        environment_path.read_text(encoding="utf-8").replace(
            '"scrublet": "0.2.3"', '"scrublet": "0.2.3-drift"'
        ),
        encoding="utf-8",
    )
    service.checkpoints.environment_registry = EnvironmentRegistry(environment_root)

    report = service.checkpoints.inspect_result(result=result, integrity=integrity)

    assert report.overall_status == "STALE"
    assert report.first_invalid_stage == "approval"
    assert report.node("approval").reasons == ["environment_fingerprint_changed"]
    assert report.node("result").status == "STALE"
    assert report.execution_request_count == 0
