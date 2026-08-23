from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.model_pack_models import ModelPackState
from execution.model_pack_manager import ModelPackManager


def _manager(tmp_path: Path) -> ModelPackManager:
    with patch("execution.model_pack_manager.platform.machine", return_value="arm64"):
        return ModelPackManager(home=tmp_path / "sckg-home")


def test_bge_m3_plan_is_pinned_and_requires_separate_approval(tmp_path):
    manager = _manager(tmp_path)
    with patch("execution.model_pack_manager.platform.machine", return_value="arm64"):
        plan = manager.create_plan()

    assert plan.state == ModelPackState.WAITING_APPROVAL
    assert plan.model_id == "BAAI/bge-m3"
    assert len(plan.revision) == 40
    assert plan.minimum_free_space_bytes == 8 * 1024**3
    assert plan.install_root_redacted.startswith("<SCKG_HOME>/")
    assert all(isinstance(argv, list) for argv in plan.command_preview)
    assert not any("shell" in token for argv in plan.command_preview for token in argv)


def test_model_pack_approval_is_plan_bound_and_not_replayable(tmp_path):
    manager = _manager(tmp_path)
    with (
        patch("execution.model_pack_manager.platform.machine", return_value="arm64"),
        patch(
            "execution.model_pack_manager.shutil.disk_usage",
            return_value=SimpleNamespace(free=20 * 1024**3),
        ),
    ):
        plan = manager.create_plan()
    approval = manager.approve(plan)
    manager._validate_approval(plan, approval)

    approval.consumed_at = approval.approved_at
    with pytest.raises(PermissionError, match="model_pack_approval_replayed"):
        manager._validate_approval(plan, approval)

    approval.consumed_at = None
    approval.expires_at = approval.approved_at - timedelta(seconds=1)
    with pytest.raises(PermissionError, match="model_pack_approval_expired"):
        manager._validate_approval(plan, approval)


def test_stale_model_pack_metadata_is_never_ready(tmp_path):
    manager = _manager(tmp_path)
    manager.environment_root.joinpath("bin").mkdir(parents=True)
    manager.python_executable.write_text("", encoding="utf-8")
    manager.snapshot_root.mkdir(parents=True)
    manager.snapshot_root.joinpath("config.json").write_text("{}", encoding="utf-8")
    manager.metadata_path.write_text(
        '{"manifest_digest":"stale","revision":"stale","snapshot_digest":"'
        + "0" * 64
        + '"}',
        encoding="utf-8",
    )

    with patch("execution.model_pack_manager.platform.machine", return_value="arm64"):
        probe = manager.probe()

    assert probe.state == ModelPackState.MISSING
    assert "model_pack_metadata_or_assets_stale" in probe.warnings
