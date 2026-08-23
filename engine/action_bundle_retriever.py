from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Optional

from core.action_space_models import ActionBundle, ActionBundleSet, ActionParameter
from core.execution_models import DataProfile, ToolContract
from core.kg_ontology import normalize_modality, normalize_task
from core.tool_contract_registry import ToolContractRegistry
from engine.decision_graph_query import DecisionGraphQuery
from execution.environment_registry import EnvironmentRegistry


class ActionBundleRetriever:
    """Compile governed graph paths into deterministic planning context."""

    def __init__(
        self,
        *,
        graph_query: DecisionGraphQuery,
        contract_registry: Optional[ToolContractRegistry] = None,
        environment_registry: Optional[EnvironmentRegistry] = None,
    ) -> None:
        self.graph_query = graph_query
        self.environment_registry = environment_registry or EnvironmentRegistry()
        self.contract_registry = contract_registry or ToolContractRegistry(
            environment_registry=self.environment_registry
        )

    def retrieve(
        self,
        *,
        task: str,
        modality: str,
        data_profile: Optional[DataProfile] = None,
        requested_tool: Optional[str] = None,
        source_limit: int = 6,
    ) -> ActionBundleSet:
        task_term = normalize_task(task)
        modality_term = normalize_modality(modality)
        candidates = self.graph_query.find_tools(task_term.label)
        contracts = self._contracts_by_tool(task_term.canonical_id)
        bundles: list[ActionBundle] = []
        missing_contracts: list[str] = []
        for candidate in candidates:
            if requested_tool and candidate.tool_name.casefold() != requested_tool.casefold():
                continue
            contract = contracts.get(candidate.tool_name.casefold())
            if contract is None:
                missing_contracts.append(candidate.tool_name)
                continue
            dossier = self.graph_query.tool_dossier(candidate.tool_name)
            planning_gate = self.contract_registry.planning_gate(
                contract, data_profile=data_profile
            )
            execution_gate = self.contract_registry.execution_gate(contract)
            compatibility = (
                "generic"
                if data_profile is None
                else "compatible"
                if planning_gate.allowed
                else "blocked"
            )
            action = dossier.actions[0] if dossier.actions else None
            action_id = str(
                (action or {}).get("node_id")
                or f"action:{task_term.canonical_id.replace('_', '-')}"
            )
            action_name = str((action or {}).get("label") or task_term.label)
            provenance_refs = sorted(
                {
                    *contract.source_refs,
                    *_provenance(dossier.contracts),
                    *_provenance(dossier.source_material),
                    *_provenance(dossier.evaluations),
                    *_provenance(dossier.know_how),
                }
            )
            profile_identity = (
                data_profile.file_hash or data_profile.profile_id
                if data_profile is not None
                else "generic"
            )
            bundle_id = _stable_id(
                "action-bundle",
                action_id,
                contract.contract_id,
                contract.contract_version,
                profile_identity,
            )
            limitations = sorted(
                {
                    *dossier.limitations,
                    *(f"Unsupported by contract: {value}" for value in contract.not_supported),
                    (
                        "Scientific evaluation is dataset-scoped and cannot establish universal superiority."
                    ),
                }
            )
            warnings = [
                "ActionBundle is planning context and cannot authorize an ExecutionRequest.",
                "Retrieved source chunks remain evidence-discovery context only.",
            ]
            if not dossier.source_material:
                warnings.append(
                    "No indexed full-text source chunk is linked; reviewed contract sources remain the execution authority."
                )
            score = _score(
                readiness=candidate.readiness,
                compatibility=compatibility,
                source_count=len(dossier.source_material),
                evaluation_available=bool(dossier.evaluations),
            )
            bundles.append(
                ActionBundle(
                    bundle_id=bundle_id,
                    action_id=action_id,
                    action_name=action_name,
                    task=task_term.label,
                    modality=modality_term.label,
                    tool_name=contract.tool_name,
                    tool_version=contract.tool_version,
                    contract_id=contract.contract_id,
                    contract_version=contract.contract_version,
                    environment_id=contract.environment_id,
                    readiness=candidate.readiness,
                    data_compatibility=compatibility,
                    data_profile_id=(data_profile.profile_id if data_profile else None),
                    planning_allowed=planning_gate.allowed,
                    execution_contract_qualified=execution_gate.allowed,
                    input_requirements=[
                        f"input_object={contract.input_object}",
                        *contract.required_fields,
                    ],
                    output_artifacts=[
                        artifact.model_dump(mode="json")
                        for artifact in contract.output_artifacts
                    ],
                    preconditions=[
                        rule.model_dump(mode="json") for rule in contract.preconditions
                    ],
                    parameters=_parameters(contract),
                    failure_modes=sorted(set(contract.failure_checks + contract.not_supported)),
                    validation_rules=sorted(
                        set(
                            contract.validation_metrics
                            + [
                                artifact.validator_id
                                for artifact in contract.output_artifacts
                                if artifact.validator_id
                            ]
                        )
                    ),
                    know_how=dossier.know_how,
                    source_material=dossier.source_material[:source_limit],
                    evaluations=dossier.evaluations,
                    planning_blockers=planning_gate.reasons,
                    execution_gate_blockers=execution_gate.reasons,
                    execution_requirements=[
                        "ExecutionPolicy=allowlisted_local_users",
                        "valid scoped data access grant",
                        "unchanged plan-specific execution approval",
                        "owner-isolated user workspace",
                        "deterministic Router authorization",
                    ],
                    limitations=limitations,
                    provenance_refs=provenance_refs,
                    retrieval_score=score,
                )
            )
        bundles.sort(
            key=lambda item: (-item.retrieval_score, item.tool_name.casefold())
        )
        blocked = sorted(
            {
                *missing_contracts,
                *(
                    bundle.tool_name
                    for bundle in bundles
                    if not bundle.planning_allowed
                ),
            },
            key=str.casefold,
        )
        warnings = [
            "Only contract-grounded actions are returned; catalog-only tools remain recall candidates.",
            "Execution requires independent policy, authorization, approval, ownership, and safety gates.",
        ]
        if requested_tool and not bundles:
            warnings.append("Requested tool has no compatible governed action bundle.")
        retrieval_id = _stable_id(
            "action-retrieval",
            task_term.canonical_id,
            modality_term.canonical_id,
            data_profile.profile_id if data_profile else "generic",
            requested_tool or "auto",
        )
        return ActionBundleSet(
            retrieval_id=retrieval_id,
            task=task_term.label,
            modality=modality_term.label,
            data_profile_id=data_profile.profile_id if data_profile else None,
            bundles=bundles,
            blocked_candidates=blocked,
            warnings=warnings,
        )

    def _contracts_by_tool(self, task_id: str) -> dict[str, ToolContract]:
        matches: dict[str, ToolContract] = {}
        for contract in self.contract_registry.load_all():
            if normalize_task(contract.task).canonical_id != task_id:
                continue
            key = contract.tool_name.casefold()
            current = matches.get(key)
            if current is None or contract.tool_version > current.tool_version:
                matches[key] = contract
        return matches


