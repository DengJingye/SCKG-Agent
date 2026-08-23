import hashlib
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.execution_models import ExecutionRun, ValidationResult
from core.research_workspace_models import PreviewRunResult
from execution.execution_policy import ExecutionPolicyMode
from execution.execution_policy import ExecutionPair
from core.execution_models import ApprovalScope
from execution.execution_ui_service import local_preview_allowance_can_be_reissued
from execution.preview_result_store import PreviewResultStore
from core.settings import PROJECT_ROOT
from tests.execution_ui_helpers import build_ui_harness, prepare_context
from streamlit.testing.v1 import AppTest
from scripts.run_path_to_preview_notebook_smoke import _write_smoke_fixture


def test_ui_service_profiles_and_plans_without_starting_execution(tmp_path):
    harness = build_ui_harness(tmp_path)
    artifacts = harness.service.list_artifacts(user_id="user-a")
    assert [item.artifact_id for item in artifacts] == [harness.artifact.artifact_id]
    assert artifacts[0].redacted_path.startswith(".../")

    _, context = prepare_context(harness)
    assert context.profile is not None
    assert context.profile.is_blocked is False
    assert context.plan is not None
    assert context.plan.plan_status == "dry_run"
    assert context.execution_approval.code == "missing"
    assert context.button_enabled is False
    assert not list((tmp_path / "users").glob("*/runs/*"))
    assert not list((tmp_path / "users").glob("*/packages/*"))


def test_disabled_policy_keeps_execution_button_disabled(tmp_path):
    harness = build_ui_harness(tmp_path, mode=ExecutionPolicyMode.DISABLED)
    _, context = prepare_context(harness)

    assert context.policy_mode == ExecutionPolicyMode.DISABLED
    assert context.button_enabled is False
    assert "execution_policy_disabled" in context.button_blockers


def test_maintainer_can_enable_one_scoped_local_preview(tmp_path):
    harness = build_ui_harness(
        tmp_path, mode=ExecutionPolicyMode.DISABLED, allow_user=False
    )

    denied = harness.service.enable_local_preview(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        actor_role="user",
    )
    assert denied.enabled is False
    assert denied.blockers == ["maintainer_role_required"]
    assert harness.service.execution_policy.mode == ExecutionPolicyMode.DISABLED

    enabled = harness.service.enable_local_preview(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        actor_role="maintainer",
    )
    assert enabled.enabled is True
    assert enabled.policy_mode == ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS
    assert harness.service.execution_policy.mode == ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS
    allowance = harness.allowlist.get("user-a")
    assert allowance.allowed_artifact_ids == [harness.artifact.artifact_id]
    assert allowance.allowed_data_scopes == ["representative_preview"]
    assert allowance.max_runs == 1


