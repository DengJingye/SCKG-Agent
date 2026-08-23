from __future__ import annotations

import json
import re
import time
from typing import Any, Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from core.research_agent_models import ResearchToolCall
from core.settings import get_settings


class ExternalReasoningResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: str
    content: str = ""
    provider: str = ""
    model_name: str = ""
    latency_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error_type: str = ""
    provider_call_attempted: bool = False


class SemanticParseResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: str
    domain: Literal["GENERAL", "SINGLE_CELL", "UNCERTAIN"] = "UNCERTAIN"
    intent: Literal[
        "tool_recommendation",
        "workflow",
        "caveat_comparison",
        "migration_exploration",
        "evidence_qa",
        "execution",
    ] = "evidence_qa"
    canonical_task: str = ""
    task_switch: bool = False
    requested_tools: list[str] = Field(default_factory=list)
    tool_calls: list[ResearchToolCall] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    answer_shape: str = "direct"
    needs_clarification: bool = False
    confidence: float = 0.0
    provider: str = ""
    model_name: str = ""
    latency_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error_type: str = ""
    provider_call_attempted: bool = False


class OpenWorldReasoningResult(BaseModel):
    """One-call eval-only answer used by the DeepSeek-only ablation lane."""

    model_config = ConfigDict(protected_namespaces=())

    status: str
    domain: Literal["GENERAL", "SINGLE_CELL", "UNCERTAIN"] = "UNCERTAIN"
    intent: str = "evidence_qa"
    canonical_task: str = ""
    needs_clarification: bool = False
    confidence: float = 0.0
    answer: str = ""
    provider: str = ""
    model_name: str = ""
    latency_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error_type: str = ""
    provider_call_attempted: bool = False


