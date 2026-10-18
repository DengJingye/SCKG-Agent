"""V4 report binding/state boundaries over synthetic local gateway fixtures.

The W02 wording/three-null shape is a captured interaction shape; its miniature
catalog and scripted interpretations here are not biological gold or a model
quality evaluation. No provider, scientific fit or production workspace is used.
"""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from sckg_workbench.storage import canonical_json, content_hash
from sckg_workbench.workflow_chat import (EXPLICIT_MISSING_VERSION, PHASE_CONTRACT_VERSION,
    REPORT_PRESENCE_VERSION, JSON_OBJECT_CANONICAL, WorkflowChatError,
    _answer_contract, _capacity_report_presence_fixture, _source_material,
    catalog_service, prepare_context, validate_turn, workflow_format)
from sckg_workbench.workflow_inputs import (REPORTED_INPUT_STATE_VERSION,
    WorkflowInputCatalog, WorkflowInputError)
from tests.test_workbench_workflow_chat import (app, current_request, evaluate,
    send, assert_no_execution_or_promotion)


W02 = ('我有一个h5ad文件，想了解细胞状态变化的方向。文件里有名叫spliced和unspliced的layer；'
       '我还没检查它们怎样生成、是否是有效观测。请先说明还缺哪些关键信息，本轮只讨论方案，不运行。')


def options(app):
    return {**app.workflow_options, 'wire_mode':JSON_OBJECT_CANONICAL,
        'answer_contract_version':REPORT_PRESENCE_VERSION}


def contract_from_payload(payload):
    for message in reversed(payload['messages']):
        text = message.get('content','')
        for encoded in (text,text.partition('\n')[2]):
            try:
                decoded = json.loads(encoded)
            except (json.JSONDecodeError,TypeError):
                continue
            if isinstance(decoded,dict) and 'answer_contract' in decoded:
                return decoded['answer_contract']
    raise AssertionError('Actual tool answer contract missing')


def finish(app,payload):
    contract = contract_from_payload(payload)
    missing = []
    if contract['unreported_requirements']:
        missing.append({'k':'not_supplied','p':[], 't':'请澄清本次检查尚无绑定报告的输入状态。'})
    if contract['premises']:
        missing.append({'k':'independent_verification_missing',
            'p':[p['p'] for p in contract['premises']], 't':'这些原话的模型解释及输入状态仍需独立核验。'})
    return {'action':'finish','route_ids':[],'reports':[], 'answer':{
        'd':'仅为候选流程的输入讨论；语义、完整适用性与执行资格均未建立。',
        's':[{'i':r['step_id'],'f':'','a':'按当前输入状态追问，保留全部来源条件和未知。',
            'e':r['evidence_aliases'][:1],'p':[],'k':'proposal'} for r in contract['step_routes']],
        'p':deepcopy(contract['premises']),'m':missing}}


def replay_context(app,turn):
    prepared = app.ledger.get_record('chat_context',turn['id'])
    return {'user_turns':prepared['workflow_material']['user_turns'],
        'calls':turn['workflow_run']['calls']}


def rederive(app,turn,*,reports=None,review=None,context=None):
    return _answer_contract(review or turn['workflow_review'],
        turn['workflow_interpretations'] if reports is None else reports,
        answer_contract_version=REPORT_PRESENCE_VERSION,
        report_context=replay_context(app,turn) if context is None else context)


@pytest.mark.parametrize('value,status,action',[(True,'reported_met','conditional_plan'),
    (False,'reported_unmet','blocked'),(None,'unknown','needs_evidence')])
def test_new_review_changes_only_unknown_wording_and_version(app,value,status,action):
    service = catalog_service(app.ledger,app.workflow_options)
    profile = {'reported_inputs':{'counts':value}}
    old = service.evaluate(['counts_route'],profile)
    new = service.evaluate(['counts_route'],profile,review_version=REPORTED_INPUT_STATE_VERSION)
    assert old['schema_version']=='workflow-reported-input-review-v1'
    assert 'reported_input_state_version' not in old
    assert new['schema_version']=='workflow-reported-input-review-v2'
    assert new['reported_input_state_version']==REPORTED_INPUT_STATE_VERSION
    check = new['route_results'][0]['assessment']['decision_check']
    assert (check['preconditions_status'],check['action_status'])==(status,action)
    requirement = new['route_results'][0]['requirements'][0]
    assert requirement['report_present'] is True and requirement['reported_value'] is value
    if value is None:
        assert '状态未确认' in check['reason'] and '尚未明确报告' not in check['reason']
        assert '原话' not in check['reason'] and '观测' not in check['reason']
        assert '尚未明确报告' in old['route_results'][0]['assessment']['decision_check']['reason']
    else:
        assert old['route_results']==new['route_results']
    assert new['model_calls']==new['scientific_fits']==0


