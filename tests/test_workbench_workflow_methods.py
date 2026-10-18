"""Typed decisions over real ledgers and synthetic sources, not scientific gold."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from sckg_workbench.storage import content_hash, canonical_json
from sckg_workbench.workflow_inputs import WorkflowInputCatalog
from sckg_workbench.workflow_methods import (WorkflowMethodCatalog, WorkflowMethodService, WorkflowMethodError,
    configured_method_service)
from tests.test_workbench_knowledge import kb, candidate
from tests.test_workbench_workflow_inputs_ui import _snapshot


def atom(field, value=None, *, other=None, op='eq'):
    return {'field_id': field, 'op': op, 'value': value, 'other_field': other}


def expr(*atoms, mode='all'):
    return {'mode': mode, 'atoms': list(atoms)}


def binding(unit, index, *, kind=False):
    attr = unit['claim']['typed_attributes'][index]
    value = {'candidate_id': unit['id'], 'candidate_hash': unit['content_hash'],
        'attribute_index': index, 'attribute_hash': content_hash(attr)}
    return {**value, 'attribute_kind': attr['name']} if kind else value


@pytest.fixture
def methods(kb, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Read-only method checks attempted a provider or source request')
    monkeypatch.setattr('sckg_workbench.model_service.ModelService.invoke', denied)
    monkeypatch.setattr('sckg_workbench.model_service.ModelService.embed', denied)
    monkeypatch.setattr('sckg_workbench.sources.fetch_public_url', denied)
    train, source, _ = candidate(kb, text='Synthetic fixture only: inputs, optional features, batching and memory.',
        claim_updates={'model_self_score': None, 'typed_attributes': [
            {'name': kind, 'value': text, 'evidence_anchor_indices': [0], 'qualifiers': ['Synthetic, not scientific evidence']}
            for kind, text in [('workflow.input', 'Synthetic normalized input or raw-file exception'),
                ('workflow.input', 'Synthetic matching axes'), ('workflow.input', 'Synthetic postfilter genes exceed top count'),
                ('workflow.action', 'Synthetic optional batching requires two flags'),
                ('workflow.action', 'Synthetic sparse memory tradeoff')]]})
    mapped, _, _ = candidate(kb, text='Synthetic alternative requires an annotated reference.', filename='map.txt',
        claim_updates={'model_self_score': None, 'typed_attributes': [{'name': 'workflow.input',
            'value': 'Synthetic annotated reference', 'evidence_anchor_indices': [0], 'qualifiers': []}]})
    def requirement(key, unit, index):
        return {'requirement_id': key, 'label': key, 'report_pointer': '/reported_inputs/' + key,
            'source_bindings': [binding(unit, index)]}
    base = WorkflowInputCatalog.model_validate({'schema_version': 'development-workflow-input-catalog-v1',
        'authority': 'developer_source_interpretation_not_human_review', 'routes': [
            {'route_id': 'train', 'label': 'Synthetic train', 'requirements': [requirement('format', train, 0),
                requirement('axes', train, 1)], 'context_candidate_ids': [], 'requirements_complete': False, 'scope_notes': []},
            {'route_id': 'mapping', 'label': 'Synthetic mapping', 'requirements': [requirement('reference', mapped, 0)],
                'context_candidate_ids': [], 'requirements_complete': False, 'scope_notes': []}]}).model_dump(mode='json')
    base_ref = {'record_id': 'synthetic-base', 'catalog_hash': content_hash(base)}
    kb.ledger.put_record('workflow_input_catalog', base_ref['record_id'],
        {'id': base_ref['record_id'], 'catalog': base, 'catalog_hash': base_ref['catalog_hash']})
    kb.ledger.set_state('workflow_input_catalog', base_ref)
    protocol = {'authority': 'investigator_experimental_protocol_not_literature_claim',
        'rules': [{'rule_id': 'reference_only', 'statement': 'Synthetic investigator policy, not an author fact'}]}
    proto_ref = {'record_id': 'synthetic-protocol', 'catalog_hash': content_hash(protocol)}
    kb.ledger.put_record('workflow_local_protocol', proto_ref['record_id'], {'id': proto_ref['record_id'],
        'protocol': protocol, 'protocol_hash': proto_ref['catalog_hash']})
    def field(key, kind='boolean', choices=None, show=None, scope='method'):
        return {'field_id': key, 'label': key, 'kind': kind, 'choices': choices or [], 'show_when': show, 'scope': scope}
    fields = [field('input_kind', 'choice', ['matrix', 'raw_file']), field('normalized'), field('feature_selection'),
        field('top_genes', 'integer', show={'field_id': 'feature_selection', 'value': True}),
        field('postfilter_genes', 'integer', show={'field_id': 'feature_selection', 'value': True}),
        field('balance'), field('sgd', show={'field_id': 'balance', 'value': True}),
        field('mini_batch', show={'field_id': 'balance', 'value': True}), field('sparse'),
        field('with_mean', show={'field_id': 'sparse', 'value': True}), field('reference_only', scope='protocol')]
    def rule(key, kind, index, when, expect, rid=None):
        return {'rule_id': key, 'label': key, 'kind': kind, 'when': when, 'expect': expect,
            'reported_requirement_id': rid, 'source_bindings': [binding(train, index, kind=True)]}
    catalog = WorkflowMethodCatalog.model_validate({
        'schema_version': 'development-workflow-method-catalog-v1',
        'authority': 'developer_source_interpretation_not_human_review', 'base_catalog': base_ref,
        'protocol': proto_ref, 'fields': fields, 'routes': [
            {'route_id': 'train', 'method_scope': 'Synthetic training only', 'version_scope': 'Synthetic version, not measured',
                'rules': [rule('format', 'precondition', 0, None,
                    expr(atom('input_kind', 'raw_file'), atom('normalized', True), mode='any'), 'format'),
                    rule('features', 'precondition', 2, expr(atom('feature_selection', True)),
                        expr(atom('postfilter_genes', other='top_genes', op='gt'))),
                    rule('balance', 'option_scope', 3, expr(atom('balance', True)),
                        expr(atom('sgd', True), atom('mini_batch', True))),
                    rule('memory', 'advisory', 4, expr(atom('sparse', True), atom('with_mean', False)), None)],
                'local_policy_checks': [{'rule_id': 'fit_scope', 'label': 'Synthetic local fitting policy',
                    'protocol_rule_id': 'reference_only', 'expect': expr(atom('reference_only', True))}]},
            {'route_id': 'mapping', 'method_scope': 'Synthetic mapping only', 'version_scope': 'No training version inferred',
                'rules': [], 'local_policy_checks': []}]}).model_dump(mode='json')
    ref = {'record_id': 'synthetic-methods', 'catalog_hash': content_hash(catalog)}
    kb.ledger.put_record('workflow_method_catalog', ref['record_id'],
        {'id': ref['record_id'], 'catalog': catalog, 'catalog_hash': ref['catalog_hash']})
    kb.ledger.set_state('workflow_method_catalog', ref)
    return SimpleNamespace(**vars(kb), catalog=catalog, train=train, train_source=source)


def service(f, catalog=None):
    value = f.catalog if catalog is None else catalog
    return WorkflowMethodService(f.ledger, value, expected_catalog_hash=content_hash(value))


def report():
    return {'reported_inputs': {'format': True, 'axes': True, 'reference': True},
        'reported_config': {'input_kind': 'matrix', 'normalized': True, 'feature_selection': False,
            'balance': False, 'sparse': True, 'with_mean': False}, 'reported_protocol': {}}


def train_result(f, profile=None, **kwargs):
    return service(f).evaluate(['train'], profile if profile is not None else report(), **kwargs)['route_results'][0]


@pytest.mark.parametrize('change,decision,rule,status,missing', [
    ({}, 'conditional_plan', 'features', 'not_applicable', []),
    ({'input_kind': 'raw_file', 'normalized': False}, 'conditional_plan', 'format', 'reported_met', []),
    ({'feature_selection': True, 'postfilter_genes': 300, 'top_genes': 300}, 'blocked', 'features', 'reported_unmet', []),
    ({'feature_selection': True, 'postfilter_genes': 301, 'top_genes': 300}, 'conditional_plan', 'features', 'reported_met', []),
    ({'feature_selection': True, 'top_genes': 300}, 'needs_information', 'features', 'needs_information', ['postfilter_genes']),
    ({'feature_selection': None}, 'needs_information', 'features', 'needs_information', ['feature_selection']),
    ({'balance': True, 'sgd': True, 'mini_batch': False}, 'conditional_plan', 'balance', 'option_not_applicable', []),
    ({'balance': True, 'sgd': False, 'mini_batch': True}, 'conditional_plan', 'balance', 'option_not_applicable', []),
    ({'balance': True, 'sgd': True, 'mini_batch': True}, 'conditional_plan', 'balance', 'reported_met', []),
    ({'balance': True, 'sgd': True}, 'needs_information', 'balance', 'needs_information', ['mini_batch']),
    ({'with_mean': True}, 'conditional_plan', 'memory', 'not_applicable', []),
])
def test_conditional_branches_and_options_do_not_become_blanket_method_rejection(methods, change, decision, rule, status, missing):
    profile = report(); profile['reported_config'].update(change)
    before = _snapshot(methods.ledger)
    result = train_result(methods, profile)
    check = next(r for r in result['configuration_checks'] if r['rule_id'] == rule)
    assert result['method_decision'] == decision and check['status'] == status
    assert check['missing_field_ids'] == missing
    assert not result['complete_scientific_applicability_established']
    assert not result['local_execution']['execution_authorized']
    assert _snapshot(methods.ledger) == before


def test_conflicting_reports_keep_both_and_never_choose_the_favorable_value(methods):
    profile = report(); profile['reported_config']['normalized'] = False
    result = train_result(methods, profile)
    assert result['method_decision'] == 'needs_clarification'
    assert result['report_conflicts'] == [{'rule_id': 'format', 'requirement_id': 'format',
        'input_report': True, 'configuration_report_result': False}]
    assert result['input_review']['requirements'][0]['reported_value'] is True
    profile['reported_inputs']['format'] = False
    assert train_result(methods, profile)['method_decision'] == 'blocked'


def test_local_policy_is_separate_and_alternative_mapping_does_not_inherit_training_rules(methods):
    profile = report(); profile['reported_protocol']['reference_only'] = False
    result = train_result(methods, profile, include_local_protocol=True)
    assert result['method_decision'] == 'conditional_plan' and result['local_protocol']['state'] == 'blocked'
    profile['reported_inputs']['axes'] = False
    result = service(methods).evaluate(['train', 'mapping'], profile, include_local_protocol=True)
    assert [r['method_decision'] for r in result['route_results']] == ['blocked', 'conditional_plan']
    assert result['route_results'][1]['configuration_checks'] == []
    assert not result['recommendation_eligible'] and not methods.knowledge.search('Synthetic').units
    assert result['result_hash'] == content_hash({k: v for k, v in result.items() if k != 'result_hash'})


@pytest.mark.parametrize('field,value', [('top_genes', True), ('top_genes', '300'),
    ('postfilter_genes', -1), ('postfilter_genes', 1.5), ('normalized', 'false'), ('input_kind', 'filename.h5ad')])
def test_no_implicit_type_or_filename_inference(methods, field, value):
    profile = report(); profile['reported_config'][field] = value
    with pytest.raises(WorkflowMethodError, match='explicit field type'):
        train_result(methods, profile)


@pytest.mark.parametrize('damage', ['kind', 'hash', 'route_scope', 'policy_scope', 'controller'])
def test_hashes_attribute_roles_and_authority_scopes_are_rechecked(methods, damage):
    value = deepcopy(methods.catalog)
    if damage == 'kind':
        value['routes'][0]['rules'][0]['source_bindings'][0]['attribute_kind'] = 'workflow.action'
    elif damage == 'hash':
        value['routes'][0]['rules'][0]['source_bindings'][0]['attribute_hash'] = 'f' * 64
    elif damage == 'route_scope':
        value['routes'][1]['rules'] = deepcopy(value['routes'][0]['rules'][1:2])
    elif damage == 'policy_scope':
        value['routes'][0]['rules'][0]['expect']['atoms'][0]['field_id'] = 'reference_only'
    else:
        value['fields'][3]['show_when'] = {'field_id': 'postfilter_genes', 'value': 300}
    before = _snapshot(methods.ledger)
    with pytest.raises(ValueError):
        service(methods, value).evaluate(['train', 'mapping'], report())
    assert _snapshot(methods.ledger) == before


def test_live_source_suspension_invalidates_previously_created_service(methods):
    checker = service(methods); checker.evaluate(['train'], report())
    methods.knowledge.suspend('source', methods.train_source['id'], actor='synthetic-fixture', reason='Fixture withdrawal')
    before = _snapshot(methods.ledger)
    with pytest.raises(ValueError, match='suspended'):
        checker.evaluate(['train'], report())
    assert checker.evaluate(['mapping'], report())['route_results'][0]['method_decision'] == 'conditional_plan'
    assert _snapshot(methods.ledger) == before


def test_borrowed_transaction_and_original_v1_result_are_preserved(methods):
    checker = service(methods)
    original = checker.inputs.evaluate(['train'], {'reported_inputs': {'format': True, 'axes': True}})
    with methods.ledger.connect() as conn:
        conn.execute('BEGIN')
        borrowed = checker.inputs.evaluate(['train'], {'reported_inputs': {'format': True, 'axes': True}}, _connection=conn)
        assert conn.in_transaction and conn.execute('SELECT 1').fetchone()[0] == 1
    assert original == borrowed


def test_method_preview_is_independent_of_legacy_chat_selection_and_context(methods):
    from sckg_workbench.workflow_chat import catalog_service, _source_material
    base = deepcopy(service(methods).inputs.catalog)
    base['routes'] = [r for r in base['routes'] if r['route_id'] == 'mapping']
    ref = {'record_id': 'legacy-chat-only', 'catalog_hash': content_hash(base)}
    methods.ledger.put_record('workflow_input_catalog', ref['record_id'],
        {'id': ref['record_id'], 'catalog': base, 'catalog_hash': ref['catalog_hash']})
    methods.ledger.set_state('workflow_input_catalog', ref)
    options = {'catalog_record_id': ref['record_id'], 'catalog_hash': ref['catalog_hash']}
    before_context = _source_material(catalog_service(methods.ledger, options))
    before = _snapshot(methods.ledger)
    checker = configured_method_service(methods.ledger)
    assert checker.evaluate(['train'], report())['route_results'][0]['method_decision'] == 'conditional_plan'
    assert _source_material(catalog_service(methods.ledger, options)) == before_context
    assert methods.ledger.get_state('workflow_input_catalog') == ref and _snapshot(methods.ledger) == before
    methods.ledger.set_state('workflow_method_catalog', {'record_id': 'different', 'catalog_hash': 'f' * 64})
    with pytest.raises(WorkflowMethodError, match='selection changed'):
        checker.evaluate(['train'], report())
