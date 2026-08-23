import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from multiprocessing import get_context
from pathlib import Path

from execution.runtime_pack_manager import RuntimePackManager
from tests.runtime_pack_helpers import FakePackCommandRunner, build_test_registry


def _mark_pack_used_in_process(
    manifest_root: str,
    asset_root: str,
    public_key_path: str,
    signature_root: str,
    home: str,
    second: int,
) -> None:
    from execution.runtime_pack_registry import RuntimePackRegistry

    manager = RuntimePackManager(
        registry=RuntimePackRegistry(
            manifest_root=manifest_root,
            asset_root=asset_root,
            public_key_path=public_key_path,
            signature_root=signature_root,
        ),
        home=Path(home),
        disk_safety_margin_bytes=0,
    )
    manager.mark_used(
        "test-pack",
        now=datetime(2026, 8, 12, 8, 0, second, tzinfo=timezone.utc),
    )


def test_missing_pack_never_installs_before_exact_approval(tmp_path):
    runner = FakePackCommandRunner()
    manager = RuntimePackManager(
        registry=build_test_registry(tmp_path),
        home=tmp_path / "home",
        command_runner=runner,
        disk_safety_margin_bytes=0,
    )
    assert manager.probe("test-pack").state == "missing"
    plan = manager.create_plan(pack_id="test-pack", user_id="user-a")
    assert runner.commands == []
    assert plan.approval_required is True
    assert plan.blockers == []

    approval = manager.approvals.approve(
        plan_id=plan.plan_id,
        user_id="user-a",
        confirmation_text=manager.approvals.confirmation_text(plan),
    )
    record = manager.provision(
        plan_id=plan.plan_id,
        approval_id=approval.approval_id,
    )
    assert record.state == "ready"
    assert record.lock_hashes_verified is True
    assert record.smoke_passed is True
    assert manager.probe("test-pack").ready
    assert all("shell" not in command for command in runner.commands)


def test_pack_quota_and_digest_mismatch_block_installation(tmp_path):
    registry = build_test_registry(tmp_path)
    manager = RuntimePackManager(
        registry=registry,
        home=tmp_path / "quota-home",
        disk_quota_bytes=1024,
        disk_safety_margin_bytes=0,
    )
    plan = manager.create_plan(pack_id="test-pack", user_id="user-a")
    assert "runtime_pack_disk_quota_exceeded" in plan.blockers

    manager = RuntimePackManager(
        registry=registry,
        home=tmp_path / "digest-home",
        command_runner=FakePackCommandRunner(),
        disk_safety_margin_bytes=0,
    )
    plan = manager.create_plan(pack_id="test-pack", user_id="user-a")
    approval = manager.approvals.approve(
        plan_id=plan.plan_id,
        user_id="user-a",
        confirmation_text=manager.approvals.confirmation_text(plan),
    )
    registry.lock_path(registry.get("test-pack").lock_files[0]).write_text(
        "tampered\n", encoding="utf-8"
    )
    record = manager.provision(plan_id=plan.plan_id, approval_id=approval.approval_id)
    assert record.state == "failed"
    assert record.smoke_passed is False


def test_install_cancellation_is_audited_without_running_commands(tmp_path):
    runner = FakePackCommandRunner()
    manager = RuntimePackManager(
        registry=build_test_registry(tmp_path),
        home=tmp_path / "cancel-home",
        command_runner=runner,
        allow_legacy_environments=False,
        disk_safety_margin_bytes=0,
    )
    plan = manager.create_plan(pack_id="test-pack", user_id="user-a")
    approval = manager.approvals.approve(
        plan_id=plan.plan_id,
        user_id="user-a",
        confirmation_text=manager.approvals.confirmation_text(plan),
    )
    record = manager.provision(
        plan_id=plan.plan_id,
        approval_id=approval.approval_id,
        cancellation_check=lambda: True,
    )
    assert record.state == "failed"
    assert record.error_code == "RuntimePackInstallationCancelled"
    assert runner.commands == []
    assert record.elapsed_ms >= 0


def test_clean_manager_never_probes_legacy_conda_prefix(tmp_path):
    registry = build_test_registry(tmp_path)
    legacy = tmp_path / "legacy"
    executable = legacy / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)

    manager = RuntimePackManager(
        registry=registry,
        home=tmp_path / "clean-home",
        allow_legacy_environments=False,
        disk_safety_margin_bytes=0,
    )
    manager._legacy_prefix = lambda manifest: legacy
    assert manager.probe("test-pack").state == "missing"


def test_concurrent_usage_updates_use_unique_atomic_temp_files(tmp_path):
    registry = build_test_registry(tmp_path)
    home = tmp_path / "shared-home"
    managers = [
        RuntimePackManager(
            registry=registry,
            home=home,
            disk_safety_margin_bytes=0,
        )
        for _ in range(8)
    ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(
                manager.mark_used,
                "test-pack",
                now=datetime(2026, 8, 12, 8, 0, index, tzinfo=timezone.utc),
            )
            for index, manager in enumerate(managers)
        ]
        for future in futures:
            future.result()

    usage = json.loads(managers[0].usage_path.read_text(encoding="utf-8"))
    assert set(usage) == {"test-pack"}
    assert not list(managers[0].usage_path.parent.glob(".usage.json.*.tmp"))


def test_cross_process_usage_updates_do_not_race(tmp_path):
    registry = build_test_registry(tmp_path)
    home = tmp_path / "process-shared-home"
    context = get_context("spawn")
    processes = [
        context.Process(
            target=_mark_pack_used_in_process,
            args=(
                str(registry.manifest_root),
                str(registry.asset_root),
                str(registry.public_key_path),
                str(registry.signature_root),
                str(home),
                index,
            ),
        )
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    usage_path = home / "registry/runtime-packs/usage.json"
    assert set(json.loads(usage_path.read_text(encoding="utf-8"))) == {"test-pack"}
    assert not list(usage_path.parent.glob(".usage.json.*.tmp"))