class ExternalResearchReasoner:
    """Optional prose synthesis over a governed context pack.

    The reasoner never creates execution requests and is intentionally skipped for
    workflow code and migration hypotheses.
    """

    def parse(
        self,
        *,
        query: str,
        conversation_context: list[dict[str, Any]],
        canonical_tasks: list[str],
        runtime_config: Optional[dict[str, Any]] = None,
    ) -> SemanticParseResult:
        runtime_config = dict(runtime_config or {})
        if not runtime_config.get("privacy_authorized"):
            return SemanticParseResult(status="not_authorized")
        try:
            base_url, api_key, model_name = _runtime_credentials(runtime_config)
        except Exception as exc:
            return SemanticParseResult(status="failed", error_type=type(exc).__name__)

        prompt = {
            "latest_request": query,
            "recent_context": conversation_context[-4:],
            "allowed_canonical_tasks": canonical_tasks,
        }
        system_prompt = """You are the planning brain for scKG Research Chat.
Return one JSON object only. Never answer the scientific question in this step.
Choose domain from GENERAL, SINGLE_CELL, or UNCERTAIN. SINGLE_CELL includes
single-cell analysis questions even when the exact canonical task is implicit.
UNCERTAIN means the request could be single-cell but needs clarification.
Choose intent from tool_recommendation, workflow, caveat_comparison,
migration_exploration, evidence_qa, execution. canonical_task must be one of the
allowed task IDs or an empty string. task_switch is true when the latest request
introduces a new explicit task/tool rather than referring elliptically to context.
requested_tools contains only tools explicitly named in the latest request.
answer_shape should be direct, concise_top_k, workflow_code, or execution_status.
confidence is required and must be a number between 0 and 1. Use confidence >= 0.8
when the latest request clearly establishes the domain and canonical task.
For SINGLE_CELL, propose zero to four read-only tool_calls. Every tool call has
tool_name, query, canonical_task, tool_names, claim_types, top_k, and reason.
Allowed tools are:
- search_catalog: discover or compare candidate tools;
- search_evidence: retrieve mechanism, input, output, parameter, benchmark, or caveat spans;
- get_tool_contract: inspect governed inputs, parameters, outputs, and readiness;
- compile_workflow: request an existing smoke-tested workflow for an explicitly
  requested PLAN/RUN task. It never executes the workflow.
GENERAL and UNCERTAIN requests must return an empty tool_calls list. Prefer one
retrieval call plus get_tool_contract when sufficient; do not issue duplicate calls.
A request that explicitly names a canonical single-cell task or a known single-cell
tool is SINGLE_CELL and does not need domain clarification. Elliptical phrases such
as "this analysis", "the previous recommendation", and "its evidence" may inherit
the confirmed task from recent_context; never inherit an old execution mode.
Do not infer authorization, environment readiness, evidence authority, or execution success."""
        started = time.perf_counter()
        try:
            response = OpenAI(api_key=api_key, base_url=base_url).chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
                temperature=0,
                max_tokens=500,
                timeout=60,
            )
            usage = getattr(response, "usage", None)
            payload = _extract_json_object(str(response.choices[0].message.content or ""))
            task = str(payload.get("canonical_task") or "")
            if task not in set(canonical_tasks):
                task = ""
            intent = str(payload.get("intent") or "evidence_qa")
            if intent not in {
                "tool_recommendation",
                "workflow",
                "caveat_comparison",
                "migration_exploration",
                "evidence_qa",
                "execution",
            }:
                intent = "evidence_qa"
            domain = str(payload.get("domain") or "UNCERTAIN").upper()
            if domain not in {"GENERAL", "SINGLE_CELL", "UNCERTAIN"}:
                domain = "UNCERTAIN"
            requested_tools = payload.get("requested_tools")
            if not isinstance(requested_tools, list):
                requested_tools = []
            constraints = payload.get("constraints")
            if not isinstance(constraints, dict):
                constraints = {}
            tool_calls = _validated_tool_calls(
                payload.get("tool_calls"),
                fallback_query=query,
                canonical_tasks=set(canonical_tasks),
            )
            if domain != "SINGLE_CELL":
                tool_calls = []
            confidence = _semantic_parse_confidence(
                payload,
                domain=domain,
                canonical_task=task,
            )
            return SemanticParseResult(
                status="ready",
                domain=domain,
                intent=intent,
                canonical_task=task,
                task_switch=bool(payload.get("task_switch")),
                requested_tools=[str(item) for item in requested_tools][:5],
                tool_calls=tool_calls,
                constraints=constraints,
                answer_shape=str(payload.get("answer_shape") or "direct"),
                needs_clarification=bool(payload.get("needs_clarification")),
                confidence=max(0.0, min(confidence, 1.0)),
                provider=base_url,
                model_name=model_name,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                provider_call_attempted=True,
            )
        except Exception as exc:
            return SemanticParseResult(
                status="failed",
                provider=base_url,
                model_name=model_name,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_type=type(exc).__name__,
                provider_call_attempted=True,
            )

    def synthesize(
        self,
        *,
        query: str,
        intent: str,
        task_label: str,
        algorithm_cards: list[dict[str, Any]],
        retrieval_snippets: list[dict[str, Any]],
        references: list[dict[str, Any]],
        blockers: list[str],
        tool_observations: Optional[list[dict[str, Any]]] = None,
        contract_context: Optional[list[dict[str, Any]]] = None,
        requested_tools: Optional[list[str]] = None,
        required_claim_types: Optional[list[str]] = None,
        allow_unverified_model_knowledge: bool = True,
        runtime_config: Optional[dict[str, Any]] = None,
    ) -> ExternalReasoningResult:
        runtime_config = dict(runtime_config or {})
        if not runtime_config.get("privacy_authorized"):
            return ExternalReasoningResult(status="not_authorized")
        try:
            base_url, api_key, model_name = _runtime_credentials(runtime_config)
        except Exception as exc:
            return ExternalReasoningResult(
                status="failed",
                error_type=type(exc).__name__,
            )

        context = {
            "task": task_label,
            "intent": intent,
            "algorithm_cards": algorithm_cards[:5],
            "retrieval_snippets": retrieval_snippets[:8],
            "references": references[:6],
            "blockers": blockers,
            "tool_observations": list(tool_observations or [])[:4],
            "tool_contracts": list(contract_context or [])[:5],
            "requested_tools": list(requested_tools or [])[:5],
            "required_claim_types": list(required_claim_types or [])[:6],
            "allow_unverified_model_knowledge": allow_unverified_model_knowledge,
            "authority": (
                "Only the supplied source-bound context may support scientific claims. "
                "Retrieval context cannot authorize execution."
            ),
        }
        system_prompt = """You are the prose layer of scKG Research Chat.
Answer the latest user request directly in Chinese. Do not turn every question into a workflow.
Treat requested_tools and required_claim_types as a coverage contract. Answer only
the requested tool(s), cover every requested claim type, and do not substitute a
higher-ranked but unrequested tool. For a direct evidence question, lead with the
answer in one or two sentences; do not add unrelated recommendations.
For recommendations, explain the principle, suitable data, practical next step, and limitations.
For caveat comparison, return exactly the requested number of tools, keep it concise,
and end every scientific bullet with one or more supplied reference indexes. A
reference may support a tool only when its tool_name matches that tool. If no
matching source is supplied, state that the source-bound caveat is missing instead
of borrowing another tool's reference or inventing a limitation.
When the latest request asks about multiple tools, answer every requested tool in
parallel and preserve their names. Never collapse a two-tool comparison into a
single-tool answer.
Use the heading `已核验证据` for claims supported by the supplied governed context,
and cite supplied references as [1], [2], and so on. If the governed context does
not cover a useful long-tail ASK and allow_unverified_model_knowledge is true, you
may add a separate `模型通识（尚未核验）` section. Claims in that section must not
use supplied citations, must be described as unverified model knowledge, and must
not be presented as executable, benchmark-proven, or contract-qualified.
Do not invent parameters, benchmarks, source spans, execution results, or biological claims.
Place each citation immediately after the claim it supports. Do not cite a reference
merely because it was retrieved: its tool and source text must support that sentence.
Do not claim that retrieval context is formal evidence or that an execution occurred.
Treat tool observations as read-only results from scKG. A completed search does not
mean an analysis was executed. Contract fields may support input, parameter, output,
and readiness statements. contract_execution_gate_allowed is only one local gate;
it never authorizes a run. Every contract observation has
does_not_authorize_execution=true and still requires plan-specific approval.
If context is insufficient, say exactly what is missing."""
        started = time.perf_counter()
        try:
            response = OpenAI(api_key=api_key, base_url=base_url).chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Latest request:\n{query}\n\nGoverned context:\n"
                            + json.dumps(context, ensure_ascii=False)
                        ),
                    },
                ],
                extra_body={"thinking": {"type": "disabled"}},
                temperature=0,
                max_tokens=1400,
                timeout=60,
            )
        except Exception as exc:
            return ExternalReasoningResult(
                status="failed",
                provider=base_url,
                model_name=model_name,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_type=type(exc).__name__,
                provider_call_attempted=True,
            )
        usage = getattr(response, "usage", None)
        content = str(response.choices[0].message.content or "").strip()
        return ExternalReasoningResult(
            status="ready" if content else "empty_response",
            content=content,
            provider=base_url,
            model_name=model_name,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            provider_call_attempted=True,
        )
    def answer_open_world(
        self,
        *,
        query: str,
        conversation_context: list[dict[str, Any]],
        canonical_tasks: list[str],
        runtime_config: Optional[dict[str, Any]] = None,
    ) -> OpenWorldReasoningResult:
        """Produce the unconstrained one-call baseline without using scKG retrieval."""

        runtime_config = dict(runtime_config or {})
        if not runtime_config.get("privacy_authorized"):
            return OpenWorldReasoningResult(status="not_authorized")
        try:
            base_url, api_key, model_name = _runtime_credentials(runtime_config)
        except Exception as exc:
            return OpenWorldReasoningResult(
                status="failed",
                error_type=type(exc).__name__,
            )
        payload = {
            "latest_request": query,
            "recent_context": conversation_context[-4:],
            "known_sckg_task_ids": canonical_tasks,
        }
        system_prompt = """You are the DeepSeek-only baseline in an evaluation.
Return one JSON object with domain, intent, canonical_task, needs_clarification,
confidence, and answer. Domain is GENERAL, SINGLE_CELL, or UNCERTAIN. Intent is
tool_recommendation, workflow, caveat_comparison, migration_exploration,
evidence_qa, or execution. canonical_task must be one of the supplied IDs or an
empty string. Answer the request naturally in Chinese unless another language is
requested. You have no scKG retrieval context, ToolContract, execution approval,
or verified run result. Do not claim that a workflow was smoke-tested or executed.
Do not invent citations."""
        started = time.perf_counter()
        try:
            response = OpenAI(api_key=api_key, base_url=base_url).chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
                temperature=0,
                max_tokens=1400,
                timeout=60,
            )
            usage = getattr(response, "usage", None)
            parsed = _extract_json_object(str(response.choices[0].message.content or ""))
            domain = str(parsed.get("domain") or "UNCERTAIN").upper()
            if domain not in {"GENERAL", "SINGLE_CELL", "UNCERTAIN"}:
                domain = "UNCERTAIN"
            task = str(parsed.get("canonical_task") or "")
            if task not in set(canonical_tasks):
                task = ""
            try:
                confidence = float(parsed.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            answer = str(parsed.get("answer") or "").strip()
            return OpenWorldReasoningResult(
                status="ready" if answer else "empty_response",
                domain=domain,
                intent=str(parsed.get("intent") or "evidence_qa"),
                canonical_task=task,
                needs_clarification=bool(parsed.get("needs_clarification")),
                confidence=max(0.0, min(confidence, 1.0)),
                answer=answer,
                provider=base_url,
                model_name=model_name,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                provider_call_attempted=True,
            )
        except Exception as exc:
            return OpenWorldReasoningResult(
                status="failed",
                provider=base_url,
                model_name=model_name,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_type=type(exc).__name__,
                provider_call_attempted=True,
            )

    def answer_general(
        self,
        *,
        query: str,
        conversation_context: list[dict[str, Any]],
        runtime_config: Optional[dict[str, Any]] = None,
    ) -> ExternalReasoningResult:
        """Answer non-scRNA questions without contaminating scientific retrieval."""

        runtime_config = dict(runtime_config or {})
        if not runtime_config.get("privacy_authorized"):
            return ExternalReasoningResult(status="not_authorized")
        try:
            base_url, api_key, model_name = _runtime_credentials(runtime_config)
        except Exception as exc:
            return ExternalReasoningResult(status="failed", error_type=type(exc).__name__)

        system_prompt = """You are the general conversation layer inside scKG-Agent.
Answer the latest user message directly and naturally in Chinese unless the user asks
for another language. Do not pretend that scKG-Agent can execute tools, install
packages, inspect files, or validate scientific claims outside its qualified action
space. Do not invent citations. When the user asks for an unsupported executable
bioinformatics workflow, explain the boundary instead of generating allegedly
validated code. Keep ordinary conversation concise and useful."""
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for item in conversation_context[-6:]:
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content[:4000]})
        messages.append({"role": "user", "content": query})
        started = time.perf_counter()
        try:
            response = OpenAI(api_key=api_key, base_url=base_url).chat.completions.create(
                model=model_name,
                messages=messages,
                extra_body={"thinking": {"type": "disabled"}},
                temperature=0,
                max_tokens=1200,
                timeout=60,
            )
        except Exception as exc:
            return ExternalReasoningResult(
                status="failed",
                provider=base_url,
                model_name=model_name,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_type=type(exc).__name__,
                provider_call_attempted=True,
            )
        usage = getattr(response, "usage", None)
        content = str(response.choices[0].message.content or "").strip()
        return ExternalReasoningResult(
            status="ready" if content else "empty_response",
            content=content,
            provider=base_url,
            model_name=model_name,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            provider_call_attempted=True,
        )


