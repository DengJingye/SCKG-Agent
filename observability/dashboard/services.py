from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.reflection_memory import (
    DEFAULT_MEMORY_DB,
    DEFAULT_REFLECTION_LOG,
    DEFAULT_SKILL_CANDIDATES_DIR,
    load_reflection_events,
)
from core.trace_context import DEFAULT_TRACE_PATH, load_traces
from core.trial_telemetry import DEFAULT_TRIAL_TELEMETRY, TrialTelemetryStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOUBLET_RECOVERY_DEMO = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "doublet_detection_recovery_demo.json"
)
DEFAULT_DECISION_WORKFLOW_DEMO = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "decision_workflow_demo_v1.json"
)
DEFAULT_PDF_INGEST_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_ingest_summary.json"
)
DEFAULT_PDF_DOWNLOAD_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_download_summary.json"
)
DEFAULT_CORE_SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core_tool_source_manifest_v2.tsv"
)
DEFAULT_ALGORITHM_REPRESENTATION_AUDIT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "algorithm_representation_v2_audit.tsv"
)
DEFAULT_ALGORITHM_REPRESENTATION_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "algorithm_representation_v2_summary.json"
)
DEFAULT_EVIDENCE_CHUNKS = PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl"
DEFAULT_LITERATURE_SOURCE_COVERAGE_TSV = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core_literature_source_coverage.tsv"
)
DEFAULT_LITERATURE_SOURCE_COVERAGE_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core_literature_source_coverage_summary.json"
)
DEFAULT_SOURCE_REGISTRY = PROJECT_ROOT / "data" / "evidence_candidates" / "source_registry.tsv"
DEFAULT_PDF_CANDIDATE_REGISTRY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "pdf_candidate_registry.tsv"
)
DEFAULT_SOURCE_VALIDATION_REPORT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "source_validation_report.tsv"
)
DEFAULT_SOURCE_ACQUISITION_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "source_acquisition_summary.json"
)
DEFAULT_SOURCE_EXTRACTION_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "source_extraction_summary.json"
)
DEFAULT_PHASE6_BASELINE_SUMMARY = PROJECT_ROOT / "eval" / "phase6" / "baseline_summary.json"
DEFAULT_PHASE6_BASELINE_CASES = PROJECT_ROOT / "eval" / "phase6" / "baseline_per_case.tsv"
DEFAULT_PHASE6_FAILURE_QUEUE = PROJECT_ROOT / "eval" / "phase6" / "failure_queue.tsv"
DEFAULT_PHASE6_TRACE_AUDIT = PROJECT_ROOT / "eval" / "phase6" / "trace_audit.json"
DEFAULT_PHASE6_DEMO_ROOT = PROJECT_ROOT / ".sckg_exec" / "demos"
DEFAULT_PORTFOLIO_ROOT = PROJECT_ROOT / ".sckg_exec" / "portfolio"


