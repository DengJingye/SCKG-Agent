"""New UI request wiring and immutable old requests; no provider or execution.

The source catalog, model profile and passphrase are synthetic local fixtures.
Launch is explicitly refused after real submission, never replaced by a fake
successful model result. This file does not test actual repair execution.
"""
from copy import deepcopy
import json

import pytest
from streamlit.testing.v1 import AppTest

from sckg_workbench.chat_runs import ChatRunService
from sckg_workbench.storage import content_hash
from sckg_workbench.workflow_chat import JSON_OBJECT_CANONICAL, PHASE_CONTRACT_VERSION, REPORT_PRESENCE_VERSION
from sckg_workbench.workflow_format_repair import FINAL_FORMAT_REPAIR_POLICY
from tests.test_workbench_workflow_chat import app, BUDGET, PASSPHRASE
from tests.test_workbench_workflow_inputs_ui import _snapshot


@pytest.fixture(autouse=True)
def no_model_or_execution(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('UI repair-policy wiring must not dispatch, obtain credentials or execute')
    for target in (
        'sckg_workbench.model_service.ModelService.invoke',
        'sckg_workbench.model_service.ModelService.embed',
        'sckg_workbench.model_service.ModelService._call',
        'sckg_workbench.model_service.ModelService._credential',
        'sckg_workbench.model_service.ModelService.validate_profile_credential',
        'sckg_workbench.model_service.http_transport',
        'sckg_workbench.sources.fetch_public_url',
        'sckg_workbench.chat.ChatService.process_registered_send',
        'sckg_workbench.chat_runs.ChatRunService.launch',
        'sckg_workbench.chat_runs.ChatRunService.claim',
        'sckg_workbench.worker.Worker.run_once',
        'sckg_workbench.analysis.AnalysisService.submit_scrublet',
        'sckg_workbench.analysis.AnalysisService.run_once',
        'sckg_workbench.tasks.TaskQueue.submit',
    ):
        monkeypatch.setattr(target, denied)


def _options_screen(options):
    import streamlit as st
    from sckg_workbench.ui import _workflow_wire_options
    before = dict(options)
    st.json({'before': before, 'after': _workflow_wire_options(options), 'original_after': options})


def _research_screen(root, conversation_id, phrase):
    from pathlib import Path
    import streamlit as st
    from sckg_workbench.model_service import ModelService
    from sckg_workbench.storage import Ledger, Workspace
    from sckg_workbench.ui import _research
    st.session_state.setdefault('vault_passphrase', phrase)
    st.session_state.setdefault('research_active_conversation', conversation_id)
    ledger = Ledger(Workspace(Path(root)))
    _research(ledger, ModelService(ledger.workspace, ledger))


def _research_ui(app):
    return AppTest.from_function(_research_screen,
        args=(str(app.ledger.workspace.root), app.conversation['id'], PASSPHRASE),
        default_timeout=15).run()


@pytest.mark.parametrize('wire', ['JSON Schema', 'JSON 对象 + 完整本地合同'])
def test_new_ui_options_bind_policy_without_mutating_input_or_adding_controls(wire):
    options = {'catalog_record_id': 'synthetic-only', 'catalog_hash': '0' * 64}
    screen = AppTest.from_function(_options_screen, args=(options,)).run()
    if wire != 'JSON Schema':
        screen.selectbox(key='research_workflow_wire_format').select(wire).run()
    assert not screen.exception
    value = json.loads(screen.json[0].value)
    assert value['before'] == value['original_after'] == options
    expected = {**options, 'answer_contract_version': REPORT_PRESENCE_VERSION,
        'repair_policy': FINAL_FORMAT_REPAIR_POLICY}
    if wire != 'JSON Schema':
        expected['wire_mode'] = JSON_OBJECT_CANONICAL
    assert value['after'] == expected
    assert len(screen.selectbox) == 1 and not screen.checkbox and not screen.button
    assert '原预算内' in screen.selectbox[0].proto.help and '一次格式修复' in screen.selectbox[0].proto.help
    screen.run()
    assert not screen.exception and json.loads(screen.json[0].value) == value


def test_real_ui_submission_persists_policy_in_request_hash_then_refuses_launch(app, monkeypatch):
    refused = []
    def refuse(self, turn_id, target, **kwargs):
        request = self.ledger.get_record('chat_request', turn_id)
        assert callable(target) and request['status'] == 'pending'
        refused.append(turn_id)
        return {'dispatch_status': 'fixture_refused_not_started'}
    monkeypatch.setattr(ChatRunService, 'launch', refuse)
    screen = _research_ui(app)
    assert not screen.exception
    screen.checkbox(key='research_workflow_enabled').check().run()
    screen.selectbox(key='research_workflow_wire_format').select('JSON 对象 + 完整本地合同').run()
    screen.number_input(key='research_input_limit').set_value(65536).run()
    screen.number_input(key='research_output_limit').set_value(4096).run()
    assert not screen.exception and not screen.chat_input(key='research_prompt').disabled
    screen.chat_input(key='research_prompt').set_value('合成UI提交夹具；不启动模型或执行分析。').run()
    assert not screen.exception and not screen.error and not screen.success
    request, = app.ledger.list_records('chat_request')
    assert refused == [request['id']] and request['status'] == 'pending'
    assert request['answer'] is None and request['receipt'] is None
    assert request['workflow_options'] == {**app.workflow_options,
        'answer_contract_version': REPORT_PRESENCE_VERSION,
        'repair_policy': FINAL_FORMAT_REPAIR_POLICY, 'wire_mode': JSON_OBJECT_CANONICAL}
    params = {key: request[key] for key in ('conversation_id', 'prompt', 'profile_id',
        'use_knowledge', 'purpose', 'budget', 'workflow_options')}
    assert request['request_hash'] == content_hash(params)
    assert request['budget']['max_input_tokens'] == 65536
    assert request['budget']['max_output_tokens'] == 4096
    control = ChatRunService(app.ledger).snapshot(request['id'])
    assert control['status'] == 'pending' and control['started'] is False
    before = _snapshot(app.ledger)
    screen.run()
    screen.run()
    assert not screen.exception and refused == [request['id']]
    assert _snapshot(app.ledger) == before and app.calls == []
    assert not app.ledger.list_records('model_request') and not app.ledger.list_records('model_call')


@pytest.mark.parametrize('version', [PHASE_CONTRACT_VERSION, REPORT_PRESENCE_VERSION])
def test_enabling_new_ui_options_and_refresh_never_upgrades_old_pending_request(app, version):
    old_options = {**app.workflow_options, 'answer_contract_version': version}
    old = app.chat.submit_send(app.conversation['id'], '合成旧请求；保持原policy缺省。',
        profile_id=app.profile['id'], use_knowledge=False, purpose='explanation',
        budget=deepcopy(BUDGET), request_id='synthetic-old-no-repair-policy', workflow_options=old_options)
    original = app.ledger.get_record('chat_request', old['id'])
    assert 'repair_policy' not in original['workflow_options']
    screen = _research_ui(app)
    assert not screen.exception and screen.chat_input(key='research_prompt').disabled
    before = _snapshot(app.ledger)
    screen.checkbox(key='research_workflow_enabled').check().run()
    screen.selectbox(key='research_workflow_wire_format').select('JSON 对象 + 完整本地合同').run()
    screen.run()
    screen.run()
    assert not screen.exception and not screen.success
    assert app.ledger.get_record('chat_request', old['id']) == original
    assert app.ledger.list_records('chat_request') == [original]
    assert _snapshot(app.ledger) == before and app.calls == []
    assert not app.ledger.list_records('model_call') and not app.ledger.list_records('model_request')
