import pytest

from execution.user_workspace import UserWorkspaceService


def test_user_run_package_ownership_and_cancellation_are_isolated(tmp_path):
    workspace = UserWorkspaceService(root=tmp_path / "users")
    run_dir = workspace.create_run_directory(user_id="user-b", run_id="run-b")
    package_dir = workspace.create_package_directory(
        user_id="user-b", package_id="package-b"
    )
    assert run_dir == tmp_path / "users" / "user-b" / "runs" / "run-b"
    assert package_dir == tmp_path / "users" / "user-b" / "packages" / "package-b"

    workspace.mark_run_running(user_id="user-b", run_id="run-b")
    cancelled = workspace.request_cancellation(user_id="user-b", run_id="run-b")
    assert cancelled.status == "cancellation_requested"
    assert cancelled.cancellation_requested_at is not None
    with pytest.raises(PermissionError, match="cross-user"):
        workspace.get_run_directory(user_id="user-a", run_id="run-b")
    with pytest.raises(PermissionError, match="cross-user"):
        workspace.get_package_directory(user_id="user-a", package_id="package-b")
    with pytest.raises(PermissionError, match="cross-user"):
        workspace.create_run_directory(user_id="user-a", run_id="run-b")

    audit = (tmp_path / "users" / "user-b" / "audit" / "resources.jsonl").read_text()
    assert str(tmp_path) not in audit
    assert "run_cancellation_requested" in audit

    restarted = UserWorkspaceService(root=tmp_path / "users")
    assert restarted.get_run_directory(user_id="user-b", run_id="run-b") == run_dir
    with pytest.raises(PermissionError, match="cross-user"):
        restarted.get_package_directory(user_id="user-a", package_id="package-b")
