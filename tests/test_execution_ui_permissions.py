from types import SimpleNamespace

import pytest

from tests.execution_ui_helpers import build_ui_harness, prepare_context


def test_non_allowlisted_and_cross_user_access_are_blocked(tmp_path):
    harness = build_ui_harness(tmp_path, allow_user=False)
    _, context = prepare_context(harness)

    assert context.allowlisted is False
    assert context.button_enabled is False
    assert "local_user_not_allowlisted" in context.button_blockers
    assert harness.service.list_artifacts(user_id="user-b") == []
    with pytest.raises(PermissionError, match="cross-user"):
        harness.registry.get(harness.artifact.artifact_id, user_id="user-b")
    with pytest.raises(PermissionError, match="cross-user"):
        harness.service.result_view(
            user_id="user-b", result=SimpleNamespace(user_id="user-a")
        )


def test_ui_redaction_hides_full_paths_and_secrets(tmp_path):
    harness = build_ui_harness(tmp_path)
    input_path = harness.registry.resolve_path(
        harness.artifact.artifact_id, user_id="user-a"
    )
    redacted_path = harness.service.redact_path(str(input_path))
    redacted_error = harness.service.redact_text(
        f"failed while reading {input_path}"
    )

    assert str(input_path) not in redacted_path
    assert str(input_path.parent) not in redacted_error
    assert input_path.name in redacted_path
    assert ".env" not in redacted_error
