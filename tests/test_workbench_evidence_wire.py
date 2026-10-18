"""Lossless ordinary-chat wire encoding; synthetic local fixtures, no network.

The gateway fixture returns labelled synthetic prose. UI cases register a real
pending request and explicitly refuse launch; they do not fake model success.
These checks establish representation and request isolation, not science gain.
"""
from copy import deepcopy
import json

import pytest
from streamlit.testing.v1 import AppTest

from sckg_workbench.chat import ChatError, SYSTEM_PROMPT
from sckg_workbench.chat_runs import ChatRunService
from sckg_workbench.evidence_wire import (
    EvidenceWireError, LITERAL_EVIDENCE_ENCODING, SHARED_EVIDENCE_ENCODING,
    SHARED_TEXT_INSTRUCTIONS, WIRE_SCHEMA, decode_evidence, encode_evidence,
)
from sckg_workbench.storage import canonical_json, content_hash
from tests.test_workbench_chat import app, send, published_source, BUDGET, PASSPHRASE
from tests.test_workbench_workflow_inputs_ui import _snapshot


def _metadata(payload):
    return json.loads(payload['messages'][1]['content'].partition('\n')[2])


def test_roundtrip_retains_scientific_fields_order_and_identity_without_mutation():
    quote = ('Synthetic fixture only: do not use normalized values as raw counts; '
             'conditions remain conditional and unknowns remain unknown.\n') * 6
    unique = 'Unique long scientific fixture text. ' * 8
    original = [{'candidate_id': quote, 'source_ids': [quote], 'source_hash': quote,
        'locator': {'description': quote}, 'source_link': quote,
        'claim': {'proposition': quote, 'conditions': [quote, 'short', 'short'],
                  'unknowns': [None, False, 0, 1.5, unique]},
        'anchors': [{'quote': quote, 'start': 0, 'end': len(quote)}],
        'json_literal_text': '{"$text":"T1"}'}]
    before = deepcopy(original)
    encoded = encode_evidence(original)
    assert decode_evidence(encoded) == original == before
    assert canonical_json(decode_evidence(encoded)) == canonical_json(original)
    assert list(encoded['text_table'].values()) == [quote]
    node = encoded['data'][0]
    for key in ('candidate_id', 'source_ids', 'source_hash', 'locator', 'source_link'):
        assert node[key] == original[0][key]
    assert node['claim']['conditions'][1:] == ['short', 'short']
    assert node['claim']['unknowns'] == [None, False, 0, 1.5, unique]
    assert node['json_literal_text'] == '{"$text":"T1"}'
    assert len(canonical_json(encoded).encode()) < len(canonical_json(original).encode())


def test_original_marker_objects_are_recursively_escaped_and_never_reinterpreted():
    text = 'Repeated synthetic original text, including Unicode 引号 and \\" escapes. ' * 8
    original = [{'$text': 'not-a-reference'}, {'$text': text},
        {'$object': [['$text', 'T1']]},
        {'$object': {'$text': {'$object': [text, {'$text': None}]}}},
        {'$text': 'T1', 'other': text}]
    encoded = encode_evidence(original)
    assert decode_evidence(encoded) == original
    assert encoded['data'][0] == {'$object': [['$text', 'not-a-reference']]}
    assert encoded['data'][2] == {'$object': [['$object', [['$text', 'T1']]]]}
    assert set(encoded['data'][-1]) == {'$text', 'other'}


def test_decoder_rejects_unknown_unused_nonrepeated_and_malformed_markers():
    text = 'Synthetic long source text. ' * 10
    valid = encode_evidence([text, text])
    invalid = []
    unknown = deepcopy(valid)
    unknown['data'][0]['$text'] = 'T9'
    invalid.append(unknown)
    unused = deepcopy(valid)
    unused['text_table']['T2'] = 'Unused synthetic long original text. ' * 8
    invalid.append(unused)
    single = deepcopy(valid)
    single['data'].pop()
    invalid.append(single)
    gap = deepcopy(valid)
    gap['text_table'] = {'T2': text}
    invalid.append(gap)
    for data in ({'$object': []}, {'$object': [['ordinary_key', 1]]}, float('nan')):
        invalid.append({'schema_version': WIRE_SCHEMA, 'text_table': {}, 'data': data})
    for value in invalid:
        with pytest.raises(EvidenceWireError):
            decode_evidence(value)
    for value in ({1: 'nonstring-key'}, {'x': float('inf')}, ('not', 'JSON'), {'x': object()}):
        with pytest.raises(EvidenceWireError):
            encode_evidence(value)


