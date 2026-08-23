import ast
from pathlib import Path

from core.tool_contract_registry import ToolContractRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.wrapper_registry import WrapperRegistry


def test_batch_wrappers_are_fixed_allowlisted_modules():
    registry = WrapperRegistry()
    harmony = registry.get("harmony_v2_0_0")
    scanorama = registry.get("scanorama_v1_7_4")

    assert harmony.environment_id == scanorama.environment_id == "sckg-batch-cpu"
    assert harmony.command()[-1] == "worker_request.json"
    assert scanorama.command()[-1] == "worker_request.json"
    root = Path(__file__).resolve().parents[1]
    for path in (
        root / "execution" / "wrappers" / "harmony.py",
        root / "execution" / "wrappers" / "scanorama.py",
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, (ast.Import, ast.ImportFrom))
            and any(alias.name in {"subprocess", "os.system"} for alias in node.names)
            for node in ast.walk(tree)
        )


def test_batch_contracts_bind_scientific_pilot_qualified_environment():
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    environment = environments.get("sckg-batch-cpu")

    assert environment.import_smoke_passed is True
    assert environment.integration_test_passed is True
    assert environment.enabled_for_execution is True
    for name, version in (("Harmony", "2.0.0"), ("Scanorama", "1.7.4")):
        contract = contracts.load(name, version)
        assert contract.environment_id == "sckg-batch-cpu"
        assert contract.wrapper_status == "smoke_passed"
        assert contract.execution_status == "integration_passed"
        assert contract.scientific_validation_status == "scientific_pilot"
        assert contract.enabled_for_execution is True
        assert contracts.planning_gate(contract).allowed is True
        assert contracts.execution_gate(contract).allowed is True