def test_exact_preview_approval_reissues_expired_mismatched_allowance(tmp_path):
    harness = build_ui_harness(
        tmp_path, mode=ExecutionPolicyMode.DISABLED, allow_user=False
    )
    contract = harness.service.contract_registry.load("Scrublet", "0.2.3")
    grant = harness.approvals.grant_data_access(
        user_id="user-a", artifact_id=harness.artifact.artifact_id
    )
    stale_pair = ExecutionPair(
        tool_name="Scrublet",
        tool_version="0.2.3",
        wrapper_id=contract.wrapper_id,
        environment_id="stale-environment",
    )
    harness.allowlist.allow_user(
        user_id="user-a",
        allowed_pairs=[stale_pair],
        allowed_artifact_ids=["stale-artifact"],
        allowed_data_scopes=["representative_preview"],
        max_runs=1,
        ttl=timedelta(minutes=5),
        now=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    scope = ApprovalScope(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        plan_id="preview-plan",
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        contract_version=contract.contract_version,
        environment_id=contract.environment_id,
        parameter_hash="a" * 64,
    )
    stale_decision = harness.allowlist.validate(
        user_id="user-a",
        pair=ExecutionPair(
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            wrapper_id=contract.wrapper_id,
            environment_id=contract.environment_id,
        ),
        artifact_id=harness.artifact.artifact_id,
        data_scope="representative_preview",
    )
    assert local_preview_allowance_can_be_reissued(stale_decision.reasons)
    assert set(stale_decision.reasons) == {
        "artifact_not_allowed_for_user",
        "local_user_allowance_expired",
        "tool_environment_pair_not_allowed_for_user",
    }

    result = harness.service.approve_local_preview(
        scope=scope,
        data_grant_id=grant.grant_id,
        confirmation_text=f"APPROVE PREVIEW {scope.fingerprint[:12]}",
        actor_role="maintainer",
    )

    assert result.enablement.enabled is True
    assert result.approval.scope == scope
    assert harness.approvals.validate_execution_approval(
        result.approval.approval_id, expected_scope=scope
    ).allowed
    refreshed = harness.allowlist.validate(
        user_id="user-a",
        pair=ExecutionPair(
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            wrapper_id=contract.wrapper_id,
            environment_id=contract.environment_id,
        ),
        artifact_id=harness.artifact.artifact_id,
        data_scope="representative_preview",
    )
    assert refreshed.allowed


def test_preview_approval_rejects_wrong_confirmation_without_enablement(tmp_path):
    harness = build_ui_harness(
        tmp_path, mode=ExecutionPolicyMode.DISABLED, allow_user=False
    )
    contract = harness.service.contract_registry.load("Scrublet", "0.2.3")
    grant = harness.approvals.grant_data_access(
        user_id="user-a", artifact_id=harness.artifact.artifact_id
    )
    scope = ApprovalScope(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        plan_id="preview-plan",
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        contract_version=contract.contract_version,
        environment_id=contract.environment_id,
        parameter_hash="b" * 64,
    )

    try:
        harness.service.approve_local_preview(
            scope=scope,
            data_grant_id=grant.grant_id,
            confirmation_text="APPROVE SOMETHING ELSE",
            actor_role="maintainer",
        )
    except PermissionError as exc:
        assert "confirmation text mismatch" in str(exc)
    else:
        raise AssertionError("wrong confirmation must be rejected")
    assert harness.service.execution_policy.mode == ExecutionPolicyMode.DISABLED
    assert not harness.service.user_allowlisted(user_id="user-a")


def test_execution_page_render_does_not_start_a_process(tmp_path, monkeypatch):
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", "ui-render-pytest")
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    user_root = PROJECT_ROOT / ".sckg_exec" / "users" / "ui-render-pytest"
    before = list(user_root.rglob("execution_run.json")) if user_root.exists() else []
    app_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=30)
    button = next(item for item in app.button if item.label == "Runs & Results")
    button.click().run(timeout=30)

    assert len(app.exception) == 0
    after = list(user_root.rglob("execution_run.json")) if user_root.exists() else []
    assert after == before


def test_runs_and_results_recovers_preview_history_without_executing(
    tmp_path, monkeypatch
):
    user_id = f"preview-history-{tmp_path.name}".replace("_", "-")
    run_id = f"preview-run-{tmp_path.name}".replace("_", "-")
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", user_id)
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    execution_root = PROJECT_ROOT / ".sckg_exec" / "users"
    research_root = PROJECT_ROOT / ".sckg_exec" / "research-workspace"
    run_root = execution_root / user_id / "runs" / run_id
    result_root = research_root / user_id
    shutil.rmtree(execution_root / user_id, ignore_errors=True)
    shutil.rmtree(result_root, ignore_errors=True)
    run_root.mkdir(parents=True, exist_ok=True)
    histogram = run_root / "doublet_score_histogram.png"
    histogram.write_bytes(b"preview-image")
    digest = hashlib.sha256(histogram.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc)
    result = PreviewRunResult(
        user_id=user_id,
        artifact_id="pbmc",
        preview_id="preview-1",
        notebook_id="notebook-1",
        plan_id="plan-1",
        status="validated",
        execution_run=ExecutionRun(
            request_id="request-1",
            run_id=run_id,
            trace_id=f"trace-{run_id}",
            plan_id="plan-1",
            step_id="doublet.scrublet.preview",
            wrapper_id="scrublet_v0_2_3",
            tool_name="Scrublet",
            tool_version="0.2.3",
            environment_id="scRNAseq",
            command_argv_redacted=["python", "-m", "execution.wrappers.scrublet"],
            parameters={"expected_doublet_rate": 0.08},
            input_hash="a" * 64,
            start_time=now,
            end_time=now,
            runtime_seconds=1.2,
            peak_memory_mb=32,
            exit_code=0,
            stdout_path=str(run_root / "stdout.log"),
            stderr_path=str(run_root / "stderr.log"),
            artifact_paths={"doublet_score_histogram.png": str(histogram)},
            artifact_hashes={"doublet_score_histogram.png": digest},
            status="succeeded",
            qualification_mode=False,
            fixture_id="preview-1",
            synthetic_fixture=False,
            user_data_used=True,
            execution_purpose="representative_preview",
            owner_user_id=user_id,
        ),
        validation_result=ValidationResult(
            validation_id="validation-1",
            run_id=run_id,
            passed=True,
            metric_authority="preview_engineering_metric",
            validation_version="doublet-preview-validator-v1",
        ),
    )
    PreviewResultStore(
        workspace_root=research_root, execution_root=execution_root
    ).save(result)
    before = list((execution_root / user_id).rglob("execution_run.json"))

    try:
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path)).run(timeout=30)
        next(item for item in app.button if item.label == "Runs & Results").click().run(
            timeout=30
        )

        assert len(app.exception) == 0
        visible = "\n".join(item.value for item in app.markdown)
        captions = "\n".join(item.value for item in app.caption)
        warnings = "\n".join(item.value for item in app.warning)
        assert "Representative Preview results" in visible
        assert "This result is stale and must not be used" in visible
        assert "Recommended next steps" in visible
        assert "scientific authority=false" in captions
        assert "STALE" in visible
        assert "legacy" in warnings.casefold()
        assert list((execution_root / user_id).rglob("execution_run.json")) == before
        assert str(PROJECT_ROOT) not in visible + captions
    finally:
        shutil.rmtree(execution_root / user_id, ignore_errors=True)
        shutil.rmtree(result_root, ignore_errors=True)


