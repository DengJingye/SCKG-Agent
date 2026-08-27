import json

import pytest

from core.capability_pack_models import (
    CapabilityPackManifest,
    CapabilityReadiness,
    RepresentationDefinition,
    RepresentationRequirement,
    compatibility_check,
)
from core.capability_pack_registry import CapabilityPackRegistry
from core.research_workspace_models import StepContract


def test_scanpy_pack_is_discoverable_but_not_execution_eligible():
    registry = CapabilityPackRegistry()
    manifest = registry.load("scanpy_core", "1.0.0")
    gate = registry.gate(manifest)
    contracts = registry.load_step_contracts(manifest)

    assert gate.passed is True
    assert gate.content_digest_valid is True
    assert CapabilityReadiness.DISCOVERED in gate.readiness
    assert CapabilityReadiness.PLANNING_READY in gate.readiness
    assert CapabilityReadiness.NOTEBOOK_READY in gate.readiness
    assert CapabilityReadiness.VALIDATION_READY in gate.readiness
    assert CapabilityReadiness.QUALIFICATION_PASSED not in gate.readiness
    assert gate.execution_eligible is False
    assert len(contracts) == len(manifest.methods)
    assert all(item.schema_version == "sckg-step-contract-v2" for item in contracts.values())
    marker = contracts["scanpy_core.rank_markers"]
    assert {item.representation_id for item in marker.consumes} == {
        "log1p_normalized",
        "cluster_labels",
    }
    assert "scaled_hvg" in marker.invalid_predecessors


def test_mock_r_pack_proves_non_python_binding_without_execution():
    registry = CapabilityPackRegistry()
    manifest = registry.load("mock_r_capability", "1.0.0")
    gate = registry.gate(manifest)
    discovery = registry.discover(capability_id="mock_r.transform")

    assert manifest.execution_adapters[0].runtime_kind == "rscript"
    assert gate.passed is True
    assert CapabilityReadiness.VALIDATION_READY in gate.readiness
    assert gate.execution_eligible is False
    assert discovery[0].method_ids == ["mock_r.identity"]
    assert discovery[0].execution_eligible is False


def test_registration_rejects_digest_drift_and_unknown_cross_reference():
    registry = CapabilityPackRegistry()
    manifest = registry.load("scanpy_core", "1.0.0")
    drifted = manifest.model_copy(update={"content_digest": "f" * 64})
    assert "capability_pack_digest_mismatch" in registry.gate(drifted).blockers

    payload = manifest.model_dump(mode="json")
    payload["methods"][0]["produces"][0]["representation_id"] = "missing_state"
    payload["content_digest"] = "f" * 64
    invalid = CapabilityPackManifest.model_validate(payload)
    blockers = registry.gate(invalid).blockers
    assert any(item.startswith("unknown_produced_representation") for item in blockers)


def test_compatibility_checks_structure_science_provenance_and_hashes():
    producer = RepresentationDefinition(
        representation_id="log1p_normalized",
        kind="expression_matrix",
        schema_version="1.0",
        axes=["cell", "gene"],
        value_state="nonnegative_continuous",
        required_provenance=["log1p"],
        require_cell_hash=True,
        require_gene_hash=True,
        scientific_constraints=["full_gene_unscaled_log1p"],
    )
    consumer = RepresentationRequirement(
        representation_id="log1p_normalized",
        accepted_schema_versions=["1.0"],
        accepted_value_states=["nonnegative_continuous"],
        required_provenance=["log1p"],
        require_cell_hash=True,
        require_gene_hash=True,
        required_metadata=["full_gene_matrix"],
        scientific_requirements=["full_gene_unscaled_log1p"],
    )
    blocked = compatibility_check(
        producer=producer,
        consumer=consumer,
        producer_provenance=["log1p"],
        producer_cell_hash="cell-a",
        consumer_cell_hash="cell-b",
        producer_gene_hash="gene-a",
        consumer_gene_hash="gene-a",
        producer_metadata={},
    )
    assert blocked.structural_compatible is True
    assert blocked.scientific_compatible is False
    assert blocked.hash_compatible is False
    assert "required_scientific_metadata_missing" in blocked.blocking_reasons
    assert "cell_index_hash_mismatch" in blocked.blocking_reasons

    allowed = compatibility_check(
        producer=producer,
        consumer=consumer,
        producer_provenance=["log1p"],
        producer_cell_hash="cell-a",
        consumer_cell_hash="cell-a",
        producer_gene_hash="gene-a",
        consumer_gene_hash="gene-a",
        producer_metadata={"full_gene_matrix": True},
    )
    assert allowed.blocking_reasons == []


def test_v1_step_contract_remains_backward_compatible():
    from execution.notebook_shadow import scrublet_step_contract

    step = scrublet_step_contract()
    restored = StepContract.model_validate_json(step.model_dump_json())
    assert restored.schema_version == "sckg-step-contract-v1"
    assert restored.step_id == "doublet.scrublet.preview"
    assert restored.consumes == []


def test_v2_step_contract_requires_typed_transition_bindings():
    with pytest.raises(ValueError, match="typed consumes and produces"):
        StepContract(
            schema_version="sckg-step-contract-v2",
            step_id="bad.step",
            step_version="1.0",
            task_family="test",
            capability_id="test.capability",
            method_id="test.method",
            operation="bad",
            tool_contract_id="test:1",
            tool_contract_version="1",
            requires_object_type="Table",
            requires_matrix_state="table",
            parameters={},
            input_artifacts=[],
            output_artifacts=[],
            validators=["schema"],
            template_digest="0" * 64,
        )
