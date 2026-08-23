import hashlib

import pytest

from tests.runtime_pack_helpers import build_test_registry


def test_registry_maps_tool_environment_and_detects_lock_tampering(tmp_path):
    registry = build_test_registry(tmp_path)
    manifest = registry.get("test-pack")
    assert registry.for_tool("TestTool", "1.0.0").pack_id == "test-pack"
    assert registry.for_environment("test-environment").pack_id == "test-pack"
    assert registry.validate_assets(manifest) == []

    lock = registry.lock_path(manifest.lock_files[0])
    lock.write_text("@EXPLICIT\n# changed\n", encoding="utf-8")
    assert registry.validate_assets(manifest) == [
        "lock_digest_mismatch:locks/osx-arm64/test-pack.conda-explicit.txt"
    ]
    assert hashlib.sha256(lock.read_bytes()).hexdigest() != manifest.lock_files[0].sha256


def test_registry_rejects_unknown_pack(tmp_path):
    registry = build_test_registry(tmp_path)
    with pytest.raises(KeyError, match="not registered"):
        registry.get("unknown")


def test_registry_rejects_unsigned_manifest_change(tmp_path):
    registry = build_test_registry(tmp_path)
    manifest_path = registry.manifest_root / "test-pack.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace("Test Pack", "Changed Pack"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="signature invalid"):
        registry.get("test-pack")
