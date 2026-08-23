import hashlib
import pytest
from pydantic import ValidationError

from pathlib import Path

from core.runtime_pack_models import ControlPlaneReleaseManifest, RuntimeLockFile
from core.settings import PROJECT_ROOT


def test_runtime_lock_rejects_traversal_and_absolute_paths():
    for path in ("../escape.lock", "/tmp/escape.lock"):
        with pytest.raises(ValidationError):
            RuntimeLockFile(path=path, kind="conda_explicit", sha256="0" * 64)


def test_versioned_runtime_manifests_have_valid_lock_digests():
    from execution.runtime_pack_registry import RuntimePackRegistry

    registry = RuntimePackRegistry()
    manifests = registry.load_all()
    assert {item.pack_id for item in manifests} == {
        "batch-cpu",
        "annotation-python",
        "annotation-r",
        "doublet-python",
        "doublet-r",
    }
    assert all(not registry.validate_assets(item) for item in manifests)


def test_control_plane_manifest_uses_pinned_reviewed_assets():
    manifest = ControlPlaneReleaseManifest.model_validate_json(
        (PROJECT_ROOT / "release" / "control-plane-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest.release_status == "release_candidate"
    assert manifest.platform == "osx-arm64"
    assert "/latest" not in manifest.micromamba.url
    assert manifest.micromamba.version in manifest.micromamba.url
    assert len(manifest.lock_files) == 2
    for lock in manifest.lock_files:
        path = PROJECT_ROOT / Path(lock.path)
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == lock.sha256


def test_batch_pack_declares_all_no_deps_scanorama_requirements():
    requirements = (
        PROJECT_ROOT
        / "runtime_packs"
        / "locks"
        / "osx-arm64"
        / "batch-cpu.pip-requirements.txt"
    ).read_text(encoding="utf-8")
    for package in (
        "fbpca==",
        "geosketch==",
        "harmonypy==",
        "intervaltree==",
        "scanorama==",
        "sortedcontainers==",
    ):
        assert package in requirements
