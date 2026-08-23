from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.bounded_parent_agent import BoundedParentAgent, ParentAgentRequest
from core.settings import PROJECT_ROOT
from core.tool_contract_registry import ToolContractRegistry
from engine.action_bundle_retriever import ActionBundleRetriever
from engine.data_profiler import AnnDataProfiler
from engine.decision_graph_builder import DecisionGraphBuilder
from engine.decision_graph_query import DecisionGraphQuery
from execution.environment_registry import EnvironmentRegistry
from tests.fixtures.anndata_factory import write_phase1_fixtures


def main() -> None:
    graph_dir = PROJECT_ROOT / "data" / "decision_graph_v3"
    _, edges, quality = DecisionGraphBuilder(
        data_dir=PROJECT_ROOT / "data",
        output_dir=graph_dir,
    ).build(write=True)
    query = DecisionGraphQuery(graph_dir)
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    retriever = ActionBundleRetriever(
        graph_query=query,
        contract_registry=contracts,
        environment_registry=environments,
    )

    generic = retriever.retrieve(task="doublet detection", modality="scRNA-seq")
    with tempfile.TemporaryDirectory(prefix="sckg-action-space-") as directory:
        fixtures = write_phase1_fixtures(Path(directory))
        profiler = AnnDataProfiler()
        raw_profile = profiler.profile(fixtures["raw_x"])
        scaled_profile = profiler.profile(fixtures["scaled"])
        raw = retriever.retrieve(
            task="doublet detection",
            modality="scRNA-seq",
            data_profile=raw_profile,
        )
        scaled = retriever.retrieve(
            task="doublet detection",
            modality="scRNA-seq",
            data_profile=scaled_profile,
        )

    parent_result = BoundedParentAgent(
        decision_graph_query=query,
        action_bundle_retriever=retriever,
    ).run(
        ParentAgentRequest(
            request_id="action-space-v1-smoke",
            query="Plan doublet detection for an scRNA-seq AnnData dataset",
        )
    )
    manifest = json.loads((graph_dir / "manifest.json").read_text(encoding="utf-8"))
    bundle_path = PROJECT_ROOT / manifest["action_bundles_path"]
    bundle_hash_valid = _sha256(bundle_path) == manifest["action_bundles_sha256"]
    action_rows = query.list_actions()

    assert quality.integrity_passed
    assert quality.action_count == 2
    assert quality.action_implementation_count == 2
    assert quality.action_bundle_count == 2
    assert len(action_rows) == 2
    doublet_action = next(
        row for row in action_rows if row["action_id"] == "action:doublet-detection"
    )
    batch_action = next(
        row for row in action_rows if row["action_id"] == "action:batch-integration"
    )
    assert doublet_action["tools"] == ["scDblFinder", "Scrublet"]
    assert batch_action["tools"] == []
    assert {bundle.action_id for bundle in generic.bundles} == {
        "action:doublet-detection"
    }
    assert all(bundle.failure_modes for bundle in generic.bundles)
    assert all(bundle.validation_rules for bundle in generic.bundles)
    assert all(bundle.know_how for bundle in generic.bundles)
    assert all(bundle.data_compatibility == "compatible" for bundle in raw.bundles)
    assert all(bundle.data_compatibility == "blocked" for bundle in scaled.bundles)
    assert all(bundle.execution_allowed is False for bundle in generic.bundles)
    assert generic.execution_request_count == 0
    assert raw.execution_request_count == 0
    assert scaled.execution_request_count == 0
    assert parent_result.execution_request_count == 0
    assert bundle_hash_valid
    assert not any(edge.relation.startswith("HYPOTHESIZED_") for edge in edges)

    summary = {
        "status": "passed",
        "snapshot_version": quality.snapshot_version,
        "action_count": quality.action_count,
        "action_implementation_count": quality.action_implementation_count,
        "action_bundle_count": len(generic.bundles),
        "qualified_action": doublet_action,
        "planning_only_action": batch_action,
        "generic_tools": [bundle.tool_name for bundle in generic.bundles],
        "raw_counts_compatible": [
            bundle.tool_name
            for bundle in raw.bundles
            if bundle.data_compatibility == "compatible"
        ],
        "scaled_blocked": scaled.blocked_candidates,
        "failure_modes_present": all(bundle.failure_modes for bundle in generic.bundles),
        "validation_rules_present": all(
            bundle.validation_rules for bundle in generic.bundles
        ),
        "know_how_present": all(bundle.know_how for bundle in generic.bundles),
        "action_bundle_snapshot": str(bundle_path.relative_to(PROJECT_ROOT)),
        "action_bundle_hash_valid": bundle_hash_valid,
        "parent_agent_route": str(parent_result.route),
        "execution_request_count": parent_result.execution_request_count,
        "execution_authorized_by_action_bundle": False,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
