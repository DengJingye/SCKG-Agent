from __future__ import annotations

import pytest

from execution.annotation_reference_registry import AnnotationReferenceRegistry
from execution.wrapper_registry import WrapperDefinition
from execution.wrappers.celltypist import validate_parameters as validate_celltypist
from execution.wrappers.singler import validate_parameters as validate_singler
from tests.annotation_helpers import build_reference


def test_annotation_reference_registry_verifies_assets_and_tool_binding(tmp_path):
    root = tmp_path / "manifests"
    root.mkdir()
    reference = build_reference(tmp_path / "assets")
    (root / f"{reference.reference_id}.json").write_text(
        reference.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    registry = AnnotationReferenceRegistry(root=root)

    loaded = registry.get(reference.reference_id, expected_tool="CellTypist")
    assert loaded.sha256 == reference.sha256
    assert registry.validate_assets(loaded) == []
    with pytest.raises(ValueError, match="tool mismatch"):
        registry.get(reference.reference_id, expected_tool="SingleR")


def test_celltypist_parameters_are_fixed_to_contract_boundary():
    default = validate_celltypist({})
    assert default["model"] == "celltypist-immune-all-low-v1"
    assert default["use_GPU"] is False
    assert validate_celltypist({"mode": "prob match", "p_thres": 0.7})[
        "p_thres"
    ] == 0.7
    with pytest.raises(ValueError, match="unknown CellTypist"):
        validate_celltypist({"shell": "rm -rf /"})
    with pytest.raises(ValueError, match="outside contract"):
        validate_celltypist({"p_thres": 1.2})
    with pytest.raises(ValueError, match="not qualified"):
        validate_celltypist({"use_GPU": True})


def test_singler_parameters_reject_dynamic_code_and_invalid_values():
    default = validate_singler({})
    assert default["reference_id"] == "singler-immune-reference-v1"
    assert default["prune"] is True
    assert validate_singler({"de_method": "wilcox"})["de_method"] == "wilcox"
    with pytest.raises(ValueError, match="unknown SingleR"):
        validate_singler({"command": "system('whoami')"})
    with pytest.raises(ValueError, match="outside contract"):
        validate_singler({"de_method": "custom"})
    with pytest.raises(ValueError, match="must be boolean"):
        validate_singler({"prune": "yes"})


def test_singler_adapter_requires_both_python_and_r_runtime_packs():
    resolver = _FakeResolver({"annotation-python": True, "annotation-r": False})
    definition = WrapperDefinition(
        wrapper_id="singler_v2_14_0",
        environment_id="annotation-r",
        tool_name="SingleR",
        tool_version="2.14.0",
        module="execution.wrappers.singler",
        runtime_pack_id="annotation-python",
        additional_runtime_pack_ids=("annotation-r",),
        resolver=resolver,
    )
    assert definition.is_runtime_ready() is False
    resolver.states["annotation-r"] = True
    assert definition.is_runtime_ready() is True


class _FakeResolver:
    def __init__(self, states):
        self.states = states

    def ready(self, pack_id):
        return self.states.get(pack_id, False)
