import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.models import Evidence, derived_evidence, github_evidence
from core.settings import get_settings
from engine.evidence_graph_query import EvidenceGraphQuery


class OfflineGraphStore:
    """Local fallback graph store built from data files."""

    def __init__(self, data_dir: Optional[Path] = None):
        settings = get_settings()
        self.settings = settings
        self.data_dir = Path(data_dir or settings.data_dir)
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.evidence_index: Dict[str, List[Evidence]] = {}
        self.kg_v2_available = False
        self.graph_query: Optional[EvidenceGraphQuery] = None
        self._load_backup(self.data_dir / "scKG_embeddings_backup.jsonl")
        self._load_tool_catalog(self.data_dir / "scrna_tools.tsv")
        self._load_governed_graph(self.data_dir / "knowledge_graph_v2")
        if self.kg_v2_available:
            self.graph_query = EvidenceGraphQuery(self.data_dir / "knowledge_graph_v2")

    def _load_governed_graph(self, graph_dir: Path) -> None:
        nodes_path = graph_dir / "nodes.jsonl"
        edges_path = graph_dir / "edges.jsonl"
        if not nodes_path.is_file() or not edges_path.is_file():
            return
        nodes = {
            row.get("node_id"): row
            for row in self._read_jsonl(nodes_path)
            if row.get("node_id")
        }
        tool_ids = {
            node_id: row.get("label", "")
            for node_id, row in nodes.items()
            if row.get("node_type") == "Tool"
        }
        for tool_id, tool_name in tool_ids.items():
            if not tool_name:
                continue
            properties = nodes[tool_id].get("properties") or {}
            entry = self.tools.setdefault(tool_name, {"name": tool_name})
            entry.setdefault("description", properties.get("description", ""))
            entry.setdefault("tasks", [])
            entry.setdefault("modalities", [])
            entry.setdefault("verified_tasks", [])
            entry.setdefault("verified_modalities", [])
            entry["kg_v2_node_id"] = tool_id

        for edge in self._read_jsonl(edges_path):
            source_id = edge.get("source_id")
            target_id = edge.get("target_id")
            source = nodes.get(source_id, {})
            target = nodes.get(target_id, {})
            governance = edge.get("governance") or {}
            layer = governance.get("layer")
            relation = edge.get("relation")
            if source.get("node_type") != "Tool":
                continue
            tool_name = source.get("label", "")
            if not tool_name:
                continue
            entry = self.tools.setdefault(tool_name, {"name": tool_name})
            if target.get("node_type") == "Task" and relation in {"EXECUTES_TASK", "ADDRESSES_TASK"}:
                target_label = target.get("label", "")
                if layer in {"execution_verified", "trusted_core"} and target_label:
                    _append_unique(entry.setdefault("verified_tasks", []), target_label)
                    _append_unique(entry.setdefault("tasks", []), target_label)
            elif target.get("node_type") == "Modality" and relation == "SUPPORTS_MODALITY":
                target_label = target.get("label", "")
                if layer in {"execution_verified", "trusted_core"} and target_label:
                    _append_unique(entry.setdefault("verified_modalities", []), target_label)
                    _append_unique(entry.setdefault("modalities", []), target_label)
            elif target.get("node_type") == "ToolContract" and relation == "HAS_TOOL_CONTRACT":
                properties = target.get("properties") or {}
                entry["contract"] = properties
                self.evidence_index.setdefault(tool_name, []).append(
                    derived_evidence(
                        evidence_id=f"kg-v2:{tool_name}:contract",
                        metric_name="official_docs_support",
                        metric_value={
                            "contract_id": properties.get("contract_id"),
                            "execution_status": properties.get("execution_status"),
                            "environment_id": properties.get("environment_id"),
                        },
                        extraction_method="offline_graph.kg_v2_loader",
                        source_title=f"Governed ToolContract for {tool_name}",
                        confidence=0.9,
                        trust_level="source_based",
                        graph_layer="experimental",
                        evidence_strength="medium",
                        use_for=["retrieval"],
                        kg_version="kg-v2.0.0",
                    )
                )
            elif target.get("node_type") == "Evaluation" and relation == "HAS_SCIENTIFIC_PILOT":
                properties = target.get("properties") or {}
                self.evidence_index.setdefault(tool_name, []).append(
                    derived_evidence(
                        evidence_id=f"kg-v2:{tool_name}:pilot:{target_id}",
                        metric_name="scientific_pilot_auprc",
                        metric_value=properties.get("auprc"),
                        extraction_method="offline_graph.kg_v2_loader",
                        source_title=f"GSE108313 scientific pilot for {tool_name}",
                        dataset_scope="GSE108313",
                        confidence=0.85,
                        trust_level="source_based",
                        graph_layer="experimental",
                        evidence_strength="medium",
                        use_for=["retrieval", "scientific_pilot_comparison"],
                        kg_version="kg-v2.0.0",
                    )
                )
        self.kg_v2_available = bool(tool_ids)

    @staticmethod
    def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
        return rows

    def _load_backup(self, path: Path) -> None:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                tool_name = record["tool_name"]
                llm_data = record.get("llm_extracted_data", {})
                self.tools.setdefault(tool_name, {})
                self.tools[tool_name].update(
                    {
                        "name": tool_name,
                        "github_url": record.get("github_url"),
                        "description": llm_data.get("description", ""),
                        "tasks": llm_data.get("supported_tasks", []),
                        "modalities": llm_data.get("supported_modalities", []),
                        "hardware": llm_data.get("hardware_requirements", []),
                        "resolution": llm_data.get("biological_resolution", []),
                        "algorithm_features": llm_data.get("algorithm_features", ""),
                        "embedding": record.get("embedding", []),
                    }
                )
                self.evidence_index.setdefault(tool_name, []).extend(
                    [
                        derived_evidence(
                            evidence_id=f"offline:{tool_name}:supported_tasks",
                            metric_name="supported_tasks",
                            metric_value=llm_data.get("supported_tasks", []),
                            extraction_method="offline_graph.backup_loader",
                            source_title=f"Backup extraction for {tool_name}",
                            confidence=0.45,
                            trust_level="model_extracted",
                            graph_layer="experimental",
                            evidence_strength="weak",
                            use_for=["retrieval"],
                            kg_version=self.settings.kg_version,
                        ),
                        derived_evidence(
                            evidence_id=f"offline:{tool_name}:supported_modalities",
                            metric_name="supported_modalities",
                            metric_value=llm_data.get("supported_modalities", []),
                            extraction_method="offline_graph.backup_loader",
                            source_title=f"Backup extraction for {tool_name}",
                            confidence=0.45,
                            trust_level="model_extracted",
                            graph_layer="experimental",
                            evidence_strength="weak",
                            use_for=["retrieval"],
                            kg_version=self.settings.kg_version,
                        ),
                        derived_evidence(
                            evidence_id=f"offline:{tool_name}:algorithm_features",
                            metric_name="algorithm_features",
                            metric_value=llm_data.get("algorithm_features", ""),
                            extraction_method="offline_graph.backup_loader",
                            source_title=f"Backup extraction for {tool_name}",
                            confidence=0.35,
                            trust_level="model_extracted",
                            graph_layer="experimental",
                            evidence_strength="exploratory",
                            use_for=["retrieval"],
                            kg_version=self.settings.kg_version,
                        ),
                    ]
                )

    def _load_tool_catalog(self, path: Path) -> None:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
            header = handle.readline().strip().split("\t")
            for line in handle:
                if not line.strip():
                    continue
                values = line.rstrip("\n").split("\t")
                row = dict(zip(header, values))
                tool_name = row.get("Tool", "").strip()
                if not tool_name or tool_name not in self.tools:
                    continue
                entry = self.tools[tool_name]
                if not entry.get("description"):
                    entry["description"] = row.get("Description", "")
                entry["source_url"] = row.get("Code", "")
                entry["license"] = row.get("License", "Unknown")
                entry["publish_year"] = str(row.get("Added", "Unknown"))[:4]

    def _normalize_text(self, text: str) -> str:
        normalized = text.lower().strip()
        aliases = {
            "qc": "quality control",
            "dtu analysis": "differential transcript usage",
            "trajectory inference": "trajectory",
            "cell type annotation": "annotation",
            "data integration": "integration",
            "differential expression": "differential expression",
            "isoform quantification": "isoform",
            "multiome integration": "multiomics",
            "scRNA-seq+scATAC-seq".lower(): "multiomics",
            "long-read scrna-seq": "long-read",
        }
        return aliases.get(normalized, normalized)

    def _matches(self, value: str, options: List[str]) -> bool:
        norm_value = self._normalize_text(value)
        options_norm = [self._normalize_text(opt) for opt in options if opt]
        if not options_norm:
            return False
        if norm_value in options_norm:
            return True
        for opt in options_norm:
            if norm_value in opt or opt in norm_value:
                return True
        return False

    def find_candidates(self, task: str, modality: str) -> List[Dict[str, Any]]:
        if self.graph_query is not None:
            graph_matches = self.graph_query.rank_tools(task=task, modality=modality, limit=50)
            if graph_matches:
                return [
                    {
                        "tool_name": match.tool_name,
                        "desc": self.tools.get(match.tool_name, {}).get("description", ""),
                        "candidate_basis": match.candidate_basis,
                        "graph_score": match.graph_score,
                        "graph_paths": match.paths,
                    }
                    for match in graph_matches
                ]
        results = []
        for tool in self.tools.values():
            verified_tasks = tool.get("verified_tasks", [])
            verified_modalities = tool.get("verified_modalities", [])
            task_options = verified_tasks or tool.get("tasks", [])
            modality_options = verified_modalities or tool.get("modalities", [])
            if self._matches(task, task_options) and self._matches(modality, modality_options):
                results.append(
                    {
                        "tool_name": tool["name"],
                        "desc": tool.get("description", ""),
                        "candidate_basis": (
                            "execution_verified" if verified_tasks and verified_modalities else "legacy_retrieval"
                        ),
                    }
                )
        return results

    def get_tool_rows(self, candidates: List[str]) -> List[Dict[str, Any]]:
        rows = []
        for name in candidates:
            tool = self.tools.get(name, {})
            rows.append(
                {
                    "tool_name": name,
                    "description": tool.get("description", ""),
                    "github_url": tool.get("github_url", ""),
                    "github_stars": tool.get("github_stars"),
                    "language": tool.get("language", "Unknown"),
                }
            )
        return rows

    def get_tool_evidence(self, tool_names: List[str]) -> Dict[str, List[Evidence]]:
        result: Dict[str, List[Evidence]] = {}
        for name in tool_names:
            result[name] = list(self.evidence_index.get(name, []))
        return result

    def upsert_evidence(self, tool_name: str, evidence: Evidence) -> None:
        self.evidence_index.setdefault(tool_name, [])
        self.evidence_index[tool_name] = [
            item for item in self.evidence_index[tool_name]
            if item.evidence_id != evidence.evidence_id
        ]
        self.evidence_index[tool_name].append(evidence)

    def get_algorithm_rows(self) -> List[Dict[str, Any]]:
        rows = []
        for tool in self.tools.values():
            embedding = tool.get("embedding")
            if embedding is None:
                continue
            rows.append(
                {
                    "tool_name": tool["name"],
                    "features": tool.get("algorithm_features", ""),
                    "embedding": embedding,
                }
            )
        return rows

    def create_github_evidence(self, tool_name: str, metric_value: Any, source_url: Optional[str]) -> Evidence:
        return github_evidence(
            tool_name=tool_name,
            metric_name="github_stars",
            metric_value=metric_value,
            source_url=source_url,
            kg_version=self.settings.kg_version,
        )


def _append_unique(values: List[str], value: str) -> None:
    if value not in values:
        values.append(value)
