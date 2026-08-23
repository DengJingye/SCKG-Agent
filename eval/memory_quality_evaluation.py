from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.settings import PROJECT_ROOT
from core.unified_memory import UnifiedMemoryStore


DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "memory_quality_v2"


@dataclass(frozen=True)
class MemoryEvalCase:
    case_id: str
    category: str
    user_id: str
    key: str = "species"
    value: Any = "human"


@dataclass(frozen=True)
class MemoryEvalResult:
    case_id: str
    category: str
    passed: bool
    scientific_authority_violation: bool
    latency_ms: float
    observed: dict[str, Any]
    failure: str = ""


@dataclass(frozen=True)
class MemoryEvalSummary:
    schema_version: str
    evaluated_at: str
    case_count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    scientific_authority_violation_count: int
    user_isolation_violation_count: int
    latency_p50_ms: float
    release_gate_passed: bool
    failures: list[str]


def build_default_memory_cases() -> list[MemoryEvalCase]:
    cases: list[MemoryEvalCase] = []
    for index, key in enumerate(("species", "platform", "strictness", "output", "language"), 1):
        cases.append(MemoryEvalCase(f"explicit-{index:02d}", "explicit_roundtrip", "user-a", key, f"value-{index}"))
    for index, key in enumerate(("species", "platform", "strictness", "modality", "format"), 1):
        cases.append(MemoryEvalCase(f"pending-{index:02d}", "inferred_pending", "user-a", key, f"inferred-{index}"))
    for index, key in enumerate(("species", "platform", "strictness", "format"), 1):
        cases.append(MemoryEvalCase(f"confirm-{index:02d}", "inferred_confirm", "user-a", key, f"confirmed-{index}"))
    for index, key in enumerate(("species", "platform", "strictness", "output"), 1):
        cases.append(MemoryEvalCase(f"isolation-{index:02d}", "user_isolation", "user-a", key, f"private-{index}"))
    for index, key in enumerate(("species", "platform", "strictness", "format"), 1):
        cases.append(MemoryEvalCase(f"conflict-{index:02d}", "conflict_boundary", "user-a", key, f"explicit-{index}"))
    for index in range(1, 4):
        cases.append(MemoryEvalCase(f"delete-{index:02d}", "deletion", "user-a", f"key-{index}", index))
    for index in range(1, 3):
        cases.append(MemoryEvalCase(f"episode-{index:02d}", "episodic_roundtrip", "user-a", value={"status": "completed", "index": index}))
    for index in range(1, 3):
        cases.append(MemoryEvalCase(f"skill-{index:02d}", "skill_deduplication", "user-a", value=index))
    cases.append(MemoryEvalCase("authority-01", "export_authority", "user-a"))
    if len(cases) != 30:
        raise AssertionError(f"expected 30 memory cases, got {len(cases)}")
    return cases


