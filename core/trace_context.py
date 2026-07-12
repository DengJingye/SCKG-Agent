from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional

from core.settings import PROJECT_ROOT


TraceType = Literal["agent_run", "rag_retrieval", "evidence_recovery", "reflection", "ingestion", "query"]

DEFAULT_TRACE_PATH = PROJECT_ROOT / "logs" / "traces.jsonl"


@dataclass
class TraceContext:
    """Request-scoped JSONL trace for agent, RAG, evidence, and reflection flows."""

    trace_type: TraceType = "agent_run"
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: f"trace_{uuid.uuid4().hex}")
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None
    stages: List[Dict[str, Any]] = field(default_factory=list)
    _start_mono: float = field(default_factory=time.perf_counter, repr=False)
    _finish_mono: Optional[float] = field(default=None, repr=False)

    def record_stage(
        self,
        stage_name: str,
        *,
        status: str = "ok",
        method: str = "",
        provider: str = "",
        input_summary: Optional[Dict[str, Any]] = None,
        output_summary: Optional[Dict[str, Any]] = None,
        warnings: Optional[List[str]] = None,
        elapsed_ms: Optional[float] = None,
        error: str = "",
    ) -> None:
        self.stages.append(
            {
                "stage": stage_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_ms": round(float(elapsed_ms or 0.0), 3),
                "status": status,
                "data": {
                    "method": method,
                    "provider": provider,
                    "input_summary": input_summary or {},
                    "output_summary": output_summary or {},
                    "warnings": list(warnings or []),
                    "error": error,
                },
            }
        )

    @contextmanager
    def stage_timer(
        self,
        stage_name: str,
        *,
        method: str = "",
        provider: str = "",
        input_summary: Optional[Dict[str, Any]] = None,
        output_summary_factory: Optional[Any] = None,
        warnings_factory: Optional[Any] = None,
    ) -> Iterator[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        started = time.perf_counter()
        try:
            yield payload
            output_summary = (
                output_summary_factory(payload)
                if output_summary_factory
                else payload.get("output_summary", {})
            )
            warnings = (
                warnings_factory(payload)
                if warnings_factory
                else payload.get("warnings", [])
            )
            self.record_stage(
                stage_name,
                status="ok",
                method=method,
                provider=provider,
                input_summary=input_summary,
                output_summary=output_summary,
                warnings=warnings,
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            self.record_stage(
                stage_name,
                status="error",
                method=method,
                provider=provider,
                input_summary=input_summary,
                output_summary=payload.get("output_summary", {}),
                warnings=payload.get("warnings", []),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    def finish(self) -> None:
        self._finish_mono = time.perf_counter()
        self.finished_at = datetime.now(timezone.utc).isoformat()

    @property
    def elapsed_ms(self) -> float:
        end = self._finish_mono if self._finish_mono is not None else time.perf_counter()
        return (end - self._start_mono) * 1000

    def to_dict(self) -> Dict[str, Any]:
        total = round(self.elapsed_ms, 3)
        return {
            "trace_id": self.trace_id,
            "trace_type": self.trace_type,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": total,
            "total_elapsed_ms": total,
            "stages": list(self.stages),
            "metadata": dict(self.metadata),
        }


class TraceCollector:
    """Append-only local JSONL trace collector."""

    def __init__(self, path: Path = DEFAULT_TRACE_PATH) -> None:
        self.path = path

    def collect(self, trace: TraceContext) -> None:
        if trace.finished_at is None:
            trace.finish()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(trace.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def load_traces(path: Path = DEFAULT_TRACE_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    traces: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                traces.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return traces
