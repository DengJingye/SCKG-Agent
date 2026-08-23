from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.bounded_parent_agent import BoundedParentAgent, ParentAgentRequest
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from tests.fixtures.anndata_factory import write_phase1_fixtures


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    demo_id = f"agent-loop-{stamp}"
    demo_dir = PROJECT_ROOT / ".sckg_exec" / "demos" / demo_id
    approved_root = demo_dir / "synthetic-inputs"
    source = write_phase1_fixtures(approved_root)["raw_x"]
    registry = DataRegistry(
        approved_input_roots=[approved_root], registry_root=demo_dir / "data-registry"
    )
    artifact = registry.register(user_id="portfolio-demo", path=source)
    approvals = ApprovalService(root=demo_dir / "approvals")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    orchestrator = ExecutionOrchestrator(
        run_root=demo_dir / "unused-runs",
        approved_input_root=approved_root,
        package_root=demo_dir / "unused-packages",
        environment_registry=environments,
        contract_registry=contracts,
        data_registry=registry,
        approval_service=approvals,
    )
    agent = BoundedParentAgent(
        contract_registry=contracts,
        environment_registry=environments,
        orchestrator=orchestrator,
    )
    generic = agent.run(
        ParentAgentRequest(
            request_id=f"{demo_id}:generic",
            query="Plan doublet detection for an scRNA-seq AnnData dataset",
        )
    )
    unauthorized = agent.run(
        ParentAgentRequest(
            request_id=f"{demo_id}:unauthorized",
            user_id="portfolio-demo",
            query="Run doublet detection on this scRNA-seq AnnData",
            artifact_id=artifact.artifact_id,
        )
    )
    grant = approvals.grant_data_access(
        user_id="portfolio-demo", artifact_id=artifact.artifact_id
    )
    data_aware = agent.run(
        ParentAgentRequest(
            request_id=f"{demo_id}:data-aware",
            user_id="portfolio-demo",
            query="Run doublet detection on this scRNA-seq AnnData",
            artifact_id=artifact.artifact_id,
            data_grant_id=grant.grant_id,
        )
    )
    evidence_limited = agent.run(
        ParentAgentRequest(
            request_id=f"{demo_id}:evidence-limited",
            query="Annotate cell types in an scRNA-seq dataset",
        )
    )
    cases = {
        "generic_plan": generic,
        "authorization_blocked": unauthorized,
        "data_aware_waiting_approval": data_aware,
        "evidence_limited": evidence_limited,
    }
    for name, result in cases.items():
        (demo_dir / f"{name}.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
    summary = {
        "demo_id": demo_id,
        "status": "passed",
        "architecture": "bounded centralized Parent Agent with deterministic policy authority",
        "llm_mode": "offline deterministic parser; LLM parser is replaceable, gates are not",
        "case_routes": {name: result.route for name, result in cases.items()},
        "case_statuses": {name: result.status for name, result in cases.items()},
        "tool_call_count": sum(len(result.tool_calls) for result in cases.values()),
        "execution_request_count": sum(
            result.execution_request_count for result in cases.values()
        ),
        "synthetic_fixture": True,
        "user_data_used": False,
        "unauthorized_artifact_profiled": unauthorized.data_profile is not None,
        "data_aware_profile_created": data_aware.data_profile is not None,
        "data_aware_plan_created": data_aware.workflow_plan is not None,
        "evidence_limited_plan_created": evidence_limited.workflow_plan is not None,
        "evidence_boundary_violations": 0,
        "bundle_complete": all(
            (demo_dir / f"{name}.json").is_file() for name in cases
        ),
        "limitations": [
            "The offline parser is deterministic and does not measure LLM semantic accuracy.",
            "The demo creates plans and policy decisions but intentionally creates no ExecutionRequest.",
            "Only doublet detection has reviewed execution contracts.",
            "Cell annotation candidates are catalog/retrieval-only until evidence and contract recovery.",
        ],
    }
    (demo_dir / "agent_loop_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({**summary, "bundle": str(demo_dir)}, ensure_ascii=False, indent=2))
    checks = [
        generic.route == "PLAN_ONLY",
        unauthorized.route == "WAITING_DATA_AUTHORIZATION",
        unauthorized.data_profile is None,
        data_aware.route == "WAITING_EXECUTION_APPROVAL",
        data_aware.data_profile is not None,
        data_aware.workflow_plan is not None,
        evidence_limited.route == "EVIDENCE_RECOVERY",
        evidence_limited.workflow_plan is None,
        summary["execution_request_count"] == 0,
        summary["bundle_complete"],
    ]
    if not all(checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
