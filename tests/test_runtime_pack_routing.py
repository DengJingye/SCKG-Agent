from core.deterministic_router import DeterministicRouter, RouterRoute
from execution.runtime_pack_manager import RuntimePackManager
from tests.runtime_pack_helpers import build_test_registry
from tests.execution_ui_helpers import build_ui_harness, prepare_context


def test_missing_runtime_requires_environment_approval_and_parent_cannot_override(tmp_path):
    manager = RuntimePackManager(
        registry=build_test_registry(tmp_path), home=tmp_path / "home"
    )
    decision = DeterministicRouter().route_runtime_pack(
        probe=manager.probe("test-pack"),
        parent_route_override=RouterRoute.RESTRICTED_USER_EXECUTION,
    )
    assert decision.route == RouterRoute.WAITING_ENVIRONMENT_APPROVAL
    assert decision.execution_allowed is False
    assert decision.parent_override_ignored is True


def test_dry_run_plan_survives_when_runtime_pack_is_not_installed(tmp_path, monkeypatch):
    harness = build_ui_harness(tmp_path)
    manager = RuntimePackManager(home=tmp_path / "empty-sckg-home")
    monkeypatch.setattr(manager, "_legacy_prefix", lambda manifest: None)
    harness.service.runtime_pack_manager = manager

    _, context = prepare_context(harness)

    assert context.profile is not None
    assert context.plan is not None
    assert context.plan.plan_status == "dry_run"
    assert context.runtime_route == "WAITING_ENVIRONMENT_APPROVAL"
    assert "runtime_pack_missing" in context.button_blockers
    assert context.button_enabled is False
    assert not list((tmp_path / "users").glob("*/runs/*"))
