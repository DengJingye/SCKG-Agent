from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.traced_runner import run_sckg_workflow_traced
from core.reflection_memory import reflect_agent_run
from core.settings import get_settings
from core.trace_context import TraceCollector, TraceContext


DEFAULT_QUERY = "我有一批 10x scRNA-seq PBMC 数据，需要去除 doublet，最好有 benchmark 依据。"


def initial_state(user_query: str) -> Dict[str, Any]:
    return {
        "user_query": user_query,
        "extracted_constraints": {},
        "candidate_tools": [],
        "tool_candidates": [],
        "retrieval_results": [],
        "scored_tools": [],
        "migration_paths": [],
        "workflow_recommendations": [],
        "decision_report": None,
        "final_report": "",
        "hallucination_audit": {},
        "context_pack": {},
        "conversation_context": [],
        "project_memory": {},
        "uploaded_context": {},
        "user_runtime_config": {},
        "current_step": "init",
        "error_message": None,
    }


def run_smoke(query: str, *, offline_llm: bool, force_offline_graph: bool) -> Dict[str, Any]:
    previous_offline_llm = os.environ.get("SCKG_OFFLINE_LLM")
    previous_force_graph = os.environ.get("SCKG_FORCE_OFFLINE_GRAPH")
    if offline_llm:
        os.environ["SCKG_OFFLINE_LLM"] = "true"
    if force_offline_graph:
        os.environ["SCKG_FORCE_OFFLINE_GRAPH"] = "true"
    get_settings.cache_clear()
    trace = TraceContext(
        trace_type="agent_run",
        metadata={
            "query": query,
            "source": "cli_trace_smoke",
            "offline_llm": offline_llm,
            "force_offline_graph": force_offline_graph,
            "architecture": "recursive_centralized_parent_agent",
        },
    )
    try:
        state = run_sckg_workflow_traced(initial_state(query), trace)
        try:
            with trace.stage_timer(
                "reflect",
                method="core.reflection_memory.reflect_agent_run",
                provider="local_sqlite_jsonl",
                input_summary={
                    "has_final_report": bool(state.get("final_report")),
                    "has_audit": bool(state.get("hallucination_audit")),
                },
            ) as payload:
                reflection = reflect_agent_run(state, trace)
                state["reflection_event"] = reflection.model_dump(mode="json")
                payload["output_summary"] = {
                    "memory_event_count": len(reflection.memory_events),
                    "skill_candidate_count": len(reflection.skill_candidates),
                    "missing_evidence_count": len(reflection.missing_evidence),
                }
                payload["warnings"] = reflection.warnings
        except Exception as exc:
            state["reflection_error"] = f"{type(exc).__name__}: {exc}"
        return {
            "trace_id": trace.trace_id,
            "stage_names": [stage["stage"] for stage in trace.stages],
            "final_report_chars": len(state.get("final_report") or ""),
            "audit_passed": (state.get("hallucination_audit") or {}).get("passed"),
            "reflection_written": bool(state.get("reflection_event")),
            "reflection_error": state.get("reflection_error", ""),
            "trace_path": str(PROJECT_ROOT / "logs" / "traces.jsonl"),
            "reflection_log": str(PROJECT_ROOT / "data" / "memory" / "reflection_events.jsonl"),
            "memory_db": str(PROJECT_ROOT / "data" / "memory" / "project_memory.sqlite"),
            "skill_candidates_dir": str(PROJECT_ROOT / "data" / "skill_candidates"),
        }
    finally:
        trace.finish()
        TraceCollector().collect(trace)
        _restore_env("SCKG_OFFLINE_LLM", previous_offline_llm)
        _restore_env("SCKG_FORCE_OFFLINE_GRAPH", previous_force_graph)
        get_settings.cache_clear()


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a real local scKG agent trace for dashboard acceptance.")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--live-llm", action="store_true", help="Use configured LLM instead of offline deterministic mode.")
    parser.add_argument(
        "--allow-neo4j",
        action="store_true",
        help="Allow Neo4j connection attempts instead of forcing offline graph fallback.",
    )
    args = parser.parse_args()
    summary = run_smoke(
        args.query,
        offline_llm=not args.live_llm,
        force_offline_graph=not args.allow_neo4j,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