def test_research_workspace_shadow_renders_without_profile_or_execution_side_effects(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", "workspace-render-pytest")
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    execution_root = PROJECT_ROOT / ".sckg_exec" / "users" / "workspace-render-pytest"
    workspace_root = (
        PROJECT_ROOT
        / ".sckg_exec"
        / "research-workspace"
        / "workspace-render-pytest"
    )
    before_runs = (
        list(execution_root.rglob("execution_run.json"))
        if execution_root.exists()
        else []
    )
    before_profiles = (
        list(workspace_root.rglob("data_asset_profile.json"))
        if workspace_root.exists()
        else []
    )
    app_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=30)

    assert len(app.exception) == 0
    after_runs = (
        list(execution_root.rglob("execution_run.json"))
        if execution_root.exists()
        else []
    )
    after_profiles = (
        list(workspace_root.rglob("data_asset_profile.json"))
        if workspace_root.exists()
        else []
    )
    assert after_runs == before_runs
    assert after_profiles == before_profiles


def test_research_workspace_ui_completes_path_to_notebook_without_execution(
    tmp_path, monkeypatch
):
    approved_root = PROJECT_ROOT / ".sckg_exec" / "approved-inputs"
    source = _write_smoke_fixture(
        approved_root / f"ui-shadow-{tmp_path.name}.h5ad"
    )
    user_id = f"workspace-ui-{tmp_path.name}".replace("_", "-")
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", user_id)
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    user_root = PROJECT_ROOT / ".sckg_exec" / "users" / user_id
    before_runs = (
        list(user_root.rglob("execution_run.json")) if user_root.exists() else []
    )

    app_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=30)
    _text_input(app, "workspace_local_path").input(str(source)).run(timeout=30)
    _button(app, "workspace_register_artifact").click().run(timeout=30)
    _button(app, "workspace_authorize").click().run(timeout=30)
    _button(app, "workspace_profile_button").click().run(timeout=30)

    assert len(app.exception) == 0
    profile = app.session_state.workspace_profile
    assert profile.storage_mode == "backed_read_only"
    assert profile.full_matrix_materialized is False
    assert profile.selected_count_source == "layers/counts"

    _button(app, "workspace_preview_button").click().run(timeout=30)
    assert len(app.exception) == 0
    preview = app.session_state.workspace_preview
    assert preview.source_unchanged is True
    assert preview.scientific_claim_allowed is False

    _button(app, "workspace_notebook_button").click().run(timeout=30)
    assert len(app.exception) == 0
    notebook = app.session_state.workspace_notebook
    assert notebook.executed is False
    assert notebook.execution_request_count == 0
    next(
        item
        for item in app.toggle
        if item.key == "workspace_show_external_notebook"
    ).set_value(True).run(timeout=30)
    assert any(
        item.label == "下载完整 Notebook bundle (.zip)"
        for item in app.get("download_button")
    )
    assert _button(app, "workspace_start_jupyter").disabled is False
    visible = "\n".join(item.value for item in app.markdown)
    assert "工作区检查点" in visible
    metric_labels = {item.label for item in app.metric}
    assert {"Source", "Profile", "Preview", "Notebook", "Approval", "Result"}.issubset(
        metric_labels
    )
    next(
        item for item in app.toggle if item.key == "workspace_show_preview_run"
    ).set_value(True).run(timeout=30)
    run_button = _button(app, "workspace_preview_run_button")
    assert run_button.disabled is True
    assert "workspace_preview_run_result" not in app.session_state
    after_runs = (
        list(user_root.rglob("execution_run.json")) if user_root.exists() else []
    )
    assert after_runs == before_runs


