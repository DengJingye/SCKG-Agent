from copy import deepcopy

from core.execution_models import ToolContract
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from execution.environment_registry import EnvironmentRegistry
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_scrublet_contract_is_qualified_for_restricted_execution_policy():
    environments = EnvironmentRegistry()
    registry = ToolContractRegistry(environment_registry=environments)
    contract = registry.load("scrublet", "0.2.3")

    planning = registry.planning_gate(contract)
    execution = registry.execution_gate(contract)

    assert planning.allowed is True
    assert planning.reasons == []
    assert contract.enabled_for_execution is True
    assert contract.source_review_status == "reviewed"
    assert contract.execution_critical_fields_reviewed is True
    assert contract.execution_status == "integration_passed"
    assert contract.wrapper_status == "smoke_passed"
    assert contract.environment_status == "smoke_passed"
    assert execution.allowed is True
    assert execution.reasons == []


def test_contract_registry_resolves_sources_and_environment():
    registry = ToolContractRegistry(environment_registry=EnvironmentRegistry())
    contracts = registry.load_all()

    assert [contract.contract_id for contract in contracts] == [
        "celltypist:1.7.1",
        "harmony:2.0.0",
        "scanorama:1.7.4",
        "scdblfinder:1.24.0",
        "scrublet:0.2.3",
        "singler:2.14.0",
    ]
    assert all(registry.planning_gate(contract).allowed for contract in contracts)


def test_annotation_contracts_are_planning_only_and_execution_blocked():
    registry = ToolContractRegistry(environment_registry=EnvironmentRegistry())

    for tool_name, version in (("CellTypist", "1.7.1"), ("SingleR", "2.14.0")):
        contract = registry.load(tool_name, version)
        planning = registry.planning_gate(contract)
        execution = registry.execution_gate(contract)

        assert planning.allowed is True
        assert execution.allowed is False
        assert contract.enabled_for_execution is False
        assert contract.wrapper_status == "implemented"
        assert contract.source_review_status == "reviewed"
        assert contract.execution_critical_fields_reviewed is True
        assert contract.execution_status == "untested"
        assert contract.scientific_validation_status == "not_evaluated"


def test_scdblfinder_contract_is_qualified_for_restricted_execution_policy():
    registry = ToolContractRegistry(environment_registry=EnvironmentRegistry())
    contract = registry.load("scDblFinder", "1.24.0")
    gate = registry.execution_gate(contract)

    assert contract.tool_version == "1.24.0"
    assert contract.wrapper_status == "smoke_passed"
    assert contract.environment_status == "smoke_passed"
    assert contract.execution_status == "integration_passed"
    assert contract.scientific_validation_status == "scientific_pilot"
    assert contract.enabled_for_execution is True
    assert gate.allowed is True
    assert gate.reasons == []


def test_execution_gate_closes_when_contract_flag_is_disabled():
    registry = ToolContractRegistry(environment_registry=EnvironmentRegistry())
    contract = registry.load("scrublet", "0.2.3")
    payload = deepcopy(contract.model_dump())
    payload["enabled_for_execution"] = False
    modified = ToolContract.model_validate(payload)
    gate = registry.execution_gate(modified)

    assert gate.allowed is False
    assert gate.reasons == ["contract_execution_disabled"]


def test_scrublet_preconditions_use_data_profile(tmp_path):
    fixtures = write_phase1_fixtures(tmp_path)
    profiler = AnnDataProfiler()
    raw_profile = profiler.profile(fixtures["raw_x"])
    scaled_profile = profiler.profile(fixtures["scaled"])
    registry = ToolContractRegistry(environment_registry=EnvironmentRegistry())
    contract = registry.load("scrublet", "0.2.3")

    raw_gate = registry.planning_gate(contract, data_profile=raw_profile)
    scaled_gate = registry.planning_gate(contract, data_profile=scaled_profile)

    assert raw_gate.allowed is True
    assert scaled_gate.allowed is False
    assert "precondition_failed:scrublet_counts_required" in scaled_gate.reasons
    assert any(reason.startswith("data_profile_blocked:") for reason in scaled_gate.reasons)
