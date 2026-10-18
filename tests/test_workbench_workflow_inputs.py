"""Meaningful input/identity failures over real services, synthetic source text.

These are engineering controls, not scientific labels or model performance.
"""
from copy import deepcopy

import pytest

from sckg_workbench.storage import content_hash
from sckg_workbench.workflow_inputs import WorkflowInputService, WorkflowInputError
from tests.test_workbench_workflow_inputs_ui import workflow, _snapshot
from tests.test_workbench_knowledge import candidate, kb


def service(f, catalog=None):
    value = catalog if catalog is not None else f.workflow_catalog
    return WorkflowInputService(f.ledger, value, expected_catalog_hash=content_hash(value))


@pytest.mark.parametrize('value,status,action', [
    (None,'unknown','needs_evidence'),(False,'reported_unmet','blocked'),
    (True,'reported_met','conditional_plan')])
def test_three_explicit_report_states_remain_reports_not_scientific_or_execution_success(workflow,value,status,action):
    before = _snapshot(workflow.ledger)
    result = service(workflow).evaluate(['synthetic_0'],{'reported_inputs':{'counts':value}})
    route = result['route_results'][0]
    check = route['assessment']['decision_check']
    assert (check['preconditions_status'],check['action_status']) == (status,action)
    assert check['scientific_support'] == 'no_claim'
    assert route['requirements'][0]['reported_value'] is value
    assert route['local_execution'] == {'state':'unbound','execution_authorized':False,'execution_attempted':False}
    assert not route['complete_scientific_applicability_established']
    assert not result['recommendation_eligible']
    assert result['independent_input_verification'] == 'not_established'
    assert result['result_hash'] == content_hash({k:v for k,v in result.items() if k!='result_hash'})
    assert _snapshot(workflow.ledger) == before


def test_metadata_names_and_explicit_unknown_do_not_become_availability(workflow):
    source = service(workflow)
    absent = source.evaluate(['synthetic_0'],{'layers':['counts'],'modality':'RNA'})
    unknown = source.evaluate(['synthetic_0'],{'reported_inputs':{'counts':None}})
    a = absent['route_results'][0]['requirements'][0]
    b = unknown['route_results'][0]['requirements'][0]
    assert not a['report_present'] and b['report_present']
    assert a['check']['preconditions_status'] == b['check']['preconditions_status'] == 'unknown'
    assert a['reported_value_hash'] is None and b['reported_value_hash'] == content_hash(None)


@pytest.mark.parametrize('value',['false',0,[],{}])
def test_nonboolean_values_are_not_silently_cast_to_presence(workflow,value):
    before = _snapshot(workflow.ledger)
    with pytest.raises(WorkflowInputError,match='explicit true, false or null'):
        service(workflow).evaluate(['synthetic_0'],{'reported_inputs':{'counts':value}})
    assert _snapshot(workflow.ledger) == before


def test_known_missing_requirement_blocks_one_route_without_invalidating_alternative(workflow):
    catalog = deepcopy(workflow.workflow_catalog)
    extra = deepcopy(catalog['routes'][0]['requirements'][0])
    extra.update(requirement_id='additional_input',report_pointer='/reported_inputs/additional')
    catalog['routes'][0]['requirements'].append(extra)
    result = service(workflow,catalog).evaluate(['synthetic_0','synthetic_1'],
        {'reported_inputs':{'counts':True,'additional':False}})
    assert [r['assessment']['decision_check']['preconditions_status']
            for r in result['route_results']] == ['reported_unmet','reported_met']
    result = service(workflow,catalog).evaluate(['synthetic_0'],
        {'reported_inputs':{'counts':False,'additional':None}})
    assert result['route_results'][0]['assessment']['decision_check']['action_status'] == 'blocked'


def test_missing_secondary_requirement_cannot_become_complete_method_readiness(workflow):
    catalog = deepcopy(workflow.workflow_catalog)
    extra = deepcopy(catalog['routes'][0]['requirements'][0])
    extra.update(requirement_id='additional_input',report_pointer='/reported_inputs/additional')
    catalog['routes'][0]['requirements'].append(extra)
    result = service(workflow,catalog).evaluate(['synthetic_0'],{'reported_inputs':{'counts':True}})
    route = result['route_results'][0]
    assert route['assessment']['decision_check']['preconditions_status'] == 'unknown'
    assert not route['requirements_complete'] and not route['source_semantics_reassessed']


def test_catalog_copy_or_pointer_edit_cannot_retain_old_fixed_hash(workflow):
    catalog = deepcopy(workflow.workflow_catalog)
    catalog['routes'][0]['requirements'][0]['report_pointer'] = '/reported_inputs/other'
    with pytest.raises(WorkflowInputError,match='catalog changed'):
        WorkflowInputService(workflow.ledger,catalog,
                             expected_catalog_hash=content_hash(workflow.workflow_catalog))


@pytest.mark.parametrize('damage',['candidate','candidate_hash','attribute_hash','attribute_index','context'])
def test_rehashed_config_still_rechecks_actual_source_bindings(workflow,damage):
    catalog = deepcopy(workflow.workflow_catalog)
    route = catalog['routes'][0]
    binding = route['requirements'][0]['source_bindings'][0]
    if damage == 'candidate':
        binding['candidate_id'] = 'candidate-'+'f'*64
    elif damage == 'attribute_index':
        binding['attribute_index'] = 100
    elif damage == 'context':
        route['context_candidate_ids'] = ['candidate-'+'f'*64]
    else:
        binding[damage] = 'f'*64
    before = _snapshot(workflow.ledger)
    with pytest.raises(WorkflowInputError):
        service(workflow,catalog).evaluate(['synthetic_0'],{'reported_inputs':{'counts':True}})
    assert _snapshot(workflow.ledger) == before


def test_action_attribute_cannot_be_reinterpreted_as_sourced_input(workflow):
    unit,_,_ = candidate(workflow, text='Synthetic action is described, not an input.',
        claim_updates={'typed_attributes':[{'name':'workflow.action','value':'synthetic action',
            'evidence_anchor_indices':[0],'qualifiers':[]}]})
    catalog = deepcopy(workflow.workflow_catalog)
    catalog['routes'][0]['requirements'][0]['source_bindings'] = [{
        'candidate_id':unit['id'],'candidate_hash':unit['content_hash'],'attribute_index':0,
        'attribute_hash':content_hash(unit['claim']['typed_attributes'][0])}]
    with pytest.raises(WorkflowInputError,match='identity, kind or content'):
        service(workflow,catalog).evaluate(['synthetic_0'],{'reported_inputs':{'counts':True}})


def test_corrupt_original_is_rejected_even_with_intact_catalog_and_candidate_hash(workflow):
    source = workflow.workflow_source
    path = workflow.ledger.workspace.artifacts_dir/'source_blobs'/source['blob_sha256']
    path.write_bytes(b'Synthetic corrupted evidence, isolated fixture only')
    with pytest.raises(ValueError,match='missing or changed'):
        service(workflow).evaluate(['synthetic_0'],{'reported_inputs':{'counts':True}})


def test_suspended_source_is_rechecked_instead_of_using_cached_candidate(workflow):
    source = service(workflow)
    source.evaluate(['synthetic_0'],{'reported_inputs':{'counts':True}})
    workflow.knowledge.suspend('source',workflow.workflow_source['id'],
                              actor='synthetic-test',reason='Synthetic source suspension')
    before = _snapshot(workflow.ledger)
    with pytest.raises(WorkflowInputError,match='suspended'):
        source.evaluate(['synthetic_0'],{'reported_inputs':{'counts':True}})
    assert _snapshot(workflow.ledger) == before
