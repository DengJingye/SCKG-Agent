from __future__ import annotations

from core.action_space_models import ActionBundle
from core.settings import PROJECT_ROOT
from core.tool_contract_registry import ToolContractRegistry
from engine.action_bundle_retriever import ActionBundleRetriever
from engine.data_profiler import AnnDataProfiler
from engine.decision_graph_builder import DecisionGraphBuilder
from engine.decision_graph_query import DecisionGraphQuery
from execution.environment_registry import EnvironmentRegistry
from tests.fixtures.anndata_factory import write_phase1_fixtures


def _retriever(tmp_path):
    output = tmp_path / "decision_graph_v3"
    DecisionGraphBuilder(
        data_dir=PROJECT_ROOT / "data",
        contract_root=PROJECT_ROOT / "contracts" / "tools",
        environment_root=PROJECT_ROOT / "execution" / "environments",
        package_root=PROJECT_ROOT / ".sckg_exec" / "packages",
        output_dir=output,
    ).build(write=True)
    environments = EnvironmentRegistry(PROJECT_ROOT / "execution" / "environments")
    contracts = ToolContractRegistry(
        PROJECT_ROOT / "contracts" / "tools",
        environment_registry=environments,
    )
    return output, ActionBundleRetriever(
        graph_query=DecisionGraphQuery(output),
        contract_registry=contracts,
        environment_registry=environments,
    )


def test_generic_action_bundle_is_governed_planning_context(tmp_path):
    output, retriever = _retriever(tmp_path)
    result = retriever.retrieve(task="doublet detection", modality="scRNA-seq")

    assert {bundle.tool_name for bundle in result.bundles} == {
        "Scrublet",
        "scDblFinder",
    }
    assert {bundle.action_id for bundle in result.bundles} == {
        "action:doublet-detection"
    }
    assert all(bundle.data_compatibility == "generic" for bundle in result.bundles)
    assert all(bundle.planning_allowed for bundle in result.bundles)
    assert all(bundle.execution_contract_qualified for bundle in result.bundles)
    assert all(bundle.execution_allowed is False for bundle in result.bundles)
    assert result.execution_request_count == 0
    assert all(bundle.failure_modes for bundle in result.bundles)
    assert all(bundle.validation_rules for bundle in result.bundles)
    assert all(bundle.know_how for bundle in result.bundles)
    snapshot = output / "action_bundles.jsonl"
    rows = [
        ActionBundle.model_validate_json(line)
        for line in snapshot.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 6


def test_batch_integration_action_bundles_are_qualified_but_do_not_authorize_execution(
    tmp_path,
):
    _, retriever = _retriever(tmp_path)

    result = retriever.retrieve(task="batch integration", modality="scRNA-seq")

    assert {bundle.tool_name for bundle in result.bundles} == {"Harmony", "Scanorama"}
    assert all(bundle.action_id == "action:batch-integration" for bundle in result.bundles)
    assert all(bundle.planning_allowed for bundle in result.bundles)
    assert all(bundle.execution_contract_qualified for bundle in result.bundles)
    assert all(bundle.evaluations for bundle in result.bundles)
    assert all(bundle.execution_allowed is False for bundle in result.bundles)
    assert result.execution_request_count == 0


def test_raw_counts_profile_makes_action_bundles_data_compatible(tmp_path):
    _, retriever = _retriever(tmp_path)
    fixtures = write_phase1_fixtures(tmp_path / "fixtures")
    profile = AnnDataProfiler().profile(fixtures["raw_x"])

    result = retriever.retrieve(
        task="doublet detection",
        modality="scRNA-seq",
        data_profile=profile,
    )

    assert len(result.bundles) == 2
    assert all(bundle.data_compatibility == "compatible" for bundle in result.bundles)
    assert all(bundle.planning_allowed for bundle in result.bundles)
    assert result.blocked_candidates == []


def test_scaled_profile_blocks_action_without_creating_execution_request(tmp_path):
    _, retriever = _retriever(tmp_path)
    fixtures = write_phase1_fixtures(tmp_path / "fixtures")
    profile = AnnDataProfiler().profile(fixtures["scaled"])

    result = retriever.retrieve(
        task="doublet detection",
        modality="scRNA-seq",
        data_profile=profile,
    )

    assert len(result.bundles) == 2
    assert all(bundle.data_compatibility == "blocked" for bundle in result.bundles)
    assert all(not bundle.planning_allowed for bundle in result.bundles)
    assert set(result.blocked_candidates) == {"Scrublet", "scDblFinder"}
    assert result.execution_request_count == 0


def test_source_only_catalog_path_does_not_become_action_bundle(tmp_path):
    _, retriever = _retriever(tmp_path)
    result = retriever.retrieve(
        task="trajectory inference",
        modality="scRNA-seq",
    )

    assert result.bundles == []
    assert result.execution_request_count == 0


def test_annotation_action_bundles_are_planning_only(tmp_path):
    _, retriever = _retriever(tmp_path)

    result = retriever.retrieve(
        task="cell type annotation",
        modality="scRNA-seq",
    )

    assert {bundle.tool_name for bundle in result.bundles} == {
        "CellTypist",
        "SingleR",
    }
    assert all(bundle.readiness == "planning_only" for bundle in result.bundles)
    assert all(bundle.planning_allowed for bundle in result.bundles)
    assert all(
        not bundle.execution_contract_qualified for bundle in result.bundles
    )
    assert all(bundle.execution_allowed is False for bundle in result.bundles)
    assert result.execution_request_count == 0
