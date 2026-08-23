from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_runtime_pack_page_is_discoverable_and_rendering_does_not_install(monkeypatch, tmp_path):
    monkeypatch.setenv("SCKG_HOME", str(tmp_path / "sckg-home"))
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    before = list((tmp_path / "sckg-home").rglob("pack-install-*.json"))
    app = AppTest.from_file(str(app_path)).run(timeout=30)
    button = next(item for item in app.button if item.label == "Runtime Packs")
    button.click().run(timeout=30)

    assert len(app.exception) == 0
    assert any(item.label == "Runtime Pack" for item in app.selectbox)
    assert any(
        item.label == "直接体验 Scrublet Preview" for item in app.button
    )
    assert list((tmp_path / "sckg-home").rglob("pack-install-*.json")) == before


def test_runtime_page_uses_reviewed_plan_not_free_form_command():
    app_text = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )
    assert "Prepare reviewed installation plan" in app_text
    assert "Advanced immutable command preview" in app_text
    assert "0 B 下载" in app_text
    assert "run_shell" not in app_text


def test_ready_scrublet_demo_routes_to_stepwise_without_installing(monkeypatch, tmp_path):
    monkeypatch.setenv("SCKG_HOME", str(tmp_path / "sckg-home"))
    monkeypatch.setenv("SCKG_EXECUTION_POLICY", "disabled")
    monkeypatch.setenv("SCKG_LOCAL_USER_ID", f"runtime-demo-{tmp_path.name}")
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    before = list((tmp_path / "sckg-home").rglob("pack-install-*.json"))
    app = AppTest.from_file(str(app_path)).run(timeout=30)
    next(item for item in app.button if item.label == "Runtime Packs").click().run(
        timeout=30
    )
    demo_button = next(
        item for item in app.button if item.key == "runtime_quick_scrublet_demo"
    )
    if demo_button.disabled:
        # A clean CI host may not have the optional Scrublet environment.
        assert "Scrublet Runtime Pack" in "\n".join(
            item.value for item in app.warning
        )
        return

    demo_button.click().run(timeout=30)

    assert len(app.exception) == 0
    assert app.session_state.current_view == "data_preview"
    assert (
        app.session_state.workspace_selected_artifact
        == app.session_state.workspace_artifact_id
    )
    assert "workspace_pending_selected_artifact" not in app.session_state
    assert app.session_state.workspace_task_handoff["tool_name"] == "Scrublet"
    assert (
        app.session_state.workspace_task_handoff["fixture_type"]
        == "synthetic_engineering_demo"
    )
    assert "workspace_preview_run_result" not in app.session_state
    assert list((tmp_path / "sckg-home").rglob("pack-install-*.json")) == before

    next(item for item in app.button if item.key == "workspace_authorize").click().run(
        timeout=30
    )
    next(
        item for item in app.button if item.key == "workspace_profile_button"
    ).click().run(timeout=30)
    next(
        item for item in app.button if item.key == "workspace_preview_button"
    ).click().run(timeout=30)
    next(
        item for item in app.button if item.key == "workspace_notebook_button"
    ).click().run(timeout=30)
    next(
        item for item in app.toggle if item.key == "workspace_show_preview_run"
    ).set_value(True).run(timeout=30)

    scope_confirmation = next(
        item
        for item in app.checkbox
        if item.key == "workspace_preview_scope_confirmation"
    )
    scope_confirmation.check().run(timeout=30)
    approve = next(
        item for item in app.button if item.key == "workspace_preview_approval_button"
    )
    assert approve.label == "1. 确认并批准当前 Preview"
    assert approve.disabled is False
    approve.click().run(timeout=30)

    assert len(app.exception) == 0
    run_confirmation = next(
        item
        for item in app.checkbox
        if item.key == "workspace_preview_run_confirmation"
    )
    run_confirmation.check().run(timeout=30)
    run_button = next(
        item for item in app.button if item.key == "workspace_preview_run_button"
    )
    assert run_button.label == "2. 运行并验证 Preview"
    assert run_button.disabled is False
    assert "workspace_preview_run_result" not in app.session_state
    assert list((tmp_path / "sckg-home").rglob("pack-install-*.json")) == before
