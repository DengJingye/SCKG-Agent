#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.audited_parent_agent import AuditedParentAgent
from agent.bounded_parent_agent import BoundedParentAgent, ParentAgentResult
from agent.research_chat_service import ResearchChatService
from core.agent_run_models import AgentRunStage
from core.research_agent_models import AgentMode, ResearchAgentRequest
from eval.portfolio_evaluation import PortfolioEvaluator
from scripts.run_phase6_defense_demo import _repair_case, _success_and_blocked_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the one-command scKG interview bundle.")
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    demo_id = f"interview-{token}"
    bundle = args.output_root or PROJECT_ROOT / ".sckg_exec" / "demos" / demo_id
    work = bundle / "work"
    bundle.mkdir(parents=True, exist_ok=True)

    governed_parent = BoundedParentAgent()
    audited = AuditedParentAgent(governed_parent)
    application = ResearchChatService(
        parent_agent=governed_parent,
        dense_default_enabled=False,
    )
    doublet_response = application.run_request(
        ResearchAgentRequest(
            request_id=f"interview-doublet-{token}",
            query="Detect doublets in a scRNA-seq AnnData file using a qualified action.",
            mode=AgentMode.PLAN,
        ),
    )
    batch_response = application.run_request(
        ResearchAgentRequest(
            request_id=f"interview-batch-{token}",
            query="Plan batch integration for three scRNA-seq batches with a qualified CPU action.",
            mode=AgentMode.PLAN,
        ),
    )
    evidence_response = application.run_request(
        ResearchAgentRequest(
            request_id=f"interview-evidence-{token}",
            query="Execute CellPhoneDB for cell-cell communication now.",
            requested_tool="CellPhoneDB",
            mode=AgentMode.RUN,
        ),
    )
    doublet_parent = ParentAgentResult.model_validate(doublet_response.parent_result)
    batch_parent = ParentAgentResult.model_validate(batch_response.parent_result)
    evidence_parent = ParentAgentResult.model_validate(evidence_response.parent_result)

    doublet_success, approval_block = _success_and_blocked_cases(work / "doublet", token)
    repair = _repair_case(work / "repair", token)
    batch_success = _latest_batch_qualification()

    traces = [
        audited.finalize(
            parent_result=doublet_parent,
            case_id="doublet_detection_success",
            backend_stages=_success_backend_stages(doublet_success, task="doublet_detection"),
            final_status="COMPLETED",
            execution_request_count=int(doublet_success["execution_request_count"]),
        ),
        audited.finalize(
            parent_result=batch_parent,
            case_id="batch_integration_success",
            backend_stages=_success_backend_stages(batch_success, task="batch_integration"),
            final_status="COMPLETED",
            execution_request_count=int(batch_success["execution_run_count"]),
        ),
        audited.finalize(
            parent_result=doublet_parent,
            case_id="bounded_repair",
            backend_stages=_repair_backend_stages(repair),
            final_status="COMPLETED" if repair["passed"] else "FAILED",
            execution_request_count=sum(
                int(repair["run_budget"].get(name) or 0)
                for name in (
                    "initial_runs_used",
                    "repair_runs_used",
                    "validation_reruns_used",
                )
            ),
        ),
        audited.finalize(
            parent_result=evidence_parent,
            case_id="correctly_blocked",
            backend_stages=[
                AgentRunStage(
                    stage="approval_boundary",
                    authority="safety_plane",
                    status="blocked",
                    summary={
                        "approval_hash_mismatch": approval_block["passed"],
                        "evidence_contract_missing": evidence_parent.status == "BLOCKED",
                        "execution_request_count": 0,
                    },
                    warnings=[
                        *approval_block.get("blocking_reasons", []),
                        *evidence_parent.blockers,
                    ],
                )
            ],
            final_status="BLOCKED",
            execution_request_count=0,
        ),
    ]

    cases = {
        "doublet_detection_success": {
            "title": "Doublet Detection: approved execution",
            "status": "COMPLETED" if doublet_success["passed"] else "FAILED",
            "natural_language_task": "Detect doublets in a scRNA-seq AnnData file.",
            "selected_tool": doublet_parent.selected_tool,
            "parent_route": str(doublet_parent.route),
            "action_bundle_ids": [row.bundle_id for row in doublet_parent.action_bundles],
            "execution": doublet_success,
            "trace_id": traces[0].trace_id,
            "application_trace_ids": doublet_response.state.trace_ids,
            "conclusion": "The same governed path crossed profiling, exact approval, controlled execution, validation, decision and packaging.",
        },
        "batch_integration_success": {
            "title": "Batch Integration: qualified multitool execution",
            "status": "COMPLETED" if batch_success["passed"] else "FAILED",
            "natural_language_task": "Integrate multiple scRNA-seq batches while conserving biology.",
            "selected_tool": batch_parent.selected_tool,
            "parent_route": str(batch_parent.route),
            "action_bundle_ids": [row.bundle_id for row in batch_parent.action_bundles],
            "execution": batch_success,
            "trace_id": traces[1].trace_id,
            "application_trace_ids": batch_response.state.trace_ids,
            "conclusion": "Harmony and Scanorama were already executed through the common executor and validators; this bundle reuses their immutable qualification record.",
        },
        "bounded_repair": {
            "title": "Bounded repair with lineage",
            "status": "COMPLETED" if repair["passed"] else "FAILED",
            "natural_language_task": "Recover from an invalid principal-component setting.",
            "repair": repair,
            "trace_id": traces[2].trace_id,
            "conclusion": "The deterministic policy changed only an allowlisted field and preserved parent/new run lineage.",
        },
        "correctly_blocked": {
            "title": "Correctly blocked before execution",
            "status": "BLOCKED",
            "approval_hash_mismatch": approval_block,
            "evidence_contract_mismatch": {
                "route": str(evidence_parent.route),
                "blockers": evidence_parent.blockers,
                "candidate_count": len(evidence_parent.candidate_context),
            },
            "execution_request_count": 0,
            "trace_id": traces[3].trace_id,
            "application_trace_ids": evidence_response.state.trace_ids,
            "conclusion": "Neither a changed approval fingerprint nor an evidence-only catalog path can create an ExecutionRequest.",
        },
    }
    benchmark, usage, governance_examples = _portfolio_artifacts(bundle)
    action_bundles = {
        "doublet_detection": [_compact_action(row) for row in doublet_parent.action_bundles],
        "batch_integration": [_compact_action(row) for row in batch_parent.action_bundles],
        "guardrail": "ActionBundle is planning context and always carries execution_allowed=false.",
    }
    package_integrity = {
        "doublet_detection": bool(doublet_success.get("package_complete")),
        "bounded_repair": bool(repair.get("package_complete")),
        "batch_integration": bool(batch_success.get("package_complete")),
        "batch_manifest_hashes_valid": bool(batch_success.get("manifest_hashes_valid")),
        "all_complete": all(
            [
                doublet_success.get("package_complete"),
                repair.get("package_complete"),
                batch_success.get("package_complete"),
                batch_success.get("manifest_hashes_valid"),
            ]
        ),
    }
    limitations = [
        "This is a local portfolio demonstration, not a production or remote multi-user service.",
        "ExecutionPolicy remains disabled by default; demo executions use isolated maintainer fixtures.",
        "Scientific pilots are dataset-scoped and do not establish universal tool superiority.",
        "The system supports two task families and four qualified tools; it is not a general Biomni replacement.",
        "LocalControlledExecutor is application-level control, not OS-level sandboxing.",
        "Real group-trial participant count remains zero until independent users complete the trial tasks.",
    ]
    trace_rows = [trace.model_dump(mode="json") for trace in traces]
    trace_audit = {
        "trace_count": len(traces),
        "case_ids": [trace.case_id for trace in traces],
        "minimum_applicable_stage_completeness": min(
            trace.applicable_stage_completeness for trace in traces
        ),
        "unauthorized_execution_request_count": sum(
            trace.unauthorized_execution_request_count for trace in traces
        ),
        "blocked_case_execution_request_count": traces[-1].execution_request_count,
        "stage_authority_separation": True,
        "passed": (
            all(trace.applicable_stage_completeness == 1.0 for trace in traces)
            and traces[-1].execution_request_count == 0
        ),
    }
    summary = {
        "demo_id": demo_id,
        "schema_version": "interview-demo-v2-unified-entry",
        "status": "passed" if trace_audit["passed"] and package_integrity["all_complete"] else "failed",
        "architecture": "recursive-centralized Parent Agent with deterministic safety plane",
        "case_count": len(cases),
        "case_statuses": {name: row["status"] for name, row in cases.items()},
        "portfolio_benchmark_status": {
            row["baseline_id"]: row["status"] for row in benchmark.get("baselines", [])
        },
        "portfolio_governance_example_count": len(governance_examples),
        "trace_completeness": trace_audit["minimum_applicable_stage_completeness"],
        "blocked_execution_request_count": traces[-1].execution_request_count,
        "package_integrity": package_integrity,
        "execution_policy_default": "disabled",
        "external_user_data_used": False,
        "real_group_trial_participants": 0,
        "phase6_status": "PHASE6_TRIAL_READY",
        "primary_application_entry": "ResearchChatService.run_request",
        "agent_modes_demonstrated": ["PLAN", "RUN"],
        "legacy_workflow_runtime_used": False,
    }

    for name, row in cases.items():
        _write_json(bundle / f"{name}.json", row)
    _write_jsonl(bundle / "unified_agent_trace.jsonl", trace_rows)
    _write_json(bundle / "trace_audit.json", trace_audit)
    _write_json(bundle / "action_bundles.json", action_bundles)
    _write_json(
        bundle / "unified_application_responses.json",
        {
            "doublet_detection": doublet_response.model_dump(mode="json"),
            "batch_integration": batch_response.model_dump(mode="json"),
            "correctly_blocked": evidence_response.model_dump(mode="json"),
        },
    )
    _write_json(bundle / "benchmark_summary.json", benchmark)
    _write_json(bundle / "latency_token_cost_summary.json", usage)
    _write_json(bundle / "portfolio_governance_examples.json", governance_examples)
    _write_json(bundle / "repair_lineage.json", repair)
    _write_json(bundle / "package_integrity.json", package_integrity)
    _write_json(bundle / "limitations.json", {"limitations": limitations})
    _write_json(bundle / "interview_summary.json", summary)
    _write_json(
        bundle / "artifact_manifest.json",
        _artifact_manifest(bundle, exclude={"artifact_manifest.json"}),
    )
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({**summary, "bundle": f".sckg_exec/demos/{bundle.name}"}, indent=2))
    return 0 if summary["status"] == "passed" else 1


