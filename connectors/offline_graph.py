import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.models import Evidence, derived_evidence, github_evidence
from core.settings import get_settings


class OfflineGraphStore:
    """Local fallback graph store built from data files."""

    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.evidence_index: Dict[str, List[Evidence]] = {}
        self._load_backup(settings.data_dir / "scKG_embeddings_backup.jsonl")
        self._load_tool_catalog(settings.data_dir / "scrna_tools.tsv")

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
        results = []
        for tool in self.tools.values():
            if self._matches(task, tool.get("tasks", [])) and self._matches(modality, tool.get("modalities", [])):
                results.append(
                    {
                        "tool_name": tool["name"],
                        "desc": tool.get("description", ""),
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
