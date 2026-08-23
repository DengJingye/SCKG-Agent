from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.knowledge_graph_models import KGGovernance
from engine.evidence_graph_builder import EvidenceGraphBuilder
from engine.evidence_graph_query import EvidenceGraphQuery
from engine.knowledge_graph_view import build_knowledge_graph_html, build_knowledge_graph_view
from connectors.offline_graph import OfflineGraphStore


def _write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _graph_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    data = tmp_path / "data"
    contracts = tmp_path / "contracts"
    environments = tmp_path / "environments"
    output = tmp_path / "graph"
    _write_tsv(
        data / "tool_publications.tsv",
        [{
            "publication_id": "CAND_PUB_Scrublet",
            "tool_name": "Scrublet",
            "title": "Scrublet paper",
            "doi": "10.1/scrublet",
            "task": "doublet_detection",
            "modality": "scRNA-seq",
        }],
    )
    _write_tsv(
        data / "tool_benchmarks.tsv",
        [{
            "benchmark_id": "HR_BMK_Scrublet",
            "tool_name": "Scrublet",
            "benchmark_name": "Qualitative benchmark",
            "paper_doi": "10.1/wrong",
            "task": "doublet_detection",
            "metric": "benchmark_result",
        }],
    )
    _write_tsv(
        data / "evidence_candidates" / "formal_publication_audit.tsv",
        [{
            "publication_id": "CAND_PUB_Scrublet",
            "runtime_recommendation_allowed": "false",
            "audit_labels": "title_only_claim_span;reviewer_identity_unclear",
            "recommended_action": "add_source_span_or_claim_text_before_recommendation",
        }],
    )
    _write_tsv(
        data / "evidence_candidates" / "formal_benchmark_audit.tsv",
        [{
            "benchmark_id": "HR_BMK_Scrublet",
            "runtime_recommendation_allowed": "false",
            "audit_labels": "qualitative_only",
            "recommended_action": "downgrade_to_retrieval_until_numeric_source_verified",
        }],
    )
    _write_tsv(
        data / "evidence_candidates" / "source_registry.tsv",
        [
            {
                "source_id": "SRC_PUB",
                "canonical_title": "Scrublet paper",
                "validation_status": "validated_source_text_available",
                "source_status": "source_text_available",
                "referring_record_ids": "CAND_PUB_Scrublet",
                "referring_tool_names": "Scrublet",
            },
            {
                "source_id": "SRC_BAD",
                "canonical_title": "Wrong benchmark paper",
                "validation_status": "source_metadata_mismatch",
                "validation_issue": "title_doi_mismatch",
                "source_status": "source_metadata_mismatch",
                "referring_record_ids": "HR_BMK_Scrublet",
                "referring_tool_names": "Scrublet",
            },
        ],
    )
    chunks = data / "indexes" / "evidence_chunks.jsonl"
    chunks.parent.mkdir(parents=True, exist_ok=True)
    chunks.write_text(
        json.dumps(
            {
                "chunk_id": "publication:CAND_PUB_Scrublet",
                "evidence_id": "CAND_PUB_Scrublet",
                "tool_name": "Scrublet",
                "task": "doublet_detection",
                "source_span": "Methods paragraph 2",
                "chunk_text": "Scrublet detects doublets from raw counts.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        contracts / "scrublet" / "0.2.3.json",
        {
            "contract_id": "scrublet:0.2.3",
            "contract_version": "test",
            "tool_name": "Scrublet",
            "tool_version": "0.2.3",
            "task": "doublet_detection",
            "language": "python",
            "environment_id": "scRNAseq",
            "wrapper_id": "scrublet_v0_2_3",
            "input_object": "AnnData",
            "required_fields": ["raw counts"],
            "output_artifacts": [],
            "source_review_status": "reviewed",
            "execution_critical_fields_reviewed": True,
            "wrapper_status": "smoke_passed",
            "environment_status": "smoke_passed",
            "execution_status": "integration_passed",
            "scientific_validation_status": "scientific_pilot",
            "enabled_for_execution": True,
            "source_refs": ["README"],
        },
    )
    _write_json(
        environments / "scRNAseq.json",
        {
            "environment_id": "scRNAseq",
            "environment_type": "conda",
            "qualification_status": "integration_passed",
            "integration_test_passed": True,
            "enabled_for_execution": True,
            "package_versions": {"scrublet": "0.2.3"},
        },
    )
    return data, contracts, environments, output


def test_governance_model_blocks_non_trusted_recommendation():
    with pytest.raises(ValidationError):
        KGGovernance(
            layer="frozen",
            recommendation_eligible=True,
            source_bound=True,
        )


def test_builder_freezes_qualitative_and_quarantines_metadata_mismatch(tmp_path):
    data, contracts, environments, output = _graph_fixture(tmp_path)
    nodes, edges, quality = EvidenceGraphBuilder(
        data_dir=data,
        contract_root=contracts,
        environment_root=environments,
        package_root=tmp_path / "packages",
        output_dir=output,
    ).build(write=True)
    by_id = {node.node_id: node for node in nodes}

    assert by_id["publication:CAND_PUB_Scrublet"].governance.layer == "frozen"
    assert by_id["benchmark:HR_BMK_Scrublet"].governance.layer == "quarantined"
    assert by_id["source:SRC_BAD"].governance.layer == "quarantined"
    assert by_id["contract:scrublet:0.2.3"].governance.layer == "execution_verified"
    scrublet_node_id = next(
        node.node_id for node in nodes if node.node_type == "Tool" and node.label == "Scrublet"
    )
    assert any(
        edge.source_id == scrublet_node_id
        and edge.target_id == "source:SRC_PUB"
        and edge.relation == "HAS_EVIDENCE_SOURCE"
        for edge in edges
    )
    assert quality.frozen_recommendation_leakage_count == 0
    assert quality.dangling_edge_count == 0
    assert quality.integrity_passed is True


def test_query_explains_contract_and_frozen_evidence(tmp_path):
    data, contracts, environments, output = _graph_fixture(tmp_path)
    EvidenceGraphBuilder(
        data_dir=data,
        contract_root=contracts,
        environment_root=environments,
        package_root=tmp_path / "packages",
        output_dir=output,
    ).build(write=True)
    query = EvidenceGraphQuery(output)
    explanation = query.explain_tool("Scrublet")

    assert explanation.trusted_tasks == ["doublet detection"]
    assert len(explanation.contracts) == 1
    assert len(explanation.environments) == 1
    assert len(explanation.frozen_or_quarantined) >= 2
    assert any("conditional" in warning.casefold() for warning in explanation.warnings)


def test_view_and_offline_agent_store_prefer_governed_snapshot(tmp_path):
    data, contracts, environments, output = _graph_fixture(tmp_path)
    EvidenceGraphBuilder(
        data_dir=data,
        contract_root=contracts,
        environment_root=environments,
        package_root=tmp_path / "packages",
        output_dir=data / "knowledge_graph_v2",
    ).build(write=True)

    graph = build_knowledge_graph_view(
        data,
        selected_kinds=("Tool", "Task", "ToolContract", "Environment"),
        max_nodes=50,
    )
    html = build_knowledge_graph_html(graph)
    store = OfflineGraphStore(data_dir=data)
    candidates = store.find_candidates("doublet detection", "scRNA-seq")

    assert graph.inventory["contracts"] == 1
    assert graph.inventory["frozen"] >= 2
    assert "execution_verified" in html
    assert "滚轮：缩放" in html
    assert "拖动画布：平移" in html
    assert "拖动节点：调整布局" in html
    assert "expandNeighbors" in html
    assert "addEventListener('wheel'" in html
    assert "addEventListener('pointermove'" in html
    assert store.kg_v2_available is True
    assert len(candidates) == 1
    assert candidates[0]["tool_name"] == "Scrublet"
    assert candidates[0]["candidate_basis"] == "execution_verified"
    assert candidates[0]["graph_score"] > 2.0
    assert [path["relation"] for path in candidates[0]["graph_paths"]] == [
        "EXECUTES_TASK",
        "SUPPORTS_MODALITY",
    ]


def test_graph_ranking_separates_verified_and_hypothesis_paths(tmp_path):
    data, contracts, environments, _ = _graph_fixture(tmp_path)
    output = data / "knowledge_graph_v2"
    EvidenceGraphBuilder(
        data_dir=data,
        contract_root=contracts,
        environment_root=environments,
        package_root=tmp_path / "packages",
        output_dir=output,
    ).build(write=True)
    query = EvidenceGraphQuery(output)

    matches = query.rank_tools(task="doublet detection", modality="single-cell RNA-seq")

    assert len(matches) == 1
    assert matches[0].candidate_basis == "execution_verified"
    assert matches[0].contract_available is True
    assert matches[0].paths[0]["governance_layer"] == "execution_verified"


def test_repository_snapshot_has_no_frozen_evidence_leakage(tmp_path):
    root = Path(__file__).resolve().parents[1]
    _, _, quality = EvidenceGraphBuilder(
        data_dir=root / "data",
        contract_root=root / "contracts" / "tools",
        environment_root=root / "execution" / "environments",
        package_root=root / ".sckg_exec" / "packages",
        output_dir=tmp_path / "snapshot",
    ).build(write=True)

    assert quality.node_count > 100
    assert quality.dangling_edge_count == 0
    assert quality.frozen_recommendation_leakage_count == 0
    assert quality.formal_publication_allowed_count == 0
    assert quality.formal_benchmark_allowed_count == 0
    assert quality.integrity_passed is True
    assert quality.connected_component_count <= 3
    assert quality.largest_component_ratio > 0.99
    assert quality.tool_relation_coverage_rate == 1.0
    assert quality.tool_semantic_coverage_rate > 0.9


def test_full_catalog_snapshot_adds_source_bound_categories_and_references(tmp_path):
    data, contracts, environments, _ = _graph_fixture(tmp_path)
    snapshot = data / "catalog" / "scrna_tools_snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "Tool": "Scrublet",
                        "Platform": "Python",
                        "Code": "https://example.org/scrublet",
                        "Description": "Doublet detection",
                        "License": "MIT",
                        "Added": "2019-01-01",
                        "Updated": "2026-01-01",
                        "Categories": ["QualityControl"],
                        "Publications": [
                            {
                                "Title": "Scrublet paper",
                                "DOI": "10.1/scrublet",
                                "Date": "2019",
                                "Citations": 10,
                            }
                        ],
                        "Preprints": [],
                        "Citations": 10,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = data / "knowledge_graph_v2"
    EvidenceGraphBuilder(
        data_dir=data,
        contract_root=contracts,
        environment_root=environments,
        package_root=tmp_path / "packages",
        output_dir=output,
    ).build(write=True)
    query = EvidenceGraphQuery(output)
    explanation = query.explain_tool("Scrublet")
    quality = json.loads((output / "quality_report.json").read_text(encoding="utf-8"))

    assert [item["label"] for item in explanation.catalog_categories] == ["Quality Control"]
    assert len(explanation.catalog_references) == 1
    assert explanation.catalog_references[0]["recommendation_eligible"] is False
    assert quality["catalog_snapshot_available"] is True
    assert quality["catalog_category_coverage_rate"] == 1.0
    assert quality["catalog_publication_count"] == 1


def test_rebuild_preserves_verified_shadow_import_only_when_hashes_match(tmp_path):
    data, contracts, environments, output = _graph_fixture(tmp_path)
    builder = EvidenceGraphBuilder(
        data_dir=data,
        contract_root=contracts,
        environment_root=environments,
        package_root=tmp_path / "packages",
        output_dir=output,
    )
    builder.build(write=True)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["neo4j_imported"] = True
    manifest["neo4j_import_status"] = "shadow_import_verified"
    manifest_path.write_text(json.dumps(manifest))

    builder.build(write=True)
    rebuilt = json.loads(manifest_path.read_text())

    assert rebuilt["neo4j_imported"] is True
    assert rebuilt["neo4j_import_status"] == "shadow_import_verified"