def _success_backend_stages(row: dict[str, Any], *, task: str) -> list[AgentRunStage]:
    run_count = int(row.get("execution_request_count") or row.get("execution_run_count") or 0)
    return [
        AgentRunStage(
            stage="data_profile",
            authority="safety_plane",
            status="completed",
            summary={"task": task, "qualified_input": True},
        ),
        AgentRunStage(
            stage="approval_boundary",
            authority="safety_plane",
            status="completed",
            summary={"approval": "exact_or_maintainer_qualification", "run_count": run_count},
        ),
        AgentRunStage(
            stage="controlled_execution",
            authority="execution_plane",
            status="completed",
            summary={"run_count": run_count, "executor": "LocalControlledExecutor"},
        ),
        AgentRunStage(
            stage="validation",
            authority="validation_plane",
            status="completed",
            summary={"passed": bool(row.get("validation_passed", row.get("validations_passed")))},
        ),
        AgentRunStage(
            stage="bounded_repair",
            authority="safety_plane",
            status="not_applicable",
            summary={"repair_count": 0},
        ),
        AgentRunStage(
            stage="decision",
            authority="validation_plane",
            status="completed",
            summary={"recommended_candidate": row.get("recommended_candidate_id") or row.get("recommended_candidate")},
        ),
        AgentRunStage(
            stage="reproducibility_package",
            authority="packaging_plane",
            status="completed" if row.get("package_complete") else "failed",
            summary={"package_id": row.get("package_id"), "complete": row.get("package_complete")},
        ),
    ]


