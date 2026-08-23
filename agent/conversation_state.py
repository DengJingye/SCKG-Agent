from __future__ import annotations

from typing import Any, Iterable

from core.research_agent_models import ConversationTaskState, DomainKind


def resolve_conversation_task_state(
    context: Iterable[dict[str, Any]],
    *,
    runtime_build_id: str,
) -> ConversationTaskState:
    """Recover only governed cross-turn references from recent messages."""

    rows = list(context)
    for row in reversed(rows):
        payload = _state_payload(row)
        if not payload:
            continue
        prior_build = str(payload.get("runtime_build_id") or "")
        epoch = int(payload.get("state_epoch") or 0)
        if prior_build and runtime_build_id and prior_build != runtime_build_id:
            return ConversationTaskState(
                state_epoch=epoch + 1,
                runtime_build_id=runtime_build_id,
            )
        domain = str(payload.get("confirmed_domain") or "UNCERTAIN")
        if domain not in {item.value for item in DomainKind}:
            domain = DomainKind.UNCERTAIN.value
        return ConversationTaskState(
            confirmed_domain=DomainKind(domain),
            confirmed_task=str(payload.get("confirmed_task") or ""),
            referenced_tools=_strings(payload.get("referenced_tools")),
            last_answer_claims=_strings(payload.get("last_answer_claims")),
            last_plan_id=_optional_string(payload.get("last_plan_id")),
            last_action_bundle_ids=_strings(payload.get("last_action_bundle_ids")),
            state_epoch=epoch,
            runtime_build_id=runtime_build_id or prior_build,
        )

    # Backward-compatible recovery from old message metadata. It deliberately
    # does not infer a task from prose alone.
    for row in reversed(rows):
        task = _canonical_task(row)
        if not task:
            continue
        return ConversationTaskState(
            confirmed_domain=DomainKind.SINGLE_CELL,
            confirmed_task=task,
            referenced_tools=_tools(row),
            last_plan_id=_plan_id(row),
            runtime_build_id=runtime_build_id,
        )
    return ConversationTaskState(runtime_build_id=runtime_build_id)


def next_conversation_task_state(
    previous: ConversationTaskState,
    *,
    domain: DomainKind,
    task: str,
    referenced_tools: list[str],
    claim_ids: list[str],
    plan_id: str | None,
    action_bundle_ids: list[str],
    task_switched: bool,
) -> ConversationTaskState:
    epoch = previous.state_epoch + int(task_switched)
    return ConversationTaskState(
        confirmed_domain=domain,
        confirmed_task=task,
        referenced_tools=list(dict.fromkeys(referenced_tools))[:8],
        last_answer_claims=list(dict.fromkeys(claim_ids))[:20],
        last_plan_id=plan_id,
        last_action_bundle_ids=list(dict.fromkeys(action_bundle_ids))[:8],
        state_epoch=epoch,
        runtime_build_id=previous.runtime_build_id,
    )


def _state_payload(row: dict[str, Any]) -> dict[str, Any]:
    direct = row.get("conversation_state")
    if isinstance(direct, dict):
        return direct
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        state = metadata.get("conversation_state")
        if isinstance(state, dict):
            return state
        response = metadata.get("state")
        if isinstance(response, dict) and isinstance(response.get("conversation_state"), dict):
            return response["conversation_state"]
    response = row.get("state")
    if isinstance(response, dict) and isinstance(response.get("conversation_state"), dict):
        return response["conversation_state"]
    return {}


def _canonical_task(row: dict[str, Any]) -> str:
    value = row.get("canonical_task")
    if value:
        return str(value)
    metadata = row.get("metadata")
    response = metadata.get("state") if isinstance(metadata, dict) else row.get("state")
    if isinstance(response, dict):
        constraints = response.get("extracted_constraints") or {}
        value = constraints.get("canonical_task")
        if value and value != "Unknown":
            return str(value)
    return ""


def _tools(row: dict[str, Any]) -> list[str]:
    metadata = row.get("metadata")
    response = metadata.get("state") if isinstance(metadata, dict) else row.get("state")
    if isinstance(response, dict):
        return _strings(response.get("candidate_tools"))
    return []


def _plan_id(row: dict[str, Any]) -> str | None:
    metadata = row.get("metadata")
    response = metadata.get("state") if isinstance(metadata, dict) else row.get("state")
    if isinstance(response, dict):
        plan = response.get("workflow_plan")
        if isinstance(plan, dict):
            return _optional_string(plan.get("plan_id"))
    return None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
