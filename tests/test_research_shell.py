from datetime import datetime, timedelta

from observability.dashboard.research_shell import (
    conversation_group, summary_model, information_html,
)


def test_handoff_targets_are_not_claimed_as_generated_plan_or_results():
    messages = [{'role': 'assistant', 'source_query': '只做 PCA', 'state': {
        'agent_mode': 'PLAN', 'workspace_handoff': {
            'status': 'available', 'target_representations': ['pca']},
        'execution_handoff': {'status': 'not_requested'},
    }}]
    model = summary_model(messages, {'original_filename': 'sample.h5ad', 'source': 'explicit_demo', 'shape': [180, 240]})
    html = information_html(model, {}, '本地模式')
    assert model['plan'] == {} and model['outputs'] == []
    assert '任务目标 · 待计划确认' in html and '尚未执行' in html
    assert '系统合成样例' in html and '已生成' not in html
    assert 'umap' not in html


def test_run_request_is_not_execution_completion():
    model = summary_model([{'role': 'assistant', 'state': {
        'agent_mode': 'RUN', 'execution_handoff': {'status': 'blocked'}}}], {})
    assert model['mode'] == 'RUN' and model['execution'] == '执行受阻'
    assert '执行已完成' not in information_html(model, {}, '本地模式')


def test_new_reply_does_not_show_old_plan_and_escapes_user_content():
    messages = [{'role': 'assistant', 'state': {'agent_mode': 'PLAN', 'workflow_plan': {'steps': [{}]}}},
                {'role': 'assistant', 'content': '你好'}]
    model = summary_model(messages, {'original_filename': '<img src=x onerror=alert(1)>'})
    assert model['plan'] == {} and model['mode'] == 'ASK'
    html = information_html(model, {'title': '<script>bad()</script>'}, 'local')
    assert '<script>' not in html and '<img src' not in html
    assert '&lt;script&gt;' in html


def test_summary_uses_exact_sent_data_identity():
    model = summary_model([{'role': 'assistant', 'state': {
        'ui_input_binding': {'original_filename': 'sent.h5ad'}}}], {'original_filename': 'other.h5ad'})
    assert model['binding']['original_filename'] == 'sent.h5ad'


def test_history_groups_use_real_dates_and_pins():
    now = datetime.now().astimezone()
    assert conversation_group({'updated_at': now.timestamp()}, now) == '今天'
    assert conversation_group({'updated_at': (now-timedelta(days=3)).timestamp()}, now) == '过去 7 天'
    assert conversation_group({'updated_at': (now-timedelta(days=30)).timestamp()}, now) == '更早'
    assert conversation_group({'pinned': True}, now) == '置顶'


def test_prepared_plan_requires_exact_conversation_input_and_handoff():
    from observability.dashboard.research_shell import current_workspace_plan
    binding = {'artifact_id': 'data-A', 'sha256': 'hash-A'}
    reply = {'ui_input_binding': binding, 'workspace_handoff': {'handoff_id': 'H'}}
    ui = {'session_id': 'C', 'capability_workspace_context_digest': 'ctx',
          'capability_workspace_result_context': 'ctx',
          'workspace_task_handoff': {'handoff_id': 'H', 'conversation_id': 'C', 'input_binding': binding},
          'capability_workspace_result': {'workflow_plan': {'steps': [{'operation': 'pca'}]}}}
    assert current_workspace_plan(ui, reply)['steps'][0]['operation'] == 'pca'
    assert current_workspace_plan({**ui, 'session_id': 'other'}, reply) == {}
    assert current_workspace_plan({**ui, 'capability_workspace_result_context': 'stale'}, reply) == {}
    assert current_workspace_plan(ui, {**reply, 'ui_input_binding': {'artifact_id': 'other'}}) == {}
    assert current_workspace_plan(ui, {**reply, 'workspace_handoff': {'handoff_id': 'old'}}) == {}


def test_route_theme_does_not_wait_for_a_chat_content_marker():
    from observability.dashboard.research_shell import app_style_html
    chat = app_style_html('/* shared */', current_view='chat')
    assert 'body:has(.research-chat-layout)' not in chat
    assert 'html:root body .block-container' in chat
    assert 'class="research-topbar"' in chat
    assert chat.count('<style>') == chat.count('</style>') == 1
    workbench = app_style_html('/* shared */', current_view='data_preview')
    assert 'class="research-topbar"' not in workbench
    assert 'html:root body .block-container' not in workbench


def test_chat_rerun_emits_theme_first_without_hidden_image_or_workbench(tmp_path):
    """Real Streamlit reruns in an isolated store, including a route round trip."""
    import os
    from pathlib import Path
    import subprocess
    import sys
    script = '''
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
app = AppTest.from_file('app.py', default_timeout=45)
with patch('execution.research_workspace_service.build_research_workspace_service',
           side_effect=AssertionError('unused Stepwise backend built by chat')):
    for _ in range(2):
        app.run()
        assert not app.exception, [x.message for x in app.exception]
        assert len(app.chat_input) == 1
        assert 'class="research-topbar"' in app.markdown[0].value
        assert 'body:has(.research-chat-layout)' not in app.markdown[0].value
        assert sum(len(x.value.encode()) for x in app.markdown) < 150_000
        assert not any('data:image/png;base64,' in x.value for x in app.markdown)
    app.session_state.current_view = 'data_preview'
    app.run()
    assert not app.exception, [x.message for x in app.exception]
    assert 'class="research-topbar"' not in app.markdown[0].value
    app.session_state.current_view = 'chat'
    app.run()
    assert not app.exception, [x.message for x in app.exception]
    assert 'class="research-topbar"' in app.markdown[0].value
print('first-delta theme, warm rerun, route round trip, no unused workbench: passed')
'''
    result = subprocess.run([sys.executable, '-c', script],
                            cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, 'SCKG_HOME': str(tmp_path),
                                 'SCKG_LOCAL_USER_ID': 'ui-rerun-test',
                                 'SCKG_OFFLINE_LLM': 'true', 'SCKG_EXECUTION_POLICY': 'disabled'},
                            capture_output=True, text=True, timeout=75)
    assert result.returncode == 0, result.stdout + result.stderr
