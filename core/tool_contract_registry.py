from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional, TYPE_CHECKING

from core.execution_models import (
    DataProfile,
    ExecutionGateResult,
    PlanningGateResult,
    ToolContract,
)
from core.settings import PROJECT_ROOT

if TYPE_CHECKING:
    from execution.environment_registry import EnvironmentRegistry


DEFAULT_CONTRACT_ROOT = PROJECT_ROOT / "contracts" / "tools"


class ToolContractRegistry:
    def __init__(
        self,
        root: Path = DEFAULT_CONTRACT_ROOT,
        *,
        environment_registry: Optional["EnvironmentRegistry"] = None,
    ) -> None:
        self.root = Path(root)
        self.environment_registry = environment_registry

    def load(self, tool_name: str, tool_version: str) -> ToolContract:
        path = self.root / tool_name.casefold() / f"{tool_version}.json"
        if not path.is_file():
            raise FileNotFoundError(f"tool contract not found: {path}")
        contract = ToolContract.model_validate_json(path.read_text(encoding="utf-8"))
        if contract.tool_name.casefold() != tool_name.casefold():
            raise ValueError(f"contract tool mismatch: expected {tool_name}, got {contract.tool_name}")
        if contract.tool_version != tool_version:
            raise ValueError(
                f"contract version mismatch: expected {tool_version}, got {contract.tool_version}"
            )
        return contract

    def load_path(self, path: Path) -> ToolContract:
        return ToolContract.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def load_all(self) -> list[ToolContract]:
        if not self.root.exists():
            return []
        return [self.load_path(path) for path in sorted(self.root.glob("*/*.json"))]

    def planning_gate(
        self,
        contract: ToolContract,
        *,
        data_profile: Optional[DataProfile] = None,
    ) -> PlanningGateResult:
        reasons: list[str] = []
        if contract.schema_status != "valid":
            reasons.append(f"schema_status_not_valid:{contract.schema_status}")
        if contract.source_review_status not in {"partial", "reviewed"}:
            reasons.append(f"source_review_status_insufficient:{contract.source_review_status}")
        if not contract.wrapper_id.strip():
            reasons.append("wrapper_id_missing")
        reasons.extend(_parameter_schema_issues(contract))
        reasons.extend(self._source_ref_issues(contract.source_refs))
        if not contract.output_artifacts:
            reasons.append("output_artifacts_missing")
        elif any(not artifact.validator_id.strip() for artifact in contract.output_artifacts):
            reasons.append("output_artifact_validator_missing")
        if self.environment_registry is not None:
            if not self.environment_registry.contains(contract.environment_id):
                reasons.append(f"environment_not_registered:{contract.environment_id}")
            else:
                environment = self.environment_registry.get(contract.environment_id)
                runtime_version = environment.package_versions.get(contract.tool_name.casefold())
                if runtime_version != contract.tool_version:
                    reasons.append(
                        "tool_runtime_version_mismatch:"
                        f"contract={contract.tool_version},environment={runtime_version or 'missing'}"
                    )
        if data_profile is not None:
            reasons.extend(_data_profile_issues(contract, data_profile))
        return PlanningGateResult(
            allowed=not reasons,
            contract_id=contract.contract_id,
            reasons=sorted(set(reasons)),
        )

    def execution_gate(self, contract: ToolContract) -> ExecutionGateResult:
        reasons = list(self.planning_gate(contract).reasons)
        if contract.source_review_status != "reviewed":
            reasons.append("source_review_status_not_reviewed")
        if not contract.execution_critical_fields_reviewed:
            reasons.append("execution_critical_fields_not_reviewed")
        if contract.wrapper_status != "smoke_passed":
            reasons.append(f"wrapper_smoke_not_passed:{contract.wrapper_status}")
        if contract.environment_status != "smoke_passed":
            reasons.append(f"contract_environment_smoke_not_passed:{contract.environment_status}")
        if contract.execution_status != "integration_passed":
            reasons.append(f"execution_integration_not_passed:{contract.execution_status}")
        if not contract.enabled_for_execution:
            reasons.append("contract_execution_disabled")
        if self.environment_registry is not None:
            environment = self.environment_registry.get(contract.environment_id)
            if environment.qualification_status != "integration_passed":
                reasons.append(
                    f"environment_not_integration_passed:{environment.qualification_status}"
                )
            if not environment.integration_test_passed:
                reasons.append("environment_integration_test_not_passed")
            if not environment.enabled_for_execution:
                reasons.append("environment_execution_disabled")
        return ExecutionGateResult(
            allowed=not reasons,
            contract_id=contract.contract_id,
            reasons=sorted(set(reasons)),
        )

    def validate_parameters(
        self,
        contract: ToolContract,
        parameters: dict[str, object],
    ) -> dict[str, object]:
        properties = contract.parameter_schema.get("properties") or {}
        unknown = sorted(set(parameters) - set(properties))
        if unknown:
            raise ValueError("unknown parameters: " + ", ".join(unknown))
        merged: dict[str, object] = dict(contract.default_parameters)
        merged.update(parameters)
        issues: list[str] = []
        for name, value in merged.items():
            field_schema = properties.get(name)
            if not isinstance(field_schema, dict):
                issues.append(f"parameter_not_declared:{name}")
                continue
            issues.extend(_value_issues(name, value, field_schema))
        if issues:
            raise ValueError("invalid parameters: " + ", ".join(sorted(set(issues))))
        return merged

    def _source_ref_issues(self, refs: Iterable[str]) -> list[str]:
        refs = list(refs)
        if not refs:
            return ["source_refs_missing"]
        issues: list[str] = []
        for ref in refs:
            if ref.startswith(("http://", "https://", "doi:")):
                continue
            path = Path(ref)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if not path.is_file():
                issues.append(f"source_ref_unresolved:{ref}")
        return issues


