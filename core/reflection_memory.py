from __future__ import annotations

import json
import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.models import MemoryEvent, ReflectionEvent, SkillCandidate
from core.settings import PROJECT_ROOT
from core.trace_context import TraceContext
from core.unified_memory import DEFAULT_SCKG_HOME, DEFAULT_WORKBENCH_DB, UnifiedMemoryStore


DEFAULT_MEMORY_DIR = DEFAULT_SCKG_HOME / "state"
DEFAULT_REFLECTION_LOG = DEFAULT_MEMORY_DIR / "reflection_events.jsonl"
DEFAULT_MEMORY_DB = DEFAULT_WORKBENCH_DB
DEFAULT_SKILL_CANDIDATES_DIR = DEFAULT_MEMORY_DIR / "skill_candidates"


def reflect_agent_run(
    state: Dict[str, Any],
    trace_id: str | TraceContext,
    *,
    reflection_log: Path = DEFAULT_REFLECTION_LOG,
    memory_db: Path = DEFAULT_MEMORY_DB,
    skill_candidates_dir: Path = DEFAULT_SKILL_CANDIDATES_DIR,
) -> ReflectionEvent:
    """Persist lightweight Hermes-like reflection after a Parent Agent run.

    Reflection writes operational memory only. It cannot promote formal evidence.
    """

    # Compatibility is limited to the legacy CLI smoke producer. Reflection
    # consumes only its immutable identifier and never trace metadata/stages.
    resolved_trace_id = trace_id.trace_id if isinstance(trace_id, TraceContext) else trace_id
    query = str(state.get("user_query") or "")
    constraints = _as_dict(state.get("extracted_constraints"))
    audit = _as_dict(state.get("hallucination_audit"))
    context_pack = _as_dict(state.get("context_pack"))
    missing = _missing_evidence(state, context_pack)
    warnings = _reflection_warnings(state, audit)
    memory_events = _memory_events_from_state(query, constraints, missing, warnings, resolved_trace_id)
    skill_candidates = _skill_candidates_from_run(query, missing, warnings, resolved_trace_id)
    event = ReflectionEvent(
        reflection_id=f"reflection_{uuid.uuid4().hex}",
        trace_id=resolved_trace_id,
        user_query=query,
        learned_facts=_learned_facts(constraints),
        failure_lessons=warnings,
        memory_events=memory_events,
        skill_candidates=skill_candidates,
        missing_evidence=missing,
        warnings=[
            "Reflection memory is private operational memory and cannot update formal evidence.",
            "Skill candidates are review-only and are not auto-loaded.",
        ],
    )
    persist_reflection(event, reflection_log=reflection_log, memory_db=memory_db)
    for candidate in skill_candidates:
        write_skill_candidate(candidate, skill_candidates_dir)
    return event


def persist_reflection(
    event: ReflectionEvent,
    *,
    reflection_log: Path = DEFAULT_REFLECTION_LOG,
    memory_db: Path = DEFAULT_MEMORY_DB,
) -> None:
    reflection_log.parent.mkdir(parents=True, exist_ok=True)
    with reflection_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n")
    store = UnifiedMemoryStore(memory_db)
    store.record_reflection("local", event.model_dump(mode="json"))
    for memory_event in event.memory_events:
        if memory_event.event_type == "user_preference":
            store.propose_inferred_preference(
                "local",
                memory_event.key,
                memory_event.value,
                confidence=memory_event.confidence,
                source=memory_event.source,
            )


def init_memory_db(path: Path = DEFAULT_MEMORY_DB) -> Path:
    UnifiedMemoryStore(path)
    return path


def load_reflection_events(path: Path = DEFAULT_REFLECTION_LOG, limit: int = 100) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return rows[:limit]


