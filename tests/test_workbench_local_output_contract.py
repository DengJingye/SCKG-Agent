"""Full local output contracts over an explicitly selected JSON-object wire.

All transports are synthetic. These cases establish admission, validation,
identity, and replay; they do not establish remote capability or scientific gain.
"""
from copy import deepcopy
import json
from urllib.error import HTTPError

import pytest

from sckg_workbench.evidence_answers import EvidenceAnswerError, _call_binding
from sckg_workbench.model_service import (ModelCallError, ModelServiceError, ModelCapabilityError,
    output_contract_request)
from sckg_workbench.model_capabilities import CAPABILITIES_VERSION, API_FAMILY
from sckg_workbench.storage import canonical_json, content_hash
from sckg_workbench.workflow_chat import (JSON_OBJECT_CANONICAL, WorkflowChatError,
    validate_turn, workflow_format, EXPLICIT_MISSING_VERSION)
from tests.test_workbench_models import (BUDGET, PASSPHRASE, answer, call,
    create_profile, setup_service)
from tests.test_workbench_workflow_chat import (app, send, finish, evaluate,
    assert_no_execution_or_promotion)


WIRE = {'type':'json_object'}
FORMAT = {'type':'json_schema','json_schema':{'name':'synthetic_local_contract',
    'strict':True,'schema':{'type':'object','properties':{'fact':{'type':'string'}},
    'required':['fact'],'additionalProperties':False}}}
MESSAGES = [{'role':'user','content':'Read this fixed source.'}]


def forbidden(*args, **kwargs):
    pytest.fail('A rejected local contract must not unlock credentials or dispatch')


def test_explicit_wire_retains_complete_contract_and_replays_readonly(tmp_path, monkeypatch):
    sent = []
    service, ledger, connection = setup_service(tmp_path, lambda *args:
        sent.append(deepcopy(args[2])) or answer(content='{"fact":"source-bound"}'))
    profile = create_profile(service, connection)
    result = call(service, profile, response_format=WIRE, validation_format=FORMAT)
    request = ledger.get_record('model_request', result['call_id'])
    assert sent[0]['response_format'] == WIRE
    assert sent[0]['messages'][0]['content'].endswith(canonical_json(FORMAT))
    assert sent[0]['messages'][0]['role'] == 'system'
    assert sent[0]['messages'][1:] == MESSAGES
    assert 'local_validation_format' not in sent[0]
    assert request['local_validation_format'] == FORMAT
    assert result['local_validation_format_hash'] == content_hash(FORMAT)
    assert result['estimated_input_tokens'] == len(json.dumps(sent[0],ensure_ascii=False).encode()) + 256
    before = tuple(ledger.events())
    monkeypatch.setattr(service,'invoke',forbidden)
    _call_binding(service, profile, result, MESSAGES, WIRE, BUDGET, validation_format=FORMAT)
    assert tuple(ledger.events()) == before and len(sent) == 1
    with pytest.raises(EvidenceAnswerError):
        _call_binding(service, profile, result, MESSAGES, WIRE, BUDGET)


@pytest.mark.parametrize('content', ['{"fact":"ok","extra":7}', '{"fact":7}', '{}',
    '{"fact":"ok","fact":"duplicate"}', '{"fact":NaN}'])
def test_json_object_does_not_weaken_full_local_validation(tmp_path, content):
    sent = []
    service, ledger, connection = setup_service(tmp_path, lambda *args:
        sent.append(args[2]) or answer(content=content,usage={'prompt_tokens':10,'completion_tokens':8}))
    profile = create_profile(service, connection)
    with pytest.raises(ModelCallError) as error:
        call(service,profile,response_format=WIRE,validation_format=FORMAT)
    assert len(sent) == 1 and error.value.outcome == 'invalid_response'
    receipt = error.value.receipt
    assert receipt['local_validation_format_hash'] == content_hash(FORMAT)
    assert ledger.get_record('model_output', receipt['call_id'])['text'] == content
    assert receipt['usage_known'] is True