def _parameter_schema_issues(contract: ToolContract) -> list[str]:
    schema = contract.parameter_schema
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        return ["parameter_schema_invalid"]
    issues: list[str] = []
    properties = schema["properties"]
    for name, value in contract.default_parameters.items():
        field_schema = properties.get(name)
        if not isinstance(field_schema, dict):
            issues.append(f"default_parameter_not_declared:{name}")
            continue
        issues.extend(_value_issues(name, value, field_schema))
    for name, bounds in contract.searchable_parameters.items():
        field_schema = properties.get(name)
        if not isinstance(field_schema, dict):
            issues.append(f"searchable_parameter_not_declared:{name}")
            continue
        if not isinstance(bounds, dict):
            issues.append(f"searchable_parameter_bounds_invalid:{name}")
            continue
        lower = bounds.get("minimum")
        upper = bounds.get("maximum")
        if lower is not None and upper is not None and lower > upper:
            issues.append(f"searchable_parameter_range_reversed:{name}")
        schema_lower = field_schema.get("minimum")
        schema_upper = field_schema.get("maximum")
        if lower is not None and schema_lower is not None and lower < schema_lower:
            issues.append(f"searchable_parameter_below_schema:{name}")
        if upper is not None and schema_upper is not None and upper > schema_upper:
            issues.append(f"searchable_parameter_above_schema:{name}")
    return issues


def _data_profile_issues(contract: ToolContract, profile: DataProfile) -> list[str]:
    issues: list[str] = []
    if profile.object_type != contract.input_object:
        issues.append(
            f"input_object_mismatch:contract={contract.input_object},profile={profile.object_type}"
        )
    if profile.blocking_errors:
        issues.extend(f"data_profile_blocked:{reason}" for reason in profile.blocking_errors)
    profiles = {item.matrix_id: item for item in profile.matrix_profiles}
    for rule in contract.preconditions:
        if rule.field == "selected_count_source" and rule.operator == "matrix_state":
            selected = profiles.get(profile.selected_count_source or "")
            if selected is None or selected.inferred_state != rule.expected:
                issues.append(f"precondition_failed:{rule.rule_id}")
        elif rule.field == "matrix_shape" and rule.operator == "gte":
            selected = profiles.get(profile.selected_count_source or "")
            expected = int(rule.expected)
            if selected is None or min(selected.shape) < expected:
                issues.append(f"precondition_failed:{rule.rule_id}")
    return issues


def _value_issues(name: str, value: object, schema: dict[str, object]) -> list[str]:
    expected = schema.get("type")
    valid_type = {
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "string": isinstance(value, str),
    }.get(str(expected), True)
    issues: list[str] = []
    if not valid_type:
        issues.append(f"default_parameter_type_invalid:{name}")
        return issues
    allowed_values = schema.get("enum")
    if isinstance(allowed_values, list) and value not in allowed_values:
        issues.append(f"default_parameter_enum_invalid:{name}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        lower = schema.get("minimum")
        upper = schema.get("maximum")
        if isinstance(lower, (int, float)) and value < lower:
            issues.append(f"default_parameter_below_minimum:{name}")
        if isinstance(upper, (int, float)) and value > upper:
            issues.append(f"default_parameter_above_maximum:{name}")
    return issues