class AgentLoopDemoService:
    """Read the newest bounded Parent Agent demo without running the Agent."""

    CASE_FILES = {
        "generic_plan": "Generic governed plan",
        "authorization_blocked": "Authorization gate",
        "data_aware_waiting_approval": "Data-aware plan",
        "evidence_limited": "Evidence-limited task",
    }

    def __init__(self, root: Path | None = None) -> None:
        configured = os.environ.get("SCKG_AGENT_LOOP_DEMO_ROOT")
        self.root = Path(root or configured or DEFAULT_PHASE6_DEMO_ROOT)

    def latest_bundle(self) -> Dict[str, Any]:
        if not self.root.is_dir():
            return {}
        candidates = sorted(
            (path for path in self.root.glob("agent-loop-*") if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        for bundle in candidates:
            required = [bundle / "agent_loop_summary.json"] + [
                bundle / f"{name}.json" for name in self.CASE_FILES
            ]
            if all(path.is_file() for path in required):
                summary = _read_json_file(bundle / "agent_loop_summary.json")
                cases = []
                for name, title in self.CASE_FILES.items():
                    row = _read_json_file(bundle / f"{name}.json")
                    candidates_preview = [
                        {
                            "tool": item.get("tool_name"),
                            "basis": item.get("candidate_basis"),
                            "score": item.get("graph_score"),
                        }
                        for item in (row.get("candidate_context") or [])[:5]
                    ]
                    plan = row.get("workflow_plan") or {}
                    profile = row.get("data_profile") or {}
                    cases.append(
                        {
                            "case_id": name,
                            "title": title,
                            "status": row.get("status", "FAILED"),
                            "route": row.get("route", "BLOCKED"),
                            "summary": row.get("final_summary", ""),
                            "selected_tool": row.get("selected_tool"),
                            "tool_call_count": len(row.get("tool_calls") or []),
                            "execution_request_count": row.get("execution_request_count", 0),
                            "plan_status": plan.get("plan_status"),
                            "plan_steps": len(plan.get("steps") or []),
                            "profile_created": bool(profile),
                            "count_source": profile.get("selected_count_source"),
                            "blockers": row.get("blockers") or [],
                            "next_actions": row.get("next_actions") or [],
                            "candidates": candidates_preview,
                            "tool_calls": row.get("tool_calls") or [],
                        }
                    )
                return {
                    "bundle_id": bundle.name,
                    "status": summary.get("status", "unknown"),
                    "architecture": summary.get("architecture", ""),
                    "llm_mode": summary.get("llm_mode", ""),
                    "tool_call_count": summary.get("tool_call_count", 0),
                    "execution_request_count": summary.get("execution_request_count", 0),
                    "evidence_boundary_violations": summary.get(
                        "evidence_boundary_violations", 0
                    ),
                    "limitations": summary.get("limitations") or [],
                    "cases": cases,
                }
        return {}


class DefenseDemoService:
    """Read the newest fixed Phase 6 defense bundle without executing anything."""

    REQUIRED_FILES = (
        "demo_summary.json",
        "success_case.json",
        "repair_case.json",
        "blocked_case.json",
        "trace_audit.json",
    )

    def __init__(self, root: Path | None = None) -> None:
        configured = os.environ.get("SCKG_DEFENSE_DEMO_ROOT")
        self.root = Path(root or configured or DEFAULT_PHASE6_DEMO_ROOT)

    def latest_bundle(self) -> Dict[str, Any]:
        if not self.root.is_dir():
            return {}
        candidates = sorted(
            (path for path in self.root.glob("phase6-defense-*") if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        for bundle in candidates:
            if all((bundle / name).is_file() for name in self.REQUIRED_FILES):
                return self._load_bundle(bundle)
        return {}

    def _load_bundle(self, bundle: Path) -> Dict[str, Any]:
        summary = _read_json_file(bundle / "demo_summary.json")
        success = _read_json_file(bundle / "success_case.json")
        repair = _read_json_file(bundle / "repair_case.json")
        blocked = _read_json_file(bundle / "blocked_case.json")
        trace = _read_json_file(bundle / "trace_audit.json")
        trace_by_case = {
            row.get("case_id"): row for row in trace.get("cases") or []
        }
        return {
            "bundle_id": bundle.name,
            "status": summary.get("status", "unknown"),
            "synthetic_fixture": bool(summary.get("synthetic_fixture")),
            "user_data_used": bool(summary.get("user_data_used")),
            "trace_completeness": trace.get("applicable_stage_completeness"),
            "cases": [
                {
                    "case_id": "success_case",
                    "title": "Successful execution",
                    "status": "COMPLETED" if success.get("passed") else "FAILED",
                    "what_happened": (
                        "A synthetic AnnData fixture was profiled, planned, explicitly approved, "
                        "executed twice through the controlled wrapper, validated and packaged."
                    ),
                    "conclusion": "A correctly approved fixed tool path can complete with auditable artifacts.",
                    "key_state": {
                        "execution_requests": success.get("execution_request_count", 0),
                        "validation_passed": success.get("validation_passed", False),
                        "recommended_candidate": success.get("recommended_candidate_id"),
                    },
                    "trace": _trace_summary(trace_by_case.get("success_case", {})),
                    "lineage": "No repair lineage; both approved runs are direct children of the plan.",
                    "package_integrity": bool(success.get("package_complete")),
                    "limitations": [
                        "Synthetic fixture only; this is not a biological accuracy result.",
                        "Controlled local execution is application-level, not OS sandboxing.",
                    ],
                    "advanced": success,
                },
                {
                    "case_id": "repair_case",
                    "title": "Bounded repair",
                    "status": "COMPLETED" if repair.get("passed") else "FAILED",
                    "what_happened": (
                        "An intentionally excessive principal-component setting failed validation; "
                        "the deterministic RepairPolicy reduced only the approved parameter and reran it."
                    ),
                    "conclusion": "Repair is explicit, budgeted and linked to the failed parent run.",
                    "key_state": {
                        "reason": repair.get("repair_reason"),
                        "changed_fields": repair.get("changed_fields") or [],
                        "validation_after_repair": repair.get("validation_passed_after_repair", False),
                    },
                    "trace": _trace_summary(trace_by_case.get("repair_case", {})),
                    "lineage": (
                        f"{_short_id(repair.get('parent_run_id'))} -> "
                        f"{_short_id(repair.get('new_run_id'))}"
                    ),
                    "package_integrity": bool(repair.get("package_complete")),
                    "limitations": [
                        "Only allowlisted deterministic repairs are demonstrated.",
                        "The demo does not permit tool, data source, wrapper or environment changes.",
                    ],
                    "advanced": repair,
                },
                {
                    "case_id": "blocked_case",
                    "title": "Correctly blocked",
                    "status": "BLOCKED" if blocked.get("passed") else "FAILED",
                    "what_happened": (
                        "The approved parameter fingerprint no longer matched the request, so the "
                        "authorization gate stopped the flow before creating an ExecutionRequest."
                    ),
                    "conclusion": "A changed request cannot reuse an old plan-specific approval.",
                    "key_state": {
                        "reason": (blocked.get("blocking_reasons") or ["unknown"])[0],
                        "execution_requests": blocked.get("execution_request_count", 0),
                        "unsafe_executions": blocked.get("unsafe_execution_count", 0),
                    },
                    "trace": _trace_summary(trace_by_case.get("blocked_case", {})),
                    "lineage": "No run lineage was created because execution never started.",
                    "package_integrity": None,
                    "limitations": [
                        "This proves the tested mismatch is blocked, not that every possible attack is covered.",
                        "No package is expected for a pre-execution block.",
                    ],
                    "advanced": blocked,
                },
            ],
        }


class InterviewDemoService:
    """Read the newest interview bundle without invoking an Agent or executor."""

    REQUIRED_FILES = (
        "interview_summary.json",
        "doublet_detection_success.json",
        "batch_integration_success.json",
        "bounded_repair.json",
        "correctly_blocked.json",
        "benchmark_summary.json",
        "trace_audit.json",
        "package_integrity.json",
        "limitations.json",
    )

    def __init__(
        self,
        root: Path | None = None,
        portfolio_root: Path | None = None,
    ) -> None:
        configured = os.environ.get("SCKG_INTERVIEW_DEMO_ROOT")
        self.root = Path(root or configured or DEFAULT_PHASE6_DEMO_ROOT)
        if portfolio_root is not None:
            self.portfolio_root: Path | None = Path(portfolio_root)
        elif root is None and not configured:
            self.portfolio_root = DEFAULT_PORTFOLIO_ROOT
        else:
            self.portfolio_root = None

    def latest_bundle(self) -> Dict[str, Any]:
        candidates = []
        if self.root.is_dir():
            candidates.extend(path for path in self.root.glob("interview-*") if path.is_dir())
        if self.portfolio_root is not None and self.portfolio_root.is_dir():
            candidates.extend(
                path
                for path in self.portfolio_root.glob("rc-*/interview")
                if path.is_dir()
            )
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        for bundle in candidates:
            if all((bundle / name).is_file() for name in self.REQUIRED_FILES):
                return self._load_bundle(bundle)
        return {}

    def _load_bundle(self, bundle: Path) -> Dict[str, Any]:
        summary = _read_json_file(bundle / "interview_summary.json")
        benchmark = _read_json_file(bundle / "benchmark_summary.json")
        trace = _read_json_file(bundle / "trace_audit.json")
        integrity = _read_json_file(bundle / "package_integrity.json")
        limitations = _read_json_file(bundle / "limitations.json").get("limitations") or []
        governance_examples = []
        examples_path = bundle / "portfolio_governance_examples.json"
        if examples_path.is_file():
            governance_examples = _redact_local_paths(
                json.loads(examples_path.read_text(encoding="utf-8"))
            )
        case_files = (
            "doublet_detection_success",
            "batch_integration_success",
            "bounded_repair",
            "correctly_blocked",
        )
        cases = []
        for case_id in case_files:
            row = _read_json_file(bundle / f"{case_id}.json")
            detail = row.get("execution") or row.get("repair") or row
            cases.append(
                {
                    "case_id": case_id,
                    "title": row.get("title", case_id.replace("_", " ").title()),
                    "status": row.get("status", "FAILED"),
                    "task": row.get("natural_language_task", ""),
                    "selected_tool": row.get("selected_tool"),
                    "parent_route": row.get("parent_route"),
                    "trace_id": row.get("trace_id"),
                    "conclusion": row.get("conclusion", ""),
                    "execution_request_count": detail.get("execution_request_count", 0),
                    "package_complete": detail.get("package_complete"),
                    "advanced": _redact_local_paths(row),
                }
            )
        return {
            "bundle_id": bundle.name if bundle.name.startswith("interview-") else bundle.parent.name,
            "status": summary.get("status", "unknown"),
            "architecture": summary.get("architecture", ""),
            "phase6_status": summary.get("phase6_status", "PHASE6_TRIAL_READY"),
            "execution_policy_default": summary.get("execution_policy_default", "disabled"),
            "trace_completeness": trace.get("minimum_applicable_stage_completeness", 0.0),
            "blocked_execution_request_count": summary.get("blocked_execution_request_count", 0),
            "package_integrity": integrity,
            "benchmark_baselines": benchmark.get("baselines") or [],
            "benchmark_completed_calls": benchmark.get("completed_model_calls", 0),
            "benchmark_requested_calls": benchmark.get("requested_model_calls", 0),
            "benchmark_new_calls": benchmark.get("new_model_calls", 0),
            "benchmark_recovered_calls": benchmark.get("recovered_model_calls", 0),
            "benchmark_replayed_calls": benchmark.get("replayed_model_calls", 0),
            "benchmark_safety": benchmark.get("safety") or {},
            "benchmark_a4_not_worse": benchmark.get("a4_not_worse_than_a3"),
            "benchmark_failure_analysis": benchmark.get("failure_analysis") or [],
            "benchmark_governance_examples": governance_examples,
            "limitations": limitations,
            "cases": cases,
        }


class Phase6EvaluationService:
    """Read-only projection of Phase 6 evaluation and trial artifacts."""

    def __init__(
        self,
        *,
        summary_path: Path = DEFAULT_PHASE6_BASELINE_SUMMARY,
        cases_path: Path = DEFAULT_PHASE6_BASELINE_CASES,
        failure_queue_path: Path = DEFAULT_PHASE6_FAILURE_QUEUE,
        trace_audit_path: Path = DEFAULT_PHASE6_TRACE_AUDIT,
        telemetry_path: Path = DEFAULT_TRIAL_TELEMETRY,
    ) -> None:
        self.summary_path = Path(summary_path)
        self.cases_path = Path(cases_path)
        self.failure_queue_path = Path(failure_queue_path)
        self.trace_audit_path = Path(trace_audit_path)
        self.telemetry = TrialTelemetryStore(Path(telemetry_path))

    def load_summary(self) -> Dict[str, Any]:
        return _read_json_file(self.summary_path)

    def list_cases(self, *, track: str | None = None, status: str | None = None) -> List[Dict[str, Any]]:
        rows = _read_tsv(self.cases_path)
        if track:
            rows = [row for row in rows if row.get("track") == track]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def list_failures(self, *, tool: str | None = None, repairable: str | None = None) -> List[Dict[str, Any]]:
        rows = _read_tsv(self.failure_queue_path)
        if tool:
            rows = [row for row in rows if tool.casefold() in row.get("tool", "").casefold()]
        if repairable:
            rows = [row for row in rows if row.get("repairable", "").casefold() == repairable.casefold()]
        return rows

    def load_trace_audit(self) -> Dict[str, Any]:
        return _read_json_file(self.trace_audit_path)

    def list_trial_events(self, *, limit: int = 500) -> List[Dict[str, Any]]:
        return self.telemetry.list_events(limit=limit)

    def load_unified_evaluation(self, *, suite: str = "pr") -> Dict[str, Any]:
        from eval.evaluation_registry import EvaluationExperimentRegistry

        return EvaluationExperimentRegistry().latest(suite)


class TraceService:
    def __init__(self, path: Path = DEFAULT_TRACE_PATH) -> None:
        self.path = path

    def list_traces(self, trace_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        traces = load_traces(self.path)
        if trace_type:
            traces = [trace for trace in traces if trace.get("trace_type") == trace_type]
        traces.sort(key=lambda item: item.get("started_at", ""), reverse=True)
        return traces[:limit]

    def latest_agent_run(self) -> Optional[Dict[str, Any]]:
        traces = self.list_traces("agent_run", limit=1)
        return traces[0] if traces else None

    def stage_timings(self, trace: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for stage in trace.get("stages") or []:
            data = stage.get("data") if isinstance(stage.get("data"), dict) else {}
            rows.append(
                {
                    "stage": stage.get("stage", ""),
                    "elapsed_ms": float(stage.get("elapsed_ms") or 0.0),
                    "status": stage.get("status") or data.get("status") or "ok",
                    "method": data.get("method", ""),
                    "provider": data.get("provider", ""),
                    "warnings": data.get("warnings") or [],
                    "error": data.get("error", ""),
                    "input_summary": data.get("input_summary") or {},
                    "output_summary": data.get("output_summary") or {},
                }
            )
        return rows

    def stage_by_name(self, trace: Dict[str, Any], stage_name: str) -> Optional[Dict[str, Any]]:
        for stage in self.stage_timings(trace):
            if stage["stage"] == stage_name:
                return stage
        return None

    def kg_gate_summary(self, trace: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        trace = trace or self.latest_agent_run()
        if not trace:
            return {}
        stage = self.stage_by_name(trace, "kg_hard_filter")
        if not stage:
            return {}
        output = stage.get("output_summary") or {}
        return {
            "trace_id": trace.get("trace_id", ""),
            "query": (trace.get("metadata") or {}).get("query", ""),
            "force_offline_graph": (trace.get("metadata") or {}).get("force_offline_graph"),
            "provider": output.get("provider", ""),
            "raw_candidate_count": output.get("raw_candidate_count", 0),
            "candidate_tool_count": output.get("candidate_tool_count", 0),
            "tool_candidate_count": output.get("tool_candidate_count", 0),
            "retrieval_result_count": output.get("retrieval_result_count", 0),
            "admitted_candidate_tools": output.get("admitted_candidate_tools") or [],
            "raw_candidate_tools": output.get("raw_candidate_tools") or [],
            "blocked_reason_counts": output.get("blocked_reason_counts") or {},
            "candidate_diagnostics": output.get("candidate_diagnostics") or [],
            "error": output.get("error", ""),
        }

    def evidence_stage_rows(self, trace: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        trace = trace or self.latest_agent_run()
        if not trace:
            return []
        evidence_stage_names = {
            "kg_hard_filter",
            "evidence_retrieval",
            "mcdm_rank",
            "migration_or_workflow_plan",
            "audit",
        }
        return [
            stage for stage in self.stage_timings(trace)
            if stage["stage"] in evidence_stage_names or "retrieval" in stage["stage"]
        ]

    def overview(self) -> Dict[str, Any]:
        traces = self.list_traces(limit=500)
        agent_runs = [trace for trace in traces if trace.get("trace_type") == "agent_run"]
        latest = agent_runs[0] if agent_runs else None
        average_ms = (
            sum(float(trace.get("elapsed_ms") or trace.get("total_elapsed_ms") or 0.0) for trace in agent_runs)
            / len(agent_runs)
            if agent_runs
            else 0.0
        )
        blocked = 0
        for trace in agent_runs:
            for stage in trace.get("stages") or []:
                data = stage.get("data") or {}
                output = data.get("output_summary") or {}
                if output.get("passed") is False:
                    blocked += 1
                    break
        return {
            "trace_count": len(traces),
            "agent_run_count": len(agent_runs),
            "latest_agent_run": latest,
            "average_agent_run_ms": average_ms,
            "audit_needs_review_count": blocked,
        }


class ReflectionService:
    def __init__(
        self,
        log_path: Path = DEFAULT_REFLECTION_LOG,
        memory_db: Path = DEFAULT_MEMORY_DB,
        skill_dir: Path = DEFAULT_SKILL_CANDIDATES_DIR,
    ) -> None:
        self.log_path = log_path
        self.memory_db = memory_db
        self.skill_dir = skill_dir

    def list_reflections(self, limit: int = 100) -> List[Dict[str, Any]]:
        return load_reflection_events(self.log_path, limit=limit)

    def list_memory_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.memory_db.exists():
            return []
        with sqlite3.connect(self.memory_db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT event_id, event_type, key, value_json, source, trace_id,
                       confidence, can_affect_scientific_authority, created_at
                FROM memory_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                **dict(row),
                "value": _load_json(row["value_json"]),
                "can_affect_scientific_authority": bool(row["can_affect_scientific_authority"]),
            }
            for row in rows
        ]

    def list_skill_candidates(self) -> List[Dict[str, str]]:
        if not self.skill_dir.exists():
            return []
        rows: List[Dict[str, str]] = []
        for path in sorted(self.skill_dir.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
            text = path.read_text(encoding="utf-8", errors="ignore")
            title = text.splitlines()[0].lstrip("# ").strip() if text else path.stem
            rows.append({"path": str(path), "title": title, "preview": text[:1200]})
        return rows


def _load_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return value


class EvidenceRecoveryService:
    def __init__(
        self,
        doublet_demo_path: Path = DEFAULT_DOUBLET_RECOVERY_DEMO,
        decision_workflow_demo_path: Path = DEFAULT_DECISION_WORKFLOW_DEMO,
        pdf_ingest_summary_path: Path = DEFAULT_PDF_INGEST_SUMMARY,
        pdf_download_summary_path: Path = DEFAULT_PDF_DOWNLOAD_SUMMARY,
        core_source_manifest_path: Path = DEFAULT_CORE_SOURCE_MANIFEST,
        algorithm_audit_path: Path = DEFAULT_ALGORITHM_REPRESENTATION_AUDIT,
        algorithm_summary_path: Path = DEFAULT_ALGORITHM_REPRESENTATION_SUMMARY,
        evidence_chunks_path: Path = DEFAULT_EVIDENCE_CHUNKS,
        literature_coverage_tsv_path: Path = DEFAULT_LITERATURE_SOURCE_COVERAGE_TSV,
        literature_coverage_summary_path: Path = DEFAULT_LITERATURE_SOURCE_COVERAGE_SUMMARY,
        source_registry_path: Path = DEFAULT_SOURCE_REGISTRY,
        pdf_candidate_registry_path: Path = DEFAULT_PDF_CANDIDATE_REGISTRY,
        source_validation_report_path: Path = DEFAULT_SOURCE_VALIDATION_REPORT,
        source_acquisition_summary_path: Path = DEFAULT_SOURCE_ACQUISITION_SUMMARY,
        source_extraction_summary_path: Path = DEFAULT_SOURCE_EXTRACTION_SUMMARY,
    ) -> None:
        self.doublet_demo_path = doublet_demo_path
        self.decision_workflow_demo_path = decision_workflow_demo_path
        self.pdf_ingest_summary_path = pdf_ingest_summary_path
        self.pdf_download_summary_path = pdf_download_summary_path
        self.core_source_manifest_path = core_source_manifest_path
        self.algorithm_audit_path = algorithm_audit_path
        self.algorithm_summary_path = algorithm_summary_path
        self.evidence_chunks_path = evidence_chunks_path
        self.literature_coverage_tsv_path = literature_coverage_tsv_path
        self.literature_coverage_summary_path = literature_coverage_summary_path
        self.source_registry_path = source_registry_path
        self.pdf_candidate_registry_path = pdf_candidate_registry_path
        self.source_validation_report_path = source_validation_report_path
        self.source_acquisition_summary_path = source_acquisition_summary_path
        self.source_extraction_summary_path = source_extraction_summary_path

    def load_doublet_demo(self) -> Dict[str, Any]:
        if not self.doublet_demo_path.exists():
            return {}
        try:
            return json.loads(self.doublet_demo_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def load_decision_workflow_demo(self) -> Dict[str, Any]:
        if not self.decision_workflow_demo_path.exists():
            return {}
        try:
            return json.loads(self.decision_workflow_demo_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def load_pdf_ingest_summary(self) -> Dict[str, Any]:
        if not self.pdf_ingest_summary_path.exists():
            return {}
        try:
            return json.loads(self.pdf_ingest_summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def load_pdf_download_summary(self) -> Dict[str, Any]:
        if not self.pdf_download_summary_path.exists():
            return {}
        try:
            return json.loads(self.pdf_download_summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def load_source_coverage(self) -> Dict[str, Any]:
        manifest_rows = _read_tsv(self.core_source_manifest_path)
        audit_rows = {
            _norm(row.get("tool_name")): row
            for row in _read_tsv(self.algorithm_audit_path)
            if row.get("tool_name")
        }
        algorithm_summary = _read_json_file(self.algorithm_summary_path)
        chunk_counts = _source_chunk_counts_by_tool(self.evidence_chunks_path)
        grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        for row in manifest_rows:
            tool_name = row.get("tool_name")
            if tool_name:
                grouped[tool_name].append(row)

        rows: List[Dict[str, Any]] = []
        for tool_name in sorted(grouped, key=str.casefold):
            source_rows = grouped[tool_name]
            audit = audit_rows.get(_norm(tool_name), {})
            source_chunk_count = int(audit.get("source_chunk_count") or chunk_counts.get(_norm(tool_name), 0))
            dense_vector_chunk_count = int(audit.get("dense_vector_chunk_count") or 0)
            rows.append(
                {
                    "tool_name": tool_name,
                    "coverage_status": "covered" if source_chunk_count > 0 else "needs_source",
                    "manifest_rows": len(source_rows),
                    "fetched_rows": sum(
                        1 for row in source_rows if str(row.get("fetch_status", "")).startswith("fetched")
                    ),
                    "local_text_available": sum(1 for row in source_rows if _path_exists(row.get("local_text_path", ""))),
                    "source_chunk_count": source_chunk_count,
                    "dense_vector_chunk_count": dense_vector_chunk_count,
                    "review_status": audit.get("review_status", ""),
                    "quality_flags": audit.get("quality_flags", ""),
                    "source_types": ", ".join(
                        sorted(
                            {
                                row.get("preferred_source_type", "")
                                for row in source_rows
                                if row.get("preferred_source_type")
                            }
                        )
                    ),
                    "fetch_statuses": ", ".join(
                        f"{row.get('preferred_source_type', '')}:{row.get('fetch_status', '')}"
                        for row in source_rows
                    ),
                    "source_urls": "\n".join(row.get("source_url", "") for row in source_rows if row.get("source_url")),
                    "notes": " | ".join(row.get("notes", "") for row in source_rows if row.get("notes")),
                }
            )

        covered_tools = sum(1 for row in rows if row["coverage_status"] == "covered")
        return {
            "summary": {
                "core_tools": len(rows),
                "covered_tools": covered_tools,
                "missing_tools": len(rows) - covered_tools,
                "manifest_rows": len(manifest_rows),
                "fetched_manifest_rows": sum(
                    1 for row in manifest_rows if str(row.get("fetch_status", "")).startswith("fetched")
                ),
                "source_chunk_count": sum(row["source_chunk_count"] for row in rows),
                "dense_vector_chunk_count": sum(row["dense_vector_chunk_count"] for row in rows),
                "tools_with_source_chunks_total": algorithm_summary.get("tools_with_source_chunks", 0),
                "tools_without_source_chunks_total": algorithm_summary.get("tools_without_source_chunks", 0),
                "algorithm_summary": algorithm_summary,
            },
            "rows": rows,
        }

    def load_literature_source_coverage(self) -> Dict[str, Any]:
        return {
            "summary": _read_json_file(self.literature_coverage_summary_path),
            "rows": _read_tsv(self.literature_coverage_tsv_path),
        }

    def load_source_registry_status(self) -> Dict[str, Any]:
        registry_rows = _read_tsv(self.source_registry_path)
        candidate_rows = _read_tsv(self.pdf_candidate_registry_path)
        validation_rows = _read_tsv(self.source_validation_report_path)
        return {
            "registry_rows": registry_rows,
            "candidate_rows": candidate_rows,
            "validation_rows": validation_rows,
            "acquisition_summary": _read_json_file(self.source_acquisition_summary_path),
            "extraction_summary": _read_json_file(self.source_extraction_summary_path),
        }


def _read_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _trace_summary(value: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "applicable_stage_completeness": value.get("applicable_stage_completeness"),
        "stages": [
            {
                "stage": row.get("stage", ""),
                "status": str(row.get("status", "")).upper(),
            }
            for row in value.get("observed_stages") or []
        ],
        "missing_stages": value.get("missing_stages") or [],
        "violations": value.get("violations") or {},
    }


def _short_id(value: Any, limit: int = 30) -> str:
    text = str(value or "not-created")
    if len(text) <= limit:
        return text
    return f"{text[:14]}...{text[-10:]}"


def _redact_local_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_local_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_local_paths(item) for item in value]
    if isinstance(value, str):
        root = str(PROJECT_ROOT)
        return value.replace(root, "<PROJECT_ROOT>")
    return value


def _source_chunk_counts_by_tool(path: Path) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            source_kind = str(row.get("source_kind", ""))
            if not source_kind.startswith("source_") and source_kind != "document":
                continue
            tool_name = row.get("tool_name")
            if tool_name:
                counts[_norm(tool_name)] += 1
    return dict(counts)


def _path_exists(value: str) -> bool:
    if not value:
        return False
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.exists() and path.is_file()


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()