@pytest.mark.parametrize('wire,canonical', [
    (None, FORMAT), (FORMAT, FORMAT), ({'type':'json_object','extra':True}, FORMAT),
    (WIRE, {'type':'json_object'}), (WIRE, {'type':'json_schema','json_schema':[]}),
    (WIRE, {**FORMAT,'json_schema':{**FORMAT['json_schema'],'strict':False}}),
    (WIRE, {**FORMAT,'json_schema':{**FORMAT['json_schema'],'schema':{'$ref':'https://example.org/schema'}}}),
])
def test_invalid_pair_is_rejected_before_any_side_effect(tmp_path,monkeypatch,wire,canonical):
    service,ledger,connection=setup_service(tmp_path,forbidden)
    profile=create_profile(service,connection)
    before=ledger.events()
    monkeypatch.setattr(service,'_credential',forbidden)
    with pytest.raises(ModelServiceError):
        call(service,profile,response_format=wire,validation_format=canonical)
    assert ledger.events()==before and not ledger.list_records('model_request')


def test_full_schema_bytes_are_budgeted_before_unlock(tmp_path,monkeypatch):
    service,ledger,connection=setup_service(tmp_path,forbidden)
    profile=create_profile(service,connection)
    large=deepcopy(FORMAT)
    large['json_schema']['schema']['description']='🧬'*2000
    monkeypatch.setattr(service,'_credential',forbidden)
    with pytest.raises(ModelServiceError,match='Estimated input'):
        call(service,profile,response_format=WIRE,validation_format=large)
    assert not ledger.list_records('model_request')


def test_owned_canonical_snapshot_survives_caller_and_transport_mutation(tmp_path,monkeypatch):
    canonical,wire,messages=deepcopy((FORMAT,WIRE,MESSAGES))
    def transport(url,headers,payload,timeout):
        payload['messages'].clear()
        return answer(content='{"fact":9}')
    service,ledger,connection=setup_service(tmp_path,transport)
    profile=create_profile(service,connection)
    original=service._credential
    def unlock(*args):
        canonical['json_schema']['schema']={}
        wire['type']='text'
        messages.clear()
        return original(*args)
    monkeypatch.setattr(service,'_credential',unlock)
    with pytest.raises(ModelCallError) as error:
        service.invoke(profile['id'],messages,passphrase=PASSPHRASE,outbound_authorized=True,
            budget=BUDGET,response_format=wire,validation_format=canonical)
    request=ledger.get_record('model_request',error.value.call_id)
    assert request['local_validation_format']==FORMAT
    assert request['payload']['messages'][1:]==MESSAGES
    assert request['payload']['response_format']==WIRE


def test_http_failure_is_one_dispatch_without_format_fallback(tmp_path):
    calls=[]
    def transport(*args):
        calls.append(deepcopy(args[2]))
        raise HTTPError('https://private.invalid',400,'private-body',{},None)
    service,ledger,connection=setup_service(tmp_path,transport)
    profile=create_profile(service,connection)
    with pytest.raises(ModelCallError) as error:
        call(service,profile,response_format=WIRE,validation_format=FORMAT)
    assert len(calls)==1 and calls[0]['response_format']==WIRE
    assert error.value.receipt['local_validation_format_hash']==content_hash(FORMAT)
    assert error.value.receipt['http_status']==400


@pytest.mark.parametrize('damage',['schema','receipt','message','private_schema','instruction_role'])
def test_contract_and_wire_identity_are_both_required(tmp_path,damage):
    service,ledger,connection=setup_service(tmp_path,lambda *a:answer(content='{"fact":"ok"}'))
    profile=create_profile(service,connection)
    result=call(service,profile,response_format=WIRE,validation_format=FORMAT)
    changed=deepcopy(FORMAT)
    if damage=='schema':
        changed['json_schema']['schema']['properties']['fact']['maxLength']=30
    else:
        kind='model_call' if damage=='receipt' else 'model_request'
        record=ledger.get_record(kind,result['call_id'])
        if damage=='receipt':
            record.pop('local_validation_format_hash')
            result.pop('local_validation_format_hash')
        elif damage=='private_schema':
            record['local_validation_format']['json_schema']['schema']={}
        else:
            if damage=='instruction_role':
                record['payload']['messages'][0]['role']='user'
            else:
                record['payload']['messages'][0]['content']='JSON'
            record['request_hash']=content_hash(record['payload'])
        # Deliberate corruption of this disposable test ledger only.
        with ledger.transaction() as conn:
            conn.execute('UPDATE records SET payload=?,digest=? WHERE kind=? AND record_id=?',
                (canonical_json(record),content_hash(record),kind,result['call_id']))
    with pytest.raises(EvidenceAnswerError):
        _call_binding(service,profile,result,MESSAGES,WIRE,BUDGET,validation_format=changed)


