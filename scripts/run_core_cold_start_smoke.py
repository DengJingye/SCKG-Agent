from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import anndata as ad
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from connectors.offline_graph import OfflineGraphStore
from core.execution_models import ExecutionBudget, RequirementSpec
from core.knowledge_intelligence_models import HybridRetrievalRequest
from core.settings import get_settings
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from engine.hybrid_retrieval import HybridRetrievalService
from execution.environment_registry import EnvironmentRegistry
from execution.runtime_pack_manager import RuntimePackManager


def main() -> int:
    os.environ["SCKG_PRIVACY_MODE"] = "strict_offline"
    os.environ["SCKG_EXTERNAL_NETWORK_ALLOWED"] = "false"
    os.environ["SCKG_OFFLINE_LLM"] = "true"
    get_settings.cache_clear()

    manager = RuntimePackManager(allow_legacy_environments=False)
    probes = manager.inventory()
    no_runtime_ready = bool(probes) and all(not probe.ready for probe in probes)

    graph = OfflineGraphStore()
    graph_ready = graph.kg_v2_available and len(graph.tools) >= 1_800
    retrieval = HybridRetrievalService(
        dense_matrix_path=Path(tempfile.gettempdir()) / "sckg-no-dense-vectors.npy",
        dense_metadata_path=Path(tempfile.gettempdir()) / "sckg-no-dense-metadata.json",
    ).search(
        HybridRetrievalRequest(
            query="doublet detection raw count input requirements",
            canonical_tasks=["doublet_detection"],
            tool_names=["Scrublet", "scDblFinder"],
            enable_dense=True,
            top_k=12,
        )
    )
    sparse_ready = (
        bool(retrieval.hits)
        and "sqlite_fts5_bm25" in retrieval.pipeline
        and "local_dense_skipped" in retrieval.pipeline
        and retrieval.dense_status != "ready"
    )
    canonical_manifest_path = PROJECT_ROOT / "data" / "canonical_knowledge" / "manifest.json"
    canonical_manifest = json.loads(canonical_manifest_path.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="sckg-core-cold-start-") as directory:
        path = Path(directory) / "fixture.h5ad"
        rng = np.random.default_rng(20260719)
        matrix = rng.poisson(1.2, size=(40, 24)).astype(np.int32)
        ad.AnnData(X=matrix).write_h5ad(path)
        profile = AnnDataProfiler().profile(path)

        environments = EnvironmentRegistry()
        contracts = ToolContractRegistry(environment_registry=environments)
        contract = contracts.load("scrublet", "0.2.3")
        requirement = RequirementSpec(
            request_id="core_cold_start_doublet_plan",
            query="Create a dry-run doublet detection plan",
            input_path=str(path),
            input_object_type="AnnData",
            data_access_authorized=True,
            execution_authorized=False,
        )
        plan = ExecutionPlanCompiler(contracts).compile(
            requirement=requirement,
            data_profile=profile,
            tool_contract=contract,
            environment=environments.get("scRNAseq"),
            execution_budget=ExecutionBudget(),
        )

    settings = get_settings()
    result = {
        "schema_version": "1.0",
        "strict_offline": settings.privacy_mode.value == "strict_offline",
        "external_network_allowed": settings.external_network_allowed,
        "runtime_pack_count": len(probes),
        "runtime_pack_ready_count": sum(1 for probe in probes if probe.ready),
        "legacy_fallback_disabled": manager.allow_legacy_environments is False,
        "no_runtime_ready": no_runtime_ready,
        "catalog_tool_count": int(canonical_manifest.get("catalog_tool_count") or 0),
        "canonical_tool_node_count": int(
            canonical_manifest.get("canonical_tool_node_count") or 0
        ),
        "local_graph_ready": graph_ready,
        "sparse_retrieval_ready": sparse_ready,
        "retrieval_snippet_count": len(retrieval.hits),
        "retrieval_mode": retrieval.mode,
        "dense_status": retrieval.dense_status,
        "data_profile_count_source": profile.selected_count_source,
        "data_profile_blockers": profile.blocking_errors,
        "workflow_plan_status": plan.plan_status,
        "workflow_execution_eligible": plan.execution_eligible,
        "execution_request_count": 0,
        "project_root_redacted": "[release-root]",
    }
    result["passed"] = all(
        [
            result["strict_offline"],
            not result["external_network_allowed"],
            no_runtime_ready,
            graph_ready,
            sparse_ready,
            profile.selected_count_source == "X",
            not profile.blocking_errors,
            plan.plan_status == "dry_run",
            plan.execution_eligible is False,
            result["execution_request_count"] == 0,
            (PROJECT_ROOT / "app.py").is_file(),
        ]
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