def test_stepwise_analysis_is_chat_handoff_only_and_renders_parameter_review(
    tmp_path, monkeypatch
):
    approved_root = PROJECT_ROOT / ".sckg_exec" / "approved-inputs"
    source = _write_smoke_fixture(
        approved_root / f"ui-stepwise-{tmp_path.name}.h5ad"
    )
    user_id = f"workspace-stepwise-{tmp_path.name}".replace("_", "-")
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", user_id)
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=30)

    assert all(button.label != "Data & Preview" for button in app.button)
    app.session_state.workspace_task_handoff = {
        "handoff_id": "workspace-test-handoff",
        "conversation_id": "conversation-test",
        "source_query": "请生成 Scrublet workflow",
        "task_family": "doublet_detection",
        "tool_name": "Scrublet",
        "agent_mode": "PLAN",
        "notebook_strategy": "fixed_shadow",
        "stepwise_preview_available": True,
    }
    app.session_state.current_view = "data_preview"
    app.run(timeout=30)
    _text_input(app, "workspace_local_path").input(str(source)).run(timeout=30)
    _button(app, "workspace_register_artifact").click().run(timeout=30)
    _button(app, "workspace_authorize").click().run(timeout=30)
    _button(app, "workspace_profile_button").click().run(timeout=30)
    _button(app, "workspace_preview_button").click().run(timeout=30)

    assert len(app.exception) == 0
    visible = "\n".join(item.value for item in app.markdown)
    captions = "\n".join(item.value for item in app.caption)
    assert "Stepwise Analysis" in visible
    assert "来自当前 Research Chat" in visible
    assert "参数来自 Scrublet 0.2.3 ToolContract" in captions
    assert "workspace_notebook" not in app.session_state
    notebook_button = _button(app, "workspace_notebook_button")
    assert notebook_button.label == "生成可交互分析 Notebook"
    assert "workspace_preview_run_result" not in app.session_state


def test_stepwise_requires_path_reauthorization_before_profile(
    tmp_path, monkeypatch
):
    approved_root = PROJECT_ROOT / ".sckg_exec" / "approved-inputs"
    source = _write_smoke_fixture(
        approved_root / f"ui-reauthorize-{tmp_path.name}.h5ad"
    )
    user_id = f"workspace-reauthorize-{tmp_path.name}".replace("_", "-")
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", user_id)
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    from execution.execution_ui_service import build_execution_ui_service

    service = build_execution_ui_service()
    record = service.register_local_artifact(
        user_id=user_id,
        local_path=str(source),
    )
    service.data_registry._resolved_paths.clear()
    service.data_registry._hash_cache.clear()

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=30)
    app.session_state.workspace_task_handoff = {
        "handoff_id": "reauthorize-handoff",
        "conversation_id": "conversation-test",
        "source_query": "请生成 Scrublet workflow",
        "task_family": "doublet_detection",
        "tool_name": "Scrublet",
        "agent_mode": "PLAN",
        "notebook_strategy": "fixed_shadow",
        "stepwise_preview_available": True,
    }
    app.session_state.workspace_artifact_id = record.artifact_id
    app.session_state.current_view = "data_preview"
    app.run(timeout=30)

    assert len(app.exception) == 0
    assert _button(app, "workspace_authorize").disabled is True
    assert _button(app, "workspace_profile_button").disabled is True
    warnings = "\n".join(item.value for item in app.warning)
    assert "应用重启后不会持久化完整本地路径" in warnings


def _button(app: AppTest, key: str):
    return next(item for item in app.button if item.key == key)


def _text_input(app: AppTest, key: str):
    return next(item for item in app.text_input if item.key == key)
