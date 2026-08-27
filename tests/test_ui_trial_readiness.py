from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.settings import PROJECT_ROOT
from observability.dashboard.services import AgentLoopDemoService, DefenseDemoService
from observability.dashboard.ui_presenters import (
    format_conversation_title,
    normalize_ui_status,
)


def test_recent_conversation_titles_are_readable_and_css_forbids_character_wrap():
    assert format_conversation_title("a" * 24, "a" * 24) == "Chat aaaaaaaa"
    title = format_conversation_title("A very long research conversation " * 3, "session", limit=34)
    assert len(title) <= 34
    assert title.endswith("...")
    source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    assert "white-space: nowrap !important" in source
    assert "text-overflow: ellipsis !important" in source
    assert "overflow-wrap: normal !important" in source
    assert source.index("nav_groups = [") < source.index('if st.button("+ New chat"')
    assert "Product shell v2" in source
    assert "workflow-stepper" in source
    assert "_invisible_widget_key" not in source
    assert "More actions for chat" in source
    assert "st.session_state.messages[:-1]" in source
    assert 'context_pack.get("conversation_state")' in source
    assert "用模拟数据在 JupyterLab 试跑" in source
    assert "workspace_pending_selected_artifact" in source
    assert "更新 Notebook（包含新版诊断图）" in source
    assert "关联我的 .h5ad" in source
    assert "1. 确认并批准当前 Preview" in source
    assert "2. 运行并验证 Preview" in source
    assert "_backend_implementation_digest" in source
    assert '"core/capability_workspace_models.py"' in source
    assert '"core/execution_models.py"' in source
    assert '"engine/data_profiler.py"' in source
    assert '"execution/renderers/scanpy_core.py"' in source
    assert "_cached_preview_execution_backend" in source
    assert "execution_service.approve_local_preview" in source
    assert "APPROVE PREVIEW" in source
    assert "在浏览器 Notebook 中逐步分析" in source
    assert "启动本地 JupyterLab" in source
    assert "打开 JupyterLab 工作区" in source
    assert "下载完整 Notebook bundle (.zip)" in source
    assert "需要审计记录时，使用受控验证运行" in source
    assert "workspace_start_jupyter" in source
    assert "_preview_execution_backend.clear()" in source


def test_status_labels_are_consistent():
    assert normalize_ui_status("dry_run") == "READY"
    assert normalize_ui_status("running") == "RUNNING"
    assert normalize_ui_status("succeeded") == "COMPLETED"
    assert normalize_ui_status("stale") == "STALE"
    assert normalize_ui_status("blocked") == "BLOCKED"
    assert normalize_ui_status("timeout") == "FAILED"


def test_primary_navigation_and_three_demo_cases_render_without_execution(tmp_path, monkeypatch):
    demo_root = tmp_path / "demos"
    _write_demo_bundle(demo_root)
    _write_agent_loop_bundle(demo_root)
    monkeypatch.setenv("SCKG_DEFENSE_DEMO_ROOT", str(demo_root))
    monkeypatch.setenv("SCKG_AGENT_LOOP_DEMO_ROOT", str(demo_root))
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", "ui-trial-render")
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    user_root = PROJECT_ROOT / ".sckg_exec" / "users" / "ui-trial-render"
    before = list(user_root.rglob("execution_run.json")) if user_root.exists() else []

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run(timeout=30)
    assert len(app.exception) == 0
    labels = {button.label for button in app.button}
    assert "Research Workspace" in labels
    assert "Runs & Results" in labels
    assert "Graph Explorer" in labels
    assert "Legacy Agent Baseline" in labels
    assert "Defense Demo" in labels

    next(
        button for button in app.button if button.label == "Legacy Agent Baseline"
    ).click().run(timeout=30)
    assert len(app.exception) == 0
    agent_rendered = "\n".join(item.value for item in app.markdown)
    assert "Generic governed plan" in agent_rendered
    assert "Evidence-limited task" in agent_rendered
    assert str(tmp_path) not in agent_rendered
    assert any(button.label == "Run plan-only Agent" for button in app.button)
    next(button for button in app.button if button.label == "Run plan-only Agent").click().run(
        timeout=30
    )
    assert len(app.exception) == 0
    assert any(
        metric.label == "Execution requests" and metric.value == "0"
        for metric in app.metric
    )

    next(button for button in app.button if button.label == "Defense Demo").click().run(timeout=30)

    next(button for button in app.button if button.label == "Defense Demo").click().run(timeout=30)
    assert len(app.exception) == 0
    rendered = "\n".join(item.value for item in app.markdown)
    assert "Successful execution" in rendered
    assert "Bounded repair" in rendered
    assert "Correctly blocked" in rendered
    assert str(tmp_path) not in rendered
    after = list(user_root.rglob("execution_run.json")) if user_root.exists() else []
    assert after == before