def test_real_stub_gateway_sees_equivalent_package_and_legacy_messages_stay_literal(app):
    unit, _, _ = published_source(app)
    legacy = send(app, 'FixtureTool', request_id='synthetic-legacy-literal')
    legacy_payload = deepcopy(app.calls[-1])
    assert legacy['status'] == 'succeeded'
    assert legacy_payload['messages'][0]['content'] == SYSTEM_PROMPT
    legacy_meta = _metadata(legacy_payload)
    assert 'evidence_encoding' not in legacy_meta
    assert legacy_meta['evidence_packages'] == legacy['evidence_packages']
    assert 'evidence_encoding' not in app.ledger.get_record('chat_request', legacy['id'])
    conversation = app.chat.create_conversation('synthetic explicit literal')
    literal = send(app, 'FixtureTool', conversation_id=conversation['id'],
        evidence_encoding=LITERAL_EVIDENCE_ENCODING)
    assert app.calls[-1]['messages'] == legacy_payload['messages']
    assert literal['evidence_packages'] == legacy['evidence_packages']
    conversation = app.chat.create_conversation('synthetic shared wire')
    shared = send(app, 'FixtureTool', conversation_id=conversation['id'],
        request_id='synthetic-stable-shared', evidence_encoding=SHARED_EVIDENCE_ENCODING)
    outbound = deepcopy(app.calls[-1])
    metadata = _metadata(outbound)
    assert shared['status'] == 'succeeded' and len(app.calls) == 3
    assert outbound['messages'][0]['content'] == SYSTEM_PROMPT + SHARED_TEXT_INSTRUCTIONS
    assert metadata['evidence_encoding'] == SHARED_EVIDENCE_ENCODING
    assert decode_evidence(metadata['evidence_packages']) == shared['evidence_packages'] == legacy['evidence_packages']
    assert shared['evidence_package']['units'][0]['candidate_id'] == unit['id']
    assert isinstance(shared['evidence_packages'], list)
    assert send(app, 'FixtureTool', conversation_id=conversation['id'],
        request_id='synthetic-stable-shared', evidence_encoding=SHARED_EVIDENCE_ENCODING) == shared
    assert send(app, 'FixtureTool', request_id='synthetic-legacy-literal') == legacy
    assert len(app.calls) == 3
    with pytest.raises(ChatError, match='different send'):
        send(app, 'FixtureTool', conversation_id=conversation['id'],
            request_id='synthetic-stable-shared', evidence_encoding=LITERAL_EVIDENCE_ENCODING)
    with pytest.raises(ChatError, match='different send'):
        send(app, 'FixtureTool', request_id='synthetic-legacy-literal',
            evidence_encoding=SHARED_EVIDENCE_ENCODING)
    assert len(app.calls) == 3


def test_shared_no_knowledge_has_same_notice_and_capacity_failure_never_dispatches(app):
    turn = send(app, use_knowledge=False, evidence_encoding=SHARED_EVIDENCE_ENCODING)
    metadata = _metadata(app.calls[-1])
    assert app.calls[-1]['messages'][0]['content'] == SYSTEM_PROMPT + SHARED_TEXT_INSTRUCTIONS
    assert metadata['local_knowledge_enabled'] is False
    assert decode_evidence(metadata['evidence_packages']) == turn['evidence_packages'] == []
    conversation = app.chat.create_conversation('synthetic capacity rejection')
    failed = send(app, conversation_id=conversation['id'], use_knowledge=False,
        evidence_encoding=SHARED_EVIDENCE_ENCODING, budget={**BUDGET, 'max_input_tokens': 1})
    assert failed['status'] == 'failed' and failed['receipt'] is None
    assert failed['error']['type'] == 'ChatError' and '超过输入预算' in failed['error']['message']
    assert len(app.calls) == 1 and len(app.ledger.list_records('model_call')) == 1


def test_unknown_encoding_and_shared_special_modes_reject_before_registration_or_preparation(app):
    before = _snapshot(app.ledger)
    base = dict(profile_id=app.profile['id'], budget=BUDGET, request_id='synthetic-invalid')
    for encoding in (None, False, {}, 'unsupported_v0'):
        with pytest.raises(ChatError, match='Unknown ordinary-chat evidence encoding'):
            app.chat.submit_send(app.conversation['id'], 'synthetic invalid encoding',
                evidence_encoding=encoding, **base)
    for options in ({'grounded_mode': True}, {'workflow_options': {}},
                    {'analysis_options': {}}, {'result_ref': 'synthetic-unselected-result'}):
        with pytest.raises(ChatError, match='requires ordinary chat'):
            app.chat.submit_send(app.conversation['id'], 'synthetic incompatible mode',
                evidence_encoding=SHARED_EVIDENCE_ENCODING, **options, **base)
        saved_options = {('result_selection' if key == 'result_ref' else key): value
                         for key, value in options.items()}
        with pytest.raises(ChatError, match='requires ordinary chat'):
            app.chat._prepare_context({'evidence_encoding': SHARED_EVIDENCE_ENCODING, **saved_options})
    assert _snapshot(app.ledger) == before and app.calls == []


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