def test_unknown_review_version_is_not_silently_inferred(app):
    with pytest.raises(WorkflowInputError,match='review version'):
        catalog_service(app.ledger,app.workflow_options).evaluate(['counts_route'],{},review_version='v999')


@pytest.mark.parametrize('value',[True,False,None])
@pytest.mark.parametrize('wire',['json_object','json_schema'])
def test_v4_bound_state_survives_native_loop_and_readonly_replay(app,monkeypatch,value,wire):
    selected = options(app)
    if wire=='json_schema':
        selected.pop('wire_mode')
    app.state['actions']=[lambda a,p:evaluate(a,value),finish]
    turn=send(app,'这是原始用户的状态说明；其含义由本 fixture 指定。',workflow_options=selected)
    assert turn['status']=='succeeded' and len(app.calls)==2
    contract=rederive(app,turn)
    assert contract['unreported_requirements']==[]
    assert contract['bound_unknown_requirements']==([
        {'report_pointer':'/reported_inputs/counts','premise_id':'P1'}] if value is None else [])
    assert contract['extraction_completeness_not_established'] is True
    assert contract['semantic_interpretation_verified'] is False
    assert all(m['kind']!='not_supplied' for m in turn['workflow_answer']['typed_missing'])
    assert turn['workflow_review']['schema_version']=='workflow-reported-input-review-v2'
    before=app.ledger.events()
    monkeypatch.setattr(app.models,'invoke',lambda *a,**k:pytest.fail('Readonly replay dispatched'))
    validate_turn(app.ledger,app.models,app.ledger.get_record('chat_request',turn['id']),turn)
    assert app.ledger.events()==before and len(app.calls)==2
    assert_no_execution_or_promotion(app)


def test_absent_binding_does_not_claim_user_never_mentioned_input(app):
    app.state['actions']=[lambda a,p:{'action':'evaluate_workflow_inputs',
        'route_ids':['counts_route'],'reports':[],'answer':None},finish]
    turn=send(app,'我有 counts；本 fixture 故意漏抽取这句话。',workflow_options=options(app))
    assert turn['status']=='succeeded'
    contract=rederive(app,turn)
    assert contract['unknown_requirements']==contract['unreported_requirements']==['/reported_inputs/counts']
    assert contract['bound_unknown_requirements']==[]
    assert contract['extraction_completeness_not_established'] is True
    assert '模型可能漏抽取' in contract['missing_rules']['not_supplied']['meaning']
    reason=turn['workflow_review']['route_results'][0]['assessment']['decision_check']['reason']
    assert '状态未确认' in reason and '尚未明确报告' not in reason
    assert turn['workflow_interpretations']==[] and turn['workflow_answer']['typed_missing'][0]['premise_ids']==[]


def test_mixed_absent_and_bound_unknown_remain_distinct(app):
    app.state['actions']=[lambda a,p:evaluate(a,None,routes=['counts_route','additional_route']),finish]
    turn=send(app,'counts 已描述但尚未核验；additional 也在原文，本次故意不提取。',workflow_options=options(app))
    assert turn['status']=='succeeded'
    contract=rederive(app,turn)
    assert contract['unknown_requirements']==['/reported_inputs/counts','/reported_inputs/additional']
    assert contract['unreported_requirements']==['/reported_inputs/additional']
    assert contract['bound_unknown_requirements']==[{'report_pointer':'/reported_inputs/counts','premise_id':'P1'}]
    assert {m['kind'] for m in turn['workflow_answer']['typed_missing']}=={
        'not_supplied','independent_verification_missing'}


