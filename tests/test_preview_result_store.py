from pathlib import Path
from datetime import datetime, timezone

import pytest

from core.execution_models import ExecutionRun, ValidationResult
from core.research_workspace_models import PreviewRunResult
from execution.approval_service import ApprovalService
from execution.preview_result_store import PreviewResultStore
from tests.test_preview_execution_service import _harness


def _execute_preview(tmp_path: Path):
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
        request_id="preview-result-store",
    )
    return service, result


def test_preview_result_history_survives_service_restart_and_is_owner_scoped(tmp_path):
    service, result = _execute_preview(tmp_path)
    store = PreviewResultStore(
        workspace_root=service.research_workspace.workspace_root,
        execution_root=service.workspace.root,
    )

    summaries = store.list_results(user_id="alice")
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.run_id == result.execution_run.run_id
    assert summary.status == "COMPLETED"
    assert summary.validation_passed is True
    assert summary.integrity.passed is True
    assert summary.scientific_claim_allowed is False

    recovered = store.load_result(
        user_id="alice", artifact_id="pbmc", run_id=summary.run_id
    )
    assert recovered.preview_id == result.preview_id
    assert recovered.execution_run.run_id == result.execution_run.run_id
    assert store.list_results(user_id="bob") == []
    with pytest.raises(FileNotFoundError):
        store.load_result(user_id="bob", artifact_id="pbmc", run_id=summary.run_id)


def test_preview_result_integrity_blocks_tampered_artifact_and_record(tmp_path):
    service, result = _execute_preview(tmp_path)
    store = PreviewResultStore(
        workspace_root=service.research_workspace.workspace_root,
        execution_root=service.workspace.root,
    )
    run_id = result.execution_run.run_id
    histogram = Path(result.execution_run.artifact_paths["doublet_score_histogram.png"])
    histogram.write_bytes(histogram.read_bytes() + b"tampered")

    summary = store.list_results(user_id="alice")[0]
    assert summary.status == "FAILED"
    assert summary.integrity.passed is False
    assert "doublet_score_histogram.png" in summary.integrity.hash_mismatches
    with pytest.raises(PermissionError, match="artifact_integrity_failed"):
        store.resolve_artifact(
            user_id="alice",
            artifact_id="pbmc",
            run_id=run_id,
            artifact_name="doublet_score_histogram.png",
        )

    result_path = (
        service.research_workspace.workspace_root
        / "alice"
        / "artifacts"
        / "pbmc"
        / "preview-runs"
        / run_id
        / "preview_run_result.json"
    )
    result_path.write_text(result_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    corrupt = store.list_results(user_id="alice")[0]
    assert corrupt.status == "FAILED"
    assert corrupt.integrity.result_digest_valid is False
    with pytest.raises(PermissionError, match="result_record_integrity_failed"):
        store.load_result(user_id="alice", artifact_id="pbmc", run_id=run_id)


def test_preview_result_history_empty_state_is_read_only(tmp_path):
    store = PreviewResultStore(
        workspace_root=tmp_path / "research",
        execution_root=tmp_path / "users",
    )

    assert store.list_results(user_id="alice") == []
    assert not (tmp_path / "research" / "alice").exists()


def test_preview_result_history_preserves_blocked_terminal_state(tmp_path):
    now = datetime.now(timezone.utc)
    run = ExecutionRun(
        request_id="request-blocked",
        run_id="preview-run-blocked",
        trace_id="trace-preview-run-blocked",
        plan_id="plan-blocked",
        step_id="doublet.scrublet.preview",
        wrapper_id="scrublet_v0_2_3",
        tool_name="Scrublet",
        tool_version="0.2.3",
        environment_id="scRNAseq",
        command_argv_redacted=["python", "-m", "execution.wrappers.scrublet"],
        parameters={},
        input_hash="a" * 64,
        start_time=now,
        end_time=now,
        runtime_seconds=0,
        stdout_path=str(tmp_path / "users/alice/runs/preview-run-blocked/stdout.log"),
        stderr_path=str(tmp_path / "users/alice/runs/preview-run-blocked/stderr.log"),
        status="blocked",
        error_type="execution_gate_failure",
        qualification_mode=False,
        fixture_id="preview-blocked",
        synthetic_fixture=False,
        user_data_used=True,
        execution_purpose="representative_preview",
        owner_user_id="alice",
    )
    result = PreviewRunResult(
        user_id="alice",
        artifact_id="pbmc",
        preview_id="preview-blocked",
        notebook_id="notebook-blocked",
        plan_id="plan-blocked",
        status="blocked",
        execution_run=run,
        validation_result=ValidationResult(
            validation_id="validation-blocked",
            run_id=run.run_id,
            passed=False,
            failures=["execution_not_successful"],
            metric_authority="preview_engineering_metric",
        ),
    )
    store = PreviewResultStore(
        workspace_root=tmp_path / "research", execution_root=tmp_path / "users"
    )
    store.save(result)

    summary = store.list_results(user_id="alice")[0]
    assert summary.status == "BLOCKED"
    assert summary.integrity.passed is True


def test_preview_result_history_ignores_symlink_escape(tmp_path):
    store = PreviewResultStore(
        workspace_root=tmp_path / "research", execution_root=tmp_path / "users"
    )
    outside = tmp_path / "outside" / "preview-runs"
    outside.mkdir(parents=True)
    owned_artifact = tmp_path / "research/alice/artifacts/pbmc"
    owned_artifact.mkdir(parents=True)
    (owned_artifact / "preview-runs").symlink_to(outside, target_is_directory=True)

    assert store.list_results(user_id="alice") == []