def write_skill_candidate(candidate: SkillCandidate, directory: Path = DEFAULT_SKILL_CANDIDATES_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate.candidate_id)
    path = directory / f"{safe_id}.md"
    lines = [
        f"# {candidate.title}",
        "",
        f"- status: {candidate.status}",
        f"- source_trace_id: {candidate.source_trace_id}",
        f"- trigger: {candidate.trigger}",
        "- evidence_boundary: review-only; cannot update formal evidence or ranking",
        "",
        "## Proposed Steps",
        "",
    ]
    lines.extend(f"{idx}. {step}" for idx, step in enumerate(candidate.proposed_steps, start=1))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _memory_events_from_state(
    query: str,
    constraints: Dict[str, Any],
    missing: List[str],
    warnings: List[str],
    trace_id: str,
) -> List[MemoryEvent]:
    events: List[MemoryEvent] = []
    for key in ("species", "platform", "strictness"):
        value = constraints.get(key)
        if value and value != "Unknown":
            events.append(_memory_event("user_preference", f"default_{key}", value, trace_id, 0.65))
    if constraints.get("task") and constraints.get("task") != "Unknown":
        events.append(
            _memory_event(
                "project_state",
                "last_task_context",
                {
                    "query": query,
                    "task": constraints.get("task"),
                    "modality": constraints.get("modality", "Unknown"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                trace_id,
                0.7,
            )
        )
    if missing:
        events.append(_memory_event("evidence_gap", "last_missing_evidence", missing[:12], trace_id, 0.8))
    if warnings:
        events.append(_memory_event("failure_lesson", "last_run_lessons", warnings[:8], trace_id, 0.75))
    return events


def _memory_event(
    event_type: str,
    key: str,
    value: Any,
    trace_id: str,
    confidence: float,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=f"memory_{uuid.uuid4().hex}",
        event_type=event_type,  # type: ignore[arg-type]
        key=key,
        value=value,
        trace_id=trace_id,
        confidence=confidence,
        can_affect_scientific_authority=False,
    )


def _skill_candidates_from_run(
    query: str,
    missing: List[str],
    warnings: List[str],
    trace_id: str,
) -> List[SkillCandidate]:
    if not missing and not warnings:
        return []
    fingerprint = hashlib.sha256(
        json.dumps(
            {"missing": sorted(missing), "warnings": sorted(warnings)},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    return [
        SkillCandidate(
            candidate_id=f"skill_candidate_{fingerprint}",
            title="Review evidence-limited scKG recommendation run",
            trigger="A run has missing evidence, audit warnings, or frozen evidence boundaries.",
            proposed_steps=[
                "Inspect the trace stages and identify the first evidence-limited stage.",
                "Open the evidence/RAG snippets and verify whether source spans are sufficient.",
                "If evidence is source-bound and numeric, send it through the formal promotion flow.",
                "Keep memory-derived or AI-reviewed claims retrieval-only until promoted.",
            ],
            source_trace_id=trace_id,
        )
    ]


def _learned_facts(constraints: Dict[str, Any]) -> List[str]:
    facts: List[str] = []
    for key in ("task", "modality", "platform", "species", "strictness"):
        value = constraints.get(key)
        if value and value != "Unknown":
            facts.append(f"{key}={value}")
    return facts


def _missing_evidence(state: Dict[str, Any], context_pack: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for item in context_pack.get("missing_evidence") or []:
        values.append(str(item))
    for tool in state.get("scored_tools") or []:
        if isinstance(tool, dict):
            evidence = tool.get("evidence") or {}
            for item in evidence.get("missing_evidence") or []:
                values.append(f"{tool.get('tool_name', 'tool')}:{item}")
    return sorted(set(values))


def _reflection_warnings(state: Dict[str, Any], audit: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    if state.get("error_message"):
        warnings.append(f"agent_error={state['error_message']}")
    if audit and not audit.get("passed", True):
        warnings.append("semantic_audit_needs_review")
    for issue in audit.get("issues") or []:
        if isinstance(issue, dict) and issue.get("severity") in {"high", "critical"}:
            warnings.append(f"{issue.get('severity')}: {issue.get('message') or issue.get('issue_type')}")
    if not state.get("scored_tools") and not state.get("migration_paths"):
        warnings.append("no_ranked_or_migration_output")
    return sorted(set(warnings))


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}
