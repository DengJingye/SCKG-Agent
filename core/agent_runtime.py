from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Optional

from pydantic import BaseModel, ValidationError

from core.models import (
    AgentRoleResult,
    AgentRunEvent,
    AgentRunTrace,
    ToolCall,
    ToolResult,
    ToolSpec,
)


ToolFn = Callable[..., Any]


class RegisteredTool(BaseModel):
    spec: ToolSpec
    fn: ToolFn
    input_model: Optional[type[BaseModel]] = None

    model_config = {"arbitrary_types_allowed": True}


class ToolRegistry:
    """Small typed tool registry for governed agent workflows."""

    def __init__(self) -> None:
        self._tools: Dict[str, RegisteredTool] = {}

    def register(
        self,
        *,
        spec: ToolSpec,
        fn: ToolFn,
        input_model: Optional[type[BaseModel]] = None,
    ) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = RegisteredTool(
            spec=spec,
            fn=fn,
            input_model=input_model,
        )

    def get(self, name: str) -> RegisteredTool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]


class ToolExecutor:
    """Execute typed tools and append trace events without mutating evidence."""

    def __init__(
        self,
        registry: ToolRegistry,
        trace: Optional[AgentRunTrace] = None,
        *,
        max_tool_iterations: int = 24,
    ) -> None:
        self.registry = registry
        self.trace = trace or AgentRunTrace(
            trace_id=f"trace_{uuid.uuid4().hex}",
            max_tool_iterations=max_tool_iterations,
        )
        self._seen_fingerprints: set[str] = set()

    def run_tool(
        self,
        tool_name: str,
        *,
        node_name: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        args = args or {}
        args_hash = stable_args_hash(args)
        call_id = f"call_{uuid.uuid4().hex[:12]}"
        started = datetime.now(timezone.utc)
        call = ToolCall(
            trace_id=self.trace.trace_id,
            call_id=call_id,
            node_name=node_name,
            tool_name=tool_name,
            args_hash=args_hash,
            started_at=started,
        )
        fingerprint = f"{node_name}:{tool_name}:{args_hash}"
        if len(self.trace.events) >= self.trace.max_tool_iterations:
            self.trace.invalid_action_count += 1
            return self._record_blocked(call, "max_tool_iterations_exceeded", "Tool iteration budget exceeded.")
        if fingerprint in self._seen_fingerprints:
            self.trace.repeated_call_count += 1
            self.trace.invalid_action_count += 1
            return self._record_blocked(call, "repeated_tool_call", "Repeated tool call fingerprint detected.")
        self._seen_fingerprints.add(fingerprint)

        timer = time.perf_counter()
        try:
            registered = self.registry.get(tool_name)
            payload = self._validate_args(registered, args)
            result = registered.fn(**payload)
            ended = datetime.now(timezone.utc)
            tool_result = ToolResult(
                trace_id=call.trace_id,
                call_id=call.call_id,
                node_name=call.node_name,
                tool_name=call.tool_name,
                args_hash=call.args_hash,
                status="ok",
                result=result,
                result_size=result_size(result),
                latency_ms=(time.perf_counter() - timer) * 1000,
                started_at=started,
                ended_at=ended,
            )
        except Exception as exc:
            ended = datetime.now(timezone.utc)
            tool_result = ToolResult(
                trace_id=call.trace_id,
                call_id=call.call_id,
                node_name=call.node_name,
                tool_name=call.tool_name,
                args_hash=call.args_hash,
                status="error",
                error_type=type(exc).__name__,
                error_message=str(exc),
                result_size=0,
                latency_ms=(time.perf_counter() - timer) * 1000,
                started_at=started,
                ended_at=ended,
            )
        self.trace.events.append(_event_from_result(tool_result))
        return tool_result

    def add_role_result(
        self,
        role_name: str,
        *,
        status: str = "ok",
        input_summary: Optional[Dict[str, Any]] = None,
        output_summary: Optional[Dict[str, Any]] = None,
        vetoed: bool = False,
        warnings: Optional[Iterable[str]] = None,
    ) -> None:
        self.trace.role_results.append(
            AgentRoleResult(
                role_name=role_name,
                status=status,  # type: ignore[arg-type]
                input_summary=input_summary or {},
                output_summary=output_summary or {},
                vetoed=vetoed,
                warnings=list(warnings or []),
            )
        )
        if vetoed:
            self.trace.blocked_by_guardrail = True

    def _validate_args(
        self,
        registered: RegisteredTool,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not registered.input_model:
            return args
        try:
            model = registered.input_model.model_validate(args)
        except ValidationError:
            raise
        return model.model_dump()

    def _record_blocked(
        self,
        call: ToolCall,
        error_type: str,
        error_message: str,
    ) -> ToolResult:
        now = datetime.now(timezone.utc)
        result = ToolResult(
            trace_id=call.trace_id,
            call_id=call.call_id,
            node_name=call.node_name,
            tool_name=call.tool_name,
            args_hash=call.args_hash,
            status="blocked",
            error_type=error_type,
            error_message=error_message,
            result_size=0,
            latency_ms=0.0,
            started_at=call.started_at,
            ended_at=now,
        )
        self.trace.events.append(_event_from_result(result))
        return result


def stable_args_hash(args: Dict[str, Any]) -> str:
    payload = json.dumps(_jsonable(args), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def result_size(result: Any) -> int:
    if result is None:
        return 0
    if isinstance(result, (list, tuple, set, dict, str)):
        return len(result)
    try:
        return len(json.dumps(_jsonable(result), ensure_ascii=False))
    except Exception:
        return 1


def _event_from_result(result: ToolResult) -> AgentRunEvent:
    return AgentRunEvent(
        trace_id=result.trace_id,
        event_id=result.call_id,
        node_name=result.node_name,
        tool_name=result.tool_name,
        status=result.status,
        args_hash=result.args_hash,
        latency_ms=result.latency_ms,
        error_type=result.error_type,
        result_size=result.result_size,
        started_at=result.started_at,
        ended_at=result.ended_at,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value