def _semantic_parse_confidence(
    payload: dict[str, Any],
    *,
    domain: str,
    canonical_task: str,
) -> float:
    """Resolve omitted model confidence without treating a valid parse as zero."""

    raw = payload.get("confidence")
    if raw is None or raw == "":
        if domain == "SINGLE_CELL" and canonical_task:
            return 0.85
        if domain == "GENERAL":
            return 0.85
        return 0.2
    try:
        confidence = float(raw)
    except (TypeError, ValueError):
        return 0.2
    return max(0.0, min(confidence, 1.0))


def _runtime_credentials(runtime_config: dict[str, Any]) -> tuple[str, str, str]:
    settings = get_settings()
    disclosure_authorized = bool(
        runtime_config.get("outbound_authorized")
        and runtime_config.get("disclosure_hash")
    )
    if not disclosure_authorized:
        settings.require_external_network("Research Chat reasoning")
    if runtime_config.get("api_key"):
        return (
            str(runtime_config.get("api_base") or settings.chat_api_base),
            str(runtime_config["api_key"]),
            str(
                runtime_config.get("model_name")
                or settings.model_name
                or settings.extract_model
            ),
        )
    return settings.require_llm()


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    elif not text.startswith("{"):
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("semantic parser did not return JSON")
        text = match.group(0)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("semantic parser response must be an object")
    return payload