def test_legacy_schema_and_json_object_calls_have_no_new_markers(tmp_path):
    service,ledger,connection=setup_service(tmp_path,lambda *a:answer(content='{"fact":"ok"}'))
    profile=create_profile(service,connection)
    for fmt in (FORMAT,WIRE):
        result=call(service,profile,response_format=fmt)
        request=ledger.get_record('model_request',result['call_id'])
        assert request['payload']['messages']==MESSAGES
        assert 'local_validation_format' not in request
        assert 'local_validation_format_hash' not in result
        _call_binding(service,profile,result,MESSAGES,fmt,BUDGET)


def test_workflow_full_journey_and_zero_dispatch_replay(app,monkeypatch):
    options={**app.workflow_options,'wire_mode':JSON_OBJECT_CANONICAL}
    app.state['actions']=[lambda a,p:evaluate(a,True),finish]
    turn=send(app,workflow_options=options)
    assert turn['status']=='succeeded' and len(app.calls)==2
    assert all(p['response_format']==WIRE for p in app.calls)
    for index,payload in enumerate(app.calls):
        fmt=workflow_format(initial=index==0,answer_contract_version=EXPLICIT_MISSING_VERSION)
        assert payload['messages'][0]['content'].endswith(canonical_json(fmt))
        assert turn['receipts'][index]['local_validation_format_hash']==content_hash(fmt)
    request=app.ledger.get_record('chat_request',turn['id'])
    before=app.ledger.events()
    monkeypatch.setattr(app.models,'invoke',forbidden)
    validate_turn(app.ledger,app.models,request,turn)
    assert app.ledger.events()==before
    assert_no_execution_or_promotion(app)


def test_workflow_initial_finish_is_rejected_by_canonical_action_enum(app):
    app.state['actions']=[{'action':'finish','route_ids':[],'reports':[],
        'answer':{'d':'Premature synthetic finish','s':[],'p':[],'m':[]}}]
    turn=send(app,workflow_options={**app.workflow_options,'wire_mode':JSON_OBJECT_CANONICAL})
    assert turn['status']=='failed' and len(app.calls)==1
    assert turn['receipts'][0]['status']=='invalid_response'
    assert not app.ledger.list_records('chat_agent_decision')
    assert_no_execution_or_promotion(app)


def test_workflow_missing_cross_field_constraint_is_not_removed(app):
    def invalid_finish(a,p):
        action=finish(a,p)
        action['answer']['m']=[{'k':'not_supplied','p':['P1'],'t':'Invalid synthetic missing item'}]
        return action
    app.state['actions']=[lambda a,p:evaluate(a,True),invalid_finish]
    turn=send(app,workflow_options={**app.workflow_options,'wire_mode':JSON_OBJECT_CANONICAL})
    assert turn['status']=='failed' and len(app.calls)==2
    assert turn['receipts'][-1]['status']=='invalid_response'
    assert_no_execution_or_promotion(app)


def test_unknown_workflow_wire_mode_does_not_queue_or_dispatch(app):
    before=app.ledger.events()
    with pytest.raises((WorkflowChatError,ValueError)):
        send(app,workflow_options={**app.workflow_options,'wire_mode':'auto_fallback'})
    assert app.ledger.events()==before and not app.calls


