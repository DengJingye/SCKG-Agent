from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional

from core.settings import PROJECT_ROOT

TraceType = Literal[
    "agent_run", "rag_retrieval", "evidence_recovery", "reflection", "ingestion", "query"
]
TRACE_SCHEMA_VERSION = "sckg-trace-v0"
DEFAULT_TRACE_PATH = PROJECT_ROOT / "logs" / "traces.jsonl"
MAX_SPANS, MAX_LINKS, MAX_REFS, MAX_DECISIONS, MAX_COUNTERS = 256, 32, 32, 16, 16

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_CORRELATION_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_HASH = re.compile(r"^[a-fA-F0-9]{64}$")
_BEARER_CREDENTIAL = re.compile(
    r"\bbearer(?:\s+|\s*[:=]\s*)[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE
)
_QUERY_CREDENTIAL = re.compile(
    r"(?:^|[?&])(?:token|access_token|auth_token|api_key)=[^&\s]+", re.IGNORECASE
)
_ASSIGNED_CREDENTIAL = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:api[_-]?key|password|passwd|secret|credential|"
    r"access[_-]?token|auth[_-]?token|token)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_JUPYTER_CREDENTIAL = re.compile(
    r"\bjupyter[-_]?token[-_:]?(?:[0-9]{6,}|[A-Fa-f0-9]{10,}|"
    r"[A-Za-z0-9._~]{16,})\b",
    re.IGNORECASE,
)
_API_CREDENTIAL = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{8,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b|"
    r"\bAKIA[A-Z0-9]{16}\b)"
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version", "trace_kind", "trace_id", "request_id", "conversation_id",
        "parent_trace_id", "handoff_id", "parent_request_id", "original_plan_id",
        "principal_ref", "created_at", "finished_at", "status", "root_span_id",
        "links", "spans",
    }
)
_SPAN_FIELDS = frozenset(
    {
        "span_id", "trace_id", "parent_span_id", "sequence", "stage", "component",
        "operation", "started_at", "ended_at", "duration_ms", "status", "input_refs",
        "output_refs", "decision_evidence", "counters", "error_code",
    }
)
_LINK_FIELDS = frozenset({"link_type", "target_type", "target_id"})
_REF_REQUIRED_FIELDS = frozenset({"record_type", "record_id", "relation"})
_REF_OPTIONAL_FIELDS = frozenset({"schema_version", "content_hash"})
_DECISION_FIELDS = frozenset(
    {"decision_type", "outcome", "reason_code", "rule_version", "record_ref"}
)