def _parameters(contract: ToolContract) -> list[ActionParameter]:
    schemas = contract.parameter_schema.get("properties") or {}
    rows = []
    for name, schema in sorted(schemas.items()):
        searchable = contract.searchable_parameters.get(name)
        rows.append(
            ActionParameter(
                name=name,
                default=contract.default_parameters.get(name),
                parameter_schema=schema if isinstance(schema, dict) else {},
                searchable_range=searchable if isinstance(searchable, dict) else None,
                provenance=(
                    "contract_searchable_range"
                    if isinstance(searchable, dict)
                    else "contract_default"
                ),
            )
        )
    return rows


def _provenance(rows: Iterable[dict[str, Any]]) -> set[str]:
    return {
        str(ref)
        for row in rows
        for ref in row.get("provenance_refs", [])
        if str(ref).strip()
    }


def _score(
    *,
    readiness: str,
    compatibility: str,
    source_count: int,
    evaluation_available: bool,
) -> float:
    value = {
        "decision_ready": 4.0,
        "contract_verified": 3.0,
        "planning_only": 2.0,
        "blocked": 0.0,
    }.get(readiness, 0.0)
    value += {"compatible": 2.0, "generic": 1.0, "blocked": 0.0}[compatibility]
    value += min(source_count, 10) * 0.02
    value += 0.5 if evaluation_available else 0.0
    return round(value, 4)


def _stable_id(prefix: str, *values: Any) -> str:
    payload = json.dumps(values, ensure_ascii=True, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"
