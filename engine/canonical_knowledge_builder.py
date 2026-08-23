from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from core.canonical_task_ontology import CANONICAL_TASKS
from core.knowledge_intelligence_models import CanonicalKnowledgeSnapshot
from core.settings import PROJECT_ROOT
from engine.decision_graph_builder import DecisionGraphBuilder
from engine.evidence_graph_builder import EvidenceGraphBuilder
from engine.source_corpus_v2 import QUALIFIED_TOOLS, SourceCorpusBuilder


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "canonical_knowledge"


class CanonicalKnowledgeBuilder:
    """Build catalog and decision projections from one versioned source corpus."""

    def __init__(
        self,
        *,
        project_root: Path = PROJECT_ROOT,
        data_dir: Path | None = None,
        contract_root: Path | None = None,
        environment_root: Path | None = None,
        package_root: Path | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.data_dir = Path(data_dir or self.project_root / "data")
        self.contract_root = Path(contract_root or self.project_root / "contracts" / "tools")
        self.environment_root = Path(
            environment_root or self.project_root / "execution" / "environments"
        )
        self.package_root = Path(package_root or self.project_root / ".sckg_exec" / "packages")
        self.output_dir = Path(
            output_dir or self.project_root / "data" / "canonical_knowledge"
        )

    def build(self, *, write: bool = True, rebuild_corpus: bool = True) -> CanonicalKnowledgeSnapshot:
        corpus_result = (
            SourceCorpusBuilder(project_root=self.project_root).build(write=write)
            if rebuild_corpus
            else self._load_corpus_manifest()
        )
        evidence_output = self.data_dir / "knowledge_graph_v2"
        decision_output = self.data_dir / "decision_graph_v3"
        evidence_nodes, evidence_edges, evidence_quality = EvidenceGraphBuilder(
            data_dir=self.data_dir,
            contract_root=self.contract_root,
            environment_root=self.environment_root,
            package_root=self.package_root,
            output_dir=evidence_output,
        ).build(write=write)
        decision_nodes, decision_edges, _ = DecisionGraphBuilder(
            data_dir=self.data_dir,
            contract_root=self.contract_root,
            environment_root=self.environment_root,
            package_root=self.package_root,
            output_dir=decision_output,
        ).build(write=write)

        evidence_tool_names = {
            node.label.casefold()
            for node in evidence_nodes
            if node.node_type == "Tool"
            and any(
                edge.source_id == node.node_id
                and edge.relation == "HAS_TOOL_CONTRACT"
                and edge.governance.layer == "execution_verified"
                for edge in evidence_edges
            )
        }
        decision_tool_names = {
            node.label.casefold()
            for node in decision_nodes
            if node.node_type == "Tool"
            and any(
                edge.source_id == node.node_id
                and edge.relation == "HAS_VERIFIED_CONTRACT"
                and edge.governance.decision_eligible
                for edge in decision_edges
            )
        }
        expected_tools = {tool.casefold() for tool in QUALIFIED_TOOLS}
        drift_reasons = []
        if evidence_tool_names != expected_tools:
            drift_reasons.append(
                f"catalog_projection_qualified_tools={sorted(evidence_tool_names)}"
            )
        if decision_tool_names != expected_tools:
            drift_reasons.append(
                f"decision_projection_qualified_tools={sorted(decision_tool_names)}"
            )

        corpus_manifest = (
            corpus_result.get("manifest", {})
            if isinstance(corpus_result, dict)
            else {}
        )
        source_digest = str(corpus_manifest.get("source_digest") or "")
        snapshot_payload = "|".join(
            [
                source_digest,
                str(corpus_manifest.get("chunk_digest") or ""),
                _digest_records(item.model_dump(mode="json") for item in evidence_nodes),
                _digest_records(item.model_dump(mode="json") for item in decision_nodes),
            ]
        )
        snapshot_id = "canonical-" + hashlib.sha256(snapshot_payload.encode("utf-8")).hexdigest()[:16]
        catalog_count = evidence_quality.catalog_tool_count
        canonical_tool_count = sum(
            node.node_type == "Tool" for node in evidence_nodes
        )
        snapshot = CanonicalKnowledgeSnapshot(
            snapshot_id=snapshot_id,
            source_digest=source_digest,
            catalog_graph_manifest="data/knowledge_graph_v2/manifest.json",
            decision_graph_manifest="data/decision_graph_v3/manifest.json",
            source_document_manifest="data/indexes/source_documents_v2.jsonl",
            evidence_index_manifest="data/indexes/evidence_index_manifest.json",
            task_count=sum(node.node_type == "Task" for node in evidence_nodes),
            catalog_tool_count=catalog_count,
            canonical_tool_node_count=canonical_tool_count,
            qualified_tool_count=len(expected_tools),
            source_document_count=int(corpus_manifest.get("source_document_count") or 0),
            evidence_chunk_count=int(corpus_manifest.get("evidence_chunk_count") or 0),
            projection_drift_count=len(drift_reasons),
            junk_task_count=evidence_quality.junk_task_count,
            unsupported_capability_edge_count=evidence_quality.unsupported_capability_edge_count,
            qualified_tool_governed_path_rate=evidence_quality.qualified_tool_governed_path_rate,
            integrity_passed=(
                evidence_quality.integrity_passed
                and len(drift_reasons) == 0
                and evidence_quality.junk_task_count == 0
                and evidence_quality.unsupported_capability_edge_count == 0
                and evidence_quality.qualified_tool_governed_path_rate == 1.0
            ),
            warnings=[
                *drift_reasons,
                "The 1,847-tool catalog is a discovery layer, not 1,847 verified capability claims.",
                "Decision Graph is a governed projection bound to this canonical snapshot ID.",
            ],
        )
        if write:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = self.output_dir / "manifest.json"
            manifest_path.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
            self._bind_projection_manifest(evidence_output / "manifest.json", snapshot_id, source_digest)
            self._bind_projection_manifest(decision_output / "manifest.json", snapshot_id, source_digest)
        return snapshot

    def _load_corpus_manifest(self) -> Dict[str, Any]:
        path = self.data_dir / "indexes" / "evidence_index_manifest.json"
        if not path.is_file():
            raise FileNotFoundError("evidence index manifest is missing; rebuild the v2 source corpus")
        return {"manifest": json.loads(path.read_text(encoding="utf-8"))}

    @staticmethod
    def _bind_projection_manifest(path: Path, snapshot_id: str, source_digest: str) -> None:
        if not path.is_file():
            return
        value = json.loads(path.read_text(encoding="utf-8"))
        value["canonical_snapshot_id"] = snapshot_id
        value["source_digest"] = source_digest
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _digest_records(records: Iterable[Dict[str, Any]]) -> str:
    payload = "\n".join(
        json.dumps(record, sort_keys=True, ensure_ascii=False) for record in records
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