def test_demo_service_has_clear_empty_state_contract(tmp_path):
    assert DefenseDemoService(tmp_path / "missing").latest_bundle() == {}
    assert AgentLoopDemoService(tmp_path / "missing").latest_bundle() == {}


def test_graph_explorer_is_a_standalone_primary_page():
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run(timeout=30)
    next(button for button in app.button if button.label == "Graph Explorer").click().run(
        timeout=30
    )

    assert len(app.exception) == 0
    rendered = "\n".join(item.value for item in app.markdown)
    assert "Graph Explorer" in rendered
    assert "1,847" in rendered
    graph_control = next(radio for radio in app.radio if radio.label == "Graph view")
    assert graph_control.value == "Decision network"
    assert set(graph_control.options) == {
        "Decision network",
        "Catalog landscape",
        "Tool neighborhood",
        "Catalog search",
    }


def test_knowledge_review_contains_governed_agent_context_without_graph_canvas():
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run(timeout=30)
    next(button for button in app.button if button.label == "Knowledge Review").click().run(
        timeout=30
    )

    assert len(app.exception) == 0
    rendered = "\n".join(item.value for item in app.markdown)
    assert "Knowledge Review" in rendered
    assert "Catalog tools" in rendered
    assert "Catalog categories" in rendered
    assert "Discovered task labels" in rendered
    assert "Qualified tasks" in rendered
    assert "Decision-ready tools" in rendered
    assert [tab.label for tab in app.tabs] == [
        "Action Space",
        "Tool Dossier",
        "Governance",
    ]
    assert not any(radio.label == "Graph view" for radio in app.radio)


def test_demo_page_shows_clear_message_when_bundle_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SCKG_DEFENSE_DEMO_ROOT", str(tmp_path / "missing"))
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", "ui-trial-empty-demo")
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run(timeout=30)
    next(button for button in app.button if button.label == "Defense Demo").click().run(timeout=30)
    assert len(app.exception) == 0
    warnings = "\n".join(item.value for item in app.warning)
    assert "No complete Phase 6 defense demo bundle was found" in warnings


def test_trial_runner_maintainer_rehearsal_is_anonymous_and_does_not_execute(
    tmp_path, monkeypatch
):
    demo_root = tmp_path / "demos"
    _write_demo_bundle(demo_root)
    session_path = tmp_path / "telemetry" / "sessions.jsonl"
    task_path = tmp_path / "telemetry" / "task_results.jsonl"
    feedback_path = tmp_path / "telemetry" / "feedback.jsonl"
    monkeypatch.setenv("SCKG_DEFENSE_DEMO_ROOT", str(demo_root))
    monkeypatch.setenv("SCKG_PHASE6_TRIAL_SESSIONS", str(session_path))
    monkeypatch.setenv("SCKG_PHASE6_TRIAL_TASK_RESULTS", str(task_path))
    monkeypatch.setenv("SCKG_PHASE6_TRIAL_FEEDBACK", str(feedback_path))
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", "trial-rehearsal-test")
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    user_root = PROJECT_ROOT / ".sckg_exec" / "users" / "trial-rehearsal-test"
    before = list(user_root.rglob("execution_run.json")) if user_root.exists() else []

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run(timeout=30)
    next(button for button in app.button if button.label == "Defense Demo").click().run(
        timeout=30
    )
    assert len(app.exception) == 0
    assert not session_path.exists()
    assert not task_path.exists()
    assert any(tab.label == "Trial Task Runner" for tab in app.tabs)
    assert any(tab.label == "Trial Summary" for tab in app.tabs)

    next(
        button for button in app.button if button.label == "Start maintainer rehearsal"
    ).click().run(timeout=30)
    assert len(app.exception) == 0
    session = json.loads(session_path.read_text(encoding="utf-8").splitlines()[-1])
    assert session["actor_type"] == "maintainer_rehearsal"
    assert session["participant_id"].startswith("trial-")
    assert session["execution_request_count"] == 0

    next(button for button in app.button if button.label == "Start task timer").click().run(
        timeout=30
    )
    next(
        button
        for button in app.button
        if button.label == "Show expected answer (counts as help)"
    ).click().run(timeout=30)
    result = json.loads(task_path.read_text(encoding="utf-8").splitlines()[-1])
    assert result["help_count"] == 1
    assert not {"query", "raw_path", "matrix", "barcodes"} & set(result)
    after = list(user_root.rglob("execution_run.json")) if user_root.exists() else []
    assert after == before


