from __future__ import annotations

from typing import Any, Dict, List

from core.models import EvidenceContextPack


def render_context_pack_report(context_pack: EvidenceContextPack) -> str:
    """Render a deterministic offline report from EvidenceContextPack only."""

    constraints = context_pack.parsed_constraints
    task = constraints.get("task", "Unknown")
    modality = constraints.get("modality", "Unknown")
    clarification_state = constraints.get("clarification_state", "needs_clarification")

    trusted = context_pack.trusted_recommendation_context or {}
    ranked_tools = _list(trusted.get("ranked_tools"))
    workflow = trusted.get("workflow")

    migration = context_pack.migration_context or {}
    migration_paths = _list(migration.get("paths"))

    lines = [
        "## 分析结果",
        "",
        _summary_line(
            recommendation_type=context_pack.recommendation_type,
            task=task,
            modality=modality,
            ranked_tools=ranked_tools,
            migration_paths=migration_paths,
            clarification_state=clarification_state,
        ),
    ]

    if ranked_tools:
        lines.extend(["", "### 推荐"])
        for item in ranked_tools[:5]:
            lines.append(
                f"- **{item.get('tool_name', 'Unknown')}**: rank "
                f"{item.get('rank', 'NA')}, MCDM score {_fmt(item.get('mcdm_score'))}, "
                f"confidence {item.get('recommendation_confidence', 'unknown')}."
            )
            missing = _list(item.get("missing_evidence"))[:3]
            if missing:
                lines.append(f"  Caveat: 缺少 {', '.join(map(str, missing))}。")

    if isinstance(workflow, dict) and workflow.get("steps"):
        step_names = [
            str(step.get("name", "Unknown"))
            for step in _list(workflow.get("steps"))
            if step.get("name")
        ]
        if step_names:
            lines.extend(["", "### 工作流"])
            lines.append(" -> ".join(step_names))
            warnings = _list(workflow.get("compatibility_warnings"))
            if warnings:
                lines.append("Caveat: " + "；".join(str(item) for item in warnings[:3]))

    if migration_paths:
        lines.extend(["", "### 探索性迁移假设"])
        for item in migration_paths[:3]:
            lines.append(
                f"- **{item.get('source_tool', 'Unknown')}** -> "
                f"{item.get('target_task', task)}: plausibility "
                f"{_fmt(item.get('migration_plausibility_score'))}。"
            )
            mechanism = _compact(item.get("transferable_mechanism", ""), 160)
            if mechanism:
                lines.append(f"  Mechanism: {mechanism}")
            gaps = _list(item.get("compatibility_gaps"))[:3]
            if gaps:
                lines.append(f"  Compatibility gaps: {'; '.join(map(str, gaps))}.")
        lines.append(
            "这些内容只能作为 MigrationHypothesis，不能写成正式推荐、直接替代方案或 benchmark-backed 结论。"
        )

    rag_items = _rag_items(context_pack)
    if rag_items:
        lines.extend(["", "### 证据来源"])
        for item in rag_items[:5]:
            lines.append(
                f"- {item['source_kind']} | {item['tool_name']} | {item['doi']} | "
                f"{item['claim']}"
            )
        lines.append("这些 RAG snippets 只用于解释和溯源，不改变排序分数。")

    caveats = _caveats(context_pack)
    if caveats:
        lines.extend(["", "### Caveats"])
        for item in caveats[:8]:
            lines.append(f"- {item}")

    next_steps = _next_steps(
        context_pack=context_pack,
        ranked_tools=ranked_tools,
        migration_paths=migration_paths,
    )
    if next_steps:
        lines.extend(["", "### 下一步"])
        for item in next_steps:
            lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "_安全说明：当前回答由受控 EvidenceContextPack 离线生成；用户上传内容和记忆只作为上下文，不会晋级为 trusted evidence。_",
        ]
    )
    return "\n".join(lines)


def _summary_line(
    *,
    recommendation_type: str,
    task: str,
    modality: str,
    ranked_tools: List[Dict[str, Any]],
    migration_paths: List[Dict[str, Any]],
    clarification_state: str,
) -> str:
    if ranked_tools:
        names = ", ".join(str(item.get("tool_name", "Unknown")) for item in ranked_tools[:3])
        return (
            f"当前识别任务为 **{task}**，模态为 **{modality}**。"
            f"在现有 trusted evidence 下，优先候选是 {names}。"
        )
    if migration_paths:
        names = ", ".join(str(item.get("source_tool", "Unknown")) for item in migration_paths[:3])
        return (
            f"当前没有足够证据输出正式推荐；系统只给出探索性迁移路线：{names}。"
        )
    if clarification_state == "needs_clarification" or task == "Unknown" or modality == "Unknown":
        return (
            "当前信息还不足以给出可靠工具推荐。需要先补充任务、模态、输入对象、规模、"
            "噪声/批次情况和目标输出。"
        )
    return f"当前输出类型为 **{recommendation_type}**，但可用可信证据仍不足，需要保守解读。"


def _rag_items(context_pack: EvidenceContextPack) -> List[Dict[str, str]]:
    retrieval = context_pack.retrieval_context or {}
    formal_rag = retrieval.get("formal_rag_context") or {}
    snippets = _list(formal_rag.get("snippets"))
    items: List[Dict[str, str]] = []
    for snippet in snippets:
        claim = _compact(
            snippet.get("claim_span")
            or snippet.get("result_text")
            or snippet.get("claim_text")
            or snippet.get("evaluation_protocol")
            or "",
            180,
        )
        if not claim:
            continue
        items.append(
            {
                "source_kind": str(snippet.get("source_kind", "source")),
                "tool_name": str(snippet.get("tool_name", "Unknown")),
                "doi": str(snippet.get("doi") or snippet.get("source_url") or "no DOI/source URL"),
                "claim": claim,
            }
        )
    return items


def _caveats(context_pack: EvidenceContextPack) -> List[str]:
    caveats: List[str] = []
    blocked = context_pack.blocked_context or {}
    caveats.extend(str(item) for item in _list(blocked.get("guardrail_warnings"))[:4])
    if context_pack.missing_evidence:
        caveats.append(
            "缺失证据/约束：" + ", ".join(context_pack.missing_evidence[:10])
        )
    policy = context_pack.prompt_policy or {}
    forbidden = _list(policy.get("forbidden"))
    if forbidden:
        caveats.append(
            "禁止外推：" + "；".join(str(item) for item in forbidden[:2])
        )
    return caveats


def _next_steps(
    *,
    context_pack: EvidenceContextPack,
    ranked_tools: List[Dict[str, Any]],
    migration_paths: List[Dict[str, Any]],
) -> List[str]:
    constraints = context_pack.parsed_constraints or {}
    if ranked_tools:
        return [
            "补充数据规模、平台、物种和硬件后重新排序。",
            "展开 Sources/caveats 查看 DOI、benchmark 和缺失证据。",
            "如果要落地分析，继续生成 workflow 和参数检查清单。",
        ]
    if migration_paths:
        return [
            "先把迁移假设写成可验证的实验设计，而不是直接执行。",
            "检查 compatibility gaps 是否能通过数据对象或实验设计补齐。",
            "只在验证通过后再考虑把路线纳入正式推荐候选。",
        ]
    pending = _list(constraints.get("pending_constraints"))
    if pending:
        return [
            "补充：" + ", ".join(str(item) for item in pending[:6]) + "。",
            "说明你希望得到的是工具推荐、workflow、证据解释，还是迁移假设。",
        ]
    return ["补充更具体的输入数据和分析目标后重新提问。"]


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except Exception:
        return "NA"


def _compact(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