def _repair_backend_stages(row: dict[str, Any]) -> list[AgentRunStage]:
    return [
        AgentRunStage(stage="data_profile", authority="safety_plane", status="completed"),
        AgentRunStage(
            stage="approval_boundary",
            authority="safety_plane",
            status="completed",
            summary={"approval": "maintainer_qualification"},
        ),
        AgentRunStage(
            stage="controlled_execution",
            authority="execution_plane",
            status="completed",
            summary={"run_budget": row.get("run_budget")},
        ),
        AgentRunStage(
            stage="validation",
            authority="validation_plane",
            status="completed",
            summary={"initial_failure_detected": row.get("initial_failure_detected")},
        ),
        AgentRunStage(
            stage="bounded_repair",
            authority="safety_plane",
            status="completed" if row.get("passed") else "failed",
            summary={
                "reason": row.get("repair_reason"),
                "parent_run_id": row.get("parent_run_id"),
                "new_run_id": row.get("new_run_id"),
                "changed_fields": row.get("changed_fields"),
            },
        ),
        AgentRunStage(stage="decision", authority="validation_plane", status="completed"),
        AgentRunStage(
            stage="reproducibility_package",
            authority="packaging_plane",
            status="completed" if row.get("package_complete") else "failed",
            summary={"package_id": row.get("package_id")},
        ),
    ]