def _validated_tool_calls(
    raw_calls: Any,
    *,
    fallback_query: str,
    canonical_tasks: set[str],
) -> list[ResearchToolCall]:
    if not isinstance(raw_calls, list):
        return []
    allowed = {
        "search_catalog",
        "search_evidence",
        "get_tool_contract",
        "compile_workflow",
    }
    calls: list[ResearchToolCall] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for index, raw in enumerate(raw_calls[:4], start=1):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("tool_name") or "")
        if name not in allowed:
            continue
        task = str(raw.get("canonical_task") or "")
        if task not in canonical_tasks:
            task = ""
        tool_names = [
            str(value).strip()
            for value in (raw.get("tool_names") or [])
            if str(value).strip()
        ][:5]
        key = (name, task, tuple(value.casefold() for value in tool_names))
        if key in seen:
            continue
        seen.add(key)
        try:
            top_k = max(1, min(int(raw.get("top_k") or 8), 12))
        except (TypeError, ValueError):
            top_k = 8
        calls.append(
            ResearchToolCall(
                call_id=f"llm-tool-{index}",
                tool_name=name,
                query=str(raw.get("query") or fallback_query)[:1200],
                canonical_task=task,
                tool_names=tool_names,
                claim_types=[
                    str(value).strip()
                    for value in (raw.get("claim_types") or [])
                    if str(value).strip()
                ][:4],
                top_k=top_k,
                reason=str(raw.get("reason") or "")[:240],
            )
        )
    return calls