def _ui(app):
    return AppTest.from_function(_research_screen,
        args=(str(app.ledger.workspace.root), app.conversation['id'], PASSPHRASE),
        default_timeout=15).run()


def _deny_ui_dispatch(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('Evidence wiring UI must not dispatch, obtain credentials or execute')
    for target in ('sckg_workbench.model_service.ModelService.invoke',
                   'sckg_workbench.model_service.ModelService._credential',
                   'sckg_workbench.model_service.ModelService._call',
                   'sckg_workbench.chat.ChatService.process_registered_send',
                   'sckg_workbench.worker.Worker.run_once',
                   'sckg_workbench.analysis.AnalysisService.run_once',
                   'sckg_workbench.tasks.TaskQueue.submit'):
        monkeypatch.setattr(target, denied)


@pytest.mark.parametrize('use_knowledge', [False, True])
def test_new_ordinary_ui_submission_is_explicit_shared_pending_and_refresh_is_readonly(app, monkeypatch, use_knowledge):
    _deny_ui_dispatch(monkeypatch)
    refused = []
    def refuse(self, turn_id, target, **kwargs):
        assert callable(target)
        refused.append(turn_id)
        return {'dispatch_status': 'fixture_refused_not_started'}
    monkeypatch.setattr(ChatRunService, 'launch', refuse)
    screen = _ui(app)
    if not use_knowledge:
        screen.checkbox(key='research_use_knowledge').uncheck().run()
    screen.chat_input(key='research_prompt').set_value('合成编码提交夹具；不启动模型或分析。').run()
    assert not screen.exception and not screen.error and not screen.success
    request, = app.ledger.list_records('chat_request')
    assert request['status'] == 'pending' and request['evidence_encoding'] == SHARED_EVIDENCE_ENCODING
    assert request['use_knowledge'] is use_knowledge and refused == [request['id']]
    assert not any(key in request for key in ('grounded_mode', 'workflow_options', 'analysis_options', 'result_selection'))
    params = {key: request[key] for key in ('conversation_id', 'prompt', 'profile_id',
        'use_knowledge', 'purpose', 'budget', 'evidence_encoding')}
    assert request['request_hash'] == content_hash(params)
    before = _snapshot(app.ledger)
    screen.run()
    screen.run()
    assert not screen.exception and _snapshot(app.ledger) == before
    assert refused == [request['id']] and app.calls == []
    assert not app.ledger.list_records('model_request') and not app.ledger.list_records('model_call')


def test_ui_refresh_does_not_add_encoding_to_old_pending_request(app, monkeypatch):
    old = app.chat.submit_send(app.conversation['id'], '合成旧literal请求；不启动执行。',
        profile_id=app.profile['id'], budget=BUDGET, request_id='synthetic-old-no-encoding')
    original = app.ledger.get_record('chat_request', old['id'])
    assert 'evidence_encoding' not in original
    _deny_ui_dispatch(monkeypatch)
    def denied_launch(*args, **kwargs):
        pytest.fail('Viewing an old pending request must not launch it')
    monkeypatch.setattr(ChatRunService, 'launch', denied_launch)
    screen = _ui(app)
    before = _snapshot(app.ledger)
    screen.run()
    screen.run()
    assert not screen.exception and screen.chat_input(key='research_prompt').disabled
    assert app.ledger.get_record('chat_request', old['id']) == original
    assert _snapshot(app.ledger) == before and app.calls == []


def test_grounded_ui_submission_omits_ordinary_encoding_and_refuses_launch(app, monkeypatch):
    from tests.test_workbench_ui import _capture_chat_submission
    _deny_ui_dispatch(monkeypatch)
    captured = []
    _capture_chat_submission(monkeypatch, captured)
    screen = _ui(app)
    screen.checkbox(key='research_grounded_mode').check().run()
    screen.chat_input(key='research_prompt').set_value('合成参数捕获；拒绝执行。').run()
    assert not screen.exception and not screen.error and not screen.success
    submission, = captured
    assert submission['grounded_mode'] is True and 'evidence_encoding' not in submission
    assert not app.ledger.list_records('chat_request') and app.calls == []
