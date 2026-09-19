"""Read-only presentation for the Research chat shell; never creates plans or runs."""
from datetime import datetime
from html import escape
import json
from pathlib import Path

import streamlit as st


def conversation_group(session, now=None):
    if session.get('pinned'):
        return '置顶'
    today = (now or datetime.now().astimezone()).date()
    when = datetime.fromtimestamp(session.get('updated_at') or 0).astimezone().date()
    age = (today - when).days
    return '今天' if age == 0 else '过去 7 天' if 0 < age < 7 else '更早'


def summary_model(messages, binding):
    """Use the latest reply, never a previous conversation's cached latest_state."""
    latest = next((m for m in reversed(messages) if m.get('role') == 'assistant'), {})
    state = latest.get('state') or {}
    plan = state.get('workflow_plan') or {}
    handoff = state.get('workspace_handoff') or {}
    execution = state.get('execution_handoff') or {}
    mode = str(state.get('agent_mode') or state.get('mode') or 'ASK').upper()
    mode = mode if mode in {'ASK', 'PLAN', 'RUN'} else 'ASK'
    # RUN denotes the requested mode, not proof that computation has happened.
    execution_text = {'not_requested': '尚未执行', 'waiting': '等待确认',
                      'ready': '等待执行', 'blocked': '执行受阻',
                      'completed': '执行已完成'}.get(execution.get('status'), '尚未执行')
    targets = list(handoff.get('target_representations') or [])
    outputs = [str(o.get('artifact_type') or o.get('artifact_id') or '')
               for o in plan.get('expected_outputs', []) if isinstance(o, dict)]
    return {'state': state, 'plan': plan, 'mode': mode, 'execution': execution_text,
            'binding': state.get('ui_input_binding') or binding or {},
            'targets': targets, 'outputs': outputs,
            'task': latest.get('source_query') or '',
            'handoff_ready': handoff.get('status') == 'available'}


def _safe(value):
    return escape(str(value))


def stage_html(mode):
    return '<div class="research-stages" aria-label="当前请求模式">' + ''.join(
        f'<span class="stage {"active" if mode == name else ""}"'
        f' {"aria-current=step" if mode == name else ""}><i>{i}</i>{name}</span>'
        for i, name in enumerate(('ASK', 'PLAN', 'RUN'), 1)) + '</div>'


def information_html(model, session, runtime_label):
    binding = model['binding']
    name = binding.get('original_filename') or '未绑定数据'
    shape = binding.get('shape') or []
    shape_text = f'{shape[0]:,} cells × {shape[1]:,} genes' if len(shape) == 2 else ''
    source = '系统合成样例' if binding.get('source') == 'explicit_demo' else '当前任务输入'
    created = session.get('created_at')
    created_text = datetime.fromtimestamp(created).astimezone().strftime('%Y-%m-%d %H:%M') if created else '—'
    plan = model['plan']
    plan_text = (f'已生成 {len(plan.get("steps") or [])} 个计划步骤。'
                 if plan else '任务已识别，进入 Stepwise 检查数据后准备计划。'
                 if model['handoff_ready'] else '发送科研问题后，这里将展示当前任务的计划摘要。')
    outputs = model['outputs'] or model['targets']
    items = ''.join(f'<li><span class="output-icon">↗</span><div>{_safe(x)}<small>'
                    f'{"计划预期产出" if model["outputs"] else "任务目标 · 待计划确认"}</small></div></li>' for x in outputs)
    if not items:
        items = '<li class="empty-output">尚未确定预期产出</li>'
    return (
        '<section class="info-card"><h3>◈ &nbsp; 对话信息</h3><dl>'
        f'<dt>会话标题</dt><dd>{_safe(("新对话" if session.get("title") == "New research chat" else session.get("title")) or "新对话")}</dd>'
        f'<dt>创建时间</dt><dd>{created_text}</dd>'
        f'<dt>当前模式</dt><dd><span class="mode-badge">{model["mode"]}</span></dd>'
        f'<dt>运行方式</dt><dd>{_safe(runtime_label)}</dd></dl></section>'
        '<section class="info-card"><h3>▤ &nbsp; 任务与数据</h3>'
        f'<p class="task-summary">{_safe(model["task"] or "尚未提出分析任务")}</p>'
        f'<div class="data-summary"><strong>{_safe(name)}</strong><small>{_safe(shape_text)}'
        f'{" · " + source if binding else "通过输入框内的 ＋ 添加文件"}</small></div></section>'
        '<section class="info-card"><h3>≡ &nbsp; 计划摘要</h3>'
        f'<p>{plan_text}</p><span class="execution-label">{model["execution"]}</span></section>'
        f'<section class="info-card"><h3>▥ &nbsp; 预期产出</h3><ul class="output-list">{items}</ul></section>'
        '<section class="info-card tip-card"><h3>☼ &nbsp; 小贴士</h3>'
        '<p>先提问，再确认计划。上传文件不会运行分析；执行前仍需确认数据、参数与审批。</p></section>'
    )