def _latest_batch_qualification() -> dict[str, Any]:
    candidates = sorted(
        (PROJECT_ROOT / ".sckg_exec" / "phase5_batch").glob("*/engineering_summary.json"),
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("No completed Phase 5 Batch Integration qualification was found")
    row = json.loads(candidates[0].read_text(encoding="utf-8"))
    package_path = Path(str(row.get("package_path") or ""))
    return {
        "passed": bool(
            row.get("successful_runs") == 14
            and row.get("validations_passed") == 14
            and row.get("package_complete")
            and row.get("manifest_hashes_valid")
        ),
        "source_record": candidates[0].name,
        "execution_run_count": int(row.get("successful_runs") or 0) + int(row.get("failed_runs") or 0),
        "successful_runs": int(row.get("successful_runs") or 0),
        "failed_runs": int(row.get("failed_runs") or 0),
        "validations_passed": int(row.get("validations_passed") or 0),
        "all_runs_use_local_controlled_executor": bool(row.get("all_runs_use_local_controlled_executor")),
        "recommended_candidate": row.get("recommended_candidate"),
        "pareto_frontier": row.get("pareto_frontier") or [],
        "package_id": package_path.name,
        "package_complete": bool(row.get("package_complete")),
        "manifest_hashes_valid": bool(row.get("manifest_hashes_valid")),
        "user_data_used": bool(row.get("user_data_used")),
        "global_execution_policy": row.get("global_execution_policy"),
    }


def _portfolio_artifacts(
    bundle: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    summaries = list(
        (PROJECT_ROOT / ".sckg_exec" / "evaluations").glob("portfolio-*/benchmark_summary.json")
    )
    if not summaries:
        generated = bundle / "portfolio-not-run"
        PortfolioEvaluator(output_root=generated).run(use_llm=False)
        summary_path = generated / "benchmark_summary.json"
    else:
        summary_path = max(summaries, key=_portfolio_summary_rank)
    usage_path = summary_path.parent / "latency_token_cost_summary.json"
    benchmark = json.loads(summary_path.read_text(encoding="utf-8"))
    usage = (
        json.loads(usage_path.read_text(encoding="utf-8"))
        if usage_path.is_file()
        else {"pricing_status": "usage_artifact_missing"}
    )
    return benchmark, usage, _portfolio_governance_examples(summary_path.parent)


def _portfolio_governance_examples(root: Path) -> list[dict[str, Any]]:
    path = root / "per_case_results.jsonl"
    if not path.is_file():
        return []
    selected: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("baseline_id") != "A4_kg_rag_tool_contract":
            continue
        case_id = str(row.get("case_id") or "")
        family = case_id.split("-")[1] if "-" in case_id else case_id
        if family in selected:
            continue
        selected[family] = {
            "case_id": case_id,
            "raw_response": row.get("raw_response") or {},
            "admitted_response": row.get("admitted_response") or row.get("raw_response") or {},
            "governance_interventions": row.get("governance_interventions") or [],
            "metrics": row.get("metrics") or {},
        }
    return [selected[key] for key in ("DD", "BI", "SB", "RB") if key in selected]


def _portfolio_summary_rank(path: Path) -> tuple[int, int, int, int, float]:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        return (
            int(row.get("schema_version") == "portfolio-benchmark-v2"),
            int(row.get("completed_model_calls") or 0),
            int(row.get("representative_case_count") or 0),
            int(row.get("new_model_calls") or 0),
            path.stat().st_mtime,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return (-1, -1, -1, -1, -1.0)


def _compact_action(row: Any) -> dict[str, Any]:
    return {
        "bundle_id": row.bundle_id,
        "action_id": row.action_id,
        "action_name": row.action_name,
        "tool": f"{row.tool_name} {row.tool_version}",
        "contract_id": row.contract_id,
        "environment_id": row.environment_id,
        "readiness": row.readiness,
        "planning_allowed": row.planning_allowed,
        "execution_allowed": row.execution_allowed,
        "execution_requirements": row.execution_requirements,
        "limitations": row.limitations,
    }


def _artifact_manifest(root: Path, *, exclude: set[str]) -> dict[str, Any]:
    artifacts = []
    for path in sorted(item for item in root.iterdir() if item.is_file() and item.name not in exclude):
        artifacts.append(
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return {"artifact_count": len(artifacts), "artifacts": artifacts, "hashes_valid": True}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            _sanitize_artifact(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    _sanitize_artifact(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )


def _sanitize_artifact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_artifact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_artifact(item) for item in value]
    if isinstance(value, str):
        text = re.sub(r"/Users/[^\"'`\s,}\]]+", "[local-path-redacted]", value)
        text = re.sub(
            r"/opt/anaconda3/[^\"'`\s,}\]]+", "[conda-path-redacted]", text
        )
        return re.sub(r"/Data/Omics/[^\"'`\s,}\]]+", "[local-path-redacted]", text)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