def w02_catalog(app):
    catalog=deepcopy(app.catalog)
    template=deepcopy(catalog['routes'][0]['requirements'][0])
    pointers=['spliced_reads','unspliced_reads','cell_expression_profiles']
    catalog['routes']=[{**catalog['routes'][0],'route_id':'w02_shape_route',
        'requirements':[{**deepcopy(template),'requirement_id':p,'label':'Synthetic '+p,
            'report_pointer':'/reported_inputs/'+p} for p in pointers]}]
    catalog=WorkflowInputCatalog.model_validate(catalog).model_dump(mode='json')
    digest=content_hash(catalog)
    record_id='synthetic-w02-shape-'+digest
    app.ledger.put_record('workflow_input_catalog',record_id,
        {'id':record_id,'catalog':catalog,'catalog_hash':digest})
    app.ledger.set_state('workflow_input_catalog',{'record_id':record_id,'catalog_hash':digest})
    app.workflow_options={'catalog_record_id':record_id,'catalog_hash':digest}


def w02_evaluate(app,payload):
    request=current_request(app)
    return {'action':'evaluate_workflow_inputs','route_ids':['w02_shape_route'],'answer':None,
        'reports':[{'report_pointer':'/reported_inputs/'+name,'reported_value':None,
            'user_turn_id':request['id'],'quote':quote} for name,quote in (
                ('spliced_reads',W02[W02.index('文件里'):W02.index('请先')]),
                ('unspliced_reads',W02[W02.index('文件里'):W02.index('请先')]),
                ('cell_expression_profiles',W02[:W02.index('文件里')]))]}


def test_actual_w02_text_three_null_shape_cannot_be_misclassified_as_absent(app):
    w02_catalog(app)
    app.state['actions']=[w02_evaluate,finish]
    turn=send(app,W02,workflow_options=options(app))
    assert turn['status']=='succeeded' and len(app.calls)==2
    contract=rederive(app,turn)
    assert len(contract['unknown_requirements'])==3 and contract['unreported_requirements']==[]
    assert [r['premise_id'] for r in contract['bound_unknown_requirements']]==['P1','P2','P3']
    assert not any(m['kind']=='not_supplied' for m in turn['workflow_answer']['typed_missing'])
    assert all(p['reported_status']=='unknown' for p in turn['workflow_answer']['premise_checks'])
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize('damage',['not_supplied','source_only','omit_one'])
def test_each_bound_null_needs_independent_verification_coverage(app,damage):
    w02_catalog(app)
    def bad_finish(a,p):
        action=finish(a,p)
        if damage=='not_supplied':
            action['answer']['m'].append({'k':'not_supplied','p':[],'t':'错误地宣称没有报告。'})
        elif damage=='source_only':
            action['answer']['m'][0]['k']='source_evidence_missing'
        else:
            action['answer']['m'][0]['p']=['P1','P2']
        return action
    app.state['actions']=[w02_evaluate,bad_finish]
    turn=send(app,W02,workflow_options=options(app))
    assert turn['status']=='failed' and len(app.calls)==2 and turn.get('answer') is None
    assert_no_execution_or_promotion(app)


def test_bound_null_coverage_can_be_split_across_missing_items(app):
    w02_catalog(app)
    def split(a,p):
        action=finish(a,p)
        action['answer']['m']=[{'k':'independent_verification_missing','p':[pid],
            't':'请核验这项已绑定原话对应的输入状态。'} for pid in ('P1','P2','P3')]
        return action
    app.state['actions']=[w02_evaluate,split]
    turn=send(app,W02,workflow_options=options(app))
    assert turn['status']=='succeeded' and len(turn['workflow_answer']['typed_missing'])==3


def test_absent_binding_requires_compatible_not_supplied_category(app):
    def no_missing(a,p):
        action=finish(a,p)
        action['answer']['m']=[]
        return action
    app.state['actions']=[lambda a,p:{'action':'evaluate_workflow_inputs',
        'route_ids':['counts_route'],'reports':[],'answer':None},no_missing]
    turn=send(app,'先讨论输入。',workflow_options=options(app))
    assert turn['status']=='failed' and len(app.calls)==2


@pytest.mark.parametrize('damage',['quote','pointer','span','prompt_hash','value_hash','origin',
    'semantic_verified','call_id','output_hash','wire_pointer','wire_hash','missing_context'])
