from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.knowledge_graph_models import (
    KGEdgeRecord,
    KGNodeRecord,
    KGToolExplanation,
    KGToolMatch,
)
from core.kg_ontology import normalize_modality, normalize_task
from core.settings import PROJECT_ROOT


class EvidenceGraphQuery:
    """Read-only deterministic query layer for the KG v2 JSONL snapshot."""

    def __init__(self, graph_dir: Optional[Path] = None) -> None:
        self.graph_dir = Path(graph_dir or PROJECT_ROOT / "data" / "knowledge_graph_v2")
        self.nodes = {
            node.node_id: node for node in self._load_nodes(self.graph_dir / "nodes.jsonl")
        }
        self.edges = self._load_edges(self.graph_dir / "edges.jsonl")
        self.outgoing: Dict[str, List[KGEdgeRecord]] = {}
        self.incoming: Dict[str, List[KGEdgeRecord]] = {}
        for edge in self.edges:
            self.outgoing.setdefault(edge.source_id, []).append(edge)
            self.incoming.setdefault(edge.target_id, []).append(edge)

    @property
    def available(self) -> bool:
        return bool(self.nodes)

    def search(self, query: str, *, node_types: Optional[Iterable[str]] = None, limit: int = 20) -> List[KGNodeRecord]:
        terms = [term for term in query.casefold().split() if term]
        allowed = set(node_types or [])
        scored: List[tuple[int, str, KGNodeRecord]] = []
        for node in self.nodes.values():
            if allowed and node.node_type not in allowed:
                continue
            haystack = " ".join(
                [node.label, json.dumps(node.properties, ensure_ascii=False, default=str)]
            ).casefold()
            if not terms:
                score = 1
            elif not all(term in haystack for term in terms):
                continue
            else:
                score = sum(5 if node.label.casefold() == term else 2 if term in node.label.casefold() else 1 for term in terms)
            scored.append((score, node.label.casefold(), node))
        return [item[2] for item in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]]

    def explain_tool(self, tool_name: str) -> KGToolExplanation:
        matches = [
            node
            for node in self.nodes.values()
            if node.node_type == "Tool" and node.label.casefold() == tool_name.casefold()
        ]
        if not matches:
            raise KeyError(f"tool not found in KG v2: {tool_name}")
        tool = matches[0]
        trusted_tasks: List[str] = []
        retrieval_tasks: List[str] = []
        catalog_categories: List[Dict[str, Any]] = []
        catalog_references: List[Dict[str, Any]] = []
        contracts: List[Dict[str, Any]] = []
        environments: List[Dict[str, Any]] = []
        evaluations: List[Dict[str, Any]] = []
        evidence: List[Dict[str, Any]] = []
        frozen: List[Dict[str, Any]] = []
        modalities: List[Dict[str, Any]] = []
        languages: List[Dict[str, Any]] = []
        runtime_platforms: List[Dict[str, Any]] = []
        algorithm_families: List[Dict[str, Any]] = []
        hardware: List[Dict[str, Any]] = []
        resolutions: List[Dict[str, Any]] = []
        paths: List[List[str]] = []

        for edge in self.outgoing.get(tool.node_id, []):
            target = self.nodes.get(edge.target_id)
            if target is None:
                continue
            paths.append([tool.node_id, edge.relation, target.node_id])
            summary = _node_summary(target, edge)
            if target.node_type == "Task":
                if edge.governance.layer in {"trusted_core", "execution_verified"}:
                    trusted_tasks.append(target.label)
                else:
                    retrieval_tasks.append(target.label)
            elif target.node_type == "Category":
                catalog_categories.append(summary)
            elif target.node_type == "ToolContract":
                contracts.append(summary)
                for contract_edge in self.outgoing.get(target.node_id, []):
                    environment = self.nodes.get(contract_edge.target_id)
                    if environment and environment.node_type == "Environment":
                        environments.append(_node_summary(environment, contract_edge))
                        paths.append(
                            [tool.node_id, edge.relation, target.node_id, contract_edge.relation, environment.node_id]
                        )
            elif target.node_type == "Evaluation":
                evaluations.append(summary)
            elif target.node_type == "Modality":
                modalities.append(summary)
            elif target.node_type == "Language":
                languages.append(summary)
            elif target.node_type == "RuntimePlatform":
                runtime_platforms.append(summary)
            elif target.node_type == "AlgorithmFamily":
                algorithm_families.append(summary)
            elif target.node_type == "Hardware":
                hardware.append(summary)
            elif target.node_type == "Resolution":
                resolutions.append(summary)
            elif target.node_type in {"Publication", "Benchmark", "Source", "SourceChunk"}:
                if edge.relation in {"CATALOG_HAS_PUBLICATION", "CATALOG_HAS_PREPRINT"}:
                    catalog_references.append(summary)
                elif edge.governance.layer in {"frozen", "quarantined"}:
                    frozen.append(summary)
                else:
                    evidence.append(summary)

        warnings: List[str] = []
        if frozen:
            warnings.append(f"{len(frozen)} linked evidence records are frozen or quarantined.")
        if not evidence:
            warnings.append("No formal promotion-ready publication or benchmark evidence is available.")
        if catalog_references:
            warnings.append(
                f"{len(catalog_references)} catalog references are discovery metadata; full-text evidence is not implied."
            )
        if evaluations:
            warnings.append("Scientific pilot results are scoped to GSE108313 and do not establish universal superiority.")
        if contracts:
            warnings.append("Execution qualification is conditional on policy, authorization, approval, and ownership gates.")
        hypothesis_count = sum(
            item.get("governance_layer") == "retrieval_only"
            for item in [*modalities, *algorithm_families, *hardware, *resolutions]
        )
        if hypothesis_count:
            warnings.append(
                f"{hypothesis_count} ontology paths are retrieval hypotheses and require source verification."
            )
        return KGToolExplanation(
            tool_name=tool.label,
            tool_node_id=tool.node_id,
            trusted_tasks=sorted(set(trusted_tasks)),
            retrieval_tasks=sorted(set(retrieval_tasks)),
            catalog_categories=_dedupe(catalog_categories),
            catalog_references=_dedupe(catalog_references),
            contracts=contracts,
            environments=_dedupe(environments),
            evaluations=evaluations,
            evidence=evidence,
            frozen_or_quarantined=frozen,
            modalities=_dedupe(modalities),
            languages=_dedupe(languages),
            runtime_platforms=_dedupe(runtime_platforms),
            algorithm_families=_dedupe(algorithm_families),
            hardware=_dedupe(hardware),
            resolutions=_dedupe(resolutions),
            paths=paths,
            warnings=warnings,
        )

    def rank_tools(
        self,
        *,
        task: str,
        modality: str,
        limit: int = 20,
        include_hypotheses: bool = True,
    ) -> List[KGToolMatch]:
        task_term = normalize_task(task)
        modality_term = normalize_modality(modality)
        task_node_id = f"task:{task_term.canonical_id}"
        modality_node_id = f"modality:{modality_term.canonical_id}"
        if task_node_id not in self.nodes or modality_node_id not in self.nodes:
            return []
        task_targets = {task_node_id: 1.0}
        for edge in self.incoming.get(task_node_id, []):
            if edge.relation == "IS_SUBTASK_OF" and edge.source_id in self.nodes:
                task_targets[edge.source_id] = 0.8
        task_matches = self._tool_edges_for_targets(
            task_targets,
            allowed_relations={
                "EXECUTES_TASK",
                "ADDRESSES_TASK",
                "CATALOG_ADDRESSES_TASK",
                "HYPOTHESIZED_TASK",
            },
            include_hypotheses=include_hypotheses,
        )
        modality_matches = self._tool_edges_for_targets(
            {modality_node_id: 1.0},
            allowed_relations={
                "SUPPORTS_MODALITY",
                "CATALOG_SUPPORTS_MODALITY",
                "HYPOTHESIZED_MODALITY",
            },
            include_hypotheses=include_hypotheses,
        )
        matches: List[KGToolMatch] = []
        for tool_id in sorted(set(task_matches) & set(modality_matches)):
            tool = self.nodes.get(tool_id)
            if tool is None or tool.node_type != "Tool":
                continue
            task_edge, task_score = task_matches[tool_id]
            modality_edge, modality_score = modality_matches[tool_id]
            contract_available = any(
                edge.relation == "HAS_TOOL_CONTRACT"
                and edge.governance.layer == "execution_verified"
                for edge in self.outgoing.get(tool_id, [])
            )
            pilot_available = any(
                edge.relation == "HAS_SCIENTIFIC_PILOT"
                and edge.governance.layer == "execution_verified"
                for edge in self.outgoing.get(tool_id, [])
            )
            source_chunk_count = sum(
                edge.relation == "HAS_RETRIEVAL_CHUNK"
                for edge in self.outgoing.get(tool_id, [])
            )
            verified = (
                task_edge.governance.layer in {"trusted_core", "execution_verified"}
                and modality_edge.governance.layer in {"trusted_core", "execution_verified"}
                and contract_available
            )
            catalog_match = (
                task_edge.relation == "CATALOG_ADDRESSES_TASK"
                and modality_edge.relation == "CATALOG_SUPPORTS_MODALITY"
            )
            source_bonus = min(0.35, math.log1p(source_chunk_count) / 10.0)
            score = (
                task_score
                + modality_score
                + 0.2 * contract_available
                + 0.1 * pilot_available
                + source_bonus
            )
            warnings = []
            if not verified:
                if catalog_match:
                    warnings.append(
                        "Graph match comes from scRNA-tools catalog metadata; use it for recall, not recommendation or execution."
                    )
                else:
                    warnings.append(
                        "Graph match includes an unverified hypothesis and cannot support recommendation or execution."
                    )
            else:
                warnings.append("Execution still requires DataProfile, policy, authorization, and exact approval.")
            matches.append(
                KGToolMatch(
                    tool_name=tool.label,
                    tool_node_id=tool_id,
                    graph_score=round(score, 4),
                    candidate_basis=(
                        "execution_verified"
                        if verified
                        else "catalog_metadata"
                        if catalog_match
                        else "graph_hypothesis"
                    ),
                    matched_task=task_term.label,
                    matched_modality=modality_term.label,
                    paths=[
                        _path_summary(task_edge, self.nodes.get(task_edge.target_id)),
                        _path_summary(modality_edge, self.nodes.get(modality_edge.target_id)),
                    ],
                    contract_available=contract_available,
                    scientific_pilot_available=pilot_available,
                    source_chunk_count=source_chunk_count,
                    warnings=warnings,
                )
            )
        matches.sort(
            key=lambda item: (
                item.candidate_basis != "execution_verified",
                -item.graph_score,
                {"catalog_metadata": 0, "graph_hypothesis": 1, "execution_verified": 0}[
                    item.candidate_basis
                ],
                item.tool_name.casefold(),
            )
        )
        return matches[:limit]

    def _tool_edges_for_targets(
        self,
        targets: Dict[str, float],
        *,
        allowed_relations: set[str],
        include_hypotheses: bool,
    ) -> Dict[str, tuple[KGEdgeRecord, float]]:
        result: Dict[str, tuple[KGEdgeRecord, float]] = {}
        layer_weight = {
            "trusted_core": 1.0,
            "execution_verified": 1.0,
            "retrieval_only": 0.35,
            "frozen": 0.3,
        }
        for target_id, target_weight in targets.items():
            for edge in self.incoming.get(target_id, []):
                if edge.relation not in allowed_relations:
                    continue
                if edge.governance.layer == "quarantined":
                    continue
                if edge.governance.layer in {"retrieval_only", "frozen"} and not include_hypotheses:
                    continue
                source = self.nodes.get(edge.source_id)
                if source is None or source.node_type != "Tool":
                    continue
                source_weight = (
                    0.55
                    if edge.governance.layer == "retrieval_only"
                    and edge.governance.source_bound
                    and edge.relation.startswith("CATALOG_")
                    else layer_weight.get(edge.governance.layer, 0.0)
                )
                score = source_weight * target_weight
                previous = result.get(edge.source_id)
                if previous is None or score > previous[1]:
                    result[edge.source_id] = (edge, score)
        return result

    @staticmethod
    def _load_nodes(path: Path) -> List[KGNodeRecord]:
        return [KGNodeRecord.model_validate(row) for row in _read_jsonl(path)]

    @staticmethod
    def _load_edges(path: Path) -> List[KGEdgeRecord]:
        return [KGEdgeRecord.model_validate(row) for row in _read_jsonl(path)]


def _node_summary(node: KGNodeRecord, edge: KGEdgeRecord) -> Dict[str, Any]:
    return {
        "node_id": node.node_id,
        "label": node.label,
        "node_type": node.node_type,
        "relation": edge.relation,
        "governance_layer": edge.governance.layer,
        "source_bound": edge.governance.source_bound,
        "recommendation_eligible": edge.governance.recommendation_eligible,
        "reason_codes": edge.governance.reason_codes,
        "properties": node.properties,
    }


def _path_summary(edge: KGEdgeRecord, target: Optional[KGNodeRecord]) -> Dict[str, Any]:
    return {
        "edge_id": edge.edge_id,
        "relation": edge.relation,
        "target_id": edge.target_id,
        "target_label": target.label if target else edge.target_id,
        "governance_layer": edge.governance.layer,
        "confidence": edge.properties.get("confidence"),
        "original_value": edge.properties.get("original_value"),
        "normalization_rule": edge.properties.get("normalization_rule"),
        "provenance_refs": edge.governance.provenance_refs,
    }


def _dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = row.get("node_id")
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
