from datetime import datetime, timedelta, timezone

from execution.user_workspace import RetentionPolicy, UserWorkspaceService


def test_retention_deletes_artifacts_but_keeps_audit_and_original_input(tmp_path):
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    old = now - timedelta(days=10)
    original = tmp_path / "approved" / "input.h5ad"
    original.parent.mkdir()
    original.write_bytes(b"original-user-data")
    workspace = UserWorkspaceService(
        root=tmp_path / "users",
        retention_policy=RetentionPolicy(
            run_artifact_ttl=timedelta(days=1),
            package_ttl=timedelta(days=1),
        ),
    )
    run_dir = workspace.create_run_directory(
        user_id="user-a", run_id="run-old", now=old
    )
    package_dir = workspace.create_package_directory(
        user_id="user-a", package_id="package-old", now=old
    )
    (run_dir / "result.tsv").write_text("result", encoding="utf-8")
    manifest = workspace.write_package_manifest(
        user_id="user-a",
        package_id="package-old",
        artifact_id="data-a",
        input_hash="a" * 64,
        plan_id="plan-a",
    )
    assert str(original) not in manifest.read_text(encoding="utf-8")
    workspace.mark_completed(
        resource_type="run", user_id="user-a", resource_id="run-old", now=old
    )
    workspace.mark_completed(
        resource_type="package",
        user_id="user-a",
        resource_id="package-old",
        now=old,
    )

    deleted = workspace.apply_retention(now=now)

    assert deleted == ["package-old", "run-old"]
    assert not run_dir.exists() and not package_dir.exists()
    assert original.read_bytes() == b"original-user-data"
    audit = tmp_path / "users" / "user-a" / "audit" / "resources.jsonl"
    assert audit.is_file()
    assert "retention_deleted" in audit.read_text(encoding="utf-8")