def render_plan_overview(state):
    """A compact, inspectable table only when an actual backend plan exists."""
    plan = state.get('workflow_plan') or {}
    steps = plan.get('steps') or []
    if not steps:
        return
    rows = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            continue
        rows.append({'步骤': i, '方法': step.get('operation') or step.get('method') or step.get('name'),
                     '输入': ', '.join(step.get('input_artifacts') or step.get('consumes') or []),
                     '输出': ', '.join(step.get('output_artifacts') or step.get('produces') or []),
                     '参数': json.dumps(step.get('parameters') or {}, ensure_ascii=False)})
    if rows:
        st.markdown('#### WorkflowPlan')
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption('计划预览 · 运行状态请以执行记录为准。')


TOPBAR_HTML = '<div class="research-topbar"><svg class="research-brand-icon" viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M8 30L19 19L9 10M19 19L30 7M19 19L31 30" stroke="currentColor" stroke-width="2"/><g fill="white" stroke="currentColor" stroke-width="2.5"><circle cx="8" cy="30" r="4"/><circle cx="19" cy="19" r="5"/><circle cx="9" cy="10" r="3"/><circle cx="30" cy="7" r="4"/><circle cx="31" cy="30" r="4"/></g></svg><span class="research-brand-name">scKG-Agent</span><span class="research-brand-subtitle">Scientific AI Assistant for single-cell analysis</span></div>'


def app_style_html(base_css: str, *, current_view: str) -> str:
    """Choose the layout server-side before emitting any page content.

    A late DOM :has() switch made the old layout reappear during reruns.
    The active route now owns the CSS for the entire render, from the first delta.
    """
    if current_view in {"home", "chat"}:
        css = Path(__file__).with_name('research_shell.css').read_text()
        return '<style>' + base_css + css + '</style>' + TOPBAR_HTML
    return ('<style>' + base_css +
            '.research-topbar,.research-info-rail{display:none!important;}'
            '[data-testid="stVerticalBlockBorderWrapper"]:has(> div > '
            '[data-testid="stVerticalBlock"] > [data-testid="element-container"] '
            '.shell-toolbar-marker){display:none;}'
            '</style>')


def render_app_styles(base_css: str, *, current_view: str):
    st.markdown(app_style_html(base_css, current_view=current_view), unsafe_allow_html=True)


def render_reply_overview(state):
    model = summary_model([{'role': 'assistant', 'state': state}], {})
    if model['mode'] not in {'PLAN', 'RUN'}:
        return
    name = model['binding'].get('original_filename') or '尚未绑定'
    targets = model['targets'] or model['outputs']
    html = (f'<div class="research-mode-banner">当前模式 <span class="mode-badge">{model["mode"]}</span>'
            f'<span>{model["execution"]}</span></div><div class="research-facts">')
    for label, value in [('输入数据', name), ('任务目标', ', '.join(targets) or '待计划确认'), ('执行状态', model['execution'])]:
        html += f'<div class="research-fact"><small>{label}</small>{_safe(value)}</div>'
    st.markdown(html + '</div>', unsafe_allow_html=True)


def current_workspace_plan(ui_state, reply_state):
    """Expose a prepared Stepwise plan only for this exact conversation/handoff/input."""
    delivery = ui_state.get('capability_workspace_result') or {}
    active = ui_state.get('workspace_task_handoff') or {}
    origin = reply_state.get('workspace_handoff') or {}
    binding = reply_state.get('ui_input_binding') or {}
    expected = ui_state.get('capability_workspace_context_digest')
    if (not expected or expected != ui_state.get('capability_workspace_result_context')
            or not origin.get('handoff_id') or origin['handoff_id'] != active.get('handoff_id')
            or active.get('conversation_id') != ui_state.get('session_id')
            or not binding or binding != active.get('input_binding')):
        return {}
    return delivery.get('workflow_plan') or {}
