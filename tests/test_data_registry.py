from pathlib import Path

import pytest

from execution.data_registry import DataRegistry
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_data_registry_persists_only_redacted_metadata_and_no_copy(tmp_path):
    approved = tmp_path / "approved"
    source = write_phase1_fixtures(approved)["raw_x"]
    registry_root = tmp_path / "registry"
    registry = DataRegistry(
        approved_input_roots=[approved], registry_root=registry_root
    )

    record = registry.register(user_id="user-a", path=source)

    assert record.owner_user_id == "user-a"
    assert record.artifact_type == "AnnData"
    assert record.redacted_path == ".../raw_counts_x.h5ad"
    assert registry.resolve_path(record.artifact_id, user_id="user-a") == source.resolve()
    persisted = (registry_root / "artifacts.jsonl").read_text(encoding="utf-8")
    assert str(source.resolve()) not in persisted
    assert list(registry_root.rglob("*.h5ad")) == []
    with pytest.raises(PermissionError, match="cross-user"):
        registry.get(record.artifact_id, user_id="user-b")


def test_data_registry_blocks_traversal_symlink_escape_and_unsupported_files(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = write_phase1_fixtures(tmp_path / "outside")["raw_x"]
    registry = DataRegistry(
        approved_input_roots=[approved], registry_root=tmp_path / "registry"
    )

    with pytest.raises(ValueError, match="traversal"):
        registry.register(
            user_id="user-a", path=approved / ".." / "outside" / outside.name
        )
    symlink = approved / "escape.h5ad"
    symlink.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        registry.register(user_id="user-a", path=symlink)
    text = approved / "notes.txt"
    text.write_text("not supported", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        registry.register(user_id="user-a", path=text)


def test_data_registry_explicit_reregistration_restores_path_without_duplicate(tmp_path):
    approved = tmp_path / "approved"
    source = write_phase1_fixtures(approved)["raw_x"]
    registry_root = tmp_path / "registry"
    first_registry = DataRegistry(
        approved_input_roots=[approved], registry_root=registry_root
    )
    original = first_registry.register(user_id="user-a", path=source)
    assert first_registry.path_authorized(
        original.artifact_id, user_id="user-a"
    ) is True

    restarted_registry = DataRegistry(
        approved_input_roots=[approved], registry_root=registry_root
    )
    with pytest.raises(RuntimeError, match="re-authorized"):
        restarted_registry.resolve_path(original.artifact_id, user_id="user-a")
    assert restarted_registry.path_authorized(
        original.artifact_id, user_id="user-a"
    ) is False

    restored = restarted_registry.register(user_id="user-a", path=source)

    assert restored.artifact_id == original.artifact_id
    assert restarted_registry.resolve_path(
        restored.artifact_id, user_id="user-a"
    ) == source.resolve()
    assert restarted_registry.path_authorized(
        restored.artifact_id, user_id="user-a"
    ) is True
    assert len((registry_root / "artifacts.jsonl").read_text().splitlines()) == 1
