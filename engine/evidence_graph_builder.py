from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.knowledge_graph_models import (
    KGEdgeRecord,
    KGGovernance,
    KGNodeRecord,
    KGQualityReport,
    KGSnapshotManifest,
)
from core.canonical_task_ontology import (
    CANONICAL_TASKS,
    canonical_task_for_text,
    is_junk_task_label,
    task_workflow_edges,
)
from core.kg_ontology import (
    catalog_category_task,
    normalize_platform_values,
    normalize_modality,
    task_label,
    task_parent,
)
from core.settings import PROJECT_ROOT


SNAPSHOT_VERSION = "kg-v2.3.0-canonical"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "knowledge_graph_v2"


class EvidenceGraphBuilder:
    """Build a deterministic, evidence-governed graph snapshot.

    The snapshot keeps retrieval material visible without allowing it to cross
    the formal recommendation or execution gates. Neo4j is intentionally not a
    prerequisite: JSONL is the canonical Phase 6 interchange artifact.
    """

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
        self.environment_root = Path(environment_root or PROJECT_ROOT / "execution" / "environments")
        self.package_root = Path(package_root or PROJECT_ROOT / ".sckg_exec" / "packages")
        self.output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
        self.nodes: Dict[str, KGNodeRecord] = {}
        self.edges: Dict[Tuple[str, str, str], KGEdgeRecord] = {}
        self.duplicate_node_count = 0
        self.duplicate_edge_count = 0

    def build(self, *, write: bool = True) -> tuple[list[KGNodeRecord], list[KGEdgeRecord], KGQualityReport]:
        self.nodes = {}
        self.edges = {}
        self.duplicate_node_count = 0
        self.duplicate_edge_count = 0
        publication_audit = self._audit_index("formal_publication_audit.tsv", "publication_id")
        benchmark_audit = self._audit_index("formal_benchmark_audit.tsv", "benchmark_id")
        source_registry = self._load_source_registry()

        self._load_catalog_tools()
        self._load_canonical_task_workflow()
        self._load_formal_publications(publication_audit, source_registry)
        self._load_formal_benchmarks(benchmark_audit, source_registry)
        self._load_sources(source_registry)
        self._load_source_documents_v2()
        self._load_source_chunks(publication_audit, benchmark_audit, source_registry)
        self._load_contracts_and_environments()
        self._load_task_hierarchy()
        self._load_latest_scientific_pilot()

        nodes = sorted(self.nodes.values(), key=lambda item: item.node_id)
        edges = sorted(self.edges.values(), key=lambda item: item.edge_id)
        report = self._quality_report(nodes, edges, publication_audit, benchmark_audit)
        if write:
            self._write_snapshot(nodes, edges, report)
        return nodes, edges, report

    def _load_catalog_tools(self) -> None:
        snapshot_path = self.data_dir / "catalog" / "scrna_tools_snapshot.json"
        catalog_rows = _read_catalog_rows(snapshot_path)
        catalog_source = (
            "data/catalog/scrna_tools_snapshot.json"
            if catalog_rows
            else "data/scrna_tools.tsv"
        )
        if not catalog_rows:
            catalog_rows = _read_tsv(self.data_dir / "scrna_tools.tsv")
        catalog_governance = KGGovernance(
            layer="retrieval_only",
            recommendation_eligible=False,
            source_bound=True,
            audit_status="upstream_catalog_metadata",
            reason_codes=["catalog_metadata_not_capability_evidence"],
            provenance_refs=[catalog_source, "https://www.scrna-tools.org/data/tools.json"],
        )
        for row in catalog_rows:
            tool_name = _clean(row.get("Tool"))
            if not tool_name:
                continue
            tool_id = self._tool(
                tool_name,
                properties={
                    "catalog_seed": True,
                    "catalog_source": catalog_source,
                    "description": _clean(row.get("Description")),
                    "platform": _clean(row.get("Platform")),
                    "code_url": _clean(row.get("Code")),
                    "license": _clean(row.get("License")),
                    "catalog_added": _clean(row.get("Added")),
                    "catalog_updated": _clean(row.get("Updated")),
                    "catalog_categories": _string_list(row.get("Categories")),
                    "catalog_citations": _to_int(row.get("Citations")),
                    "catalog_publication_count": len(_dict_list(row.get("Publications"))),
                    "catalog_preprint_count": len(_dict_list(row.get("Preprints"))),
                    "github_repository": _clean(row.get("GitHub")),
                    "bioconductor_package": _clean(row.get("Bioc")),
                    "cran_package": _clean(row.get("CRAN")),
                    "pypi_package": _clean(row.get("PyPI")),
                    "catalog_status": "seed_only_not_evidence_verified",
                },
            )
            for node_type, platform in normalize_platform_values(_clean(row.get("Platform"))):
                platform_id = self._ontology_node(
                    node_type,
                    platform.canonical_id,
                    platform.label,
                    {
                        "ontology": (
                            "implementation_language"
                            if node_type == "Language"
                            else "runtime_platform"
                        )
                    },
                )
                self._add_edge(
                    tool_id,
                    platform_id,
                    "CATALOG_IMPLEMENTED_IN"
                    if node_type == "Language"
                    else "CATALOG_RUNS_ON",
                    catalog_governance,
                    {
                        "original_value": platform.original_value,
                        "normalization_rule": platform.matched_rule,
                        "confidence": 0.9,
                    },
                )
            modality_id = self._modality("scRNA-seq")
            self._add_edge(
                tool_id,
                modality_id,
                "CATALOG_SUPPORTS_MODALITY",
                catalog_governance,
                {"basis": "upstream_catalog_scope"},
            )
            for category in _string_list(row.get("Categories")):
                category_id = self._category(category)
                self._add_edge(
                    tool_id,
                    category_id,
                    "CATALOG_HAS_CATEGORY",
                    catalog_governance,
                    {"original_value": category},
                )
                mapped_task = catalog_category_task(category)
                if mapped_task:
                    task_id = self._task(mapped_task.label)
                    self._add_edge(
                        tool_id,
                        task_id,
                        "CATALOG_ADDRESSES_TASK",
                        catalog_governance,
                        {
                            "original_value": category,
                            "normalization_rule": f"catalog_category:{category}",
                        },
                    )
            for status, field, relation in (
                ("published", "Publications", "CATALOG_HAS_PUBLICATION"),
                ("preprint", "Preprints", "CATALOG_HAS_PREPRINT"),
            ):
                for reference in _dict_list(row.get(field)):
                    reference_id = self._catalog_reference(reference, status, catalog_governance)
                    if reference_id:
                        self._add_edge(tool_id, reference_id, relation, catalog_governance)

    def _load_canonical_task_workflow(self) -> None:
        governance = KGGovernance(
            layer="retrieval_only",
            recommendation_eligible=False,
            source_bound=True,
            audit_status="reviewed_canonical_task_ontology",
            reason_codes=["workflow_relation_is_planning_context_only"],
            provenance_refs=["core/canonical_task_ontology.py"],
        )
        for task in CANONICAL_TASKS:
            self._task(task.task_id)
        for source_task, target_task, relation in task_workflow_edges():
            self._add_edge(
                self._task(source_task),
                self._task(target_task),
                relation,
                governance,
            )

    def _load_formal_publications(
        self,
        audit: Dict[str, Dict[str, str]],
        source_registry: Sequence[Dict[str, str]],
    ) -> None:
        source_by_record = self._source_by_record(source_registry)
        for row in _read_tsv(self.data_dir / "tool_publications.tsv"):
            record_id = _clean(row.get("publication_id"))
            tool_name = _clean(row.get("tool_name"))
            if not record_id or not tool_name:
                continue
            audit_row = audit.get(record_id, {})
            source_row = source_by_record.get(record_id)
            governance = self._formal_governance(
                audit_row,
                source_row,
                provenance=[
                    "data/tool_publications.tsv",
                    "data/evidence_candidates/formal_publication_audit.tsv",
                ],
            )
            tool_id = self._tool(tool_name)
            publication_id = f"publication:{record_id}"
            self._add_node(
                KGNodeRecord(
                    node_id=publication_id,
                    node_type="Publication",
                    label=_clean(row.get("title")) or record_id,
                    properties={
                        "record_id": record_id,
                        "tool_name": tool_name,
                        "doi": _clean(row.get("doi")),
                        "source_url": _clean(row.get("source_url") or row.get("paper_url")),
                        "claim_span": _clean(row.get("claim_span")),
                        "reviewed_by": _clean(row.get("reviewed_by")),
                        "task": _clean(row.get("task")),
                        "modality": _clean(row.get("modality")),
                    },
                    governance=governance,
                )
            )
            self._add_edge(tool_id, publication_id, "HAS_PUBLICATION", governance)
            self._link_task_and_modality(tool_id, publication_id, row, governance)

    def _load_formal_benchmarks(
        self,
        audit: Dict[str, Dict[str, str]],
        source_registry: Sequence[Dict[str, str]],
    ) -> None:
        source_by_record = self._source_by_record(source_registry)
        for row in _read_tsv(self.data_dir / "tool_benchmarks.tsv"):
            record_id = _clean(row.get("benchmark_id"))
            tool_name = _clean(row.get("tool_name"))
            if not record_id or not tool_name:
                continue
            audit_row = audit.get(record_id, {})
            source_row = source_by_record.get(record_id)
            governance = self._formal_governance(
                audit_row,
                source_row,
                provenance=[
                    "data/tool_benchmarks.tsv",
                    "data/evidence_candidates/formal_benchmark_audit.tsv",
                ],
            )
            tool_id = self._tool(tool_name)
            benchmark_id = f"benchmark:{record_id}"
            self._add_node(
                KGNodeRecord(
                    node_id=benchmark_id,
                    node_type="Benchmark",
                    label=_clean(row.get("benchmark_name")) or record_id,
                    properties={
                        "record_id": record_id,
                        "tool_name": tool_name,
                        "paper_doi": _clean(row.get("paper_doi")),
                        "source_url": _clean(row.get("source_url")),
                        "metric": _clean(row.get("metric")),
                        "rank": _clean(row.get("rank")),
                        "score": _clean(row.get("score")),
                        "normalized_score": _clean(row.get("normalized_score")),
                        "rank_scope": _clean(row.get("rank_scope")),
                        "n_tools_compared": _clean(row.get("n_tools_compared")),
                        "task": _clean(row.get("task")),
                        "modality": _clean(row.get("modality")),
                    },
                    governance=governance,
                )
            )
            self._add_edge(tool_id, benchmark_id, "EVALUATED_IN_BENCHMARK", governance)
            self._link_task_and_modality(tool_id, benchmark_id, row, governance)

    def _load_sources(self, source_registry: Sequence[Dict[str, str]]) -> None:
        for row in source_registry:
            source_id = _clean(row.get("source_id"))
            if not source_id:
                continue
            validation = _clean(row.get("validation_status"))
            if validation == "source_metadata_mismatch":
                layer = "quarantined"
            elif validation == "validated_source_text_available":
                layer = "retrieval_only"
            else:
                layer = "frozen"
            governance = KGGovernance(
                layer=layer,
                recommendation_eligible=False,
                source_bound=validation == "validated_source_text_available",
                audit_status=validation or "unvalidated",
                reason_codes=[validation, _clean(row.get("validation_issue"))],
                provenance_refs=["data/evidence_candidates/source_registry.tsv"],
            )
            node_id = f"source:{source_id}"
            self._add_node(
                KGNodeRecord(
                    node_id=node_id,
                    node_type="Source",
                    label=_clean(row.get("canonical_title")) or source_id,
                    properties={
                        "source_id": source_id,
                        "doi": _clean(row.get("doi")),
                        "source_url": _clean(row.get("source_url")),
                        "source_type": _clean(row.get("source_type")),
                        "source_status": _clean(row.get("source_status")),
                        "text_chars": _to_int(row.get("text_chars")),
                        "referring_tools": _split_refs(row.get("referring_tool_names")),
                    },
                    governance=governance,
                )
            )
            for tool_name in _split_refs(row.get("referring_tool_names")):
                self._add_edge(
                    self._tool(tool_name),
                    node_id,
                    "HAS_EVIDENCE_SOURCE",
                    governance,
                )
            for record_id in _split_refs(row.get("referring_record_ids")):
                evidence_node = self._evidence_node_id(record_id)
                if evidence_node and evidence_node in self.nodes:
                    edge_governance = _more_restrictive(governance, self.nodes[evidence_node].governance)
                    self._add_edge(evidence_node, node_id, "RESOLVES_TO_SOURCE", edge_governance)

    def _load_source_documents_v2(self) -> None:
        path = self.data_dir / "indexes" / "source_documents_v2.jsonl"
        governance = KGGovernance(
            layer="retrieval_only",
            recommendation_eligible=False,
            source_bound=True,
            audit_status="source_document_v2",
            reason_codes=["source_document_is_retrieval_only"],
            provenance_refs=[_relative(path)],
        )
        for row in _read_jsonl(path):
            if row.get("source_status") != "source_text_available":
                continue
            source_id = _clean(row.get("source_id"))
            if not source_id:
                continue
            node_id = f"source:{source_id}"
            self._add_node(
                KGNodeRecord(
                    node_id=node_id,
                    node_type="Source",
                    label=_clean(row.get("canonical_title")) or source_id,
                    properties={
                        "doi": _clean(row.get("doi")),
                        "source_url": _clean(row.get("source_url")),
                        "source_type": _clean(row.get("source_type")),
                        "content_hash": _clean(row.get("content_hash")),
                        "retrieval_only": True,
                    },
                    governance=governance,
                )
            )
            for tool_name in _string_list(row.get("referring_tool_names")):
                self._add_edge(self._tool(tool_name), node_id, "HAS_EVIDENCE_SOURCE", governance)

    def _load_source_chunks(
        self,
        publication_audit: Dict[str, Dict[str, str]],
        benchmark_audit: Dict[str, Dict[str, str]],
        source_registry: Sequence[Dict[str, str]],
    ) -> None:
        source_by_record = self._source_by_record(source_registry)
        paths = [
            self.data_dir / "indexes" / "evidence_chunks.jsonl",
            self.data_dir / "indexes" / "scrna_tools_catalog_chunks.jsonl",
        ]
        for path in paths:
            self._load_source_chunk_path(
                path,
                publication_audit=publication_audit,
                benchmark_audit=benchmark_audit,
                source_by_record=source_by_record,
            )

    def _load_source_chunk_path(
        self,
        path: Path,
        *,
        publication_audit: Dict[str, Dict[str, str]],
        benchmark_audit: Dict[str, Dict[str, str]],
        source_by_record: Dict[str, Dict[str, str]],
    ) -> None:
        path_ref = _relative(path)
        for row in _read_jsonl(path):
            chunk_id = _clean(row.get("chunk_id"))
            if not chunk_id:
                continue
            record_id = _clean(row.get("source_record_id") or row.get("evidence_id") or row.get("source_id"))
            audit_row = publication_audit.get(record_id) or benchmark_audit.get(record_id) or {}
            source_row = source_by_record.get(record_id)
            if audit_row:
                governance = self._formal_governance(
                    audit_row,
                    source_row,
                    provenance=[path_ref],
                )
            else:
                governance = KGGovernance(
                    layer="retrieval_only",
                    recommendation_eligible=False,
                    source_bound=bool(_clean(row.get("source_span")) and _clean(row.get("chunk_text"))),
                    audit_status="retrieval_chunk",
                    reason_codes=["chunk_requires_formal_promotion"],
                    provenance_refs=[path_ref],
                )
            node_id = f"chunk:{chunk_id}"
            chunk_text = _clean(row.get("chunk_text"))
            self._add_node(
                KGNodeRecord(
                    node_id=node_id,
                    node_type="SourceChunk",
                    label=_clean(row.get("title")) or _short_text(chunk_text, 72) or chunk_id,
                    properties={
                        "chunk_id": chunk_id,
                        "record_id": record_id,
                        "tool_name": _clean(row.get("tool_name")),
                        "task": _clean(row.get("canonical_task") or row.get("task")),
                        "task_tags": _string_list(row.get("task_tags")),
                        "claim_type": _clean(row.get("claim_type")),
                        "modality": _clean(row.get("modality")),
                        "source_span": _clean(row.get("source_span")),
                        "source_type": _clean(row.get("source_type")),
                        "page": row.get("page"),
                        "section": _clean(row.get("section")),
                        "text_preview": _short_text(chunk_text, 260),
                    },
                    governance=governance,
                )
            )
            tool_names = _string_list(row.get("tool_names")) or [_clean(row.get("tool_name"))]
            for tool_name in (name for name in tool_names if name):
                self._add_edge(self._tool(tool_name), node_id, "HAS_RETRIEVAL_CHUNK", governance)
            source_document_id = _clean(row.get("source_document_id"))
            source_node_id = f"source:{source_document_id}"
            if source_document_id and source_node_id in self.nodes:
                self._add_edge(source_node_id, node_id, "HAS_SOURCE_CHUNK", governance)
            evidence_node = self._evidence_node_id(record_id)
            if evidence_node and evidence_node in self.nodes:
                self._add_edge(evidence_node, node_id, "HAS_SOURCE_CHUNK", governance)

    def _load_contracts_and_environments(self) -> None:
        environments: Dict[str, Dict[str, Any]] = {}
        for path in sorted(self.environment_root.glob("*.json")):
            row = _read_json(path)
            environment_id = _clean(row.get("environment_id"))
            if not environment_id:
                continue
            environments[environment_id] = row
            qualified = (
                row.get("qualification_status") == "integration_passed"
                and row.get("integration_test_passed") is True
            )
            governance = KGGovernance(
                layer="execution_verified" if qualified else "frozen",
                recommendation_eligible=False,
                source_bound=qualified,
                audit_status=_clean(row.get("qualification_status")) or "unknown",
                reason_codes=[] if qualified else ["environment_not_integration_qualified"],
                provenance_refs=[_relative(path)],
            )
            self._add_node(
                KGNodeRecord(
                    node_id=f"environment:{environment_id}",
                    node_type="Environment",
                    label=environment_id,
                    properties={
                        "environment_id": environment_id,
                        "environment_type": row.get("environment_type"),
                        "platform": row.get("platform"),
                        "architecture": row.get("architecture"),
                        "qualification_status": row.get("qualification_status"),
                        "enabled_for_execution": row.get("enabled_for_execution") is True,
                        "policy_note": "global ExecutionPolicy remains disabled by default",
                        "package_versions": row.get("package_versions", {}),
                    },
                    governance=governance,
                )
            )

        for path in sorted(self.contract_root.glob("*/*.json")):
            row = _read_json(path)
            tool_name = _clean(row.get("tool_name"))
            contract_id = _clean(row.get("contract_id"))
            if not tool_name or not contract_id:
                continue
            qualified = all(
                [
                    row.get("source_review_status") == "reviewed",
                    row.get("execution_critical_fields_reviewed") is True,
                    row.get("wrapper_status") == "smoke_passed",
                    row.get("environment_status") == "smoke_passed",
                    row.get("execution_status") == "integration_passed",
                ]
            )
            governance = KGGovernance(
                layer="execution_verified" if qualified else "frozen",
                recommendation_eligible=False,
                source_bound=qualified,
                audit_status="integration_passed" if qualified else "execution_gate_incomplete",
                reason_codes=[] if qualified else ["contract_not_integration_qualified"],
                provenance_refs=[_relative(path), *[str(item) for item in row.get("source_refs", [])]],
            )
            tool_id = self._tool(tool_name, properties={"language": row.get("language")})
            node_id = f"contract:{contract_id}"
            self._add_node(
                KGNodeRecord(
                    node_id=node_id,
                    node_type="ToolContract",
                    label=f"{tool_name} {row.get('tool_version', '')} contract".strip(),
                    properties={
                        "contract_id": contract_id,
                        "contract_version": row.get("contract_version"),
                        "tool_name": tool_name,
                        "tool_version": row.get("tool_version"),
                        "task": row.get("task"),
                        "language": row.get("language"),
                        "environment_id": row.get("environment_id"),
                        "wrapper_id": row.get("wrapper_id"),
                        "input_object": row.get("input_object"),
                        "required_fields": row.get("required_fields", []),
                        "output_artifacts": row.get("output_artifacts", []),
                        "execution_status": row.get("execution_status"),
                        "scientific_validation_status": row.get("scientific_validation_status"),
                        "enabled_for_execution": row.get("enabled_for_execution") is True,
                        "execution_is_conditional": True,
                    },
                    governance=governance,
                )
            )
            self._add_edge(tool_id, node_id, "HAS_TOOL_CONTRACT", governance)
            environment_id = _clean(row.get("environment_id"))
            if environment_id and f"environment:{environment_id}" in self.nodes:
                self._add_edge(node_id, f"environment:{environment_id}", "RUNS_IN", governance)
            task = _clean(row.get("task"))
            canonical = canonical_task_for_text(task)
            if canonical:
                task_id = self._task(canonical.task_id)
                self._add_edge(tool_id, task_id, "EXECUTES_TASK", governance)
                self._add_edge(node_id, task_id, "CONTRACTS_TASK", governance)
            if _clean(row.get("input_object")).casefold() == "anndata":
                modality_id = self._modality("scRNA-seq")
                self._add_edge(tool_id, modality_id, "SUPPORTS_MODALITY", governance)
                self._add_edge(node_id, modality_id, "CONTRACTS_MODALITY", governance)

    def _load_latest_scientific_pilot(self) -> None:
        specs = (
            (
                "phase5c-gse108313-*",
                "dataset:GSE108313",
                "GSE108313 Cell Hashing PBMC",
                "GSE108313",
                "10.1186/s13059-018-1603-1",
                [
                    "HTO mainly labels cross-sample multiplets.",
                    "Same-donor doublets may be labelled singlet.",
                    "Results apply only to this PBMC dataset and recorded preprocessing.",
                ],
            ),
            (
                "phase5-batch-scientific-*",
                "dataset:scIB-pancreas",
                "scIB Pancreas",
                "scIB-pancreas",
                "",
                [
                    "Results apply only to the registered scIB pancreas dataset and preprocessing.",
                    "Batch mixing and biological conservation are dataset-scoped metrics.",
                ],
            ),
        )
        for pattern, dataset_id, label, accession, doi, limitations in specs:
            packages = sorted(self.package_root.glob(pattern))
            if packages:
                self._load_scientific_package(
                    package=packages[-1],
                    dataset_id=dataset_id,
                    dataset_label=label,
                    accession=accession,
                    doi=doi,
                    limitations=limitations,
                )

    def _load_scientific_package(
        self,
        *,
        package: Path,
        dataset_id: str,
        dataset_label: str,
        accession: str,
        doi: str,
        limitations: Sequence[str],
    ) -> None:
        candidates = _read_json(package / "candidate_evaluations.json")
        if not isinstance(candidates, list):
            return
        dataset_manifest = _read_json(package / "dataset_manifest.json")
        split_manifest = _read_json(package / "split_manifest.json")
        package_ref = _relative(package)
        governance = KGGovernance(
            layer="execution_verified",
            recommendation_eligible=False,
            source_bound=True,
            audit_status="scientific_pilot",
            reason_codes=["single_dataset_pilot_only", "not_universal_tool_superiority"],
            provenance_refs=[package_ref, *( [f"DOI:{doi}"] if doi else [] )],
        )
        self._add_node(
            KGNodeRecord(
                node_id=dataset_id,
                node_type="Dataset",
                label=dataset_label,
                properties={
                    "accession": accession,
                    "doi": doi,
                    "dataset_hash": dataset_manifest.get("dataset_hash") or dataset_manifest.get("sha256"),
                    "split_hash": split_manifest.get("split_hash"),
                    "metric_authority": "scientific_pilot_metric",
                    "limitations": list(limitations),
                },
                governance=governance,
            )
        )
        for row in candidates:
            tool_name = _clean(row.get("tool_name"))
            candidate_id = _clean(row.get("candidate_id"))
            if not tool_name or not candidate_id:
                continue
            metrics = row.get("metric_summaries") or {}
            evaluation_id = f"evaluation:{_stable_id(candidate_id)}"
            self._add_node(
                KGNodeRecord(
                    node_id=evaluation_id,
                    node_type="Evaluation",
                    label=f"{tool_name} {dataset_label} pilot",
                    properties={
                        "candidate_id": candidate_id,
                        "tool_name": tool_name,
                        "tool_version": row.get("tool_version"),
                        "configuration_hash": row.get("configuration_hash"),
                        "eligible_for_decision": row.get("eligible_for_decision") is True,
                        "execution_success_rate": row.get("execution_success_rate"),
                        "auprc": _metric_mean(metrics, "scientific_pilot_auprc"),
                        "auroc": _metric_mean(metrics, "scientific_pilot_auroc"),
                        "f1": _metric_mean(metrics, "scientific_pilot_f1"),
                        "metric_authority": row.get("metric_authority"),
                        "limitations": row.get("limitations", []),
                    },
                    governance=governance,
                )
            )
            self._add_edge(self._tool(tool_name), evaluation_id, "HAS_SCIENTIFIC_PILOT", governance)
            self._add_edge(evaluation_id, dataset_id, "EVALUATED_ON", governance)

    def _link_task_and_modality(
        self,
        tool_id: str,
        evidence_id: str,
        row: Dict[str, str],
        governance: KGGovernance,
    ) -> None:
        task = _clean(row.get("task"))
        canonical = canonical_task_for_text(task)
        if canonical:
            task_id = self._task(canonical.task_id)
            self._add_edge(evidence_id, task_id, "SUPPORTS_TASK_CLAIM", governance)
            self._add_edge(tool_id, task_id, "ADDRESSES_TASK", governance)
        modality = _clean(row.get("modality"))
        if modality:
            modality_id = self._modality(modality)
            self._add_edge(evidence_id, modality_id, "HAS_MODALITY_SCOPE", governance)
            self._add_edge(tool_id, modality_id, "SUPPORTS_MODALITY", governance)

    def _formal_governance(
        self,
        audit_row: Dict[str, str],
        source_row: Optional[Dict[str, str]],
        *,
        provenance: Sequence[str],
    ) -> KGGovernance:
        allowed = _as_bool(audit_row.get("runtime_recommendation_allowed"))
        audit_labels = _split_semicolon(audit_row.get("audit_labels"))
        validation_status = _clean((source_row or {}).get("validation_status"))
        if validation_status == "source_metadata_mismatch":
            layer = "quarantined"
            allowed = False
            audit_labels.append("source_metadata_mismatch")
        elif allowed:
            layer = "trusted_core"
        else:
            layer = "frozen"
        source_bound = allowed and bool(source_row) and validation_status == "validated_source_text_available"
        if allowed and not source_bound:
            layer = "frozen"
            allowed = False
            audit_labels.append("validated_source_text_missing")
        return KGGovernance(
            layer=layer,
            recommendation_eligible=allowed,
            source_bound=source_bound,
            audit_status="allowed" if allowed else "blocked_by_runtime_audit",
            reason_codes=[*audit_labels, _clean(audit_row.get("recommended_action")), validation_status],
            provenance_refs=list(provenance),
        )

    def _quality_report(
        self,
        nodes: Sequence[KGNodeRecord],
        edges: Sequence[KGEdgeRecord],
        publication_audit: Dict[str, Dict[str, str]],
        benchmark_audit: Dict[str, Dict[str, str]],
    ) -> KGQualityReport:
        node_ids = {node.node_id for node in nodes}
        dangling = sum(
            1 for edge in edges if edge.source_id not in node_ids or edge.target_id not in node_ids
        )
        frozen_leakage = sum(
            1
            for record in [*nodes, *edges]
            if record.governance.layer in {"frozen", "quarantined"}
            and record.governance.recommendation_eligible
        )
        hypothesis_leakage = sum(
            edge.governance.recommendation_eligible
            for edge in edges
            if edge.relation.startswith("HYPOTHESIZED_")
        )
        trusted = [
            record
            for record in [*nodes, *edges]
            if record.governance.layer in {"trusted_core", "execution_verified"}
        ]
        recommendation = [
            record for record in [*nodes, *edges] if record.governance.recommendation_eligible
        ]
        trusted_source_bound = sum(record.governance.source_bound for record in trusted)
        recommendation_source_bound = sum(record.governance.source_bound for record in recommendation)
        warnings: List[str] = []
        if not any(node.governance.layer == "trusted_core" for node in nodes):
            warnings.append("No formal publication or benchmark is currently promotion-ready.")
        snapshot_available = (self.data_dir / "catalog" / "scrna_tools_snapshot.json").is_file()
        if not snapshot_available:
            warnings.append(
                "Full scRNA-tools catalog snapshot is missing; the compatibility TSV omits categories and references."
            )
        if any(node.governance.layer == "quarantined" for node in nodes):
            warnings.append("Metadata-mismatched sources remain quarantined and are excluded from trusted paths.")
        warnings.append("Execution-verified pilot metrics are dataset-scoped and cannot prove universal superiority.")
        tool_ids = {node.node_id for node in nodes if node.node_type == "Tool"}
        connected_tool_ids = {
            node_id
            for edge in edges
            for node_id in (edge.source_id, edge.target_id)
            if node_id in tool_ids
        }
        execution_verified_tool_ids = {
            edge.source_id
            for edge in edges
            if edge.source_id in tool_ids and edge.governance.layer == "execution_verified"
        }
        isolated_tool_count = len(tool_ids - connected_tool_ids)
        if isolated_tool_count:
            warnings.append(
                f"{isolated_tool_count} catalog tools remain entity-only seeds without governed relation claims."
            )
        integrity_passed = not any(
            [
                dangling,
                self.duplicate_node_count,
                self.duplicate_edge_count,
                frozen_leakage,
                hypothesis_leakage,
            ]
        )
        component_sizes, isolated_node_count = _component_sizes(nodes, edges)
        semantic_relations = {
            "EXECUTES_TASK",
            "ADDRESSES_TASK",
            "SUPPORTS_MODALITY",
            "CATALOG_ADDRESSES_TASK",
            "CATALOG_SUPPORTS_MODALITY",
            "HYPOTHESIZED_TASK",
            "HYPOTHESIZED_MODALITY",
            "HYPOTHESIZED_ALGORITHM_FAMILY",
        }
        semantic_tool_ids = {
            edge.source_id
            for edge in edges
            if edge.source_id in tool_ids and edge.relation in semantic_relations
        }
        catalog_category_tool_ids = {
            edge.source_id
            for edge in edges
            if edge.source_id in tool_ids and edge.relation == "CATALOG_HAS_CATEGORY"
        }
        catalog_reference_tool_ids = {
            edge.source_id
            for edge in edges
            if edge.source_id in tool_ids
            and edge.relation in {"CATALOG_HAS_PUBLICATION", "CATALOG_HAS_PREPRINT"}
        }
        source_bound_semantic_tool_ids = {
            edge.source_id
            for edge in edges
            if edge.source_id in tool_ids
            and edge.governance.source_bound
            and edge.relation == "HAS_EVIDENCE_SOURCE"
        }
        contract_qualified_tool_ids = {
            edge.source_id
            for edge in edges
            if edge.source_id in tool_ids
            and edge.relation == "HAS_TOOL_CONTRACT"
            and edge.governance.layer == "execution_verified"
        }
        formal_evidence_tool_ids = {
            edge.source_id
            for edge in edges
            if edge.source_id in tool_ids
            and edge.relation in {"HAS_PUBLICATION", "HAS_BENCHMARK"}
            and edge.governance.layer == "trusted_core"
        }
        qualified_relations = {
            tool_id: {
                edge.relation
                for edge in edges
                if edge.source_id == tool_id
            }
            for tool_id in contract_qualified_tool_ids
        }
        qualified_path_tool_ids = {
            tool_id
            for tool_id, relations in qualified_relations.items()
            if "HAS_TOOL_CONTRACT" in relations
            and "EXECUTES_TASK" in relations
            and "HAS_SCIENTIFIC_PILOT" in relations
            and ({"HAS_EVIDENCE_SOURCE", "HAS_RETRIEVAL_CHUNK"} & relations)
        }
        junk_task_count = sum(
            node.node_type == "Task"
            and (
                is_junk_task_label(node.label)
                or _clean(node.properties.get("task_id"))
                not in {task.task_id for task in CANONICAL_TASKS}
            )
            for node in nodes
        )
        unsupported_capability_edges = sum(
            edge.relation.startswith("HYPOTHESIZED_") for edge in edges
        )
        if contract_qualified_tool_ids - qualified_path_tool_ids:
            warnings.append(
                "Some qualified tools lack a complete contract/task/source/pilot governed path."
            )
        warnings.append(
            "Catalog connectivity, source-bound coverage, contract coverage, and formal evidence coverage are reported separately."
        )
        integrity_passed = integrity_passed and not junk_task_count and not unsupported_capability_edges
        return KGQualityReport(
            snapshot_version=SNAPSHOT_VERSION,
            node_count=len(nodes),
            edge_count=len(edges),
            node_counts_by_type=dict(Counter(node.node_type for node in nodes)),
            node_counts_by_layer=dict(Counter(node.governance.layer for node in nodes)),
            edge_counts_by_relation=dict(Counter(edge.relation for edge in edges)),
            dangling_edge_count=dangling,
            duplicate_node_count=self.duplicate_node_count,
            duplicate_edge_count=self.duplicate_edge_count,
            frozen_recommendation_leakage_count=frozen_leakage,
            trusted_source_bound_rate=(trusted_source_bound / len(trusted) if trusted else 1.0),
            recommendation_source_bound_rate=(
                recommendation_source_bound / len(recommendation) if recommendation else 1.0
            ),
            formal_publication_allowed_count=sum(
                _as_bool(row.get("runtime_recommendation_allowed"))
                for row in publication_audit.values()
            ),
            formal_benchmark_allowed_count=sum(
                _as_bool(row.get("runtime_recommendation_allowed"))
                for row in benchmark_audit.values()
            ),
            catalog_tool_count=_catalog_record_count(
                self.data_dir / "catalog" / "scrna_tools_snapshot.json"
            ),
            canonical_tool_node_count=len(tool_ids),
            connected_tool_count=len(connected_tool_ids),
            isolated_tool_count=isolated_tool_count,
            execution_verified_tool_count=len(execution_verified_tool_ids),
            connected_component_count=len(component_sizes),
            largest_component_node_count=max(component_sizes, default=0),
            largest_component_ratio=(max(component_sizes, default=0) / len(nodes) if nodes else 0.0),
            isolated_node_count=isolated_node_count,
            tool_relation_coverage_rate=(len(connected_tool_ids) / len(tool_ids) if tool_ids else 0.0),
            tool_semantic_coverage_rate=(len(semantic_tool_ids) / len(tool_ids) if tool_ids else 0.0),
            catalog_snapshot_available=snapshot_available,
            catalog_category_coverage_rate=(
                len(catalog_category_tool_ids) / len(tool_ids) if tool_ids else 0.0
            ),
            catalog_reference_tool_coverage_rate=(
                len(catalog_reference_tool_ids) / len(tool_ids) if tool_ids else 0.0
            ),
            catalog_publication_count=sum(
                _to_int(node.properties.get("catalog_publication_count"))
                for node in nodes
                if node.node_type == "Tool" and node.properties.get("catalog_seed")
            ),
            catalog_preprint_count=sum(
                _to_int(node.properties.get("catalog_preprint_count"))
                for node in nodes
                if node.node_type == "Tool" and node.properties.get("catalog_seed")
            ),
            hypothesis_edge_count=sum(edge.relation.startswith("HYPOTHESIZED_") for edge in edges),
            hypothesis_recommendation_leakage_count=hypothesis_leakage,
            catalog_connectivity_rate=(len(connected_tool_ids) / len(tool_ids) if tool_ids else 0.0),
            source_bound_semantic_coverage_rate=(
                len(source_bound_semantic_tool_ids) / len(tool_ids) if tool_ids else 0.0
            ),
            contract_qualified_coverage_rate=(
                len(contract_qualified_tool_ids) / len(tool_ids) if tool_ids else 0.0
            ),
            formal_evidence_coverage_rate=(
                len(formal_evidence_tool_ids) / len(tool_ids) if tool_ids else 0.0
            ),
            qualified_tool_governed_path_rate=(
                len(qualified_path_tool_ids) / len(contract_qualified_tool_ids)
                if contract_qualified_tool_ids
                else 0.0
            ),
            junk_task_count=junk_task_count,
            unsupported_capability_edge_count=unsupported_capability_edges,
            integrity_passed=integrity_passed,
            warnings=warnings,
        )

    def _write_snapshot(
        self,
        nodes: Sequence[KGNodeRecord],
        edges: Sequence[KGEdgeRecord],
        report: KGQualityReport,
    ) -> KGSnapshotManifest:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        nodes_path = self.output_dir / "nodes.jsonl"
        edges_path = self.output_dir / "edges.jsonl"
        report_path = self.output_dir / "quality_report.json"
        previous_manifest = _read_json(self.output_dir / "manifest.json")
        _write_jsonl(nodes_path, [item.model_dump(mode="json") for item in nodes])
        _write_jsonl(edges_path, [item.model_dump(mode="json") for item in edges])
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        nodes_hash = _sha256(nodes_path)
        edges_hash = _sha256(edges_path)
        preserve_import_status = (
            isinstance(previous_manifest, dict)
            and previous_manifest.get("nodes_sha256") == nodes_hash
            and previous_manifest.get("edges_sha256") == edges_hash
            and previous_manifest.get("neo4j_import_status") == "shadow_import_verified"
        )
        evidence_manifest = _read_json(self.data_dir / "indexes" / "evidence_index_manifest.json")
        source_digest = (
            _clean(evidence_manifest.get("source_digest"))
            if isinstance(evidence_manifest, dict)
            else ""
        )
        manifest = KGSnapshotManifest(
            snapshot_id=f"{SNAPSHOT_VERSION}:{nodes_hash[:12]}",
            snapshot_version=SNAPSHOT_VERSION,
            nodes_path=_relative(nodes_path),
            edges_path=_relative(edges_path),
            quality_report_path=_relative(report_path),
            nodes_sha256=nodes_hash,
            edges_sha256=edges_hash,
            input_fingerprints=self._input_fingerprints(),
            node_count=len(nodes),
            edge_count=len(edges),
            neo4j_imported=preserve_import_status,
            neo4j_import_status=(
                "shadow_import_verified" if preserve_import_status else "not_attempted"
            ),
            source_digest=source_digest,
        )
        (self.output_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        return manifest

    def _input_fingerprints(self) -> Dict[str, str]:
        paths = [
            self.data_dir / "scrna_tools.tsv",
            self.data_dir / "catalog" / "scrna_tools_snapshot.json",
            self.data_dir / "evidence_candidates" / "scrna_tools_catalog_audit.json",
            self.data_dir / "tool_publications.tsv",
            self.data_dir / "tool_benchmarks.tsv",
            self.data_dir / "evidence_candidates" / "formal_publication_audit.tsv",
            self.data_dir / "evidence_candidates" / "formal_benchmark_audit.tsv",
            self.data_dir / "evidence_candidates" / "source_registry.tsv",
            self.data_dir / "indexes" / "source_documents_v2.jsonl",
            self.data_dir / "indexes" / "evidence_index_manifest.json",
            self.data_dir / "indexes" / "evidence_chunks.jsonl",
            self.data_dir / "indexes" / "scrna_tools_catalog_chunks.jsonl",
            *sorted(self.contract_root.glob("*/*.json")),
            *sorted(self.environment_root.glob("*.json")),
        ]
        return {_relative(path): _sha256(path) for path in paths if path.is_file()}

    def _audit_index(self, filename: str, key: str) -> Dict[str, Dict[str, str]]:
        return {
            _clean(row.get(key)): row
            for row in _read_tsv(self.data_dir / "evidence_candidates" / filename)
            if _clean(row.get(key))
        }

    def _load_source_registry(self) -> List[Dict[str, str]]:
        return _read_tsv(self.data_dir / "evidence_candidates" / "source_registry.tsv")

    @staticmethod
    def _source_by_record(rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        index: Dict[str, Dict[str, str]] = {}
        for row in rows:
            for record_id in _split_refs(row.get("referring_record_ids")):
                index[record_id] = row
        return index

    def _tool(self, name: str, properties: Optional[Dict[str, Any]] = None) -> str:
        node_id = f"tool:{_stable_id(name)}"
        self._add_node(
            KGNodeRecord(
                node_id=node_id,
                node_type="Tool",
                label=name,
                properties={"tool_name": name, **(properties or {})},
                governance=KGGovernance(
                    layer="retrieval_only",
                    source_bound=False,
                    audit_status="entity",
                    reason_codes=["entity_requires_edge_level_governance"],
                ),
            )
        )
        return node_id

    def _task(self, name: str) -> str:
        canonical = canonical_task_for_text(name)
        if canonical is None:
            raise ValueError(f"non-canonical task cannot enter governed graph: {name}")
        node_id = f"task:{canonical.task_id}"
        self._add_node(
            KGNodeRecord(
                node_id=node_id,
                node_type="Task",
                label=canonical.label,
                properties={
                    "task_id": canonical.task_id,
                    "ontology_rule": "core/canonical_task_ontology.py",
                    "stage_order": canonical.stage_order,
                    "expected_input_types": canonical.expected_input_types,
                    "expected_output_types": canonical.expected_output_types,
                },
                governance=KGGovernance(
                    layer="retrieval_only", source_bound=False, audit_status="ontology_entity"
                ),
            )
        )
        return node_id

    def _modality(self, name: str) -> str:
        term = normalize_modality(name)
        node_id = f"modality:{term.canonical_id}"
        self._add_node(
            KGNodeRecord(
                node_id=node_id,
                node_type="Modality",
                label=term.label,
                properties={"modality_id": term.canonical_id, "ontology_rule": term.matched_rule},
                governance=KGGovernance(
                    layer="retrieval_only", source_bound=False, audit_status="ontology_entity"
                ),
            )
        )
        return node_id

    def _category(self, name: str) -> str:
        category_id = _stable_id(name)
        node_id = f"category:{category_id}"
        self._add_node(
            KGNodeRecord(
                node_id=node_id,
                node_type="Category",
                label=_humanize_category(name),
                properties={
                    "category_id": name,
                    "upstream_source": "scRNA-tools",
                },
                governance=KGGovernance(
                    layer="retrieval_only",
                    source_bound=True,
                    audit_status="upstream_catalog_taxonomy",
                    reason_codes=["catalog_category_not_recommendation_evidence"],
                    provenance_refs=[
                        "data/catalog/scrna_tools_snapshot.json",
                        "https://www.scrna-tools.org/tools",
                    ],
                ),
            )
        )
        return node_id

    def _catalog_reference(
        self,
        reference: Dict[str, Any],
        status: str,
        governance: KGGovernance,
    ) -> Optional[str]:
        doi = _clean(reference.get("DOI"))
        title = _clean(reference.get("Title"))
        key = doi or title
        if not key:
            return None
        node_id = f"catalogpublication:{_stable_id(key.casefold())}"
        self._add_node(
            KGNodeRecord(
                node_id=node_id,
                node_type="Publication",
                label=title or doi,
                properties={
                    "title": title,
                    "doi": doi,
                    "date": _clean(reference.get("Date")),
                    "citations_at_snapshot": _to_int(reference.get("Citations")),
                    "publication_status": status,
                    "metadata_source": "scRNA-tools catalog",
                    "full_text_indexed": False,
                },
                governance=governance,
            )
        )
        return node_id

    def _ontology_node(
        self,
        node_type: str,
        canonical_id: str,
        label: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        node_id = f"{node_type.casefold()}:{canonical_id}"
        self._add_node(
            KGNodeRecord(
                node_id=node_id,
                node_type=node_type,
                label=label,
                properties={"canonical_id": canonical_id, **(properties or {})},
                governance=KGGovernance(
                    layer="retrieval_only",
                    source_bound=False,
                    audit_status="deterministic_ontology",
                    reason_codes=["ontology_entity_not_recommendation_evidence"],
                    provenance_refs=["core/kg_ontology.py"],
                ),
            )
        )
        return node_id

    def _load_task_hierarchy(self) -> None:
        governance = KGGovernance(
            layer="retrieval_only",
            source_bound=False,
            audit_status="deterministic_ontology",
            reason_codes=["ontology_relation_not_recommendation_evidence"],
            provenance_refs=["core/kg_ontology.py"],
        )
        task_nodes = [node for node in list(self.nodes.values()) if node.node_type == "Task"]
        for node in task_nodes:
            canonical_id = _clean(node.properties.get("task_id"))
            parent_id = task_parent(canonical_id)
            if not parent_id:
                continue
            parent_node = self._task(task_label(parent_id))
            self._add_edge(node.node_id, parent_node, "IS_SUBTASK_OF", governance)

    def _add_node(self, node: KGNodeRecord) -> None:
        existing = self.nodes.get(node.node_id)
        if existing is None:
            self.nodes[node.node_id] = node
            return
        if (
            existing.node_type != node.node_type
            or _identity_text(existing.label) != _identity_text(node.label)
        ):
            self.duplicate_node_count += 1
            return
        merged = {**existing.properties, **node.properties}
        governance = _less_restrictive(existing.governance, node.governance)
        self.nodes[node.node_id] = existing.model_copy(
            update={
                "label": _preferred_label(existing.label, node.label),
                "properties": merged,
                "governance": governance,
            }
        )

    def _add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        governance: KGGovernance,
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not source_id or not target_id or source_id == target_id:
            return
        key = (source_id, target_id, relation)
        if key in self.edges:
            existing = self.edges[key]
            if existing.governance != governance or existing.properties != (properties or {}):
                self.edges[key] = existing.model_copy(
                    update={
                        "governance": _less_restrictive(existing.governance, governance),
                        "properties": {**existing.properties, **(properties or {})},
                    }
                )
            return
        edge_id = f"edge:{_stable_id('|'.join(key))}"
        self.edges[key] = KGEdgeRecord(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            properties=properties or {},
            governance=governance,
        )

    @staticmethod
    def _evidence_node_id(record_id: str) -> Optional[str]:
        if not record_id:
            return None
        if record_id.startswith(("CAND_PUB_", "PUB_")):
            return f"publication:{record_id}"
        if "BMK" in record_id or record_id.startswith("benchmark:"):
            return f"benchmark:{record_id.removeprefix('benchmark:')}"
        return None


def _read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.is_file():
        return []
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


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_catalog_rows(path: Path) -> List[Dict[str, Any]]:
    value = _read_json(path)
    if isinstance(value, dict):
        value = value.get("tools")
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    content = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )
    path.write_text(content, encoding="utf-8")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return sorted({_clean(item) for item in value if _clean(item)})


def _dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _humanize_category(value: str) -> str:
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value).strip()
    aliases = {"UMIs": "UMIs", "Marker Genes": "Marker genes"}
    return aliases.get(text, text)


def _short_text(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _stable_id(value: str) -> str:
    normalized = " ".join(str(value or "").split()).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:54]
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{slug or 'record'}-{digest}"


def _identity_text(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _preferred_label(first: str, second: str) -> str:
    values = [str(first or "").strip(), str(second or "").strip()]
    return max(
        values,
        key=lambda value: (sum(character.isupper() for character in value), len(value)),
    )


def _catalog_record_count(path: Path) -> int:
    value = _read_json(path)
    rows = value.get("tools", []) if isinstance(value, dict) else value
    return len(rows) if isinstance(rows, list) else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)


def _as_bool(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0")))
    except ValueError:
        return 0


def _split_semicolon(value: Any) -> List[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def _split_refs(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in re.split(r"[;,|]", text) if part.strip()]


def _metric_mean(metrics: Dict[str, Any], name: str) -> Optional[float]:
    value = metrics.get(name)
    if isinstance(value, dict):
        value = value.get("mean")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _component_sizes(
    nodes: Sequence[KGNodeRecord], edges: Sequence[KGEdgeRecord]
) -> Tuple[List[int], int]:
    adjacency: Dict[str, set[str]] = {node.node_id: set() for node in nodes}
    for edge in edges:
        if edge.source_id in adjacency and edge.target_id in adjacency:
            adjacency[edge.source_id].add(edge.target_id)
            adjacency[edge.target_id].add(edge.source_id)
    seen: set[str] = set()
    sizes: List[int] = []
    for node_id in adjacency:
        if node_id in seen:
            continue
        stack = [node_id]
        seen.add(node_id)
        size = 0
        while stack:
            current = stack.pop()
            size += 1
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        sizes.append(size)
    return sorted(sizes, reverse=True), sum(not neighbors for neighbors in adjacency.values())


def _more_restrictive(left: KGGovernance, right: KGGovernance) -> KGGovernance:
    order = {"quarantined": 0, "frozen": 1, "retrieval_only": 2, "execution_verified": 3, "trusted_core": 4}
    chosen = left if order[left.layer] <= order[right.layer] else right
    return chosen.model_copy(
        update={
            "recommendation_eligible": left.recommendation_eligible and right.recommendation_eligible,
            "source_bound": left.source_bound and right.source_bound,
            "reason_codes": sorted(set(left.reason_codes + right.reason_codes)),
            "provenance_refs": sorted(set(left.provenance_refs + right.provenance_refs)),
        }
    )


def _less_restrictive(left: KGGovernance, right: KGGovernance) -> KGGovernance:
    order = {"quarantined": 0, "frozen": 1, "retrieval_only": 2, "execution_verified": 3, "trusted_core": 4}
    chosen = left if order[left.layer] >= order[right.layer] else right
    recommendation_eligible = left.recommendation_eligible or right.recommendation_eligible
    source_bound = left.source_bound or right.source_bound
    if recommendation_eligible and chosen.layer != "trusted_core":
        chosen = chosen.model_copy(update={"layer": "trusted_core"})
    return chosen.model_copy(
        update={
            "recommendation_eligible": recommendation_eligible,
            "source_bound": source_bound,
            "reason_codes": sorted(set(left.reason_codes + right.reason_codes)),
            "provenance_refs": sorted(set(left.provenance_refs + right.provenance_refs)),
        }
    )