class MemoryQualityEvaluator:
    def evaluate(
        self,
        cases: Iterable[MemoryEvalCase],
    ) -> tuple[list[MemoryEvalResult], MemoryEvalSummary]:
        case_list = list(cases)
        results: list[MemoryEvalResult] = []
        with tempfile.TemporaryDirectory(prefix="sckg-memory-eval-") as directory:
            for case in case_list:
                store = UnifiedMemoryStore(Path(directory) / f"{case.case_id}.sqlite3")
                started = time.perf_counter()
                try:
                    passed, observed = self._run_case(store, case)
                    authority_violation = bool(
                        observed.get("can_affect_scientific_authority")
                        or observed.get("evidence_authority")
                    )
                    results.append(
                        MemoryEvalResult(
                            case_id=case.case_id,
                            category=case.category,
                            passed=passed and not authority_violation,
                            scientific_authority_violation=authority_violation,
                            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
                            observed=observed,
                            failure="" if passed else "memory_behavior_mismatch",
                        )
                    )
                except Exception as exc:
                    results.append(
                        MemoryEvalResult(
                            case_id=case.case_id,
                            category=case.category,
                            passed=False,
                            scientific_authority_violation=False,
                            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
                            observed={},
                            failure=f"{type(exc).__name__}: {exc}",
                        )
                    )
        return results, _summarize(case_list, results)

    def _run_case(
        self,
        store: UnifiedMemoryStore,
        case: MemoryEvalCase,
    ) -> tuple[bool, dict[str, Any]]:
        if case.category == "explicit_roundtrip":
            store.set_explicit_preference(case.user_id, case.key, case.value)
            context = store.context(case.user_id)
            return context.explicit_preferences.get(case.key) == case.value, context.model_dump(mode="json")
        if case.category == "inferred_pending":
            store.propose_inferred_preference(
                case.user_id,
                case.key,
                case.value,
                confidence=0.75,
                source="memory_eval",
            )
            context = store.context(case.user_id)
            exported = store.export_user_memory(case.user_id)
            observed = {
                **context.model_dump(mode="json"),
                "pending_count": len(exported["pending_inferences"]),
                "evidence_authority": exported["evidence_authority"],
            }
            return case.key not in context.confirmed_inferences and observed["pending_count"] == 1, observed
        if case.category == "inferred_confirm":
            store.propose_inferred_preference(
                case.user_id,
                case.key,
                case.value,
                confidence=0.8,
                source="memory_eval",
            )
            confirmed = store.confirm_inferred_preference(case.user_id, case.key)
            context = store.context(case.user_id)
            return confirmed and context.confirmed_inferences.get(case.key) == case.value, context.model_dump(mode="json")
        if case.category == "user_isolation":
            store.set_explicit_preference(case.user_id, case.key, case.value)
            owner = store.context(case.user_id)
            other = store.context("user-b")
            observed = {
                "owner_value": owner.explicit_preferences.get(case.key),
                "other_value": other.explicit_preferences.get(case.key),
                "can_affect_scientific_authority": owner.can_affect_scientific_authority,
            }
            return observed["owner_value"] == case.value and observed["other_value"] is None, observed
        if case.category == "conflict_boundary":
            store.set_explicit_preference(case.user_id, case.key, case.value)
            store.propose_inferred_preference(
                case.user_id,
                case.key,
                f"conflicting-{case.value}",
                confidence=0.9,
                source="memory_eval",
            )
            context = store.context(case.user_id)
            conflicts = store.list_conflicts(case.user_id)
            observed = {
                "retained_value": context.explicit_preferences.get(case.key),
                "conflict_count": len(conflicts),
                "conflict_status": conflicts[0]["status"] if conflicts else "",
                "can_affect_scientific_authority": context.can_affect_scientific_authority,
            }
            return (
                observed["retained_value"] == case.value
                and observed["conflict_count"] == 1
                and observed["conflict_status"] == "pending"
            ), observed
        if case.category == "deletion":
            store.set_explicit_preference(case.user_id, case.key, case.value)
            store.record_episodic_run(case.user_id, "run-1", {"status": "completed"})
            store.delete_user_memory(case.user_id)
            context = store.context(case.user_id)
            observed = context.model_dump(mode="json")
            return not context.explicit_preferences and not context.episodic_runs, observed
        if case.category == "episodic_roundtrip":
            store.record_episodic_run(case.user_id, case.case_id, case.value, trace_id="trace-memory")
            context = store.context(case.user_id)
            observed = context.model_dump(mode="json")
            return (
                len(context.episodic_runs) == 1
                and context.episodic_runs[0]["summary"] == case.value
            ), observed
        if case.category == "skill_deduplication":
            candidate = {
                "candidate_id": "skill-1",
                "title": "Recover source span",
                "trigger": "source span missing",
                "proposed_steps": ["inspect source", "record source span"],
            }
            for suffix in ("a", "b"):
                candidate["candidate_id"] = f"skill-{suffix}"
                store.record_reflection(
                    case.user_id,
                    {
                        "reflection_id": f"reflection-{suffix}",
                        "trace_id": f"trace-{suffix}",
                        "skill_candidates": [candidate],
                    },
                )
            context = store.context(case.user_id)
            observed = context.model_dump(mode="json")
            return len(context.skill_candidates) == 1, observed
        if case.category == "export_authority":
            store.set_explicit_preference(case.user_id, "species", "human")
            exported = store.export_user_memory(case.user_id)
            return exported["evidence_authority"] is False, exported
        raise ValueError(f"unsupported memory evaluation category: {case.category}")


def write_memory_artifacts(
    output_dir: Path,
    results: list[MemoryEvalResult],
    summary: MemoryEvalSummary,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cases.json").write_text(
        json.dumps([asdict(case) for case in build_default_memory_cases()], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "results.jsonl").write_text(
        "".join(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True) + "\n" for result in results),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _summarize(
    cases: list[MemoryEvalCase],
    results: list[MemoryEvalResult],
) -> MemoryEvalSummary:
    passed = sum(result.passed for result in results)
    authority = sum(result.scientific_authority_violation for result in results)
    isolation = sum(
        not result.passed
        for result in results
        if result.category == "user_isolation"
    )
    latencies = sorted(result.latency_ms for result in results)
    failures = [f"{result.case_id}:{result.failure}" for result in results if not result.passed]
    return MemoryEvalSummary(
        schema_version="memory-quality-v2.0",
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        case_count=len(cases),
        passed_count=passed,
        failed_count=len(results) - passed,
        pass_rate=round(passed / max(1, len(results)), 6),
        scientific_authority_violation_count=authority,
        user_isolation_violation_count=isolation,
        latency_p50_ms=latencies[len(latencies) // 2] if latencies else 0.0,
        release_gate_passed=passed == len(results) and authority == 0 and isolation == 0,
        failures=failures,
    )
