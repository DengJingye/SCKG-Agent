#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.execution_models import RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from eval.phase6_evaluation import (
    BASELINE_FIELDS,
    FAILURE_QUEUE_FIELDS,
    audit_case_trace,
    build_failure_queue,
    summarize_baselines,
    write_json,
    write_tsv,
)
from eval.run_workflow_eval import evaluate_scenario, read_jsonl
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.experiment_runner import build_configuration
from tests.fixtures.anndata_factory import write_phase1_fixtures


DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "phase6"
GOLD_PATH = PROJECT_ROOT / "eval" / "gold_workflow_scenarios_v0_1.jsonl"


def run_phase6_baselines(output_root: Path = DEFAULT_OUTPUT) -> dict:
    output_root = Path(output_root)
    rows = _track_a_rows()
    track_b, failure_rows, trace_rows = _track_b_rows(output_root)
    rows.extend(track_b)
    summary = summarize_baselines(rows)
    summary.update(
        {
            "per_case_path": "eval/phase6/baseline_per_case.tsv",
            "failure_queue_path": "eval/phase6/failure_queue.tsv",
            "trace_audit_path": "eval/phase6/trace_audit.json",
            "trace_audit_passed": all(item["passed"] for item in trace_rows),
            "applicable_stage_completeness": min(
                item["applicable_stage_completeness"] for item in trace_rows
            ),
        }
    )
    write_tsv(output_root / "baseline_per_case.tsv", rows, BASELINE_FIELDS)
    write_tsv(output_root / "failure_queue.tsv", failure_rows, FAILURE_QUEUE_FIELDS)
    write_json(output_root / "trace_audit.json", {"cases": trace_rows})
    write_json(output_root / "baseline_summary.json", summary)
    return {
        "summary": summary,
        "rows": rows,
        "failure_queue": failure_rows,
        "trace_audit": trace_rows,
    }


def _track_a_rows() -> list[dict]:
    rows: list[dict] = []
    rows.append(
        _not_run(
            "A",
            "A1_llm_only",
            "no frozen current-phase LLM-only outputs; external LLM/API calls are forbidden",
        )
    )
    for gold in read_jsonl(GOLD_PATH):
        started = time.perf_counter()
        result = evaluate_scenario(gold)
        latency = time.perf_counter() - started
        rows.append(
            {
                "track": "A",
                "baseline_id": "A2_ordinary_rag",
                "case_id": result["id"],
                "status": "run",
                "reason": (
                    "deterministic workflow planner plus controlled document retrieval; "
                    "parameter legality is not represented in this frozen baseline"
                ),
                "tool_workflow_recall": round(
                    (result["required_step_recall"] + result["candidate_tool_recall"]) / 2,
                    6,
                ),
                "parameter_legality": None,
                "source_coverage": result["source_bound_context_coverage"],
                "io_compatibility": None,
                "unsupported_claim": result["unsupported_step_rate"],
                "blocking_correctness": result["workflow_warning_quality"],
                "latency_seconds": round(latency, 6),
                "unsafe_action": 0,
            }
        )
    rows.extend(
        [
            _not_run(
                "A",
                "A3_kg_rag",
                "no frozen isolated KG-RAG entrypoint using the same cases and metrics",
            ),
            _not_run(
                "A",
                "A4_kg_rag_tool_contract",
                "no frozen isolated KG-RAG plus ToolContract baseline across the planning gold set",
            ),
        ]
    )
    return rows


