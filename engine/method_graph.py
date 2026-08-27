from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from core.capability_pack_models import CapabilityPackManifest
from core.capability_pack_registry import CapabilityPackRegistry
from core.method_graph_models import (
    MethodGraphEdge,
    MethodGraphManifest,
    MethodGraphNode,
    MethodGraphQuality,
    MethodTransition,
)


class MethodGraphBuilder:
    """Project stable pack facts into canonical JSONL without runtime state."""

    def __init__(self, registry: CapabilityPackRegistry | None = None) -> None:
        self.registry = registry or CapabilityPackRegistry()

    def build(self, output_dir: Path) -> MethodGraphManifest:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifests = self.registry.load_all()
        nodes: dict[str, MethodGraphNode] = {}
        edges: dict[str, MethodGraphEdge] = {}
        for manifest in manifests:
            self._project_pack(manifest, nodes, edges)
        node_rows = sorted(nodes.values(), key=lambda item: item.node_id)
        edge_rows = sorted(edges.values(), key=lambda item: item.edge_id)
        quality = _quality(node_rows, edge_rows)
        nodes_path = output_dir / "nodes.jsonl"
        edges_path = output_dir / "edges.jsonl"
        quality_path = output_dir / "quality.json"
        _write_jsonl(nodes_path, node_rows)
        _write_jsonl(edges_path, edge_rows)
        quality_path.write_text(quality.model_dump_json(indent=2) + "\n", encoding="utf-8")
        source_digest = _source_digest(manifests)
        result = MethodGraphManifest(
            snapshot_id=f"method-graph-{source_digest[:16]}",
            source_digest=source_digest,
            nodes_path=nodes_path.name,
            edges_path=edges_path.name,
            quality_path=quality_path.name,
            nodes_sha256=_sha256(nodes_path),
            edges_sha256=_sha256(edges_path),
            node_count=len(node_rows),
            edge_count=len(edge_rows),
        )
        (output_dir / "manifest.json").write_text(
            result.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return result

    def _project_pack(
        self,
        manifest: CapabilityPackManifest,
        nodes: dict[str, MethodGraphNode],
        edges: dict[str, MethodGraphEdge],
    ) -> None:
        pack_node = f"pack:{manifest.pack_id}:{manifest.pack_version}"
        _node(nodes, pack_node, "CapabilityPack", manifest.pack_id, manifest.pack_id, {
            "pack_version": manifest.pack_version,
            "status": str(manifest.status),
            "content_digest": manifest.content_digest,
            "limitations": manifest.limitations,
        })
        gate = self.registry.gate(manifest)
        for representation in manifest.representation_contracts:
            rep_node = f"representation:{representation.representation_id}"
            _node(nodes, rep_node, "Representation", representation.representation_id, manifest.pack_id, representation.model_dump(mode="json"))
            _edge(edges, pack_node, rep_node, "CONTAINS", manifest.pack_id)
        for capability in manifest.capabilities:
            cap_node = f"capability:{capability.capability_id}"
            _node(nodes, cap_node, "Capability", capability.title, manifest.pack_id, capability.model_dump(mode="json"))
            _edge(edges, pack_node, cap_node, "CONTAINS", manifest.pack_id)
        for evidence in manifest.evidence_bindings:
            evidence_node = f"evidence:{evidence.evidence_id}"
            _node(nodes, evidence_node, "Evidence", evidence.source_span, manifest.pack_id, evidence.model_dump(mode="json"))
            _edge(edges, pack_node, evidence_node, "CONTAINS", manifest.pack_id)
        for case in manifest.gold_case_bindings:
            case_node = f"gold:{case.case_id}"
            _node(nodes, case_node, "GoldCase", case.case_id, manifest.pack_id, case.model_dump(mode="json"))
            _edge(edges, pack_node, case_node, "CONTAINS", manifest.pack_id)
        for adapter in manifest.execution_adapters:
            adapter_node = f"adapter:{adapter.adapter_id}"
            _node(nodes, adapter_node, "ExecutionAdapter", adapter.adapter_id, manifest.pack_id, adapter.model_dump(mode="json"))
            env_node = f"environment:{adapter.environment_id}"
            _node(nodes, env_node, "Environment", adapter.environment_id, manifest.pack_id, {})
            _edge(edges, adapter_node, env_node, "RUNS_IN", manifest.pack_id)
        for renderer in manifest.notebook_renderers:
            renderer_node = f"renderer:{renderer.renderer_id}"
            _node(nodes, renderer_node, "NotebookRenderer", renderer.renderer_id, manifest.pack_id, renderer.model_dump(mode="json"))

        methods_by_output: dict[str, list[str]] = defaultdict(list)
        for method in manifest.methods:
            method_node = f"method:{method.method_id}"
            _node(nodes, method_node, "Method", method.method_id, manifest.pack_id, {
                "implementation_kind": method.implementation_kind,
                "optional": method.optional,
                "invalid_predecessors": method.invalid_predecessors,
                "planning_ready": "planning_ready" in gate.readiness,
            })
            _edge(edges, pack_node, method_node, "CONTAINS", manifest.pack_id)
            _edge(edges, method_node, f"capability:{method.capability_id}", "PROVIDES", manifest.pack_id)
            for requirement in method.consumes:
                rep_node = f"representation:{requirement.representation_id}"
                _edge(edges, method_node, rep_node, "CONSUMES", manifest.pack_id, requirement.model_dump(mode="json"))
            for production in method.produces:
                rep_node = f"representation:{production.representation_id}"
                _edge(edges, method_node, rep_node, "PRODUCES", manifest.pack_id, production.model_dump(mode="json"))
                methods_by_output[production.representation_id].append(method_node)
            for evidence_id in method.evidence_ids:
                _edge(edges, method_node, f"evidence:{evidence_id}", "SUPPORTED_BY", manifest.pack_id)
            for case_id in method.gold_case_ids:
                _edge(edges, method_node, f"gold:{case_id}", "EVALUATED_BY", manifest.pack_id)
            validator_node = f"validation:{method.validation_pipeline.scientific_validator_id}"
            _node(
                nodes,
                validator_node,
                "Validation",
                method.validation_pipeline.scientific_validator_id,
                manifest.pack_id,
                {
                    "validation_kind": "scientific_validator",
                    "scientific_validator_id": method.validation_pipeline.scientific_validator_id,
                },
            )
            _edge(edges, method_node, validator_node, "VALIDATED_BY", manifest.pack_id)
            for primitive in method.validation_pipeline.generic_primitives:
                primitive_node = f"validation-primitive:{primitive}"
                _node(
                    nodes,
                    primitive_node,
                    "Validation",
                    primitive,
                    "capability_pack_registry",
                    {"validation_kind": "generic_primitive", "primitive_id": primitive},
                )
                _edge(edges, method_node, primitive_node, "VALIDATED_BY", manifest.pack_id)
            renderer_node = f"renderer:{method.notebook_renderer_id}"
            _edge(edges, method_node, renderer_node, "RENDERED_BY", manifest.pack_id)
            if method.execution_adapter_id:
                _edge(edges, method_node, f"adapter:{method.execution_adapter_id}", "BOUND_BY", manifest.pack_id)
            if method.tool_contract_ref:
                tool_name = method.tool_contract_ref.split(":", 1)[0]
                tool_node = f"tool:{tool_name.casefold()}"
                contract_node = f"tool-contract:{method.tool_contract_ref.casefold()}"
                _node(nodes, tool_node, "Tool", tool_name, manifest.pack_id, {})
                _node(nodes, contract_node, "ToolContract", method.tool_contract_ref, manifest.pack_id, {"contract_ref": method.tool_contract_ref})
                _edge(edges, tool_node, method_node, "IMPLEMENTS", manifest.pack_id)
                _edge(edges, method_node, contract_node, "BOUND_BY", manifest.pack_id)
                if method.environment_id:
                    env_node = f"environment:{method.environment_id}"
                    _node(nodes, env_node, "Environment", method.environment_id, manifest.pack_id, {})
                    _edge(edges, contract_node, env_node, "RUNS_IN", manifest.pack_id)

        for binding in manifest.implementation_bindings:
            method_node = f"method:{binding.method_id}"
            tool_name = binding.tool_contract_ref.split(":", 1)[0]
            tool_node = f"tool:{tool_name.casefold()}"
            contract_node = f"tool-contract:{binding.tool_contract_ref.casefold()}"
            environment_node = f"environment:{binding.environment_id}"
            properties = {
                "binding_id": binding.binding_id,
                "binding_status": binding.status,
                "execution_eligible": binding.execution_eligible,
            }
            _node(nodes, tool_node, "Tool", tool_name, manifest.pack_id, properties)
            _node(
                nodes,
                contract_node,
                "ToolContract",
                binding.tool_contract_ref,
                manifest.pack_id,
                {**properties, "contract_ref": binding.tool_contract_ref},
            )
            _node(
                nodes,
                environment_node,
                "Environment",
                binding.environment_id,
                manifest.pack_id,
                properties,
            )
            _edge(edges, tool_node, method_node, "IMPLEMENTS", manifest.pack_id, properties)
            _edge(edges, method_node, contract_node, "BOUND_BY", manifest.pack_id, properties)
            _edge(edges, contract_node, environment_node, "RUNS_IN", manifest.pack_id, properties)
            for evidence_id in binding.evidence_ids:
                _edge(
                    edges,
                    contract_node,
                    f"evidence:{evidence_id}",
                    "SUPPORTED_BY",
                    manifest.pack_id,
                    properties,
                )

        # PRECEDES is derived strictly from typed production/consumption, never UI order.
        for method in manifest.methods:
            target = f"method:{method.method_id}"
            for requirement in method.consumes:
                for source in methods_by_output.get(requirement.representation_id, []):
                    if source != target:
                        _edge(edges, source, target, "PRECEDES", manifest.pack_id, {"via": requirement.representation_id})
        groups: dict[str, list[str]] = defaultdict(list)
        for method in manifest.methods:
            groups[method.capability_id].append(f"method:{method.method_id}")
        for capability_id, method_nodes in groups.items():
            for index, left in enumerate(sorted(method_nodes)):
                for right in sorted(method_nodes)[index + 1 :]:
                    relation = "COMPLEMENTS" if capability_id.endswith("annotation") else "ALTERNATIVE_TO"
                    _edge(edges, left, right, relation, manifest.pack_id)


class MethodGraphQuery:
    def __init__(self, graph_dir: Path) -> None:
        self.graph_dir = Path(graph_dir)
        self.nodes = {item.node_id: item for item in _load_jsonl(self.graph_dir / "nodes.jsonl", MethodGraphNode)}
        self.edges = list(_load_jsonl(self.graph_dir / "edges.jsonl", MethodGraphEdge))
        self.outgoing: dict[str, list[MethodGraphEdge]] = defaultdict(list)
        self.incoming: dict[str, list[MethodGraphEdge]] = defaultdict(list)
        for edge in self.edges:
            self.outgoing[edge.source_id].append(edge)
            self.incoming[edge.target_id].append(edge)

    @property
    def available(self) -> bool:
        return bool(self.nodes)

    def transition(self, method_id: str) -> MethodTransition:
        node_id = f"method:{method_id}"
        if node_id not in self.nodes:
            raise KeyError(f"method is not present: {method_id}")
        outgoing = self.outgoing[node_id]
        return MethodTransition(
            method_id=method_id,
            consumes=sorted(edge.target_id.removeprefix("representation:") for edge in outgoing if edge.relation == "CONSUMES"),
            produces=sorted(edge.target_id.removeprefix("representation:") for edge in outgoing if edge.relation == "PRODUCES"),
            prerequisites=sorted(edge.source_id.removeprefix("method:") for edge in self.incoming[node_id] if edge.relation == "PRECEDES"),
            invalid_predecessors=list(self.nodes[node_id].properties.get("invalid_predecessors") or []),
            supporting_evidence=sorted(edge.target_id.removeprefix("evidence:") for edge in outgoing if edge.relation == "SUPPORTED_BY"),
            planning_ready=bool(self.nodes[node_id].properties.get("planning_ready")),
        )

    def methods_consuming(self, representation_id: str) -> list[str]:
        node_id = f"representation:{representation_id}"
        return sorted(edge.source_id.removeprefix("method:") for edge in self.incoming.get(node_id, []) if edge.relation == "CONSUMES")


class OptionalNeo4jMethodGraphProjector:
    """Optional one-way projection; graph queries never depend on this adapter."""

    def __init__(self, driver: object | None = None) -> None:
        self.driver = driver

    @property
    def available(self) -> bool:
        return self.driver is not None

    def project(self, graph_dir: Path) -> dict[str, object]:
        if self.driver is None:
            return {"status": "not_available", "projected": False, "reason": "neo4j_driver_unavailable"}
        return {"status": "adapter_present_not_executed", "projected": False, "reason": "explicit_projection_command_required"}


def _node(nodes, node_id, node_type, label, pack_id, properties):
    candidate = MethodGraphNode(node_id=node_id, node_type=node_type, label=label, properties=properties, source_pack_id=pack_id)
    existing = nodes.get(node_id)
    if existing and existing.model_dump(mode="json") != candidate.model_dump(mode="json"):
        raise ValueError(f"method graph node drift: {node_id}")
    nodes[node_id] = candidate


def _edge(edges, source, target, relation, pack_id, properties=None):
    edge_id = f"edge:{_digest([source, relation, target, properties or {}])[:20]}"
    edges[edge_id] = MethodGraphEdge(edge_id=edge_id, source_id=source, target_id=target, relation=relation, properties=properties or {}, source_pack_id=pack_id)


def _quality(nodes, edges):
    ids = {item.node_id for item in nodes}
    dangling = sum(edge.source_id not in ids or edge.target_id not in ids for edge in edges)
    connected = {edge.source_id for edge in edges} | {edge.target_id for edge in edges}
    orphans = sum(node.node_id not in connected for node in nodes)
    runtime_keys = {"run_id", "artifact_hash", "cell_index_hash", "gene_index_hash", "runtime_seconds", "execution_status"}
    runtime_facts = sum(bool(runtime_keys & set(node.properties)) for node in nodes)
    return MethodGraphQuality(
        node_count=len(nodes), edge_count=len(edges),
        node_counts_by_type=dict(Counter(item.node_type for item in nodes)),
        edge_counts_by_relation=dict(Counter(item.relation for item in edges)),
        dangling_edge_count=dangling, accidental_orphan_count=orphans,
        unsupported_edge_count=0, projection_drift_count=0,
        runtime_state_fact_count=runtime_facts,
        integrity_passed=dangling == 0 and orphans == 0 and runtime_facts == 0,
    )


def _write_jsonl(path: Path, rows: Iterable[object]) -> None:
    path.write_text("".join(item.model_dump_json() + "\n" for item in rows), encoding="utf-8")


def _load_jsonl(path: Path, model):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield model.model_validate_json(line)


def _source_digest(manifests: list[CapabilityPackManifest]) -> str:
    return _digest([item.content_digest for item in manifests])


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
