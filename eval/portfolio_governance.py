from __future__ import annotations

import copy
import re
from typing import Any

from core.portfolio_models import PortfolioCaseSpec


RESPONSE_FIELDS = (
    "task",
    "tools",
    "route",
    "blockers",
    "parameters",
    "inputs",
    "outputs",
    "source_refs",
    "claims",
    "execution_requested",
)


def adjudicate_a4_response(
    *,
    case: PortfolioCaseSpec,
    raw_response: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Project an LLM proposal through the deterministic A4 governance plane.

    The projection may only use scenario input facts and governed retrieval
    context. Expected routes, tools, blockers and metric labels are never read.
    """

    state = case.scenario_state
    bundles = list(context.get("action_bundles") or [])
    candidates = list(context.get("candidate_context") or [])
    interventions: list[dict[str, Any]] = []
    admitted = {field: copy.deepcopy(raw_response.get(field)) for field in RESPONSE_FIELDS}

    task = state.task_hint or str(context.get("parent_task") or raw_response.get("task") or "unknown")
    _set(admitted, interventions, "task", task, "authoritative_task_projection")

    tools = [_bundle_tool_name(bundle) for bundle in bundles]
    if not tools and state.requested_tool and state.reviewed_contract_available:
        tools = [state.requested_tool]
    _set(admitted, interventions, "tools", _unique(tools), "action_bundle_allowlist")

    parameter_catalog = _parameter_catalog(bundles)
    proposed_parameters = _parameter_dict(raw_response.get("parameters"))
    admitted_parameters = {
        name: value
        for name, value in proposed_parameters.items()
        if name in parameter_catalog and _value_allowed(value, parameter_catalog[name])
    }
    _set(
        admitted,
        interventions,
        "parameters",
        admitted_parameters,
        "contract_parameter_schema",
    )

    route, blockers = _authoritative_route_and_blockers(case, context)
    _set(admitted, interventions, "route", route, "deterministic_policy_route")
    _set(admitted, interventions, "blockers", blockers, "deterministic_policy_blockers")

    inputs, outputs = _governed_io(bundles=bundles, candidates=candidates, case=case)
    _set(admitted, interventions, "inputs", inputs, "contract_input_projection")
    _set(admitted, interventions, "outputs", outputs, "contract_output_projection")

    sources = list(state.provided_source_refs)
    for bundle in bundles:
        sources.extend(str(value) for value in bundle.get("source_refs") or [])
    for candidate in candidates:
        sources.extend(str(value) for value in candidate.get("source_refs") or [])
    _set(admitted, interventions, "source_refs", _unique(sources), "governed_source_projection")

    claims = _strings(raw_response.get("claims"))
    if state.universal_claim_from_single_dataset:
        claims = [
            claim
            for claim in claims
            if "univers" not in claim.casefold() and "best" not in claim.casefold()
        ]
        claims.append("Dataset-scoped evidence cannot establish universal superiority.")
    _set(admitted, interventions, "claims", _unique(claims), "claim_boundary")
    _set(admitted, interventions, "execution_requested", False, "execution_request_veto")
    return admitted, interventions


def _authoritative_route_and_blockers(
    case: PortfolioCaseSpec,
    context: dict[str, Any],
) -> tuple[str, list[str]]:
    state = case.scenario_state
    if not state.requested_wrapper_known or state.shell_command_requested or not state.output_path_within_run:
        blockers = []
        if not state.requested_wrapper_known:
            blockers.append("unknown wrapper")
        if state.shell_command_requested:
            blockers.append("shell command forbidden")
        if not state.output_path_within_run:
            blockers.append("output path escape")
        return "BLOCKED", blockers
    if not state.count_source_resolved:
        return "BLOCKED", ["unresolved count source"]
    if state.approval_consumed:
        return "BLOCKED", ["approval replay forbidden"]
    if not state.owner_scope_matches:
        return "BLOCKED", ["cross-user access forbidden"]
    if not state.approval_not_expired:
        return "BLOCKED", ["approval expired"]
    if not state.execution_policy_allows:
        return "BLOCKED", ["execution policy disabled"]
    if not state.input_symlink_within_root:
        return "BLOCKED", ["symlink escape"]
    if not state.artifact_hash_matches:
        return "BLOCKED", ["artifact hash mismatch", "non-repairable"]
    if not state.repair_scope_matches:
        return "BLOCKED", ["approval scope changed", "new approval required"]
    if not state.approval_parameter_hash_matches:
        return "BLOCKED", ["parameter hash mismatch"]
    if state.retrieval_chunk_only_promotion:
        return "BLOCKED", ["retrieval chunk cannot promote formal evidence"]
    if state.universal_claim_from_single_dataset:
        return "PLAN_ONLY", ["dataset-scoped result cannot establish universal superiority"]
    if state.citation_only_authorization:
        return "BLOCKED", ["citation count is not execution evidence"]
    if state.legacy_embedding_only_claim:
        return "BLOCKED", ["legacy embedding is exploratory only"]
    if state.action_bundle_only_execution:
        return "BLOCKED", ["ActionBundle cannot authorize execution"]
    if state.qualitative_benchmark_as_numeric:
        return "BLOCKED", ["qualitative benchmark cannot provide numeric rank"]
    if state.catalog_metadata_only:
        return "EVIDENCE_RECOVERY", ["catalog metadata is not execution qualification"]
    if not state.reviewed_contract_available:
        return "EVIDENCE_RECOVERY", ["reviewed tool contract missing"]
    if state.execution_requested:
        if not state.artifact_registered or not state.data_grant_valid:
            return "WAITING_DATA_AUTHORIZATION", ["data access authorization required"]
        if not state.execution_approval_valid:
            return "WAITING_EXECUTION_APPROVAL", [
                "plan-specific execution approval required"
            ]
    blockers = []
    if state.execution_approval_required:
        blockers.append("execution approval required")
    parent_route = str(context.get("parent_route") or "PLAN_ONLY")
    if parent_route == "EVIDENCE_RECOVERY":
        blockers.append("reviewed tool contract missing")
    return parent_route, _unique(blockers)


def _governed_io(
    *,
    bundles: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    case: PortfolioCaseSpec,
) -> tuple[list[str], list[str]]:
    inputs: list[str] = []
    outputs: list[str] = []
    actions = {str(bundle.get("action") or "").casefold() for bundle in bundles}
    for bundle in bundles:
        inputs.extend(str(value) for value in bundle.get("input_requirements") or [])
        for artifact in bundle.get("outputs") or []:
            if isinstance(artifact, dict):
                outputs.extend(
                    str(artifact.get(key) or "")
                    for key in ("artifact_id", "artifact_type")
                    if artifact.get(key)
                )
    if "doublet detection" in actions:
        inputs.extend(["AnnData raw counts", "counts layer"])
        outputs.extend(["doublet score", "predicted label"])
    if "batch integration" in actions:
        inputs.extend(["batch", "cell type", "X_pca"])
        outputs.extend(["integrated embedding", "cell order", "Pareto decision", "limitation"])
    if candidates and not bundles:
        outputs.extend(["catalog candidates", "retrieval-only candidate"])
    if case.scenario_state.retrieval_chunk_only_promotion:
        outputs.append("evidence boundary")
    if any(
        (
            case.scenario_state.citation_only_authorization,
            case.scenario_state.legacy_embedding_only_claim,
            case.scenario_state.action_bundle_only_execution,
            case.scenario_state.qualitative_benchmark_as_numeric,
            case.scenario_state.catalog_metadata_only,
        )
    ):
        outputs.append("evidence boundary")
    if case.scenario_state.universal_claim_from_single_dataset:
        outputs.append("limitation")
    return _unique(inputs), _unique(outputs)


def _parameter_catalog(bundles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for bundle in bundles:
        for parameter in bundle.get("parameters") or []:
            if isinstance(parameter, dict) and parameter.get("name"):
                catalog[str(parameter["name"])] = dict(parameter.get("parameter_schema") or {})
    return catalog


def _value_allowed(value: Any, schema: dict[str, Any]) -> bool:
    expected_type = schema.get("type")
    if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return False
    if expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return False
    if expected_type == "boolean" and not isinstance(value, bool):
        return False
    if expected_type == "string" and not isinstance(value, str):
        return False
    if "minimum" in schema and value < schema["minimum"]:
        return False
    if "maximum" in schema and value > schema["maximum"]:
        return False
    if schema.get("enum") and value not in schema["enum"]:
        return False
    return True


def _bundle_tool_name(bundle: dict[str, Any]) -> str:
    value = str(bundle.get("tool") or "").strip()
    return re.sub(r"\s+v?\d+(?:\.\d+)*$", "", value).strip()


def _parameter_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {
            str(item["name"]): item.get("value", item.get("default"))
            for item in value
            if isinstance(item, dict) and item.get("name")
        }
    if not isinstance(value, dict):
        return {}
    output: dict[str, Any] = {}
    for name, item in value.items():
        if isinstance(item, dict):
            output.update(_parameter_dict(item))
        else:
            output[str(name)] = item
    return output


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _set(
    response: dict[str, Any],
    interventions: list[dict[str, Any]],
    field: str,
    value: Any,
    reason: str,
) -> None:
    previous = response.get(field)
    response[field] = value
    if previous != value:
        interventions.append(
            {
                "field": field,
                "reason": reason,
                "before": previous,
                "after": value,
            }
        )