def test_task_bank_has_ten_complete_schema_records():
    payload = json.loads(
        (PROJECT_ROOT / "eval" / "phase6" / "group_trial_task_bank.json").read_text(
            encoding="utf-8"
        )
    )
    required = {
        "task_id",
        "instruction",
        "expected_answer",
        "completion",
        "time_seconds",
        "help_count",
        "critical_error",
        "observer_notes",
    }
    assert payload["trial_status"] == "not_started"
    assert len(payload["tasks"]) == 10
    assert len({row["task_id"] for row in payload["tasks"]}) == 10
    assert all(required <= set(row) for row in payload["tasks"])
    assert payload["levels"]["level_1"]["real_execution"] is False
    assert payload["levels"]["level_2"]["user_data_required"] is False


def _write_demo_bundle(root: Path) -> None:
    bundle = root / "phase6-defense-20990101T000000"
    bundle.mkdir(parents=True)
    values = {
        "demo_summary.json": {
            "status": "passed",
            "synthetic_fixture": True,
            "user_data_used": False,
        },
        "success_case.json": {
            "passed": True,
            "execution_request_count": 2,
            "validation_passed": True,
            "recommended_candidate_id": "Scrublet:0.2.3:test",
            "package_complete": True,
        },
        "repair_case.json": {
            "passed": True,
            "repair_reason": "invalid_n_prin_comps",
            "changed_fields": ["n_prin_comps"],
            "validation_passed_after_repair": True,
            "parent_run_id": "parent-run",
            "new_run_id": "repair-run",
            "package_complete": True,
        },
        "blocked_case.json": {
            "passed": True,
            "blocking_reasons": ["approval_scope_or_fingerprint_mismatch"],
            "execution_request_count": 0,
            "unsafe_execution_count": 0,
        },
        "trace_audit.json": {
            "applicable_stage_completeness": 1.0,
            "cases": [
                {
                    "case_id": name,
                    "applicable_stage_completeness": 1.0,
                    "observed_stages": [{"stage": "audit", "status": "passed"}],
                    "missing_stages": [],
                    "violations": {},
                }
                for name in ["success_case", "repair_case", "blocked_case"]
            ],
        },
    }
    for name, value in values.items():
        (bundle / name).write_text(json.dumps(value), encoding="utf-8")


def _write_agent_loop_bundle(root: Path) -> None:
    bundle = root / "agent-loop-20990101T000000"
    bundle.mkdir(parents=True)
    summary = {
        "status": "passed",
        "architecture": "bounded centralized Parent Agent",
        "llm_mode": "offline deterministic parser",
        "tool_call_count": 12,
        "execution_request_count": 0,
        "evidence_boundary_violations": 0,
        "limitations": ["Synthetic planning demo only."],
    }
    (bundle / "agent_loop_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    for name, status, route in [
        ("generic_plan", "READY", "PLAN_ONLY"),
        ("authorization_blocked", "WAITING", "WAITING_DATA_AUTHORIZATION"),
        ("data_aware_waiting_approval", "WAITING", "WAITING_EXECUTION_APPROVAL"),
        ("evidence_limited", "BLOCKED", "EVIDENCE_RECOVERY"),
    ]:
        payload = {
            "status": status,
            "route": route,
            "final_summary": f"{name} summary",
            "selected_tool": "Scrublet" if name != "evidence_limited" else None,
            "candidate_context": [
                {"tool_name": "Scrublet", "candidate_basis": "execution_verified", "graph_score": 2.3}
            ],
            "workflow_plan": {"plan_status": "dry_run", "steps": [{"node_id": "validate"}]}
            if name in {"generic_plan", "data_aware_waiting_approval"}
            else None,
            "data_profile": {"selected_count_source": "X"}
            if name == "data_aware_waiting_approval"
            else None,
            "tool_calls": [
                {
                    "stage": "knowledge",
                    "capability": "evidence_graph_query.rank_tools",
                    "status": "completed",
                    "elapsed_ms": 1.0,
                }
            ],
            "blockers": [],
            "next_actions": [],
            "execution_request_count": 0,
        }
        (bundle / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