@pytest.mark.parametrize('last_action',['finish','evaluate'])
def test_workflow_third_call_is_bound_to_final_only_contract(app,last_action):
    app.state['actions']=[lambda a,p:evaluate(a,True),lambda a,p:evaluate(a,True),
                         finish if last_action=='finish' else lambda a,p:evaluate(a,True)]
    turn=send(app,workflow_options={**app.workflow_options,'wire_mode':JSON_OBJECT_CANONICAL})
    assert len(app.calls)==3 and len(turn['agent_steps'])==2
    final=workflow_format(True,answer_contract_version=EXPLICIT_MISSING_VERSION)
    assert turn['receipts'][-1]['local_validation_format_hash']==content_hash(final)
    assert app.calls[-1]['messages'][0]['content'].endswith(canonical_json(final))
    assert final['json_schema']['schema']['properties']['action']['enum']==['finish']
    if last_action=='finish':
        assert turn['status']=='succeeded'
        validate_turn(app.ledger,app.models,app.ledger.get_record('chat_request',turn['id']),turn)
    else:
        assert turn['status']=='failed' and turn['receipts'][-1]['status']=='invalid_response'
        assert len(app.ledger.list_records('chat_agent_decision'))==2
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize('declared_format',['json_schema','json_object'])
def test_explicit_wire_uses_declared_actual_format_not_canonical(tmp_path,monkeypatch,declared_format):
    sent=[]
    service,ledger,connection=setup_service(tmp_path,lambda *a:
        sent.append(a[2]) or answer(content='{"fact":"ok"}'))
    limits={'schema_version':CAPABILITIES_VERSION,'api_family':API_FAMILY,
        'response_formats':[declared_format],
        'json_schema_format_hashes':[content_hash(FORMAT)] if declared_format=='json_schema' else []}
    profile=create_profile(service,connection,wire_capabilities=limits)
    if declared_format=='json_schema':
        monkeypatch.setattr(service,'_credential',forbidden)
        with pytest.raises(ModelCapabilityError):
            call(service,profile,response_format=WIRE,validation_format=FORMAT)
        assert not sent and not ledger.list_records('model_request')
    else:
        result=call(service,profile,response_format=WIRE,validation_format=FORMAT)
        assert result['wire_response_format_hash']==content_hash(WIRE)
        assert result['local_validation_format_hash']==content_hash(FORMAT)
        assert result['wire_response_format_hash']!=result['local_validation_format_hash']
        assert len(sent)==1


def test_final_body_including_long_model_is_budgeted_before_unlock(tmp_path,monkeypatch):
    service,ledger,connection=setup_service(tmp_path,forbidden)
    profile=service.create_profile('Long model fixture','chat',connection['id'],'x'*5000)
    monkeypatch.setattr(service,'_credential',forbidden)
    with pytest.raises(ModelServiceError,match='Estimated input'):
        call(service,profile,response_format=WIRE,validation_format=FORMAT)
    assert not ledger.list_records('model_request')


def _wire_control():
    import streamlit as st
    from sckg_workbench.ui import _workflow_wire_options
    original={'catalog_record_id':'synthetic-only','catalog_hash':'0'*64}
    selected=_workflow_wire_options(original)
    assert original=={'catalog_record_id':'synthetic-only','catalog_hash':'0'*64}
    st.json(selected)


def test_ui_wire_choice_is_explicit_persists_refresh_and_keeps_legacy_default():
    from streamlit.testing.v1 import AppTest
    ui=AppTest.from_function(_wire_control).run()
    assert not ui.exception and not ui.error
    assert 'wire_mode' not in json.loads(ui.json[0].value)
    ui.selectbox(key='research_workflow_wire_format').select('JSON 对象 + 完整本地合同').run()
    assert json.loads(ui.json[0].value)['wire_mode']==JSON_OBJECT_CANONICAL
    ui.run()
    assert not ui.exception and json.loads(ui.json[0].value)['wire_mode']==JSON_OBJECT_CANONICAL
    ui.selectbox(key='research_workflow_wire_format').select('JSON Schema').run()
    assert 'wire_mode' not in json.loads(ui.json[0].value)
