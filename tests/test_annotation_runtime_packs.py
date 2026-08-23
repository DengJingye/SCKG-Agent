from __future__ import annotations

from collections import namedtuple
from pathlib import Path

from execution.runtime_pack_manager import (
    DISK_SAFETY_MARGIN_BYTES,
    RuntimePackManager,
)
from execution.runtime_pack_registry import RuntimePackRegistry


def test_annotation_runtime_manifests_are_signed_and_digest_bound():
    registry = RuntimePackRegistry()
    python_pack = registry.get("annotation-python")
    r_pack = registry.get("annotation-r")

    assert registry.validate_assets(python_pack) == []
    assert registry.validate_assets(r_pack) == []
    assert registry.verify_signature(
        registry.manifest_root / "annotation-python.json"
    )
    assert registry.verify_signature(registry.manifest_root / "annotation-r.json")
    assert python_pack.supported_tools[0].tool_version == "1.7.1"
    assert r_pack.supported_tools[0].tool_version == "2.14.0"
    assert {item.kind for item in r_pack.lock_files} == {
        "conda_explicit",
        "r_source_requirements",
    }


def test_annotation_pack_requires_six_gib_post_install_reserve(tmp_path, monkeypatch):
    usage = namedtuple("usage", "total used free")
    registry = RuntimePackRegistry()
    manifest = registry.get("annotation-python")
    insufficient = manifest.estimated_installed_size_bytes + DISK_SAFETY_MARGIN_BYTES - 1
    monkeypatch.setattr(
        "execution.runtime_pack_manager.shutil.disk_usage",
        lambda _path: usage(insufficient * 2, insufficient, insufficient),
    )
    manager = RuntimePackManager(
        registry=registry,
        home=tmp_path / "home",
        allow_legacy_environments=False,
        disk_quota_bytes=20 * 1024**3,
    )

    plan = manager.create_plan(pack_id="annotation-python", user_id="maintainer")
    assert "runtime_pack_insufficient_disk" in plan.blockers


def test_singler_install_plan_uses_only_digest_pinned_r_source(tmp_path):
    manager = RuntimePackManager(
        home=tmp_path / "home",
        allow_legacy_environments=False,
    )
    manifest = manager.registry.get("annotation-r")
    commands = manager._install_commands(manifest, Path("/usr/bin/conda"))
    source_commands = [command for command in commands if "INSTALL" in command]

    assert len(source_commands) == 1
    assert source_commands[0][1:3] == ["CMD", "INSTALL"]
    assert source_commands[0][-1].endswith(
        "7999102dc8a83154b39f8fce37cb18880135cc315278288fb8c293a982125744.tar.gz"
    )
    assert all(command != ["sh"] for command in commands)