def test_p_alias_or_present_null_cannot_replace_original_binding(app,damage):
    app.state['actions']=[lambda a,p:evaluate(a,None),finish]
    turn=send(app,workflow_options=options(app))
    assert turn['status']=='succeeded'
    reports=deepcopy(turn['workflow_interpretations'])
    context=deepcopy(replay_context(app,turn))
    if damage=='quote': reports[0].pop('quote')
    elif damage=='pointer': reports[0]['report_pointer']='/reported_inputs/additional'
    elif damage=='span': reports[0]['unicode_spans']=[{'start':0,'end':1}]
    elif damage=='prompt_hash': reports[0]['prompt_hash']='f'*64
    elif damage=='value_hash': reports[0]['reported_value_hash']='f'*64
    elif damage=='origin': reports[0]['semantic_origin']='source_paper'
    elif damage=='semantic_verified': reports[0]['semantic_interpretation_verified']=True
    elif damage=='call_id': reports[0]['call_id']='invented-call'
    elif damage=='output_hash': reports[0]['model_output_hash']='f'*64
    elif damage=='wire_pointer':
        context['calls'][0]['wire']['reports'][0]['report_pointer']='/reported_inputs/additional'
        context['calls'][0]['receipt']['structured_output_hash']=content_hash(context['calls'][0]['wire'])
    elif damage=='wire_hash': context['calls'][0]['receipt']['structured_output_hash']='f'*64
    else: context={}
    with pytest.raises(WorkflowChatError,match='binding|originating'):
        rederive(app,turn,reports=reports,context=context)


def test_profile_presence_alone_never_supplies_a_quote(app):
    service=catalog_service(app.ledger,app.workflow_options)
    review=service.evaluate(['counts_route'],{'reported_inputs':{'counts':None}},
        review_version=REPORTED_INPUT_STATE_VERSION)
    assert review['route_results'][0]['requirements'][0]['report_present'] is True
    with pytest.raises(WorkflowChatError,match='profile and interpretation bindings differ'):
        _answer_contract(review,[],answer_contract_version=REPORT_PRESENCE_VERSION)


def test_deleting_all_interpretations_cannot_turn_a_saved_report_into_absent(app):
    app.state['actions']=[lambda a,p:evaluate(a,None),finish]
    turn=send(app,workflow_options=options(app))
    with pytest.raises(WorkflowChatError,match='bindings differ'):
        rederive(app,turn,reports=[])


def test_latest_evaluation_wire_cannot_retain_a_hidden_report(app):
    app.state['actions']=[lambda a,p:{'action':'evaluate_workflow_inputs',
        'route_ids':['counts_route'],'reports':[],'answer':None},finish]
    turn=send(app,workflow_options=options(app))
    context=deepcopy(replay_context(app,turn))
    call=context['calls'][0]
    call['wire']['reports']=[{'report_pointer':'/reported_inputs/counts','reported_value':None,
        'user_turn_id':turn['id'],'quote':turn['prompt']}]
    call['receipt']['structured_output_hash']=content_hash(call['wire'])
    with pytest.raises(WorkflowChatError,match='evaluation call binding changed'):
        rederive(app,turn,context=context)


@pytest.mark.parametrize('origin',['source','assistant'])
def test_source_or_assistant_text_is_rejected_as_original_user_report(app,origin):
    if origin=='assistant':
        app.state['actions']=['ASSISTANT_ONLY_INPUT']
        first=send(app,'先问好。',workflow_options=None,request_id='ordinary-prefix')
        quote,turn_id=first['answer'],first['id']
    else:
        quote,turn_id='Synthetic counts are required.',None
    app.state['actions']=[lambda a,p:evaluate(a,None,quote=quote,turn_id=turn_id)]
    turn=send(app,'本轮仅讨论输入。',workflow_options=options(app),request_id='invalid-origin')
    assert turn['status']=='failed' and turn.get('workflow_review') is None and turn.get('answer') is None
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize('override',[None,EXPLICIT_MISSING_VERSION,PHASE_CONTRACT_VERSION])
def test_explicit_v4_cannot_be_downgraded(app,override):
    app.state['actions']=[lambda a,p:evaluate(a,True),finish]
    turn=send(app,workflow_options=options(app))
    request=app.ledger.get_record('chat_request',turn['id'])
    with pytest.raises(WorkflowChatError,match='phase contract'):
        prepare_context(app.ledger,request,answer_contract_version=override)


@pytest.mark.parametrize('stage',['initial','middle','final'])
def test_v4_schema_reuses_exact_v3_phase_and_missing_constraints(stage):
    arguments={'initial':stage=='initial','final_only':stage=='final'}
    old=workflow_format(**arguments,answer_contract_version=PHASE_CONTRACT_VERSION)
    new=workflow_format(**arguments,answer_contract_version=REPORT_PRESENCE_VERSION)
    Draft202012Validator.check_schema(new['json_schema']['schema'])
    assert old['json_schema']['schema']==new['json_schema']['schema']
    assert new['json_schema']['name']=='development_workflow_action_report_presence_v4'