_PATH_LOCKS: dict[Path, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class TraceKind(str, Enum):
    RESEARCH = "RESEARCH"
    STEPWISE = "STEPWISE"
    CONTROLLED_EXECUTION = "CONTROLLED_EXECUTION"


class TraceStage(str, Enum):
    REQUEST = "REQUEST"
    ROUTING = "ROUTING"
    RETRIEVAL = "RETRIEVAL"
    STATE_INSPECTION = "STATE_INSPECTION"
    PLANNING = "PLANNING"
    POLICY = "POLICY"
    APPROVAL = "APPROVAL"
    HANDOFF = "HANDOFF"
    NOTEBOOK_COMPILE = "NOTEBOOK_COMPILE"
    RUNTIME_BIND = "RUNTIME_BIND"
    EXECUTION = "EXECUTION"
    VALIDATION = "VALIDATION"
    REPAIR = "REPAIR"
    DECISION = "DECISION"
    PACKAGE = "PACKAGE"


class TraceStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"
    PARTIAL = "PARTIAL"


class TraceLinkType(str, Enum):
    LEGACY_TRACE = "LEGACY_TRACE"
    UNIFIED_AGENT_TRACE = "UNIFIED_AGENT_TRACE"
    APPLICATION_GRAPH_ALIAS = "APPLICATION_GRAPH_ALIAS"
    RELATED_TRACE = "RELATED_TRACE"
    ORIGIN_REQUEST = "ORIGIN_REQUEST"
    ORIGIN_PLAN = "ORIGIN_PLAN"


class TraceCorrelationKind(str, Enum):
    REQUEST = "request"
    CONVERSATION = "conversation"


class _TraceMode(str, Enum):
    LEGACY = "LEGACY"
    V0 = "V0"


class _CollectionState(str, Enum):
    READY = "READY"
    COLLECTING = "COLLECTING"
    COLLECTED = "COLLECTED"


class TraceValidationError(ValueError):
    pass


class TracePrivacyError(TraceValidationError):
    pass


class TraceStateError(RuntimeError):
    pass


class TracePersistenceError(RuntimeError):
    pass


def _id(value: Any, name: str) -> None:
    if (
        not isinstance(value, str)
        or not _ID.fullmatch(value)
        or "/" in value
        or "\\" in value
        or "://" in value
    ):
        raise TraceValidationError(f"{name} is not a safe opaque identifier")


def _code(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise TraceValidationError(f"{name} must be a bounded code")


def _optional_id(value: Any, name: str) -> None:
    if value is not None:
        _id(value, name)


def trace_correlation_id(
    source_id: str,
    *,
    kind: TraceCorrelationKind,
) -> str:
    """Return a Trace-safe correlation ID without changing the source ID.

    Canonical request/conversation IDs are correlation identifiers. Safe source
    IDs remain readable; non-secret Research-style opaque IDs that exceed the
    Trace bound (or start with punctuation) receive a deterministic surrogate.
    Unsafe paths, URLs, credentials, and free-form content are never hashed.
    """

    try:
        correlation_kind = TraceCorrelationKind(kind)
    except (TypeError, ValueError):
        raise TraceValidationError("unsupported trace correlation kind") from None
    if not isinstance(source_id, str) or not source_id:
        raise TraceValidationError("trace correlation source must be a non-empty identifier")
    _privacy(source_id)
    try:
        _id(source_id, "trace correlation source")
    except TraceValidationError:
        if _CORRELATION_SOURCE_ID.fullmatch(source_id) is None:
            raise TraceValidationError(
                "trace correlation source is not an opaque business identifier"
            ) from None
    else:
        return source_id
    digest = hashlib.sha256(
        (
            "sckg-trace-correlation-v0\0"
            f"{correlation_kind.value}\0{source_id}"
        ).encode("utf-8")
    ).hexdigest()
    surrogate = f"{correlation_kind.value}-ref:{digest}"
    _id(surrogate, "trace correlation surrogate")
    return surrogate


def _timestamp(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise TraceValidationError(f"{name} must be an ISO timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise TraceValidationError(f"{name} must be timezone-aware UTC")
    return parsed


@dataclass(frozen=True)
class TraceRecordRef:
    record_type: str
    record_id: str
    relation: str
    schema_version: Optional[str] = None
    content_hash: Optional[str] = None

    def __post_init__(self) -> None:
        _code(self.record_type, "record_type")
        _id(self.record_id, "record_id")
        _code(self.relation, "relation")
        if self.schema_version is not None:
            _code(self.schema_version, "record schema_version")
        if self.content_hash is not None and not _HASH.fullmatch(self.content_hash):
            raise TraceValidationError("content_hash must be sha256")

    def to_dict(self) -> dict[str, Any]:
        row = {"record_type": self.record_type, "record_id": self.record_id, "relation": self.relation}
        if self.schema_version is not None:
            row["schema_version"] = self.schema_version
        if self.content_hash is not None:
            row["content_hash"] = self.content_hash.lower()
        return row


@dataclass(frozen=True)
class TraceLink:
    link_type: TraceLinkType
    target_type: str
    target_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "link_type", TraceLinkType(self.link_type))
        _code(self.target_type, "target_type")
        _id(self.target_id, "target_id")

    def to_dict(self) -> dict[str, str]:
        return {"link_type": self.link_type.value, "target_type": self.target_type, "target_id": self.target_id}


@dataclass(frozen=True)
class DecisionEvidence:
    decision_type: str
    outcome: str
    reason_code: str
    rule_version: str
    record_ref: Optional[TraceRecordRef] = None

    def __post_init__(self) -> None:
        for name, value in (
            ("decision_type", self.decision_type), ("outcome", self.outcome),
            ("reason_code", self.reason_code), ("rule_version", self.rule_version),
        ):
            _code(value, name)
        if self.record_ref is not None and not isinstance(self.record_ref, TraceRecordRef):
            raise TraceValidationError("record_ref must be TraceRecordRef")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type, "outcome": self.outcome,
            "reason_code": self.reason_code, "rule_version": self.rule_version,
            "record_ref": self.record_ref.to_dict() if self.record_ref else None,
        }


@dataclass
class TraceSpan:
    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    sequence: int
    stage: TraceStage
    component: str
    operation: str
    started_at: str
    ended_at: Optional[str] = None
    duration_ms: Optional[float] = None
    status: Optional[TraceStatus] = None
    input_refs: List[TraceRecordRef] = field(default_factory=list)
    output_refs: List[TraceRecordRef] = field(default_factory=list)
    decision_evidence: List[DecisionEvidence] = field(default_factory=list)
    counters: Dict[str, int] = field(default_factory=dict)
    error_code: Optional[str] = None

    @property
    def terminal(self) -> bool:
        return self.status is not None

    def to_dict(self) -> dict[str, Any]:
        if not self.terminal or self.ended_at is None or self.duration_ms is None:
            raise TraceStateError("open span cannot be serialized")
        return {
            "span_id": self.span_id, "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id, "sequence": self.sequence,
            "stage": self.stage.value, "component": self.component,
            "operation": self.operation, "started_at": self.started_at,
            "ended_at": self.ended_at, "duration_ms": round(self.duration_ms, 3),
            "status": self.status.value,
            "input_refs": [item.to_dict() for item in self.input_refs],
            "output_refs": [item.to_dict() for item in self.output_refs],
            "decision_evidence": [item.to_dict() for item in self.decision_evidence],
            "counters": dict(sorted(self.counters.items())), "error_code": self.error_code,
        }


@dataclass
class TraceContext:
    """Legacy transport plus an isolated canonical v0 lifecycle."""

    trace_type: TraceType = "agent_run"
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: f"trace_{uuid.uuid4().hex}")
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None
    stages: List[Dict[str, Any]] = field(default_factory=list)
    schema_version: Optional[str] = None
    trace_kind: Optional[TraceKind] = None
    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    parent_trace_id: Optional[str] = None
    handoff_id: Optional[str] = None
    parent_request_id: Optional[str] = None
    original_plan_id: Optional[str] = None
    principal_ref: Optional[str] = None
    created_at: Optional[str] = None
    status: Optional[TraceStatus] = None
    root_span_id: Optional[str] = None
    links: List[TraceLink] = field(default_factory=list)
    spans: List[TraceSpan] = field(default_factory=list)
    _start_mono: float = field(default_factory=time.perf_counter, repr=False)
    _finish_mono: Optional[float] = field(default=None, repr=False)
    _next_sequence: int = field(default=1, init=False, repr=False)
    _mono: Dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _open: set[str] = field(default_factory=set, init=False, repr=False)
    _mode: _TraceMode = field(init=False, repr=False)
    _collection_state: _CollectionState = field(default=_CollectionState.READY, init=False, repr=False)
    _finalized_json: Optional[str] = field(default=None, init=False, repr=False)
    _outcome_set: bool = field(default=False, init=False, repr=False)
    _request_error: Optional[str] = field(default=None, init=False, repr=False)
    _obs_errors: List[str] = field(default_factory=list, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.schema_version is None:
            self._mode = _TraceMode.LEGACY
            return
        if self.schema_version != TRACE_SCHEMA_VERSION:
            raise TraceValidationError("unsupported trace schema_version")
        self._mode = _TraceMode.V0
        if self.trace_kind is None or self.request_id is None:
            raise TraceValidationError("invalid v0 context header")
        self.trace_kind = TraceKind(self.trace_kind)
        _id(self.trace_id, "trace_id")
        _id(self.request_id, "request_id")
        if not self.trace_id.startswith("trace_"):
            raise TraceValidationError("canonical trace_id must start with trace_")
        for name in ("conversation_id", "handoff_id", "parent_request_id", "original_plan_id", "principal_ref"):
            _optional_id(getattr(self, name), name)
        if self.parent_trace_id is not None:
            _id(self.parent_trace_id, "parent_trace_id")
            if not self.parent_trace_id.startswith("trace_"):
                raise TraceValidationError("canonical parent_trace_id must start with trace_")
        if self.metadata or self.stages or self.links or self.spans or self.root_span_id:
            raise TraceValidationError("v0 cannot inherit legacy payload")
        self.created_at = self.created_at or datetime.now(timezone.utc).isoformat()
        _timestamp(self.created_at, "created_at")
        self.started_at = self.created_at
        root = self._start(TraceStage.REQUEST, "trace_context", "request", None, [])
        self.root_span_id = root.span_id

    @classmethod
    def new_request(
        cls,
        *,
        trace_kind: TraceKind,
        request_id: str,
        conversation_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        handoff_id: Optional[str] = None,
        parent_request_id: Optional[str] = None,
        original_plan_id: Optional[str] = None,
        principal_ref: Optional[str] = None,
        trace_id: Optional[str] = None,
        links: Optional[List[TraceLink]] = None,
    ) -> "TraceContext":
        obj = cls(
            schema_version=TRACE_SCHEMA_VERSION, trace_kind=trace_kind,
            request_id=request_id, conversation_id=conversation_id,
            parent_trace_id=parent_trace_id, handoff_id=handoff_id,
            parent_request_id=parent_request_id, original_plan_id=original_plan_id,
            principal_ref=principal_ref, trace_id=trace_id or f"trace_{uuid.uuid4().hex}",
        )
        for link in links or []:
            obj.add_link(link)
        return obj

    @property
    def is_v0(self) -> bool:
        return self._mode is _TraceMode.V0

    @property
    def collected(self) -> bool:
        with self._lock:
            return self._collection_state is _CollectionState.COLLECTED

    @property
    def observability_error_codes(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._obs_errors)

    def instrumentation(self) -> "_SafeInstrumentation":
        return _SafeInstrumentation(self)

    def record_stage(
        self, stage_name: str, *, status: str = "ok", method: str = "", provider: str = "",
        input_summary: Optional[Dict[str, Any]] = None,
        output_summary: Optional[Dict[str, Any]] = None,
        warnings: Optional[List[str]] = None, elapsed_ms: Optional[float] = None,
        error: str = "",
    ) -> None:
        if self.is_v0:
            raise TraceStateError("record_stage is legacy-only")
        self.stages.append(
            {
                "stage": stage_name, "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_ms": round(float(elapsed_ms or 0), 3), "status": status,
                "data": {
                    "method": method, "provider": provider,
                    "input_summary": input_summary or {}, "output_summary": output_summary or {},
                    "warnings": list(warnings or []), "error": error,
                },
            }
        )

    @contextmanager
    def stage_timer(
        self, stage_name: str, *, method: str = "", provider: str = "",
        input_summary: Optional[Dict[str, Any]] = None,
        output_summary_factory: Optional[Any] = None,
        warnings_factory: Optional[Any] = None,
    ) -> Iterator[Dict[str, Any]]:
        if self.is_v0:
            raise TraceStateError("stage_timer is legacy-only")
        payload: Dict[str, Any] = {}
        started = time.perf_counter()
        try:
            yield payload
            self.record_stage(
                stage_name, method=method, provider=provider, input_summary=input_summary,
                output_summary=(output_summary_factory(payload) if output_summary_factory else payload.get("output_summary", {})),
                warnings=(warnings_factory(payload) if warnings_factory else payload.get("warnings", [])),
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            self.record_stage(
                stage_name, status="error", method=method, provider=provider,
                input_summary=input_summary, output_summary=payload.get("output_summary", {}),
                warnings=payload.get("warnings", []),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    def span(
        self, *, stage: TraceStage, component: str, operation: str,
        parent: Optional["_SpanScope"] = None,
        input_refs: Optional[List[TraceRecordRef]] = None,
        exception_error_code: str = "unhandled_exception",
    ) -> "_SpanScope":
        self._require_open()
        _code(component, "component")
        _code(operation, "operation")
        _code(exception_error_code, "error_code")
        if parent is not None and (
            parent.trace is not self or parent.record is None or parent.record.terminal
        ):
            raise TraceStateError("invalid span parent")
        return _SpanScope(
            self, TraceStage(stage), component, operation, parent,
            list(input_refs or []), exception_error_code,
        )

    def add_link(self, link: TraceLink) -> None:
        with self._lock:
            self._require_open()
            if not isinstance(link, TraceLink) or len(self.links) >= MAX_LINKS:
                raise TraceValidationError("invalid or excessive trace link")
            self.links.append(link)

    def set_request_outcome(
        self, status: TraceStatus, *, decision: Optional[DecisionEvidence] = None,
        error_code: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._require_open()
            if self._outcome_set:
                raise TraceStateError("request outcome already set")
            status = TraceStatus(status)
            root = self._root()
            if decision:
                _append_decision(root.decision_evidence, decision)
            if status in {TraceStatus.BLOCKED, TraceStatus.SKIPPED, TraceStatus.PARTIAL} and not root.decision_evidence:
                raise TraceValidationError("bounded decision required")
            if status is TraceStatus.FAILED:
                _code(error_code or "", "error_code")
            elif error_code is not None:
                raise TraceValidationError("only FAILED accepts error_code")
            self.status, self._request_error, self._outcome_set = status, error_code, True

    def finish(self) -> None:
        self._assert_mode_invariant()
        if self.is_v0:
            self._finish_request()
            return
        self._finish_mono = time.perf_counter()
        self.finished_at = datetime.now(timezone.utc).isoformat()

    @property
    def elapsed_ms(self) -> float:
        finished = self._finish_mono if self._finish_mono is not None else time.perf_counter()
        return (finished - self._start_mono) * 1000

    def to_dict(self) -> Dict[str, Any]:
        self._assert_mode_invariant()
        if not self.is_v0:
            total = round(self.elapsed_ms, 3)
            return {
                "trace_id": self.trace_id, "trace_type": self.trace_type,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "elapsed_ms": total, "total_elapsed_ms": total,
                "stages": list(self.stages), "metadata": dict(self.metadata),
            }
        with self._lock:
            if self._finalized_json is None:
                raise TraceStateError("open v0 trace cannot serialize")
            row = _decode_v0_snapshot(self._finalized_json)
        _validate_v0(row)
        return row

    def _assert_mode_invariant(self) -> None:
        if self._mode is _TraceMode.V0:
            if self.schema_version != TRACE_SCHEMA_VERSION:
                raise TraceValidationError("v0 mode/schema invariant violated")
            return
        if self.schema_version is not None:
            raise TraceValidationError("legacy mode/schema invariant violated")

    def _require_open(self) -> None:
        self._assert_mode_invariant()
        if not self.is_v0:
            raise TraceStateError("canonical API requires v0")
        if self._finalized_json is not None or self.finished_at is not None:
            raise TraceStateError("trace finalized")
        if self._collection_state is not _CollectionState.READY:
            raise TraceStateError("trace collection already started")

    def _root(self) -> TraceSpan:
        return self._find(self.root_span_id or "")

    def _find(self, span_id: str) -> TraceSpan:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        raise TraceStateError("span not owned by trace")

    def _start(
        self, stage: TraceStage, component: str, operation: str,
        parent_id: Optional[str], refs: List[TraceRecordRef],
    ) -> TraceSpan:
        with self._lock:
            if self._mode is _TraceMode.V0:
                self._require_open()
            if (
                len(self.spans) >= MAX_SPANS or len(refs) > MAX_REFS
                or any(not isinstance(item, TraceRecordRef) for item in refs)
            ):
                raise TraceValidationError("span bound exceeded")
            if parent_id is not None and (parent_id not in self._open or self._find(parent_id).terminal):
                raise TraceStateError("parent not open")
            span = TraceSpan(
                span_id=f"span_{uuid.uuid4().hex}", trace_id=self.trace_id,
                parent_span_id=parent_id, sequence=self._next_sequence, stage=stage,
                component=component, operation=operation,
                started_at=datetime.now(timezone.utc).isoformat(), input_refs=refs,
            )
            self._next_sequence += 1
            self.spans.append(span)
            self._open.add(span.span_id)
            self._mono[span.span_id] = time.perf_counter()
            return span

    def _finish_span(
        self, span: TraceSpan, status: TraceStatus, error_code: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._require_open()
            if span.span_id not in self._open or self._find(span.span_id) is not span:
                raise TraceStateError("span already finished")
            if any(item.parent_span_id == span.span_id and item.span_id in self._open for item in self.spans):
                raise TraceStateError("child still open")
            status = TraceStatus(status)
            if status in {TraceStatus.BLOCKED, TraceStatus.SKIPPED, TraceStatus.PARTIAL} and not span.decision_evidence:
                raise TraceValidationError("bounded decision required")
            if status is TraceStatus.FAILED:
                _code(error_code or "", "error_code")
            elif error_code is not None:
                raise TraceValidationError("only FAILED accepts error_code")
            span.ended_at = datetime.now(timezone.utc).isoformat()
            span.duration_ms = max(0, (time.perf_counter() - self._mono.pop(span.span_id)) * 1000)
            span.status, span.error_code = status, error_code
            self._open.remove(span.span_id)

    def _finish_request(self, failed_error_code: Optional[str] = None) -> None:
        with self._lock:
            self._require_open()
            outcome = TraceStatus.FAILED if failed_error_code else (self.status or TraceStatus.SUCCESS)
            self._finish_span(self._root(), outcome, failed_error_code or self._request_error)
            self.status = outcome
            self.finished_at = self._root().ended_at
            self._finish_mono = time.perf_counter()
            row = self._build_v0_row()
            _validate_v0(row)
            self._finalized_json = _encode_v0_snapshot(row)

    def _build_v0_row(self) -> dict[str, Any]:
        if self.trace_kind is None or self.status is None:
            raise TraceStateError("v0 trace header is incomplete")
        return {
            "schema_version": TRACE_SCHEMA_VERSION, "trace_kind": self.trace_kind.value,
            "trace_id": self.trace_id, "request_id": self.request_id,
            "conversation_id": self.conversation_id, "parent_trace_id": self.parent_trace_id,
            "handoff_id": self.handoff_id, "parent_request_id": self.parent_request_id,
            "original_plan_id": self.original_plan_id, "principal_ref": self.principal_ref,
            "created_at": self.created_at, "finished_at": self.finished_at,
            "status": self.status.value, "root_span_id": self.root_span_id,
            "links": [item.to_dict() for item in self.links],
            "spans": [item.to_dict() for item in self.spans],
        }

    def _add_span_ref(self, span: TraceSpan, ref: TraceRecordRef, *, output: bool) -> None:
        with self._lock:
            self._require_open()
            if span.span_id not in self._open or self._find(span.span_id) is not span:
                raise TraceStateError("span not active")
            _append_ref(span, ref, output=output)

    def _add_span_decision(self, span: TraceSpan, decision: DecisionEvidence) -> None:
        with self._lock:
            self._require_open()
            if span.span_id not in self._open or self._find(span.span_id) is not span:
                raise TraceStateError("span not active")
            _append_decision(span.decision_evidence, decision)

    def _set_span_counter(self, span: TraceSpan, name: str, value: int) -> None:
        with self._lock:
            self._require_open()
            if span.span_id not in self._open or self._find(span.span_id) is not span:
                raise TraceStateError("span not active")
            _code(name, "counter")
            if (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                or (name not in span.counters and len(span.counters) >= MAX_COUNTERS)
            ):
                raise TraceValidationError("invalid counter")
            span.counters[name] = value

    def _degrade(self, code: str) -> None:
        _code(code, "observability code")
        with self._lock:
            if code not in self._obs_errors:
                self._obs_errors.append(code)

    def _safe_degrade(self, code: str) -> None:
        try:
            self._degrade(code)
        except Exception:
            return


class _SpanScope:
    def __init__(self, trace, stage, component, operation, parent, refs, error):
        self.trace, self.stage, self.component = trace, stage, component
        self.operation, self.parent, self.refs, self.error = operation, parent, refs, error
        self.record: Optional[TraceSpan] = None

    def __enter__(self) -> "_SpanScope":
        parent_id = self.parent.record.span_id if self.parent and self.parent.record else self.trace.root_span_id
        self.record = self.trace._start(self.stage, self.component, self.operation, parent_id, self.refs)
        return self

    def __exit__(self, typ, exc, tb) -> bool:
        if self.record and not self.record.terminal:
            try:
                self.trace._finish_span(
                    self.record, TraceStatus.FAILED if typ else TraceStatus.SUCCESS,
                    self.error if typ else None,
                )
            except Exception:
                self.trace._safe_degrade("span_cleanup_failed")
        elif typ:
            self.trace._safe_degrade("exception_after_span_terminal")
        return False

    def _active(self) -> TraceSpan:
        if self.record is None or self.record.terminal:
            raise TraceStateError("span not active")
        return self.record

    def add_input_ref(self, ref: TraceRecordRef) -> None:
        self.trace._add_span_ref(self._active(), ref, output=False)

    def add_output_ref(self, ref: TraceRecordRef) -> None:
        self.trace._add_span_ref(self._active(), ref, output=True)

    def add_decision(self, value: DecisionEvidence) -> None:
        self.trace._add_span_decision(self._active(), value)

    def set_counter(self, name: str, value: int) -> None:
        self.trace._set_span_counter(self._active(), name, value)

    def succeed(self) -> None:
        self.trace._finish_span(self._active(), TraceStatus.SUCCESS)

    def fail(self, code: str) -> None:
        self.trace._finish_span(self._active(), TraceStatus.FAILED, code)

    def blocked(self, evidence: DecisionEvidence) -> None:
        self.add_decision(evidence)
        self.trace._finish_span(self._active(), TraceStatus.BLOCKED)

    def skipped(self, evidence: DecisionEvidence) -> None:
        self.add_decision(evidence)
        self.trace._finish_span(self._active(), TraceStatus.SKIPPED)

    def partial(self, evidence: DecisionEvidence) -> None:
        self.add_decision(evidence)
        self.trace._finish_span(self._active(), TraceStatus.PARTIAL)


def _ref_from_safe_spec(spec: Any) -> Optional[TraceRecordRef]:
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise TraceValidationError("safe record ref must be a primitive specification")
    fields = set(spec)
    if (
        not _REF_REQUIRED_FIELDS.issubset(fields)
        or not fields.issubset(_REF_REQUIRED_FIELDS | _REF_OPTIONAL_FIELDS)
    ):
        raise TraceValidationError("invalid safe record ref specification")
    return TraceRecordRef(**spec)


def _decision_from_safe_primitives(
    *,
    decision_type: Any,
    outcome: Any,
    reason_code: Any,
    rule_version: Any,
    record_ref: Optional[dict[str, Any]] = None,
) -> DecisionEvidence:
    return DecisionEvidence(
        decision_type=decision_type,
        outcome=outcome,
        reason_code=reason_code,
        rule_version=rule_version,
        record_ref=_ref_from_safe_spec(record_ref),
    )


class _SafeInstrumentation:
    def __init__(self, trace: TraceContext) -> None:
        self.trace = trace

    def span(
        self, *, stage: Any, component: Any, operation: Any,
        parent: Optional["_SafeSpanScope"] = None,
        input_refs: Optional[List[dict[str, Any]]] = None,
        exception_error_code: Any = "unhandled_exception",
    ) -> "_SafeSpanScope":
        return _SafeSpanScope(
            self.trace, stage=stage, component=component, operation=operation,
            parent=parent, input_refs=input_refs, exception_error_code=exception_error_code,
        )

    def add_link(self, *, link_type: Any, target_type: Any, target_id: Any) -> bool:
        return self._emit(
            lambda: self.trace.add_link(
                TraceLink(link_type=link_type, target_type=target_type, target_id=target_id)
            )
        )

    def set_request_outcome(
        self, status: Any, *, error_code: Optional[Any] = None,
        decision_type: Optional[Any] = None, outcome: Optional[Any] = None,
        reason_code: Optional[Any] = None, rule_version: Optional[Any] = None,
        record_ref: Optional[dict[str, Any]] = None,
    ) -> bool:
        def emit() -> None:
            fields = (decision_type, outcome, reason_code, rule_version, record_ref)
            decision = None
            if any(item is not None for item in fields):
                if not all(
                    item is not None
                    for item in (decision_type, outcome, reason_code, rule_version)
                ):
                    raise TraceValidationError("incomplete decision evidence")
                decision = _decision_from_safe_primitives(
                    decision_type=decision_type, outcome=outcome,
                    reason_code=reason_code, rule_version=rule_version,
                    record_ref=record_ref,
                )
            self.trace.set_request_outcome(status, decision=decision, error_code=error_code)
        return self._emit(emit)

    def _emit(self, action: Any) -> bool:
        try:
            action()
            return True
        except (TraceValidationError, TraceStateError, TypeError, ValueError):
            self.trace._safe_degrade("trace_emission_rejected")
            return False
        except Exception:
            self.trace._safe_degrade("trace_instrumentation_failed")
            return False


class _SafeSpanScope:
    def __init__(
        self, trace: TraceContext, *, stage: Any, component: Any, operation: Any,
        parent: Optional["_SafeSpanScope"],
        input_refs: Optional[List[dict[str, Any]]],
        exception_error_code: Any,
    ) -> None:
        self.trace, self.stage, self.component = trace, stage, component
        self.operation, self.parent = operation, parent
        self.input_refs, self.exception_error_code = input_refs, exception_error_code
        self._strict_scope: Optional[_SpanScope] = None

    @property
    def record(self) -> Optional[TraceSpan]:
        return self._strict_scope.record if self._strict_scope else None

    def __enter__(self) -> "_SafeSpanScope":
        try:
            if self.parent is not None and self.parent._strict_scope is None:
                raise TraceStateError("safe parent span unavailable")
            strict_input_refs = []
            for spec in self.input_refs or []:
                ref = _ref_from_safe_spec(spec)
                if ref is None:
                    raise TraceValidationError("safe input ref cannot be null")
                strict_input_refs.append(ref)
            self._strict_scope = self.trace.span(
                stage=self.stage, component=self.component, operation=self.operation,
                parent=self.parent._strict_scope if self.parent else None,
                input_refs=strict_input_refs,
                exception_error_code=self.exception_error_code,
            )
            self._strict_scope.__enter__()
        except (TraceValidationError, TraceStateError, TypeError, ValueError):
            self._strict_scope = None
            self.trace._safe_degrade("trace_emission_rejected")
        except Exception:
            self._strict_scope = None
            self.trace._safe_degrade("trace_instrumentation_failed")
        return self

    def __exit__(self, typ, exc, tb) -> bool:
        if self._strict_scope is not None:
            try:
                self._strict_scope.__exit__(typ, exc, tb)
            except Exception:
                self.trace._safe_degrade("span_cleanup_failed")
        return False

    def add_input_ref(
        self, *, record_type: Any, record_id: Any, relation: Any,
        schema_version: Optional[Any] = None, content_hash: Optional[Any] = None,
    ) -> bool:
        return self._add_ref(
            output=False, record_type=record_type, record_id=record_id, relation=relation,
            schema_version=schema_version, content_hash=content_hash,
        )

    def add_output_ref(
        self, *, record_type: Any, record_id: Any, relation: Any,
        schema_version: Optional[Any] = None, content_hash: Optional[Any] = None,
    ) -> bool:
        return self._add_ref(
            output=True, record_type=record_type, record_id=record_id, relation=relation,
            schema_version=schema_version, content_hash=content_hash,
        )

    def _add_ref(self, *, output: bool, **fields: Any) -> bool:
        def emit() -> None:
            scope = self._require_scope()
            ref = TraceRecordRef(**fields)
            scope.add_output_ref(ref) if output else scope.add_input_ref(ref)
        return self._emit(emit)

    def add_decision(
        self, *, decision_type: Any, outcome: Any, reason_code: Any,
        rule_version: Any, record_ref: Optional[dict[str, Any]] = None,
    ) -> bool:
        return self._emit(
            lambda: self._require_scope().add_decision(
                _decision_from_safe_primitives(
                    decision_type=decision_type, outcome=outcome,
                    reason_code=reason_code, rule_version=rule_version,
                    record_ref=record_ref,
                )
            )
        )

    def set_counter(self, name: Any, value: Any) -> bool:
        return self._emit(lambda: self._require_scope().set_counter(name, value))

    def succeed(self) -> bool:
        return self._emit(lambda: self._require_scope().succeed())

    def fail(self, code: Any) -> bool:
        return self._emit(lambda: self._require_scope().fail(code))

    def blocked(
        self, *, decision_type: Any, outcome: Any, reason_code: Any,
        rule_version: Any, record_ref: Optional[dict[str, Any]] = None,
    ) -> bool:
        return self._terminal_with_decision(
            "blocked", decision_type, outcome, reason_code, rule_version, record_ref
        )

    def skipped(
        self, *, decision_type: Any, outcome: Any, reason_code: Any,
        rule_version: Any, record_ref: Optional[dict[str, Any]] = None,
    ) -> bool:
        return self._terminal_with_decision(
            "skipped", decision_type, outcome, reason_code, rule_version, record_ref
        )

    def partial(
        self, *, decision_type: Any, outcome: Any, reason_code: Any,
        rule_version: Any, record_ref: Optional[dict[str, Any]] = None,
    ) -> bool:
        return self._terminal_with_decision(
            "partial", decision_type, outcome, reason_code, rule_version, record_ref
        )

    def _terminal_with_decision(
        self,
        method_name: str,
        decision_type: Any,
        outcome: Any,
        reason_code: Any,
        rule_version: Any,
        record_ref: Optional[dict[str, Any]],
    ) -> bool:
        return self._emit(
            lambda: getattr(self._require_scope(), method_name)(
                _decision_from_safe_primitives(
                    decision_type=decision_type,
                    outcome=outcome,
                    reason_code=reason_code,
                    rule_version=rule_version,
                    record_ref=record_ref,
                )
            )
        )

    def _require_scope(self) -> _SpanScope:
        if self._strict_scope is None:
            raise TraceStateError("safe span unavailable")
        return self._strict_scope

    def _emit(self, action: Any) -> bool:
        try:
            action()
            return True
        except (TraceValidationError, TraceStateError, TypeError, ValueError):
            self.trace._safe_degrade("trace_emission_rejected")
            return False
        except Exception:
            self.trace._safe_degrade("trace_instrumentation_failed")
            return False


class _RequestScope:
    def __init__(self, collector: "TraceCollector", trace: TraceContext, error: str) -> None:
        self.collector, self.trace, self.error = collector, trace, error

    def __enter__(self) -> TraceContext:
        self.trace._require_open()
        _code(self.error, "request error")
        return self.trace

    def __exit__(self, typ, exc, tb) -> bool:
        try:
            self.trace._finish_request(self.error if typ else None)
        except TracePrivacyError:
            self.trace._safe_degrade("trace_privacy_rejected")
        except TraceValidationError:
            self.trace._safe_degrade("trace_validation_rejected")
        except Exception:
            self.trace._safe_degrade("trace_finalization_failed")
        if self.trace._finalized_json is not None:
            try:
                self.collector.collect(self.trace)
            except TracePrivacyError:
                self.trace._safe_degrade("trace_privacy_rejected")
            except TraceValidationError:
                self.trace._safe_degrade("trace_validation_rejected")
            except Exception:
                self.trace._safe_degrade("trace_persistence_failed")
        return False


class TraceCollector:
    def __init__(self, path: Path = DEFAULT_TRACE_PATH) -> None:
        self.path = Path(path)

    def request_scope(
        self, trace: TraceContext, *, exception_error_code: str = "request_failed"
    ) -> _RequestScope:
        if not isinstance(trace, TraceContext) or not trace.is_v0:
            raise TraceStateError("request_scope requires v0")
        trace._assert_mode_invariant()
        return _RequestScope(self, trace, exception_error_code)

    def collect(self, trace: TraceContext) -> None:
        trace._assert_mode_invariant()
        if not trace.is_v0:
            if trace.finished_at is None:
                trace.finish()
            self._append(trace.to_dict())
            return
        with trace._lock:
            trace._assert_mode_invariant()
            if trace._finalized_json is None:
                raise TraceStateError("v0 collect requires finalize")
            if trace._collection_state is _CollectionState.COLLECTING:
                raise TraceStateError("v0 trace collection in progress")
            if trace._collection_state is _CollectionState.COLLECTED:
                raise TraceStateError("v0 trace already collected")
            snapshot = trace._finalized_json
            trace._collection_state = _CollectionState.COLLECTING
        try:
            row = _decode_v0_snapshot(snapshot)
            _validate_v0(row)
            self._append_encoded(snapshot)
        except Exception:
            with trace._lock:
                if trace._collection_state is _CollectionState.COLLECTING:
                    trace._collection_state = _CollectionState.READY
            raise
        with trace._lock:
            if trace._collection_state is not _CollectionState.COLLECTING:
                raise TraceStateError("invalid collection reservation")
            trace._collection_state = _CollectionState.COLLECTED

    def _append(self, row: dict[str, Any]) -> None:
        try:
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
        except Exception:
            raise TraceValidationError("trace serialization failed") from None
        self._append_encoded(encoded)

    def _append_encoded(self, encoded: str) -> None:
        try:
            with _path_lock(self.path):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(encoded + "\n")
        except OSError:
            raise TracePersistenceError("trace append failed") from None


def load_traces(path: Path = DEFAULT_TRACE_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if "schema_version" not in row:
                rows.append(row)
                continue
            if row.get("schema_version") != TRACE_SCHEMA_VERSION:
                continue
            try:
                _validate_v0(row)
            except TraceValidationError:
                continue
            rows.append(row)
    return rows


def _append_ref(span: TraceSpan, ref: TraceRecordRef, *, output: bool) -> None:
    if not isinstance(ref, TraceRecordRef):
        raise TraceValidationError("invalid reference")
    if len(span.input_refs) + len(span.output_refs) >= MAX_REFS:
        raise TraceValidationError("reference bound exceeded")
    (span.output_refs if output else span.input_refs).append(ref)


def _append_decision(values: List[DecisionEvidence], decision: DecisionEvidence) -> None:
    if not isinstance(decision, DecisionEvidence) or len(values) >= MAX_DECISIONS:
        raise TraceValidationError("invalid or excessive decision")
    values.append(decision)


def _validate_v0(row: dict[str, Any]) -> None:
    if set(row) != _TOP_LEVEL_FIELDS or row.get("schema_version") != TRACE_SCHEMA_VERSION:
        raise TraceValidationError("invalid canonical schema")
    try:
        TraceKind(row["trace_kind"])
        trace_status = TraceStatus(row["status"])
    except (TypeError, ValueError):
        raise TraceValidationError("invalid trace enum") from None
    _id(row["trace_id"], "trace_id")
    if not row["trace_id"].startswith("trace_"):
        raise TraceValidationError("canonical trace_id must start with trace_")
    _id(row["request_id"], "request_id")
    created_at = _timestamp(row["created_at"], "created_at")
    finished_at = _timestamp(row["finished_at"], "finished_at")
    if finished_at < created_at:
        raise TraceValidationError("trace finished_at precedes created_at")
    for name in ("conversation_id", "handoff_id", "parent_request_id", "original_plan_id", "principal_ref"):
        _optional_id(row[name], name)
    if row["parent_trace_id"] is not None:
        _id(row["parent_trace_id"], "parent_trace_id")
        if not row["parent_trace_id"].startswith("trace_"):
            raise TraceValidationError("canonical parent_trace_id must start with trace_")
    _id(row["root_span_id"], "root_span_id")

    links, spans = row["links"], row["spans"]
    if not isinstance(links, list) or len(links) > MAX_LINKS:
        raise TraceValidationError("invalid link collection bound")
    if not isinstance(spans, list) or not spans or len(spans) > MAX_SPANS:
        raise TraceValidationError("invalid span collection bound")
    for link in links:
        if not isinstance(link, dict) or set(link) != _LINK_FIELDS:
            raise TraceValidationError("invalid trace link")
        try:
            TraceLink(TraceLinkType(link["link_type"]), link["target_type"], link["target_id"])
        except (TypeError, ValueError):
            raise TraceValidationError("invalid trace link") from None

    span_by_id: dict[str, dict[str, Any]] = {}
    sequences: List[int] = []
    root_rows: List[dict[str, Any]] = []
    for span in spans:
        if not isinstance(span, dict) or set(span) != _SPAN_FIELDS:
            raise TraceValidationError("invalid span schema")
        span_id, sequence = span["span_id"], span["sequence"]
        _id(span_id, "span_id")
        if not span_id.startswith("span_"):
            raise TraceValidationError("canonical span_id must start with span_")
        if (
            not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0
            or span_id in span_by_id
        ):
            raise TraceValidationError("invalid span identity")
        if span["trace_id"] != row["trace_id"]:
            raise TraceValidationError("span trace owner mismatch")
        if span["parent_span_id"] is None:
            root_rows.append(span)
        else:
            _id(span["parent_span_id"], "parent_span_id")
        try:
            TraceStage(span["stage"])
            status = TraceStatus(span["status"])
        except (TypeError, ValueError):
            raise TraceValidationError("invalid span enum") from None
        _code(span["component"], "component")
        _code(span["operation"], "operation")
        started_at = _timestamp(span["started_at"], "started_at")
        ended_at = _timestamp(span["ended_at"], "ended_at")
        if ended_at < started_at:
            raise TraceValidationError("span ended_at precedes started_at")
        duration = span["duration_ms"]
        if (
            not isinstance(duration, (int, float)) or isinstance(duration, bool)
            or not math.isfinite(duration) or duration < 0
        ):
            raise TraceValidationError("invalid span duration")
        input_refs, output_refs = _validate_refs(span["input_refs"]), _validate_refs(span["output_refs"])
        if len(input_refs) + len(output_refs) > MAX_REFS:
            raise TraceValidationError("reference bound exceeded")
        decisions = _validate_decisions(span["decision_evidence"])
        counters = span["counters"]
        if not isinstance(counters, dict) or len(counters) > MAX_COUNTERS:
            raise TraceValidationError("counter bound exceeded")
        for name, value in counters.items():
            _code(name, "counter")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise TraceValidationError("invalid counter")
        if status is TraceStatus.FAILED:
            _code(span["error_code"] or "", "error_code")
        elif span["error_code"] is not None:
            raise TraceValidationError("only FAILED accepts error_code")
        if status in {TraceStatus.BLOCKED, TraceStatus.SKIPPED, TraceStatus.PARTIAL} and not decisions:
            raise TraceValidationError("bounded decision required")
        span_by_id[span_id] = span
        sequences.append(sequence)

    if sequences != list(range(1, len(spans) + 1)):
        raise TraceValidationError("invalid serialized sequence order")
    if len(root_rows) != 1:
        raise TraceValidationError("canonical trace requires exactly one root")
    root = root_rows[0]
    if (
        root["span_id"] != row["root_span_id"] or root["parent_span_id"] is not None
        or root["sequence"] != 1 or root["stage"] != TraceStage.REQUEST.value
        or root["status"] != trace_status.value
    ):
        raise TraceValidationError("invalid canonical root")
    for span in spans:
        parent_id = span["parent_span_id"]
        if parent_id is None:
            continue
        parent = span_by_id.get(parent_id)
        if parent is None:
            raise TraceValidationError("span parent not owned by trace")
        if parent["sequence"] >= span["sequence"]:
            raise TraceValidationError("span parent must precede child")
    _privacy(row)


def _validate_refs(value: Any) -> List[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_REFS:
        raise TraceValidationError("reference bound exceeded")
    for ref in value:
        if not isinstance(ref, dict):
            raise TraceValidationError("invalid record reference")
        fields = set(ref)
        if (
            not _REF_REQUIRED_FIELDS.issubset(fields)
            or not fields.issubset(_REF_REQUIRED_FIELDS | _REF_OPTIONAL_FIELDS)
        ):
            raise TraceValidationError("invalid record reference schema")
        try:
            TraceRecordRef(**ref)
        except (TypeError, ValueError):
            raise TraceValidationError("invalid record reference") from None
    return value


def _validate_decisions(value: Any) -> List[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_DECISIONS:
        raise TraceValidationError("decision bound exceeded")
    for decision in value:
        if not isinstance(decision, dict) or set(decision) != _DECISION_FIELDS:
            raise TraceValidationError("invalid decision evidence")
        ref = decision["record_ref"]
        if ref is not None:
            _validate_refs([ref])
            ref = TraceRecordRef(**ref)
        try:
            DecisionEvidence(
                decision["decision_type"], decision["outcome"], decision["reason_code"],
                decision["rule_version"], ref,
            )
        except (TypeError, ValueError):
            raise TraceValidationError("invalid decision evidence") from None
    return value


def _encode_v0_snapshot(row: dict[str, Any]) -> str:
    try:
        return json.dumps(row, ensure_ascii=False, sort_keys=True)
    except Exception:
        raise TraceValidationError("trace serialization failed") from None


def _decode_v0_snapshot(encoded: str) -> dict[str, Any]:
    try:
        row = json.loads(encoded)
    except (TypeError, json.JSONDecodeError):
        raise TraceValidationError("invalid finalized trace snapshot") from None
    if not isinstance(row, dict):
        raise TraceValidationError("invalid finalized trace snapshot")
    return row


def _privacy(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _privacy(item, path + (str(key),))
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _privacy(item, path)
        return
    if not isinstance(value, str):
        return
    lowered = value.casefold()
    unsafe_path = (
        value.startswith(("/", "~/", "\\\\"))
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None
        or lowered.startswith("file:")
    )
    unsafe_credential = any(
        pattern.search(value) is not None
        for pattern in (
            _BEARER_CREDENTIAL, _QUERY_CREDENTIAL, _ASSIGNED_CREDENTIAL,
            _JUPYTER_CREDENTIAL, _API_CREDENTIAL,
        )
    )
    if (
        "\n" in value or "\r" in value or unsafe_path or "://" in lowered
        or unsafe_credential
    ):
        raise TracePrivacyError("trace persistence rejected unsafe value")


def _path_lock(path: Path) -> threading.Lock:
    resolved = path.expanduser().resolve()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.Lock())
