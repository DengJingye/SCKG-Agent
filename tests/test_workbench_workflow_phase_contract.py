"""Phase/action contracts with real local gateway records and synthetic transport."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import pytest

from sckg_workbench.storage import canonical_json,content_hash
from sckg_workbench.workflow_chat import (PHASE_CONTRACT_VERSION,EXPLICIT_MISSING_VERSION,
    JSON_OBJECT_CANONICAL,WorkflowChatError,prepare_context,validate_turn,workflow_format)
from tests.test_workbench_workflow_chat import (app,send,evaluate,finish,
    assert_no_execution_or_promotion)


def fmt(stage):
    return workflow_format(initial=stage=='initial',final_only=stage=='final',
        answer_contract_version=PHASE_CONTRACT_VERSION)


def initial_action():
    return {'action':'evaluate_workflow_inputs','route_ids':['counts_route'],'reports':[],'answer':None}


def final_action():
    return {'action':'finish','route_ids':[],'reports':[],
        'answer':{'d':'Synthetic proposal only','s':[],'p':[],'m':[]}}


@pytest.mark.parametrize('stage,action',[('initial',initial_action()),('middle',initial_action()),
    ('middle',final_action()),('final',final_action())])
def test_reachable_phase_actions_are_valid(stage,action):
    schema=fmt(stage)['json_schema']['schema']
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(action)


@pytest.mark.parametrize('stage,action',[
    ('initial',final_action()),('final',initial_action()),
    ('initial',{**initial_action(),'answer':final_action()['answer']}),
    ('middle',{**initial_action(),'answer':final_action()['answer']}),
    ('initial',{**initial_action(),'route_ids':[]}),('middle',{**initial_action(),'route_ids':[]}),
    ('middle',{**initial_action(),'route_ids':['counts_route','counts_route']}),
    ('middle',{**final_action(),'answer':None}),('final',{**final_action(),'answer':None}),
    ('middle',{**final_action(),'route_ids':['counts_route']}),
    ('final',{**final_action(),'route_ids':['counts_route']}),
    ('middle',{**final_action(),'reports':[{'report_pointer':'/reported_inputs/counts',
        'reported_value':None,'user_turn_id':'synthetic','quote':'Synthetic only'}]}),
])
def test_phase_field_relationships_reject_premature_or_inconsistent_actions(stage,action):
    with pytest.raises(ValidationError):
        Draft202012Validator(fmt(stage)['json_schema']['schema']).validate(action)


@pytest.mark.parametrize('stage',['initial','middle','final'])
def test_existing_alias_and_missing_constraints_are_retained_exactly(stage):
    old=workflow_format(answer_contract_version=EXPLICIT_MISSING_VERSION)['json_schema']['schema']
    new=fmt(stage)['json_schema']['schema']
    assert canonical_json(old['$defs'])==canonical_json(new['$defs'])
    assert new['properties']['route_ids']['maxItems'] in (0,4)
    assert new['properties']['reports']['maxItems'] in (0,8)
    assert new['additionalProperties'] is False


def options(app):
    return {**app.workflow_options,'wire_mode':JSON_OBJECT_CANONICAL,
            'answer_contract_version':PHASE_CONTRACT_VERSION}


@pytest.mark.parametrize('tool_checks',[1,2])
@pytest.mark.parametrize('wire',['json_object','json_schema'])
def test_native_loop_phase_receipts_tools_and_readonly_replay(app,monkeypatch,tool_checks,wire):
    app.state['actions']=[*[lambda a,p:evaluate(a,True) for _ in range(tool_checks)],finish]
    selected=options(app)
    if wire=='json_schema':selected.pop('wire_mode')
    turn=send(app,workflow_options=selected)
    assert turn['status']=='succeeded' and len(app.calls)==tool_checks+1
    assert len(turn['agent_steps'])==tool_checks
    prepared=app.ledger.get_record('chat_context',turn['id'])
    assert prepared['workflow_material']['answer_contract_version']==PHASE_CONTRACT_VERSION
    assert 'answer必须为null' in prepared['messages'][0]['content']
    assert turn['workflow_answer'] and turn['workflow_run']['scientific_semantics_verified'] is False
    for index,call in enumerate(app.calls):
        phase='initial' if index==0 else 'final' if index==2 else 'middle'
        expected=fmt(phase)
        receipt=turn['receipts'][index]
        request=app.ledger.get_record('model_request',receipt['call_id'])
        if wire=='json_object':
            assert receipt['local_validation_format_hash']==content_hash(expected)
            assert request['local_validation_format']==expected
            assert call['messages'][0]['content'].endswith(canonical_json(expected))
        else:
            assert request['payload']['response_format']==expected
            assert 'local_validation_format_hash' not in receipt
    def deny(*a,**k):pytest.fail('Replay must not dispatch or mutate records')
    monkeypatch.setattr(app.models,'invoke',deny)
    before=app.ledger.events()
    validate_turn(app.ledger,app.models,app.ledger.get_record('chat_request',turn['id']),turn)
    assert app.ledger.events()==before
    assert_no_execution_or_promotion(app)


def test_schema_rejects_premature_validly_typed_answer_before_any_tool(app):
    # All fields in this answer are individually valid, unlike the captured
    # failure's long candidate IDs. Rejection must come from phase semantics.
    def premature(a,p):
        return {**evaluate(a,True),'answer':final_action()['answer']}
    app.state['actions']=[premature]
    turn=send(app,workflow_options=options(app))
    assert turn['status']=='failed' and len(app.calls)==1
    assert turn['receipts'][0]['status']=='invalid_response'
    assert turn['agent_steps']==[] and not app.ledger.list_records('chat_agent_decision')
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize('override',[None,EXPLICIT_MISSING_VERSION])
def test_new_request_cannot_downgrade_prepared_contract(app,override):
    app.state['actions']=[lambda a,p:evaluate(a,True),finish]
    turn=send(app,workflow_options=options(app))
    request=app.ledger.get_record('chat_request',turn['id'])
    with pytest.raises(WorkflowChatError,match='phase contract'):
        prepare_context(app.ledger,request,answer_contract_version=override)
    assert len(app.calls)==2


def test_new_version_is_not_inferred_for_legacy_api_requests(app):
    app.state['actions']=[lambda a,p:evaluate(a,True),finish]
    turn=send(app)
    assert turn['status']=='succeeded'
    saved=app.ledger.get_record('chat_context',turn['id'])
    assert saved['workflow_material']['answer_contract_version']==EXPLICIT_MISSING_VERSION
    assert saved['messages'][0]['content'].find('阶段合同：')==-1


def _phase_ui():
    import streamlit as st
    from sckg_workbench.ui import _workflow_wire_options
    st.json(_workflow_wire_options({'catalog_record_id':'synthetic-only','catalog_hash':'0'*64}))


def test_real_ui_options_always_bind_v3_for_new_submissions():
    # Historical test ID is retained; new UI submissions now use the presence
    # contract while all explicit V3 compatibility cases above stay unchanged.
    from sckg_workbench.workflow_chat import REPORT_PRESENCE_VERSION
    from streamlit.testing.v1 import AppTest
    ui=AppTest.from_function(_phase_ui).run()
    assert not ui.exception
    default=json.loads(ui.json[0].value)
    assert default['answer_contract_version']==REPORT_PRESENCE_VERSION and 'wire_mode' not in default
    ui.selectbox(key='research_workflow_wire_format').select('JSON 对象 + 完整本地合同').run()
    selected=json.loads(ui.json[0].value)
    assert selected['answer_contract_version']==REPORT_PRESENCE_VERSION
    assert selected['wire_mode']==JSON_OBJECT_CANONICAL
    ui.run()
    assert json.loads(ui.json[0].value)==selected and not ui.exception


@pytest.mark.parametrize('initial,final_only',[(False,False),(False,True),(True,False),(True,True)])
def test_archived_v2_canonical_formats_remain_identical(initial,final_only):
    archive=json.loads((Path(__file__).parent/'fixtures/workflow_missing_v2_formats.json').read_text())
    expected=archive['formats'][f'initial_{int(initial)}_final_{int(final_only)}']
    assert canonical_json(workflow_format(initial=initial,final_only=final_only,
        answer_contract_version=EXPLICIT_MISSING_VERSION))==canonical_json(expected)