def test_legacy_api_stays_v2_and_v4_prompt_has_no_unknown_equals_unreported_rule(app):
    from tests.test_workbench_workflow_chat import finish as legacy_finish
    app.state['actions']=[lambda a,p:evaluate(a,None),legacy_finish]
    old=send(app,request_id='legacy-default')
    assert old['status']=='succeeded'
    prepared=app.ledger.get_record('chat_context',old['id'])
    assert prepared['workflow_material']['answer_contract_version']==EXPLICIT_MISSING_VERSION
    assert old['workflow_review']['schema_version']=='workflow-reported-input-review-v1'
    assert '尚未明确报告' in old['workflow_review']['route_results'][0]['assessment']['decision_check']['reason']
    app.state['actions']=[lambda a,p:evaluate(a,None),finish]
    new=send(app,workflow_options=options(app),request_id='new-version')
    prompt=app.ledger.get_record('chat_context',new['id'])['messages'][0]['content']
    assert 'answer_contract_version=report_presence_v4' in prompt
    assert 'reported_value=null也仍然是已有原话' not in prompt
    assert '有未报告输入时m至少一项not_supplied' not in prompt
    assert '模型可能漏抽取' in prompt and '不证明原话与该输入相关' in prompt


def test_sizing_fixture_is_explicitly_synthetic_and_not_registered(app):
    app.state['actions']=[lambda a,p:evaluate(a,None),finish]
    turn=send(app,workflow_options=options(app))
    prepared=app.ledger.get_record('chat_context',turn['id'])
    service=catalog_service(app.ledger,options(app))
    _,reviews=_source_material(service,include_reviews=True,review_version=REPORTED_INPUT_STATE_VERSION)
    before=app.ledger.events()
    review,reports,context,action=_capacity_report_presence_fixture(prepared,reviews,
        ['counts_route','additional_route'],'🧬'*1000)
    contract=_answer_contract(review,reports,answer_contract_version=REPORT_PRESENCE_VERSION,
        report_context=context)
    assert contract['unreported_requirements']==[] and len(contract['bound_unknown_requirements'])==2
    assert context['scope']=='synthetic_capacity_sizing_only_not_ledger_evidence'
    assert context['user_turns'][0]['prompt']=='🧬'*1000
    assert content_hash(action)==context['calls'][0]['receipt']['structured_output_hash']
    assert app.ledger.events()==before and len(app.calls)==2


def test_v4_one_shared_report_keeps_both_route_step_bindings_in_replay(app,monkeypatch):
    # Synthetic source mapping and scripted extraction: no semantic-gold claim.
    catalog=deepcopy(app.catalog)
    catalog['routes'][1]['label']='Synthetic second route sharing counts'
    catalog['routes'][1]['requirements']=[deepcopy(catalog['routes'][0]['requirements'][0])]
    catalog=WorkflowInputCatalog.model_validate(catalog).model_dump(mode='json')
    digest=content_hash(catalog)
    record_id='synthetic-shared-presence-'+digest
    app.ledger.put_record('workflow_input_catalog',record_id,
        {'id':record_id,'catalog':catalog,'catalog_hash':digest})
    app.ledger.set_state('workflow_input_catalog',{'record_id':record_id,'catalog_hash':digest})
    app.workflow_options={'catalog_record_id':record_id,'catalog_hash':digest}
    app.state['actions']=[lambda a,p:evaluate(a,None,
        routes=['counts_route','additional_route']),finish]
    turn=send(app,'合成夹具：counts 状态尚未核验。',workflow_options=options(app))
    assert turn['status']=='succeeded' and len(app.calls)==2
    assert len(turn['workflow_interpretations'])==1
    assert [r['route_id'] for r in turn['workflow_review']['route_results']]==[
        'counts_route','additional_route']
    contract=rederive(app,turn)
    assert contract['premises']==[{'p':'P1','s':['s1','s2'],'r':'unknown','a':'needs_evidence'}]
    assert contract['unreported_requirements']==[]
    assert contract['unknown_requirements']==['/reported_inputs/counts']
    assert contract['bound_unknown_requirements']==[
        {'report_pointer':'/reported_inputs/counts','premise_id':'P1'}]
    assert turn['workflow_answer']['premise_checks'][0]['step_ids']==['s1','s2']
    assert all(r['requirements'][0]['report_present'] is True
        and r['requirements'][0]['reported_value'] is None
        for r in turn['workflow_review']['route_results'])
    assert turn['workflow_interpretations'][0]['call_id']==turn['receipts'][0]['call_id']
    before=app.ledger.events()
    monkeypatch.setattr(app.models,'invoke',lambda *a,**k:pytest.fail('Shared-pointer replay dispatched'))
    validate_turn(app.ledger,app.models,app.ledger.get_record('chat_request',turn['id']),turn)
    assert app.chat.view_turn(turn['id'])['usable'] is True and app.ledger.events()==before
    assert_no_execution_or_promotion(app)


