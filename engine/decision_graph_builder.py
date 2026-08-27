from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from core.decision_graph_models import (
    DecisionEdge,
    DecisionGovernance,
    DecisionGraphManifest,
    DecisionGraphQuality,
    DecisionNode,
)
from core.execution_models import ToolContract
from core.settings import PROJECT_ROOT
from core.tool_contract_registry import ToolContractRegistry
from execution.environment_registry import EnvironmentRegistry


SNAPSHOT_VERSION = "decision-kg-v3.1.0-action-space"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "decision_graph_v3"


class DecisionGraphBuilder:
    """Build the small, provenance-only graph used for decisions and dossiers."""

    def __init__(
        self,
        *,
        data_dir: Path,
        contract_root: Optional[Path] = None,
        environment_root: Optional[Path] = None,
        package_root: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.contract_root = Path(contract_root or PROJECT_ROOT / "contracts" / "tools")
        self.environment_root = Path(
            environment_root or PROJECT_ROOT / "execution" / "environments"
        )
        self.package_root = Path(package_root or PROJECT_ROOT / ".sckg_exec" / "packages")
        self.output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
        self.nodes: Dict[str, DecisionNode] = {}
        self.edges: Dict[Tuple[str, str, str], DecisionEdge] = {}
        self.duplicate_edge_count = 0
        self._source_tools: set[str] = set()
        self._source_rich_tools: set[str] = set()
        self._contract_tools: set[str] = set()
        self._planning_contract_tools: set[str] = set()
        self._planning_action_implementation_count = 0
        self._verified_contract_tools: set[str] = set()
        self._evaluation_tools: set[str] = set()
        self._contract_io: Dict[str, Dict[str, bool]] = defaultdict(
            lambda: {"input": False, "output": False}
        )

    def build(
        self, *, write: bool = True
    ) -> tuple[list[DecisionNode], list[DecisionEdge], DecisionGraphQuality]:
        self.__init__(
            data_dir=self.data_dir,
            contract_root=self.contract_root,
            environment_root=self.environment_root,
            package_root=self.package_root,
            output_dir=self.output_dir,
        )
        self._load_source_material()
        self._load_contracts()
        self._load_scientific_pilot()
        nodes = sorted(self.nodes.values(), key=lambda item: item.node_id)
        edges = sorted(self.edges.values(), key=lambda item: item.edge_id)
        quality = self._quality(nodes, edges)
        if write:
            self._write(nodes, edges, quality)
        return nodes, edges, quality

    def _load_source_material(self) -> None:
        path = self.data_dir / "indexes" / "evidence_chunks.jsonl"
        for row in _read_jsonl(path):
            tool_names = _string_list(row.get("tool_names")) or [_clean(row.get("tool_name"))]
            tool_names = [tool_name for tool_name in tool_names if tool_name]
            chunk_id = _clean(row.get("chunk_id"))
            if not tool_names or not chunk_id:
                continue
            source_kind = _clean(row.get("source_kind"))
            provenance = f"data/indexes/evidence_chunks.jsonl#{chunk_id}"
            governance = DecisionGovernance(
                tier="source_material",
                decision_eligible=False,
                scope="retrieval_and_evidence_discovery_only",
                limitations=[
                    "Source material cannot promote formal evidence or authorize execution."
                ],
                provenance_refs=[provenance],
            )
            source_node_id = f"source_chunk:{_slug(chunk_id)}"
            self._add_node(
                DecisionNode(
                    node_id=source_node_id,
                    node_type="SourceChunk",
                    label=_clean(row.get("title")) or chunk_id,
                    properties={
                        "chunk_id": chunk_id,
                        "source_kind": source_kind,
                        "source_type": _clean(row.get("source_type")),
                        "source_span": _clean(row.get("source_span")),
                        "doi": _clean(row.get("doi")),
                        "source_url": _clean(row.get("source_url")),
                        "task": _clean(row.get("canonical_task") or row.get("task")),
                        "task_tags": _string_list(row.get("task_tags")),
                        "claim_type": _clean(row.get("claim_type")),
                        "modality": _clean(row.get("modality")),
                        "text_preview": _clean(row.get("chunk_text"))[:360],
                    },
                    governance=governance,
                )
            )
            for tool_name in tool_names:
                tool_id = self._tool(tool_name, governance)
                self._source_tools.add(tool_name.casefold())
                if source_kind in {"source_document", "source_publication", "source_benchmark", "source_docs"}:
                    self._source_rich_tools.add(tool_name.casefold())
                self._add_edge(tool_id, source_node_id, "HAS_SOURCE_MATERIAL", governance)
            # Legacy task labels attached to source chunks were AI-assisted and
            # have not passed promotion review. Keep the source discoverable,
            # but do not turn that metadata into a capability edge.

    def _load_contracts(self) -> None:
        environment_registry = EnvironmentRegistry(self.environment_root)
        registry = ToolContractRegistry(
            self.contract_root,
            environment_registry=environment_registry,
        )
        for contract in registry.load_all():
            contract_path = (
                self.contract_root / contract.tool_name.casefold() / f"{contract.tool_version}.json"
            )
            provenance = _relative(contract_path)
            environment = (
                environment_registry.get(contract.environment_id)
                if environment_registry.contains(contract.environment_id)
                else None
            )
            planning_allowed = registry.planning_gate(contract).allowed
            verified = bool(
                contract.execution_gate_fields_satisfied
                and contract.enabled_for_execution
                and environment is not None
                and environment.qualification_status == "integration_passed"
                and environment.enabled_for_execution
            )
            governance = DecisionGovernance(
                tier="contract_verified" if verified else "blocked",
                decision_eligible=verified,
                scope="contract_version_and_registered_environment",
                limitations=[
                    "Execution still requires policy, ownership, data authorization, and exact approval."
                ],
                provenance_refs=[provenance],
            )
            tool_id = self._tool(contract.tool_name, governance)
            self._contract_tools.add(contract.tool_name.casefold())
            if planning_allowed:
                self._planning_contract_tools.add(contract.tool_name.casefold())
                if contract.action_space_registration == "admitted":
                    self._planning_action_implementation_count += 1
            if verified:
                self._verified_contract_tools.add(contract.tool_name.casefold())
            contract_id = f"contract:{_slug(contract.contract_id)}"
            self._add_node(
                DecisionNode(
                    node_id=contract_id,
                    node_type="ToolContract",
                    label=f"{contract.tool_name} {contract.tool_version}",
                    properties={
                        "contract_id": contract.contract_id,
                        "contract_version": contract.contract_version,
                        "tool_version": contract.tool_version,
                        "wrapper_id": contract.wrapper_id,
                        "language": str(contract.language),
                        "execution_status": str(contract.execution_status),
                        "scientific_validation_status": str(
                            contract.scientific_validation_status
                        ),
                        "enabled_for_execution": contract.enabled_for_execution,
                        "planning_allowed": planning_allowed,
                        "execution_contract_qualified": verified,
                        "execution_condition": "restricted_local_policy_and_exact_approval",
                    },
                    governance=governance,
                )
            )
            self._add_edge(
                tool_id,
                contract_id,
                "HAS_VERIFIED_CONTRACT",
                governance,
                properties={
                    "planning_allowed": planning_allowed,
                    "execution_contract_qualified": verified,
                },
            )
            task_id = self._task(contract.task, governance)
            self._add_edge(contract_id, task_id, "CONTRACTS_TASK", governance)
            # Registered drafts remain discoverable as contracts, but cannot
            # create a formal Action before their planning gate succeeds.
            action_id: str | None = None
            if planning_allowed and contract.action_space_registration == "admitted":
                action_id = self._action(contract.task, governance)
                self._add_edge(contract_id, action_id, "IMPLEMENTS_ACTION", governance)
                self._add_edge(action_id, task_id, "REALIZES_TASK", governance)
            input_id = f"input:{_slug(str(contract.input_object))}"
            self._add_node(
                DecisionNode(
                    node_id=input_id,
                    node_type="InputArtifact",
                    label=str(contract.input_object),
                    properties={"artifact_class": "input_object"},
                    governance=governance,
                )
            )
            self._add_edge(contract_id, input_id, "ACCEPTS_INPUT", governance)
            if action_id:
                self._add_edge(action_id, input_id, "CONSUMES_INPUT", governance)
            self._contract_io[contract.tool_name.casefold()]["input"] = True
            for requirement in contract.required_fields:
                assumption_id = self._assumption(
                    contract_id, contract, requirement, "required_field", governance
                )
                if action_id:
                    self._add_edge(action_id, assumption_id, "REQUIRES_ASSUMPTION", governance)
            for rule in contract.preconditions:
                assumption_id = self._assumption(
                    contract_id,
                    contract,
                    rule.message or f"{rule.field} {rule.operator} {rule.expected}",
                    "blocking_precondition" if rule.blocking else "precondition",
                    governance,
                    properties=rule.model_dump(mode="json"),
                )
                if action_id:
                    self._add_edge(action_id, assumption_id, "REQUIRES_ASSUMPTION", governance)
            for artifact in contract.output_artifacts:
                output_id = f"output:{_slug(contract.tool_name)}:{_slug(artifact.artifact_id)}"
                self._add_node(
                    DecisionNode(
                        node_id=output_id,
                        node_type="OutputArtifact",
                        label=artifact.artifact_id,
                        properties=artifact.model_dump(mode="json"),
                        governance=governance,
                    )
                )
                self._add_edge(contract_id, output_id, "PRODUCES_OUTPUT", governance)
                if action_id:
                    self._add_edge(action_id, output_id, "MAY_PRODUCE_OUTPUT", governance)
                self._contract_io[contract.tool_name.casefold()]["output"] = True
            environment_id = f"environment:{_slug(contract.environment_id)}"
            environment_properties = (
                environment.model_dump(mode="json")
                if environment is not None
                else {"environment_id": contract.environment_id, "registered": False}
            )
            environment_refs = [provenance]
            env_path = self.environment_root / f"{contract.environment_id}.json"
            if env_path.is_file():
                environment_refs.append(_relative(env_path))
            environment_governance = governance.model_copy(
                update={"provenance_refs": sorted(environment_refs)}
            )
            self._add_node(
                DecisionNode(
                    node_id=environment_id,
                    node_type="Environment",
                    label=contract.environment_id,
                    properties=environment_properties,
                    governance=environment_governance,
                )
            )
            self._add_edge(contract_id, environment_id, "RUNS_IN", environment_governance)
            self._parameters(contract_id, contract, governance)
            self._failure_modes(contract_id, action_id, contract, governance)
            self._validation_rules(contract_id, action_id, contract, governance)
            self._know_how(contract_id, action_id, contract, governance)

    def _parameters(
        self, contract_id: str, contract: ToolContract, governance: DecisionGovernance
    ) -> None:
        schemas = contract.parameter_schema.get("properties", {})
        for name, schema in sorted(schemas.items()):
            parameter_id = f"parameter:{_slug(contract.contract_id)}:{_slug(name)}"
            self._add_node(
                DecisionNode(
                    node_id=parameter_id,
                    node_type="Parameter",
                    label=name,
                    properties={
                        "schema": schema,
                        "default": contract.default_parameters.get(name),
                        "searchable_range": contract.searchable_parameters.get(name),
                    },
                    governance=governance,
                )
            )
            self._add_edge(contract_id, parameter_id, "DECLARES_PARAMETER", governance)

    def _assumption(
        self,
        contract_id: str,
        contract: ToolContract,
        label: str,
        kind: str,
        governance: DecisionGovernance,
        *,
        properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        assumption_id = f"assumption:{_slug(contract.contract_id)}:{_slug(kind + '-' + label)}"
        self._add_node(
            DecisionNode(
                node_id=assumption_id,
                node_type="DataAssumption",
                label=label,
                properties={"assumption_kind": kind, **(properties or {})},
                governance=governance,
            )
        )
        self._add_edge(contract_id, assumption_id, "REQUIRES_ASSUMPTION", governance)
        return assumption_id

    def _failure_modes(
        self,
        contract_id: str,
        action_id: str | None,
        contract: ToolContract,
        governance: DecisionGovernance,
    ) -> None:
        rows = [(value, "runtime_check") for value in contract.failure_checks]
        rows.extend((value, "unsupported_input") for value in contract.not_supported)
        for label, category in rows:
            node_id = f"failure:{_slug(contract.contract_id)}:{_slug(label)}"
            self._add_node(
                DecisionNode(
                    node_id=node_id,
                    node_type="FailureMode",
                    label=label,
                    properties={"category": category, "contract_id": contract.contract_id},
                    governance=governance,
                )
            )
            self._add_edge(contract_id, node_id, "DECLARES_FAILURE_MODE", governance)
            if action_id:
                self._add_edge(action_id, node_id, "GUARDED_AGAINST", governance)

    def _validation_rules(
        self,
        contract_id: str,
        action_id: str | None,
        contract: ToolContract,
        governance: DecisionGovernance,
    ) -> None:
        artifact_validators = [
            artifact.validator_id for artifact in contract.output_artifacts if artifact.validator_id
        ]
        for label in sorted(set([*contract.validation_metrics, *artifact_validators])):
            node_id = f"validation:{_slug(contract.contract_id)}:{_slug(label)}"
            self._add_node(
                DecisionNode(
                    node_id=node_id,
                    node_type="ValidationRule",
                    label=label,
                    properties={
                        "metric_authority": "contract_bound_validation",
                        "contract_id": contract.contract_id,
                    },
                    governance=governance,
                )
            )
            self._add_edge(contract_id, node_id, "USES_VALIDATION_RULE", governance)
            if action_id:
                self._add_edge(action_id, node_id, "VALIDATED_BY", governance)

    def _know_how(
        self,
        contract_id: str,
        action_id: str | None,
        contract: ToolContract,
        governance: DecisionGovernance,
    ) -> None:
        review = contract.execution_critical_review
        if not review:
            return
        node_id = f"know-how:{_slug(contract.contract_id)}"
        self._add_node(
            DecisionNode(
                node_id=node_id,
                node_type="KnowHow",
                label=f"{contract.tool_name} execution know-how",
                properties={
                    "reviewer": review.get("reviewer", ""),
                    "review_scope": review.get("review_scope", []),
                    "claim_boundary": review.get("claim_boundary", ""),
                    "source_refs": contract.source_refs,
                    "resource_requirements": contract.resource_requirements,
                },
                governance=governance,
            )
        )
        self._add_edge(contract_id, node_id, "HAS_REVIEWED_KNOW_HOW", governance)
        if action_id:
            self._add_edge(action_id, node_id, "INFORMED_BY_KNOW_HOW", governance)

    def _load_scientific_pilot(self) -> None:
        package_specs = [
            (
                "phase5c-*",
                "dataset:GSE108313",
                "GSE108313 Cell Hashing PBMC",
                "GSE108313_PBMC_HTO_cross_sample_multiplets",
                _pilot_limitations(),
            ),
            (
                "phase5-batch-scientific-*",
                "dataset:scIB-pancreas",
                "scIB Pancreas",
                "scIB_pancreas_batch_integration",
                _batch_pilot_limitations(),
            ),
        ]
        for pattern, dataset_id, label, scope, limitations in package_specs:
            packages = sorted(self.package_root.glob(f"{pattern}/candidate_evaluations.json"))
            if packages:
                self._load_scientific_package(
                    candidates_path=packages[-1],
                    dataset_id=dataset_id,
                    dataset_label=label,
                    scope=scope,
                    limitations=limitations,
                )

    def _load_scientific_package(
        self,
        *,
        candidates_path: Path,
        dataset_id: str,
        dataset_label: str,
        scope: str,
        limitations: list[str],
    ) -> None:
        package_dir = candidates_path.parent
        decision_path = package_dir / "decision_result.json"
        dataset_path = package_dir / "dataset_manifest.json"
        candidates = _read_json(candidates_path, [])
        decision = _read_json(decision_path, {})
        dataset = _read_json(dataset_path, {})
        dataset_refs = [_relative(dataset_path)]
        dataset_governance = DecisionGovernance(
            tier="evaluation_scoped",
            decision_eligible=True,
            scope=scope,
            limitations=limitations,
            provenance_refs=dataset_refs,
        )
        self._add_node(
            DecisionNode(
                node_id=dataset_id,
                node_type="Dataset",
                label=dataset_label,
                properties={
                    "accession": _clean(dataset.get("accession")),
                    "doi": _clean(dataset.get("doi")),
                    "manifest": dataset,
                },
                governance=dataset_governance,
            )
        )
        recommended = _clean(decision.get("recommended_candidate_id"))
        for candidate in candidates if isinstance(candidates, list) else []:
            if not isinstance(candidate, dict):
                continue
            tool_name = _clean(candidate.get("tool_name"))
            candidate_id = _clean(candidate.get("candidate_id"))
            if not tool_name or not candidate_id:
                continue
            provenance = [_relative(candidates_path), _relative(decision_path)]
            governance = DecisionGovernance(
                tier="evaluation_scoped",
                decision_eligible=bool(candidate.get("eligible_for_decision")),
                scope=scope,
                limitations=limitations
                + [str(item) for item in candidate.get("limitations", [])],
                provenance_refs=provenance,
            )
            tool_id = self._tool(tool_name, governance)
            self._evaluation_tools.add(tool_name.casefold())
            evaluation_id = f"evaluation:{_slug(candidate_id)}"
            metrics = {
                key: value.get("mean")
                for key, value in (candidate.get("metric_summaries") or {}).items()
                if isinstance(value, dict)
            }
            self._add_node(
                DecisionNode(
                    node_id=evaluation_id,
                    node_type="Evaluation",
                    label=candidate_id,
                    properties={
                        "candidate_id": candidate_id,
                        "configuration_hash": candidate.get("configuration_hash"),
                        "parameters": candidate.get("parameters", {}),
                        "metrics": metrics,
                        "runtime_summary": candidate.get("runtime_summary", {}),
                        "peak_memory_summary": candidate.get("peak_memory_summary", {}),
                        "seed_stability": candidate.get("seed_stability", {}),
                        "execution_success_rate": candidate.get("execution_success_rate"),
                        "metric_authority": candidate.get("metric_authority"),
                        "recommended_in_package": candidate_id == recommended,
                    },
                    governance=governance,
                )
            )
            self._add_edge(tool_id, evaluation_id, "HAS_DATASET_SCOPED_EVALUATION", governance)
            self._add_edge(evaluation_id, dataset_id, "EVALUATED_ON", governance)

    def _tool(self, name: str, governance: DecisionGovernance) -> str:
        node_id = f"tool:{_slug(name)}"
        current = self.nodes.get(node_id)
        if current is None:
            self._add_node(
                DecisionNode(
                    node_id=node_id,
                    node_type="Tool",
                    label=name,
                    properties={},
                    governance=governance,
                )
            )
        elif _tier_rank(governance.tier) > _tier_rank(current.governance.tier):
            self.nodes[node_id] = current.model_copy(update={"governance": governance})
        return node_id

    def _task(self, name: str, governance: DecisionGovernance) -> str:
        node_id = f"task:{_slug(name)}"
        self._add_node(
            DecisionNode(
                node_id=node_id,
                node_type="Task",
                label=name,
                properties={},
                governance=governance,
            )
        )
        return node_id

    def _action(self, task: str, governance: DecisionGovernance) -> str:
        node_id = f"action:{_slug(task)}"
        self._add_node(
            DecisionNode(
                node_id=node_id,
                node_type="Action",
                label=_display_name(task),
                properties={
                    "canonical_task": task,
                    "operation_type": "analysis",
                    "composition_status": "qualified_vertical_slice",
                    "authority": "versioned_tool_contract",
                },
                governance=governance,
            )
        )
        return node_id

    def _add_node(self, node: DecisionNode) -> None:
        current = self.nodes.get(node.node_id)
        if current is None or _tier_rank(node.governance.tier) > _tier_rank(current.governance.tier):
            self.nodes[node.node_id] = node
        elif current.governance.tier == node.governance.tier:
            merged_refs = sorted(
                set(current.governance.provenance_refs)
                | set(node.governance.provenance_refs)
            )
            merged_limitations = sorted(
                set(current.governance.limitations)
                | set(node.governance.limitations)
            )
            self.nodes[node.node_id] = current.model_copy(
                update={
                    "governance": current.governance.model_copy(
                        update={
                            "provenance_refs": merged_refs,
                            "limitations": merged_limitations,
                            "decision_eligible": (
                                current.governance.decision_eligible
                                or node.governance.decision_eligible
                            ),
                        }
                    )
                }
            )

    def _add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        governance: DecisionGovernance,
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        key = (source_id, target_id, relation)
        if key in self.edges:
            current = self.edges[key]
            merged_refs = sorted(
                set(current.governance.provenance_refs) | set(governance.provenance_refs)
            )
            self.edges[key] = current.model_copy(
                update={
                    "governance": current.governance.model_copy(
                        update={"provenance_refs": merged_refs}
                    )
                }
            )
            return
        digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:20]
        self.edges[key] = DecisionEdge(
            edge_id=f"decision-edge:{digest}",
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            properties=properties or {},
            governance=governance,
        )

    def _quality(
        self, nodes: list[DecisionNode], edges: list[DecisionEdge]
    ) -> DecisionGraphQuality:
        node_ids = {node.node_id for node in nodes}
        dangling = sum(
            edge.source_id not in node_ids or edge.target_id not in node_ids for edge in edges
        )
        hypothesis = sum(edge.relation.startswith("HYPOTHESIZED_") for edge in edges)
        provenance_rate = (
            sum(bool(edge.governance.provenance_refs) for edge in edges) / len(edges)
            if edges
            else 1.0
        )
        decision_edges = [edge for edge in edges if edge.governance.decision_eligible]
        source_bound_rate = (
            sum(edge.governance.source_bound for edge in decision_edges) / len(decision_edges)
            if decision_edges
            else 1.0
        )
        contract_io_rate = (
            sum(all(flags.values()) for flags in self._contract_io.values())
            / len(self._contract_io)
            if self._contract_io
            else 0.0
        )
        components, isolates = _components(node_ids, edges)
        catalog_count = _catalog_tool_count(self.data_dir)
        ready = self._verified_contract_tools & self._evaluation_tools
        action_count = sum(node.node_type == "Action" for node in nodes)
        action_implementations = sum(
            edge.relation == "IMPLEMENTS_ACTION" and edge.governance.decision_eligible
            for edge in edges
        )
        warnings = [
            "Decision Graph v3 is intentionally scoped; full catalog recall remains in Catalog Graph v2.",
            "Source material edges support discovery only and do not create capability claims.",
            "Scientific pilot edges are dataset-scoped and cannot establish universal superiority.",
        ]
        return DecisionGraphQuality(
            snapshot_version=SNAPSHOT_VERSION,
            node_count=len(nodes),
            edge_count=len(edges),
            node_counts_by_type=dict(Counter(node.node_type for node in nodes)),
            edge_counts_by_relation=dict(Counter(edge.relation for edge in edges)),
            catalog_tool_count=catalog_count,
            scoped_tool_count=sum(node.node_type == "Tool" for node in nodes),
            source_material_tool_count=len(self._source_tools),
            source_rich_tool_count=len(self._source_rich_tools),
            contract_verified_tool_count=len(self._verified_contract_tools),
            evaluation_scoped_tool_count=len(self._evaluation_tools),
            decision_ready_tool_count=len(ready),
            action_count=action_count,
            action_implementation_count=action_implementations,
            action_bundle_count=self._planning_action_implementation_count,
            hypothesis_edge_count=hypothesis,
            dangling_edge_count=dangling,
            duplicate_edge_count=self.duplicate_edge_count,
            edge_provenance_coverage=provenance_rate,
            decision_edge_source_bound_rate=source_bound_rate,
            contract_io_coverage_rate=contract_io_rate,
            connected_component_count=components,
            isolated_node_count=isolates,
            integrity_passed=bool(
                not dangling
                and not hypothesis
                and provenance_rate == 1.0
                and source_bound_rate == 1.0
                and contract_io_rate == 1.0
            ),
            warnings=warnings,
        )

    def _write(
        self,
        nodes: list[DecisionNode],
        edges: list[DecisionEdge],
        quality: DecisionGraphQuality,
    ) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        nodes_path = self.output_dir / "nodes.jsonl"
        edges_path = self.output_dir / "edges.jsonl"
        quality_path = self.output_dir / "quality_report.json"
        action_bundles_path = self.output_dir / "action_bundles.jsonl"
        _write_jsonl(nodes_path, (item.model_dump(mode="json") for item in nodes))
        _write_jsonl(edges_path, (item.model_dump(mode="json") for item in edges))
        quality_path.write_text(
            json.dumps(quality.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._write_action_bundles(action_bundles_path)
        evidence_manifest = _read_json(
            self.data_dir / "indexes" / "evidence_index_manifest.json", {}
        )
        source_digest = _clean(evidence_manifest.get("source_digest"))
        input_paths = [
            self.data_dir / "indexes" / "evidence_chunks.jsonl",
            self.data_dir / "indexes" / "source_documents_v2.jsonl",
            self.data_dir / "indexes" / "evidence_index_manifest.json",
            *sorted(self.contract_root.glob("*/*.json")),
            *sorted(self.environment_root.glob("*.json")),
        ]
        manifest = DecisionGraphManifest(
            snapshot_id=f"decision-graph-{_sha256(nodes_path)[:16]}",
            snapshot_version=SNAPSHOT_VERSION,
            nodes_path=_relative(nodes_path),
            edges_path=_relative(edges_path),
            quality_path=_relative(quality_path),
            nodes_sha256=_sha256(nodes_path),
            edges_sha256=_sha256(edges_path),
            node_count=len(nodes),
            edge_count=len(edges),
            action_bundles_path=_relative(action_bundles_path),
            action_bundles_sha256=_sha256(action_bundles_path),
            action_bundle_count=sum(
                bool(line.strip())
                for line in action_bundles_path.read_text(encoding="utf-8").splitlines()
            ),
            source_digest=source_digest,
            input_fingerprints={
                _relative(path): _sha256(path) for path in input_paths if path.is_file()
            },
        )
        (self.output_dir / "manifest.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _write_action_bundles(self, path: Path) -> None:
        from engine.action_bundle_retriever import ActionBundleRetriever
        from engine.decision_graph_query import DecisionGraphQuery

        environment_registry = EnvironmentRegistry(self.environment_root)
        contract_registry = ToolContractRegistry(
            self.contract_root, environment_registry=environment_registry
        )
        retriever = ActionBundleRetriever(
            graph_query=DecisionGraphQuery(self.output_dir),
            contract_registry=contract_registry,
            environment_registry=environment_registry,
        )
        bundles = []
        for action in retriever.graph_query.list_actions():
            result = retriever.retrieve(
                task=str(action["task"]),
                modality="scRNA-seq",
            )
            bundles.extend(result.bundles)
        unique = {bundle.bundle_id: bundle for bundle in bundles}
        _write_jsonl(
            path,
            (
                bundle.model_dump(mode="json")
                for bundle in sorted(unique.values(), key=lambda item: item.bundle_id)
            ),
        )


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({_clean(item) for item in value if _clean(item)})


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")
    return slug or hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _display_name(value: str) -> str:
    return " ".join(part.capitalize() for part in str(value).replace("-", "_").split("_") if part)


def _tier_rank(tier: str) -> int:
    return {
        "blocked": 0,
        "catalog_seed": 1,
        "source_material": 2,
        "evaluation_scoped": 3,
        "contract_verified": 4,
    }.get(tier, 0)


def _relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _catalog_tool_count(data_dir: Path) -> int:
    path = data_dir / "catalog" / "scrna_tools_snapshot.json"
    data = _read_json(path, [])
    if isinstance(data, dict):
        rows = data.get("tools", [])
    else:
        rows = data
    return len(rows) if isinstance(rows, list) else 0


def _components(node_ids: set[str], edges: list[DecisionEdge]) -> tuple[int, int]:
    adjacency: Dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source_id].add(edge.target_id)
        adjacency[edge.target_id].add(edge.source_id)
    seen: set[str] = set()
    components = 0
    for node_id in node_ids:
        if node_id in seen:
            continue
        components += 1
        queue = deque([node_id])
        seen.add(node_id)
        while queue:
            current = queue.popleft()
            for neighbor in adjacency.get(current, set()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
    return components, sum(not adjacency.get(node_id) for node_id in node_ids)


def _pilot_limitations() -> list[str]:
    return [
        "HTO primarily labels cross-sample multiplets.",
        "Same-donor doublets may be labelled as singlets.",
        "Labels use the recorded deterministic HTO fraction rule.",
        "Results apply only to GSE108313 PBMC and the recorded preprocessing.",
        "The pilot cannot establish that a tool is universally optimal.",
    ]


def _batch_pilot_limitations() -> list[str]:
    return [
        "Results apply only to the registered scIB pancreas dataset and source PCA.",
        "The pilot measures batch mixing and cell-type conservation, not every integration objective.",
        "Development parameters are frozen before evaluation.",
        "The pilot cannot establish that a tool is universally optimal.",
    ]