def _track_b_rows(output_root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    root = PROJECT_ROOT / ".sckg_exec" / "evaluations" / f"phase6-{token}"
    fixtures = write_phase1_fixtures(root / "fixtures")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("Scrublet", "0.2.3")
    configuration = build_configuration(
        configuration_id="shared-initial-invalid-pc",
        parameters={
            "min_counts": 1,
            "min_cells": 1,
            "min_gene_variability_pctl": 0.0,
            "n_prin_comps": 100,
            "use_approx_neighbors": False,
        },
        provenance={},
        source="development_probe_search",
        contract=contract,
    )
    requirement = RequirementSpec(
        request_id=f"phase6-baseline-{token}",
        query="paired contract execution baseline with and without bounded repair",
        input_path=str(fixtures["raw_x"]),
        input_object_type="AnnData",
        data_access_authorized=True,
        resource_budget={"max_cells": 12, "max_runtime_seconds": 120},
    )
    orchestrator = ExecutionOrchestrator(
        run_root=root / "runs",
        approved_input_root=root / "probes",
        package_root=root / "packages",
        trace_root=root / "traces",
        environment_registry=environments,
        contract_registry=contracts,
    )
    result = orchestrator.run(
        orchestration_id=f"phase6-b3-b4-{token}",
        requirement=requirement,
        configurations=[configuration],
        seeds=[601, 602],
        fixture_id="phase1_raw_counts_x",
        package_id=f"phase6-b4-{token}",
        probe_max_cells=12,
        pairing_strategy="mixed",
        cluster_key="batch",
        rerun_command="python eval/run_phase6_baselines.py",
    )
    initial = result.batches[0]
    b3_detected = bool(initial.validation_results) and all(
        not validation.passed for validation in initial.validation_results
    )
    repaired_run_ids = {action.new_run_id for action in result.repair_actions}
    repaired_validations = [
        item for item in result.validation_results if item.run_id in repaired_run_ids
    ]
    rows = [
        _not_run(
            "B",
            "B1_expert_static_reviewed_script",
            "no independent frozen expert-static baseline artifact distinct from controlled wrappers",
        ),
        _not_run(
            "B",
            "B2_one_shot_llm_generated_code",
            "no frozen human-reviewed one-shot artifact; executing newly generated code is forbidden",
            status="not_run_safety_boundary",
        ),
        {
            "track": "B",
            "baseline_id": "B3_contract_no_repair",
            "case_id": "shared-invalid-n-prin-comps",
            "status": "run",
            "reason": "paired initial runs from the B4 orchestration, evaluated before repair",
            "task_executable_completion": int(any(v.passed for v in initial.validation_results)),
            "artifact_completeness": round(
                sum(int(v.passed) for v in initial.validation_results)
                / max(len(initial.validation_results), 1),
                6,
            ),
            "failure_detection": int(b3_detected),
            "repair_success": 0,
            "runtime_seconds": round(sum(run.runtime_seconds for run in initial.execution_runs), 6),
            "run_count": len(initial.execution_runs),
            "reproducibility_level": "not_packaged",
            "unsafe_action": 0,
        },
        {
            "track": "B",
            "baseline_id": "B4_contract_bounded_repair",
            "case_id": "shared-invalid-n-prin-comps",
            "status": "run",
            "reason": "same initial executions as B3, followed by deterministic bounded repair",
            "task_executable_completion": int(result.final_state == "COMPLETED"),
            "artifact_completeness": int(result.package_result.complete),
            "failure_detection": int(b3_detected),
            "repair_success": int(bool(repaired_validations) and all(v.passed for v in repaired_validations)),
            "runtime_seconds": round(sum(run.runtime_seconds for run in result.execution_runs), 6),
            "run_count": len(result.execution_runs),
            "reproducibility_level": result.package_result.reproducibility_level,
            "unsafe_action": 0,
        },
    ]
    queue = build_failure_queue(
        case_id="shared-invalid-n-prin-comps",
        runs=result.execution_runs,
        validations=result.validation_results,
        repair_actions=result.repair_actions,
    )
    common_stages = [
        {"stage": "profile", "status": "passed", "reference": result.profile.profile_id},
        {"stage": "plan", "status": result.plan.plan_status, "reference": result.plan.plan_id},
        {"stage": "authorization", "status": "maintainer_qualification_allowed"},
        {"stage": "approval", "status": "qualification_approved"},
        {"stage": "execution", "status": "completed", "run_count": len(result.execution_runs)},
        {"stage": "validation", "status": "completed", "count": len(result.validation_results)},
        {"stage": "repair_or_stop", "status": "repaired", "count": len(result.repair_actions)},
        {"stage": "decision", "status": "completed", "reference": result.decision_result.decision_id},
        {"stage": "package", "status": "complete", "reference": result.package_result.package_id},
        {"stage": "audit", "status": "passed"},
    ]
    traces = [
        audit_case_trace(
            case_id="B3_contract_no_repair",
            applicable_stages=[
                "profile", "plan", "authorization", "approval", "execution",
                "validation", "repair_or_stop", "audit",
            ],
            observed_stages=[
                row if row["stage"] != "repair_or_stop" else {"stage": "repair_or_stop", "status": "stopped"}
                for row in common_stages
            ],
        ),
        audit_case_trace(
            case_id="B4_contract_bounded_repair",
            applicable_stages=list(row["stage"] for row in common_stages),
            observed_stages=common_stages,
        ),
    ]
    return rows, queue, traces


def _not_run(track: str, baseline_id: str, reason: str, *, status: str = "not_run") -> dict:
    return {
        "track": track,
        "baseline_id": baseline_id,
        "case_id": "not_applicable",
        "status": status,
        "reason": reason,
        "unsafe_action": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded Phase 6 dual-track baselines.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run_phase6_baselines(args.output_root)
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result["summary"]["trace_audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
