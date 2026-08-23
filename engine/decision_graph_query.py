from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from core.decision_graph_models import (
    DecisionEdge,
    DecisionNode,
    DecisionToolCandidate,
    DecisionToolDossier,
)


class DecisionGraphQuery:
    def __init__(self, graph_dir: Path) -> None:
        self.graph_dir = Path(graph_dir)
        self.nodes = {
            node.node_id: node
            for node in _load_models(self.graph_dir / "nodes.jsonl", DecisionNode)
        }
        self.edges = list(_load_models(self.graph_dir / "edges.jsonl", DecisionEdge))
        self.outgoing: Dict[str, List[DecisionEdge]] = defaultdict(list)
        self.incoming: Dict[str, List[DecisionEdge]] = defaultdict(list)
        for edge in self.edges:
            self.outgoing[edge.source_id].append(edge)
            self.incoming[edge.target_id].append(edge)

    @property
    def available(self) -> bool:
        return bool(self.nodes)

    def list_tools(self) -> list[str]:
        return sorted(
            (node.label for node in self.nodes.values() if node.node_type == "Tool"),
            key=str.casefold,
        )

    def list_tasks(self) -> list[Dict[str, Any]]:
        rows = []
        for node in self.nodes.values():
            if node.node_type != "Task":
                continue
            contract_tools = self._contract_tools_for_task(node.node_id)
            source_tools = {
                edge.source_id
                for edge in self.incoming.get(node.node_id, [])
                if edge.relation == "SOURCE_MENTIONS_TASK"
            }
            rows.append(
                {
                    "task": node.label,
                    "contract_verified_tools": len(contract_tools),
                    "source_material_tools": len(source_tools),
                }
            )
        return sorted(rows, key=lambda row: (-row["contract_verified_tools"], row["task"].casefold()))

    def list_actions(self) -> list[Dict[str, Any]]:
        rows = []
        for node in self.nodes.values():
            if node.node_type != "Action":
                continue
            contract_ids = {
                edge.source_id
                for edge in self.incoming.get(node.node_id, [])
                if edge.relation == "IMPLEMENTS_ACTION"
                and edge.governance.decision_eligible
            }
            tool_ids = {
                edge.source_id
                for contract_id in contract_ids
                for edge in self.incoming.get(contract_id, [])
                if edge.relation == "HAS_VERIFIED_CONTRACT"
                and edge.governance.decision_eligible
            }
            rows.append(
                {
                    "action_id": node.node_id,
                    "action": node.label,
                    "task": str(node.properties.get("canonical_task") or node.label),
                    "implementation_count": len(contract_ids),
                    "tool_count": len(tool_ids),
                    "tools": sorted(
                        (self.nodes[tool_id].label for tool_id in tool_ids),
                        key=str.casefold,
                    ),
                    "provenance_refs": node.governance.provenance_refs,
                }
            )
        return sorted(rows, key=lambda row: str(row["action"]).casefold())

    def find_tools(self, task: str) -> list[DecisionToolCandidate]:
        wanted = _normalize(task)
        task_nodes = [
            node
            for node in self.nodes.values()
            if node.node_type == "Task"
            and (wanted == _normalize(node.label) or wanted in _normalize(node.label))
        ]
        matches: Dict[str, str] = {}
        matched_labels: Dict[str, str] = {}
        for task_node in task_nodes:
            for tool_id in self._planning_contract_tools_for_task(task_node.node_id):
                matches[tool_id] = "contract"
                matched_labels[tool_id] = task_node.label
            for edge in self.incoming.get(task_node.node_id, []):
                if edge.relation == "SOURCE_MENTIONS_TASK" and edge.source_id not in matches:
                    matches[edge.source_id] = "source_metadata"
                    matched_labels[edge.source_id] = task_node.label
        candidates = []
        for tool_id, basis in matches.items():
            tool = self.nodes[tool_id]
            dossier = self.tool_dossier(tool.label)
            candidates.append(
                DecisionToolCandidate(
                    tool_name=tool.label,
                    tool_node_id=tool_id,
                    readiness=dossier.readiness,
                    matched_task=matched_labels[tool_id],
                    match_basis=basis,
                    source_chunk_count=len(dossier.source_material),
                    contract_available=bool(dossier.contracts),
                    evaluation_available=bool(dossier.evaluations),
                    execution_condition=(
                        "policy_authorization_and_exact_approval_required"
                        if dossier.contracts
                        else "not_execution_eligible"
                    ),
                    blockers=dossier.blockers,
                )
            )
        rank = {
            "decision_ready": 0,
            "contract_verified": 1,
            "planning_only": 2,
            "source_material": 3,
            "catalog_seed": 4,
            "blocked": 5,
        }
        return sorted(candidates, key=lambda item: (rank[item.readiness], item.tool_name.casefold()))

    def tool_dossier(self, tool_name: str) -> DecisionToolDossier:
        tools = [
            node
            for node in self.nodes.values()
            if node.node_type == "Tool" and node.label.casefold() == tool_name.casefold()
        ]
        if not tools:
            raise KeyError(f"tool not found in Decision Graph v3: {tool_name}")
        tool = tools[0]
        tasks: list[Dict[str, Any]] = []
        actions: list[Dict[str, Any]] = []
        inputs: list[Dict[str, Any]] = []
        outputs: list[Dict[str, Any]] = []
        assumptions: list[Dict[str, Any]] = []
        contracts: list[Dict[str, Any]] = []
        environments: list[Dict[str, Any]] = []
        parameters: list[Dict[str, Any]] = []
        failure_modes: list[Dict[str, Any]] = []
        validation_rules: list[Dict[str, Any]] = []
        know_how: list[Dict[str, Any]] = []
        sources: list[Dict[str, Any]] = []
        evaluations: list[Dict[str, Any]] = []
        contract_ids: list[str] = []
        for edge in self.outgoing.get(tool.node_id, []):
            target = self.nodes.get(edge.target_id)
            if target is None:
                continue
            summary = _summary(target, edge)
            if edge.relation == "SOURCE_MENTIONS_TASK":
                tasks.append(summary)
            elif edge.relation == "HAS_SOURCE_MATERIAL":
                sources.append(summary)
            elif edge.relation == "HAS_VERIFIED_CONTRACT":
                contracts.append(summary)
                contract_ids.append(target.node_id)
            elif edge.relation == "HAS_DATASET_SCOPED_EVALUATION":
                evaluations.append(summary)
        for contract_id in contract_ids:
            for edge in self.outgoing.get(contract_id, []):
                target = self.nodes.get(edge.target_id)
                if target is None:
                    continue
                summary = _summary(target, edge)
                if edge.relation == "CONTRACTS_TASK":
                    tasks.append(summary)
                elif edge.relation == "IMPLEMENTS_ACTION":
                    actions.append(summary)
                elif edge.relation == "ACCEPTS_INPUT":
                    inputs.append(summary)
                elif edge.relation == "PRODUCES_OUTPUT":
                    outputs.append(summary)
                elif edge.relation == "REQUIRES_ASSUMPTION":
                    assumptions.append(summary)
                elif edge.relation == "RUNS_IN":
                    environments.append(summary)
                elif edge.relation == "DECLARES_PARAMETER":
                    parameters.append(summary)
                elif edge.relation == "DECLARES_FAILURE_MODE":
                    failure_modes.append(summary)
                elif edge.relation == "USES_VALIDATION_RULE":
                    validation_rules.append(summary)
                elif edge.relation == "HAS_REVIEWED_KNOW_HOW":
                    know_how.append(summary)
        verified_contract = any(item.get("decision_eligible") for item in contracts)
        planning_contract = any(
            bool(item.get("properties", {}).get("planning_allowed"))
            for item in contracts
        )
        if verified_contract and evaluations:
            readiness = "decision_ready"
        elif verified_contract:
            readiness = "contract_verified"
        elif planning_contract:
            readiness = "planning_only"
        elif contracts:
            readiness = "blocked"
        elif sources:
            readiness = "source_material"
        else:
            readiness = "catalog_seed"
        blockers = []
        if not contracts:
            blockers.append("verified_tool_contract_missing")
        if not evaluations:
            blockers.append("dataset_scoped_evaluation_missing")
        if not sources:
            blockers.append("source_material_missing")
        limitations = sorted(
            {
                limitation
                for item in [*contracts, *evaluations, *sources]
                for limitation in item.get("limitations", [])
            }
        )
        return DecisionToolDossier(
            tool_name=tool.label,
            tool_node_id=tool.node_id,
            readiness=readiness,
            tasks=_dedupe(tasks),
            actions=_dedupe(actions),
            inputs=_dedupe(inputs),
            outputs=_dedupe(outputs),
            assumptions=_dedupe(assumptions),
            contracts=_dedupe(contracts),
            environments=_dedupe(environments),
            parameters=_dedupe(parameters),
            failure_modes=_dedupe(failure_modes),
            validation_rules=_dedupe(validation_rules),
            know_how=_dedupe(know_how),
            source_material=_dedupe(sources),
            evaluations=_dedupe(evaluations),
            limitations=limitations,
            blockers=blockers,
        )

    def neighborhood(self, tool_name: str, *, include_source_chunks: int = 6) -> Dict[str, Any]:
        dossier = self.tool_dossier(tool_name)
        selected = {dossier.tool_node_id}
        source_seen = 0
        for edge in self.outgoing.get(dossier.tool_node_id, []):
            target = self.nodes.get(edge.target_id)
            if target is None:
                continue
            if target.node_type == "SourceChunk":
                if source_seen >= include_source_chunks:
                    continue
                source_seen += 1
            selected.add(target.node_id)
            if target.node_type in {"ToolContract", "Evaluation"}:
                selected.update(item.target_id for item in self.outgoing.get(target.node_id, []))
        edges = [
            edge
            for edge in self.edges
            if edge.source_id in selected and edge.target_id in selected
        ]
        return {
            "nodes": [self.nodes[node_id].model_dump(mode="json") for node_id in sorted(selected)],
            "edges": [edge.model_dump(mode="json") for edge in edges],
        }

    def _contract_tools_for_task(self, task_node_id: str) -> set[str]:
        contract_ids = {
            edge.source_id
            for edge in self.incoming.get(task_node_id, [])
            if edge.relation == "CONTRACTS_TASK"
        }
        return {
            edge.source_id
            for contract_id in contract_ids
            for edge in self.incoming.get(contract_id, [])
            if edge.relation == "HAS_VERIFIED_CONTRACT" and edge.governance.decision_eligible
        }

    def _planning_contract_tools_for_task(self, task_node_id: str) -> set[str]:
        contract_ids = {
            edge.source_id
            for edge in self.incoming.get(task_node_id, [])
            if edge.relation == "CONTRACTS_TASK"
            and bool(self.nodes[edge.source_id].properties.get("planning_allowed"))
        }
        return {
            edge.source_id
            for contract_id in contract_ids
            for edge in self.incoming.get(contract_id, [])
            if edge.relation == "HAS_VERIFIED_CONTRACT"
            and bool(edge.properties.get("planning_allowed"))
        }


def _load_models(path: Path, model: Any) -> Iterable[Any]:
    if not path.is_file():
        return []
    return [
        model.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _summary(node: DecisionNode, edge: DecisionEdge) -> Dict[str, Any]:
    return {
        "node_id": node.node_id,
        "node_type": node.node_type,
        "label": node.label,
        "relation": edge.relation,
        "tier": edge.governance.tier,
        "decision_eligible": edge.governance.decision_eligible,
        "scope": edge.governance.scope,
        "limitations": edge.governance.limitations,
        "provenance_refs": edge.governance.provenance_refs,
        "properties": node.properties,
    }


def _normalize(value: str) -> str:
    return " ".join(str(value).casefold().replace("_", " ").replace("-", " ").split())


def _dedupe(rows: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    unique: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        unique[str(row.get("node_id"))] = row
    return sorted(unique.values(), key=lambda row: str(row.get("label", "")).casefold())