def test_v4_second_evaluation_replaces_routes_reports_and_requires_latest_call(app,monkeypatch):
    # Deliberate scripted state replacement within one bounded native loop.
    # It tests provenance mechanics, not interpretation of the user wording.
    def first(a,p):
        request=current_request(a)
        return {'action':'evaluate_workflow_inputs','route_ids':['counts_route','additional_route'],
            'reports':[{'report_pointer':pointer,'reported_value':value,
                'user_turn_id':request['id'],'quote':quote} for pointer,value,quote in (
                    ('/reported_inputs/counts',True,'初次 counts 已有'),
                    ('/reported_inputs/additional',False,'additional 没有'))], 'answer':None}
    app.state['actions']=[first,
        lambda a,p:evaluate(a,None,quote='随后 counts 状态未知'),finish]
    turn=send(app,'合成脚本形状：初次 counts 已有；additional 没有；随后 counts 状态未知。',
        workflow_options=options(app))
    assert turn['status']=='succeeded' and len(app.calls)==3 and len(turn['agent_steps'])==2
    first_result,last_result=[step['result'] for step in turn['agent_steps']]
    assert [r['premise_id'] for r in first_result['workflow_interpretations']]==['P1','P2']
    assert [r['reported_value'] for r in first_result['workflow_interpretations']]==[True,False]
    assert [r['route_id'] for r in first_result['workflow_review']['route_results']]==[
        'counts_route','additional_route']
    assert [r['route_id'] for r in turn['workflow_review']['route_results']]==['counts_route']
    assert turn['workflow_review']==last_result['workflow_review']
    assert turn['workflow_interpretations']==last_result['workflow_interpretations']
    leaf,=turn['workflow_interpretations']
    assert leaf['premise_id']=='P1' and leaf['report_pointer']=='/reported_inputs/counts'
    assert leaf['reported_value'] is None and leaf['quote']=='随后 counts 状态未知'
    assert leaf['call_id']==turn['receipts'][1]['call_id']!=turn['receipts'][0]['call_id']
    assert leaf['model_output_hash']==turn['receipts'][1]['structured_output_hash']
    contract=rederive(app,turn)
    assert contract['premises']==[{'p':'P1','s':['s1'],'r':'unknown','a':'needs_evidence'}]
    assert contract['unreported_requirements']==[]
    assert contract['bound_unknown_requirements']==[
        {'report_pointer':'/reported_inputs/counts','premise_id':'P1'}]
    assert len(turn['workflow_answer']['steps'])==len(turn['workflow_answer']['premise_checks'])==1
    context=deepcopy(replay_context(app,turn))
    context['calls'][1]['receipt']=deepcopy(context['calls'][0]['receipt'])
    context['calls'][1]['call_id']=context['calls'][0]['call_id']
    with pytest.raises(WorkflowChatError,match='evaluation call binding changed'):
        rederive(app,turn,context=context)
    stale_reports=deepcopy(turn['workflow_interpretations'])
    stale_reports[0]['call_id']=turn['receipts'][0]['call_id']
    with pytest.raises(WorkflowChatError,match='original quote, pointer or call binding changed'):
        rederive(app,turn,reports=stale_reports)
    before=app.ledger.events()
    monkeypatch.setattr(app.models,'invoke',lambda *a,**k:pytest.fail('Replacement replay dispatched'))
    validate_turn(app.ledger,app.models,app.ledger.get_record('chat_request',turn['id']),turn)
    assert app.chat.view_turn(turn['id'])['usable'] is True and app.ledger.events()==before
    assert_no_execution_or_promotion(app)
