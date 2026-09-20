"""5C design-only contract checks. No application/schema migration or writes.

The helpers validate small synthetic design examples; they are not a production
validator or compatibility adapter. Protected-root checks also detect new files.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'data/ontology/scientific_decision_ontology_v2_core'
OLD = ROOT / 'data/ontology/scientific_decision_ontology_v2'


def load(name):
    return json.loads((CORE / f'{name}.json').read_text())


def object_types():
    return {r['item_id']: r for r in load('object_type_registry')['objects']
            if r['disposition'] == 'CORE_OBJECT_TYPE'}


def links():
    return {r['predicate_id']: r for r in load('link_type_registry')['links']}


def properties():
    return {r['property_id']: r for r in load('property_registry')['properties']}


def qualifier_ids():
    return {r['qualifier_id'] for r in load('qualifier_registry')['qualifiers']}


def tree_hashes(roots):
    files = set()
    for relative in roots:
        path = ROOT / relative
        assert path.exists(), relative
        for item in ([path] if path.is_file() else path.rglob('*')):
            name = str(item.relative_to(ROOT)).lower()
            if item.is_file() and '__pycache__' not in item.parts and not any(
                part in name for part in ('sealed', 'quarantine', '/c7')
            ):
                files.add(item)
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


def entity_type(value):
    return value.get('record_type') if isinstance(value, dict) else value


def validate_typed_value(value, datatype, allowed_values=None):
    if datatype not in {'string', 'boolean', 'integer', 'number'}:
        raise ValueError('invalid datatype')
    valid = (type(value) is str and bool(value)) if datatype == 'string' else (
        type(value) is bool if datatype == 'boolean' else
        type(value) is int if datatype == 'integer' else
        type(value) in {int, float} and math.isfinite(value))
    if not valid:
        raise ValueError('invalid datatype/value')
    if allowed_values is not None and value not in allowed_values:
        raise ValueError('invalid enum value')


def validate_parameter_condition(condition, *, parameters=None, resources=None, subject_id=None):
    shape = load('property_registry')['embedded_value_shapes']['parameter_condition']
    if not isinstance(condition, dict) or not set(shape['required']) <= condition.keys():
        raise ValueError('invalid activation condition shape')
    if not set(condition) <= set(shape['required'] + shape['optional']):
        raise ValueError('invalid activation condition shape')
    parameter = (parameters or {}).get(condition['parameter_id'])
    if not parameter:
        raise ValueError('unknown ParameterDefinition')
    subject = (resources or {}).get(subject_id, {})
    if not isinstance(subject, dict) or subject.get('record_type') != 'OperatorRevision' or (
        parameter['owner_operator_id'] != subject.get('operator_id') or
        subject_id not in parameter['allowed_operator_revision_ids']
    ):
        raise ValueError('parameter owned by wrong OperatorRevision')
    op = condition['operator']
    if op not in shape['operator']:
        raise ValueError('invalid comparison operator')
    if op == 'present':
        if any(k in condition for k in ('values', 'datatype', 'unit')):
            raise ValueError('present condition forbids comparison payload')
        return
    values = condition.get('values')
    if not isinstance(values, list) or not values or op == 'equals' and len(values) != 1:
        raise ValueError('invalid comparison values')
    if condition.get('datatype') != parameter['datatype']:
        raise ValueError('invalid datatype')
    if condition.get('unit') != parameter.get('unit'):
        raise ValueError('invalid unit/value combination')
    for value in values:
        validate_typed_value(value, condition['datatype'], parameter.get('allowed_values'))


def validate_version_condition(value, qualifier, *, resources=None, subject_id=None):
    shape = load('property_registry')['embedded_value_shapes']['version_constraint']
    if not isinstance(value, dict) or not {'subject_id', 'status'} <= value.keys() or not set(value) <= {'subject_id','status','expression'}:
        raise ValueError('invalid version condition shape')
    if value['status'] not in shape['status']:
        raise ValueError('invalid version state')
    resource = (resources or {}).get(value['subject_id'])
    families = load('qualifier_registry')['value_validation']['version_families'][qualifier]
    if entity_type(resource) not in families:
        raise ValueError('cross-family version reference')
    subject = (resources or {}).get(subject_id, {})
    valid_subject_ids = {subject_id}
    if isinstance(subject, dict):
        valid_subject_ids |= {subject.get(k) for k in ['operator_id','package_id','package_release_id','method_id']}
        valid_subject_ids |= set(subject.get('implements_method_ids', []))
    if value['subject_id'] not in valid_subject_ids:
        raise ValueError('unrelated version subject')
    if value['status'] not in {'exact','range'}:
        if 'expression' in value:
            raise ValueError('non-specific version state forbids pin')
        return
    expression = value.get('expression')
    if not isinstance(expression, str):
        raise ValueError('invalid version pin')
    pattern = shape['exact_pattern']
    clauses = []
    if value['status'] == 'exact':
        if not re.fullmatch(pattern, expression): raise ValueError('invalid version pin')
        clauses = [('==', expression)]
    else:
        for clause in expression.split(','):
            match = re.fullmatch(r'(>=|<=|>|<|==)(' + pattern + ')', clause)
            if not match: raise ValueError('invalid version pin')
            clauses.append(match.groups())
    pinned = resource.get('version') if isinstance(resource, dict) else None
    if pinned:
        if not re.fullmatch(pattern, pinned): raise ValueError('unsupported pinned version format')
        for op, pin in clauses:
            if op == '==':
                if pin != pinned: raise ValueError('pin conflicts with resource version')
            else:
                # Ordering prerelease/build strings is deliberately unsupported in this design helper.
                if any(c in pinned + pin for c in '-+'):
                    raise ValueError('unsupported version ordering')
                def parts(v):
                    p = tuple(map(int, v.split('.')))
                    return p + (0,) * (4-len(p))
                a,b = parts(pinned), parts(pin)
                if not {'>=':a>=b,'<=':a<=b,'>':a>b,'<':a<b}[op]:
                    raise ValueError('pin conflicts with resource version')


def validate_qualifiers(values, allowed, *, parameters=None, resources=None, subject_id=None, terms=None):
    if not isinstance(values, dict): raise ValueError('invalid qualifier value shape')
    if not set(values) <= set(allowed): raise ValueError('qualifier forbidden for predicate')
    spec = load('qualifier_registry')['value_validation']
    for key,value in values.items():
        if key not in qualifier_ids(): raise ValueError('unknown qualifier')
        if key == 'parameter_condition':
            validate_parameter_condition(value, parameters=parameters, resources=resources, subject_id=subject_id)
        elif key in spec['version_families']:
            validate_version_condition(value,key,resources=resources,subject_id=subject_id)
        elif key == 'organism_taxon':
            if not isinstance(value,str) or not re.fullmatch(spec['organism_taxon_pattern'],value):
                raise ValueError('invalid taxon value')
        else:
            if not isinstance(value,str) or not value: raise ValueError('invalid qualifier value shape')
            valid = spec['observation_unit_enum'] if key == 'observation_unit' else (terms or {}).get(key, [])
            if value not in valid: raise ValueError('invalid enum value')


def validate_link(predicate, subject_type, object_type, *, qualifiers=None, as_statement=False, **context):
    row = links().get(predicate)
    if row is None: raise ValueError('unknown predicate')
    if [subject_type, object_type] not in row['allowed_endpoint_pairs']:
        raise ValueError('incompatible endpoint family')
    validate_qualifiers({} if qualifiers is None else qualifiers, row['qualifier_policy']['allowed'], **context)
    if as_statement and not row['statement_predicate_allowed']:
        raise ValueError('not an authoritative scientific statement predicate')


def validate_context(inline, shared, status, allowed, **context):
    validate_qualifiers(inline, allowed, **context)
    validate_qualifiers(shared, allowed, **context)
    for k in set(inline) & set(shared):
        if inline[k] != shared[k]: raise ValueError('scope conflict')
    combined = {**shared, **inline}
    if status not in load('scope_policy')['scope_status']: raise ValueError('scope status')
    if status in {'explicit','partially_known'} and not combined: raise ValueError('known context required')
    if status in {'unknown','not_applicable'} and combined: raise ValueError('context forbidden')
    return combined


def validate_shared_scope(scope, allowed, *, previous=None, **context):
    contract=load('scope_policy')['shared_scope_contract']
    if not isinstance(scope,dict) or not set(contract['required_fields']) <= scope.keys():
        raise ValueError('shared scope fields')
    if not isinstance(scope['id'],str) or not scope['id']:
        raise ValueError('scope identity')
    if scope['combination'] not in contract['combination']: raise ValueError('scope combination')
    validate_context({},scope['qualifiers'],scope['scope_status'],allowed,**context)
    unknown=scope.get('unknown_dimensions',[])
    if not isinstance(unknown,list) or not all(isinstance(k,str) for k in unknown) or len(unknown)!=len(set(unknown)) or not set(unknown)<=set(allowed) or set(unknown)&scope['qualifiers'].keys():
        raise ValueError('unknown dimensions')
    if bool(unknown)!=(scope['scope_status']=='partially_known'):
        raise ValueError('partial scope needs disjoint unknown dimensions')
    if previous and previous['id']==scope['id'] and previous!=scope:
        raise ValueError('immutable scope requires new ID')
    return scope


def combine_scope(inline, shared, allowed, **context):
    validate_shared_scope(shared,allowed,**context)
    validate_qualifiers(inline,allowed,**context)
    for k in set(inline)&shared['qualifiers'].keys():
        if inline[k]!=shared['qualifiers'][k]:raise ValueError('scope conflict')
    # Preserve ANY_OF: duplicates stay inside the shared group, not promoted to an extra AND clause.
    return {'shared': shared, 'inline': {k:v for k,v in inline.items() if k not in shared['qualifiers']}}


def scope_truth(expression, observations):
    """Synthetic three-valued context check, never a production applicability gate."""
    def fold(values, combination):
        if combination=='ALL_OF':
            return False if False in values else None if None in values else True
        return True if True in values else None if None in values else False
    shared=expression['shared']
    if shared['scope_status']=='unknown': result=None
    elif shared['scope_status']=='not_applicable': result=True
    else:
        values=[observations[k]==v if k in observations else None for k,v in shared['qualifiers'].items()]
        if shared['scope_status']=='partially_known':values.append(None)
        result=fold(values,shared['combination'])
    rest=[observations[k]==v if k in observations else None for k,v in expression['inline'].items()]
    return fold([result,*rest],'ALL_OF')


def validate_statement(record, entities, scopes=None, *, parameters=None, terms=None):
    model=load('statement_model')['revision']
    if not set(model['required_fields'])<=record.keys():raise ValueError('missing statement field')
    for name in ['polarity','epistemic_status','assertion_kind']:
        if record[name] not in model[name]:raise ValueError('invalid '+name)
    if entity_type(entities.get(record['statement_id']))!='ScientificStatement':raise ValueError('statement identity')
    subject=entity_type(entities.get(record['subject_id']))
    has_object=record.get('object_id') is not None;has_literal=record.get('literal_value') is not None
    if has_object==has_literal:raise ValueError('object XOR literal')
    pred=record['predicate']
    if has_object:
        row=links().get(pred)
        validate_link(pred,subject,entity_type(entities.get(record['object_id'])),as_statement=True)
        allowed=row['qualifier_policy']['allowed']
    else:
        row=properties().get(pred)
        if not row or not row.get('assertion_allowed') or subject not in row['owners']:
            raise ValueError('literal property domain or assertion forbidden')
        literal=record['literal_value']
        if not isinstance(literal,dict) or set(literal)!={'datatype','value'}:raise ValueError('literal value shape')
        if literal['datatype']!=row['value_type']:raise ValueError('literal datatype')
        try:validate_typed_value(literal['value'],literal['datatype'])
        except ValueError as exc:raise ValueError('literal value') from exc
        allowed=row['assertion_qualifier_policy']['allowed']
    ctx={'parameters':parameters,'resources':entities,'subject_id':record['subject_id'],'terms':terms}
    if record.get('scope_ref'):
        scope=(scopes or {}).get(record['scope_ref'])
        if scope is None:raise ValueError('dangling scope')
        expression=combine_scope(record['qualifiers'],scope,allowed,**ctx)
        # Statement status cannot hide unknown shared context as fully explicit.
        if scope['scope_status'] in {'unknown','partially_known'} and record['scope_status']=='explicit':
            raise ValueError('statement scope status hides unknown shared context')
        if scope['scope_status']=='unknown' and not record['qualifiers']:
            if record['scope_status']!='unknown':raise ValueError('statement scope status')
        else:validate_context(record['qualifiers'],scope['qualifiers'],record['scope_status'],allowed,**ctx)
        return expression
    validate_context(record['qualifiers'],{},record['scope_status'],allowed,**ctx)


def validate_reference_revision(record, resources):
    if not isinstance(record,dict) or record.get('record_type')!='ReferenceArtifactRevision':
        raise ValueError('invalid reference family')
    if entity_type(resources.get(record.get('artifact_id')))!='ReferenceArtifact':
        raise ValueError('invalid reference family')
    if not isinstance(record.get('version'),str) or not record['version'].strip():raise ValueError('missing reference pin')
    if not re.fullmatch(r'[0-9a-f]{64}',record.get('content_hash','')):raise ValueError('invalid reference digest')


def validate_requirement(record, *, resources=None, parameters=None, subject_id=None):
    if record.get('strength') not in properties()['strength']['enum']:raise ValueError('requirement strength')
    if 'level' in record:raise ValueError('legacy level forbidden')
    policy=load('scope_policy')['activation_policy'];status=record.get('activation_status')
    when=record.get('when',[])
    if status not in policy['status'] or not isinstance(when,list):raise ValueError('invalid activation condition shape/status')
    if bool(when)!=(status=='specified'):raise ValueError('activation status conflicts with when')
    for cond in when:validate_parameter_condition(cond,parameters=parameters,resources=resources,subject_id=subject_id)
    if record.get('combination') not in properties()['combination']['enum']:raise ValueError('requirement combination')
    targets=record.get('targets')
    if not isinstance(targets,list) or not targets:raise ValueError('at least one requirement target')
    for target in targets:
        obj=(resources or {}).get(target);typ=entity_type(obj)
        if typ=='RepresentationConstraint':validate_link('requires_constraint','Requirement',typ)
        elif typ=='ReferenceArtifactRevision':
            validate_link('requires_reference','Requirement',typ)
            validate_reference_revision(obj,resources)
        else:raise ValueError('invalid requirement target/reference family')
    return None if status=='unknown' else 'conditioned' if when else 'unconditional'


def validate_effect_evidence(record, *, entities=None, assessments=None):
    """Required design structure only; success grants no execution/gate authority."""
    if record.get('record_type')!='StatementRevision':
        raise ValueError('machine-readable effect requires StatementRevision, not display metadata')
    validate_statement(record,entities or {})
    matching=[a for a in assessments or [] if a.get('statement_revision_id')==record['statement_revision_id']]
    if not matching:raise ValueError('machine-readable effect requires EvidenceAssessment')
    for a in matching:validate_assessment(a,{record['statement_revision_id']},{a['evidence_span_id']})
    return {'required_evidence_structure_valid':True,'decision_authorized':False}


def validate_span(record):
    model = load('evidence_model')
    if not set(model['EVIDENCE_SPAN_CORE_FIELDS']) <= record.keys():
        raise ValueError('missing span field')
    allowed = set(model['EVIDENCE_SPAN_CORE_FIELDS'] + model['EVIDENCE_SPAN_OPTIONAL_FIELDS'])
    if not set(record) <= allowed:
        raise ValueError('non-excerpt semantics')
    if hashlib.sha256(record['exact_text'].encode('utf-8')).hexdigest() != record['content_hash']:
        raise ValueError('exact text hash')
    locator = record['locator']
    if locator.get('kind') not in load('property_registry')['embedded_value_shapes']['locator']['kind'] or not locator.get('value'):
        raise ValueError('locator')
    if locator['kind'] == 'pdf_page' and (type(record.get('page')) is not int or record['page'] < 1):
        raise ValueError('PDF page')
    if ('start_offset' in record) != ('end_offset' in record):
        raise ValueError('offset pair')
    if 'start_offset' in record and not (type(record['start_offset']) is int and type(record['end_offset']) is int and 0 <= record['start_offset'] < record['end_offset']):
        raise ValueError('offset interval')


def validate_assessment(row, statements, spans):
    model = load('evidence_model')['assessment']
    if not set(model['required_fields']) <= row.keys():
        raise ValueError('assessment fields')
    if row['statement_revision_id'] not in statements or row['evidence_span_id'] not in spans:
        raise ValueError('dangling evidence binding')
    if row['support_type'] not in {r['value'] for r in load('evidence_model')['support_types']}:
        raise ValueError('support type')
    if row['status'] not in model['status']:
        raise ValueError('assessment status')
    if row['support_type'] in {'DIRECT_SUPPORT', 'REFUTES'} and not (
        row['subject_aligned'] is True and row['predicate_aligned'] is True
        and row['object_aligned'] is True and row['scope_alignment'] == 'aligned'
    ):
        raise ValueError('support alignment')
    if 'confidence' in row and (type(row['confidence']) not in {int, float} or not math.isfinite(row['confidence']) or not 0 <= row['confidence'] <= 1):
        raise ValueError('confidence')


def test_unique_core_objects_properties_links_and_qualifiers():
    for rows, key in [(load('object_type_registry')['objects'], 'item_id'),
                      (load('property_registry')['properties'], 'property_id'),
                      (load('link_type_registry')['links'], 'predicate_id'),
                      (load('qualifier_registry')['qualifiers'], 'qualifier_id')]:
        ids = [r[key] for r in rows]
        assert len(ids) == len(set(ids))


def test_core_objects_are_defined_modular_and_admitted():
    registry = load('object_type_registry')
    assert set(registry['modules']) == {'scKG-core', 'scKG-representation', 'scKG-statement', 'scKG-evidence', 'runtime-bridge'}
    for name, row in object_types().items():
        assert row['definition'] and row['module'] and row['identity_rule'] and row['lifecycle']
        assert name in registry['modules'][row['module']]
        assert all(row['admission'].values())
        assert row['supporting_cq_ids']
        assert row['parent_class'] is None


def test_properties_are_values_with_valid_owners():
    for row in properties().values():
        assert row['definition'] and row['value_type']
        assert row['classification'] == 'PROPERTY' and not row['graph_node']
        assert set(row['owners']) <= object_types().keys()
    assert not (set(properties()) & object_types().keys())


def test_links_have_resolvable_domains_ranges_no_unknown_interfaces():
    for row in links().values():
        assert row['definition'] and row['direction'] == 'subject_to_object'
        assert row['domain'] and row['range']
        assert set(row['domain'] + row['range']) <= object_types().keys()
        assert row['allowed_endpoint_pairs']
        for a, b in row['allowed_endpoint_pairs']:
            assert a in row['domain'] and b in row['range']
        assert row['cardinality'] in {'1', '0..*', '1..*'}
        if row['symmetric']:
            assert {tuple(p) for p in row['allowed_endpoint_pairs']} == {(b,a) for a,b in row['allowed_endpoint_pairs']}
        assert not row['transitive']
        assert row['inverse_predicate'] is None or row['inverse_predicate'] in links()


def test_class_properties_required_links_and_record_references_resolve():
    for row in object_types().values():
        assert set(row['required_properties'] + row['optional_properties']) <= properties().keys()
        for p in row['required_properties'] + row['optional_properties']:
            assert row['item_id'] in properties()[p]['owners']
        for p in row['required_links']:
            assert row['item_id'] in links()[p]['domain']
        for p in row['required_incoming_links']:
            assert row['item_id'] in links()[p]['range']
    for row in load('object_type_registry')['record_reference_fields']:
        assert set(row['range']) <= object_types().keys()


def test_link_evidence_and_authority_policies_are_explicit():
    for row in links().values():
        assert row['classification'] in {'AUTHORITATIVE', 'DERIVED_PROJECTION'}
        assert type(row['evidence_required']) is bool
        assert row['evidence_policy']['kind'] and row['evidence_policy']['rule']
        assert row['supporting_cq_ids']
        if row['classification'] == 'DERIVED_PROJECTION':
            assert not row['statement_predicate_allowed']
    assert not load('link_type_registry')['projection_policy']['authoritative']


def test_predicate_specific_qualifiers_not_universal_template():
    policies = []
    for row in links().values():
        policy = row['qualifier_policy']
        assert policy['rule']
        assert set(policy['allowed']) <= qualifier_ids()
        assert set(policy['required']) <= set(policy['allowed'])
        policies.append(tuple(policy['allowed']))
    assert len(set(policies)) >= 4
    assert links()['revision_of']['qualifier_policy']['allowed'] == []
    assert links()['uses_evidence']['qualifier_policy']['allowed'] == []
    assert 'organism_taxon' not in links()['implements_method']['qualifier_policy']['allowed']


def test_no_runtime_ownership_leaks_to_scientific_layer():
    bridge = object_types()['RepresentationRecord']
    assert bridge['owner'] == 'RepresentationLedger' and bridge['layer'] == 'runtime'
    assert bridge['runtime_bridge_only'] and not bridge['required_properties']
    assert 'GovernedAction' not in object_types() and 'TraceSpan' not in object_types()
    runtime = {'lineage_id','cell_index_hash','gene_index_hash','freshness_status','observation_identity'}
    for row in object_types().values():
        if row['layer'] == 'scientific':
            assert not runtime & set(row['required_properties'] + row['optional_properties'])


def test_minimal_evidence_span_excludes_support_governance_and_retrieval():
    model = load('evidence_model')
    allowed = set(model['EVIDENCE_SPAN_CORE_FIELDS'] + model['EVIDENCE_SPAN_OPTIONAL_FIELDS'])
    forbidden = {'support_type','review_status','knowledge_status','candidate_only','authority','retrieval_eligible','normalized_proposition','recommendation_eligible'}
    assert not allowed & forbidden
    assert 'page' not in model['EVIDENCE_SPAN_CORE_FIELDS']
    assert forbidden <= {r['field'] for r in model['EVIDENCE_SPAN_REMOVED_OR_EXTERNALIZED_FIELDS']}


def test_statement_identity_revision_polarity_and_object_union_are_explicit():
    model = load('statement_model')
    assert model['identity']['class'] == 'ScientificStatement'
    assert not model['identity']['large_text_bag']
    assert {'statement_id','statement_revision_id','subject_id','predicate','polarity','qualifiers','scope_status','epistemic_status','schema_version','ontology_version'} <= set(model['revision']['required_fields'])
    assert set(model['revision']['exactly_one']) == {'object_id','literal_value'}
    assert set(model['revision']['polarity']) == {'POSITIVE','NEGATIVE'}
    assert not model['compatibility']['implemented']
    assert 'AtomicClaimRevision' not in object_types()


def test_scope_policy_explains_inline_reuse_and_conflicts():
    p = load('scope_policy')
    assert p['SCOPE_AS_QUALIFIER_RULES'] and p['SCOPE_AS_OBJECT_RULES']
    assert p['scope_reuse_not_mandatory'] and p['conflict_rule']
    assert 'scope_ref' not in load('statement_model')['revision']['required_fields']


def test_support_types_and_multiple_evidence_are_reified():
    m = load('evidence_model')
    assert {r['value'] for r in m['support_types']} == {'DIRECT_SUPPORT','PARTIAL_SUPPORT','CONTEXTUAL_SUPPORT','CONTRADICTS','REFUTES','DOES_NOT_SUPPORT','UNCERTAIN'}
    assert m['multiple_evidence'] and m['independence']
    assert len(m['distinct_gates']) == 5 and not m['automatic_promotion']
    assert not {'supports','contradicts','refutes'} & links().keys()


def test_every_design1_class_and_predicate_has_exactly_one_disposition():
    old_classes = json.loads((OLD/'class_registry.json').read_text())['proposed_classes']
    old_links = json.loads((OLD/'predicate_registry.json').read_text())['proposed_predicates']
    current = load('object_type_registry')['objects']
    review = load('link_type_registry')['design1_review']
    assert {r['class_id'] for r in old_classes} == {r['item_id'] for r in current}
    assert {r['predicate_id'] for r in old_links} == {r['predicate_id'] for r in review}
    assert len(current) == 45 and len(review) == 46
    for row in current + review:
        assert row['reason'] and row['disposition'] and row['supporting_cq_ids']


def test_noncore_concepts_are_preserved_in_extension_or_deferred_registry():
    objects = load('object_type_registry')['objects']
    review = load('link_type_registry')['design1_review']
    expected = {('OBJECT_TYPE',r['item_id']) for r in objects if r['disposition']!='CORE_OBJECT_TYPE'}
    expected |= {('LINK_TYPE',r['predicate_id']) for r in review if r['predicate_id'] not in links()}
    rows = load('extension_registry')['items'] + load('deferred_registry')['items']
    actual = {(r['item_type'],r['item_id']) for r in rows}
    assert actual == expected and len(actual)==len(rows)
    assert all(r['disposition']=='EXTENSION' for r in load('extension_registry')['items'])


def test_original_77_cqs_remain_verbatim_with_individual_classification():
    old = json.loads((OLD/'competency_question_coverage.json').read_text())['questions']
    new = load('competency_question_coverage')['questions']
    by = {r['competency_question_id']:r for r in new}
    assert len(by)==len(new)
    assert len(old)==77
    assert all(by[r['competency_question_id']]['question']==r['question'] for r in old)
    valid = {'ANSWERABLE_BY_CORE','ANSWERABLE_BY_EXTENSION','PARTIALLY_ANSWERABLE','DEFERRED','OUT_OF_SCOPE'}
    all_types = {r['item_id'] for r in load('object_type_registry')['objects']}
    for row in new:
        assert row['coverage'] in valid and row['reason']
        assert set(row['required_object_types']) <= all_types
        assert set(row['required_link_types']) <= links().keys()
        if row['coverage']=='ANSWERABLE_BY_CORE':
            assert set(row['required_object_types']) <= object_types().keys()
    cq_ids = by.keys()
    for row in list(object_types().values()) + list(links().values()):
        assert set(row['supporting_cq_ids']) <= cq_ids


def test_counts_are_computed_not_design1_counts_relabelled():
    m=load('manifest')['counts']; c=load('competency_question_coverage')
    assert m['core_object_types']==len(object_types())<45
    assert m['core_link_types']==sum(r['classification']=='AUTHORITATIVE' for r in links().values())<46
    assert m['properties']==len(properties()) and m['qualifiers']==len(qualifier_ids())
    assert c['question_count']==len(c['questions'])==sum(c['coverage_counts'].values())
    assert m['cq_coverage']==c['coverage_counts']


def test_human_packet_is_complete_and_all_decisions_blank():
    with (CORE/'ontology_v2_core_human_review.csv').open(newline='') as f:
        reader=csv.DictReader(f); rows=list(reader)
    assert reader.fieldnames==['item_type','item_id','module','definition','design1_status','proposed_5c_status','reason','competency_questions','human_decision','human_notes']
    assert all(not r['human_decision'] and not r['human_notes'] for r in rows)
    assert len({(r['item_type'],r['item_id']) for r in rows})==len(rows)
    assert {r['item_id'] for r in rows if r['item_type']=='OBJECT_TYPE'}=={r['item_id'] for r in load('object_type_registry')['objects']}
    assert {r['item_id'] for r in rows if r['item_type']=='LINK_TYPE'}==links().keys()|{r['predicate_id'] for r in load('link_type_registry')['design1_review']}


def test_generator_examples_use_real_type_specific_ids():
    graph=json.loads((ROOT/'data/evidence_candidates/scientific_kg_v1_inventory/scientific_kg_v1_consolidated_graph.json').read_text())
    nodes={n['graph_node_id']:n for n in graph['nodes']}
    for row in load('object_type_registry')['example_audit']:
        node=nodes[row['source_graph_node_id']]
        assert node['record_type']==row['item_id']
        assert node['record'][row['actual_identity_field']]==row['verified_example']
        if row['item_id']!='ApplicabilityScope': assert not row['verified_example'].startswith('scope:')


@pytest.mark.parametrize('group', ['production_ontology','scientific_kg','catalog_kg','decision_graph','rag','planner','contracts','capability_packs','gold','protected_source','design1'])
def test_protected_assets_unchanged_including_added_or_deleted_files(group):
    expected=load('manifest')['baseline']['groups'][group]
    assert tree_hashes(expected['roots'])==expected['files'], group


def test_delivery_hashes_and_stop_boundary():
    m=load('manifest')
    assert not m['production_migration'] and not m['checkpoint_5d_started']
    assert m['next_recommended_action']=='STOP_FOR_QA_RECHECK'
    assert m['human_review_status']=='PENDING'
    expected={p.name for p in CORE.iterdir() if p.is_file() and p.name!='manifest.json'}
    assert set(m['artifacts'])==expected
    for name,digest in m['artifacts'].items():
        assert hashlib.sha256((CORE/name).read_bytes()).hexdigest()==digest
    assert len(m['documents'])==4
    for name,digest in m['documents'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest


@pytest.mark.parametrize('a,b', [('PackageRelease','Package'),('OperatorRevision','Operator'),('SourceRevision','SourceWork'),('StatementRevision','ScientificStatement')])
def test_revision_identity_families_positive(a,b):
    validate_link('revision_of',a,b)


@pytest.mark.parametrize('a,b', [('SourceRevision','PackageRelease'),('SourceRevision','Package'),('OperatorRevision','SourceWork'),('StatementRevision','StatementRevision')])
def test_revision_identity_families_negative(a,b):
    with pytest.raises(ValueError,match='endpoint'): validate_link('revision_of',a,b)


def test_entity_first_domain_and_projection_rejection():
    validate_link('applicable_to','Method','ApplicabilityScope',as_statement=True)
    with pytest.raises(ValueError,match='endpoint'):
        validate_link('applicable_to','ScientificStatement','ApplicabilityScope',as_statement=True)
    with pytest.raises(ValueError,match='authoritative'):
        validate_link('produces','OperatorRevision','RepresentationType',as_statement=True)
    with pytest.raises(ValueError,match='unknown'):
        validate_link('normalizes','OperatorRevision','RepresentationType')


def test_scope_conflict_unknown_and_predicate_specific_rejection():
    assert validate_context({'assay':'a'},{'assay':'a'},'explicit',['assay'],terms={'assay':['a','b']})=={'assay':'a'}
    assert validate_context({}, {}, 'unknown', [])=={}
    with pytest.raises(ValueError,match='scope conflict'):
        validate_context({'assay':'a'},{'assay':'b'},'explicit',['assay'],terms={'assay':['a','b']})
    with pytest.raises(ValueError,match='context forbidden'):
        validate_context({'assay':'a'},{},'unknown',['assay'],terms={'assay':['a','b']})
    with pytest.raises(ValueError,match='qualifier forbidden'):
        validate_link('revision_of','SourceRevision','SourceWork',qualifiers={'assay':'a'})


def test_positive_negative_statements_and_literal_union():
    entities={'s':'ScientificStatement','op':'OperatorRevision','method':'Method','type':'RepresentationType'}
    r={'statement_revision_id':'r1','statement_id':'s','subject_id':'op','predicate':'implements_method','object_id':'method','polarity':'POSITIVE','qualifiers':{},'scope_status':'unknown','epistemic_status':'asserted','schema_version':'design','ontology_version':'design','assertion_kind':'capability'}
    validate_statement(r,entities)
    validate_statement({**r,'polarity':'NEGATIVE'},entities)
    with pytest.raises(ValueError,match='object XOR'):
        validate_statement({**r,'literal_value':{'datatype':'boolean','value':True}},entities)
    with pytest.raises(ValueError,match='endpoint'):
        validate_statement({**r,'object_id':'missing'},entities)
    literal={**r,'subject_id':'type','predicate':'is_sparse','literal_value':{'datatype':'boolean','value':True}}
    del literal['object_id']
    validate_statement(literal,entities)
    with pytest.raises(ValueError,match='literal value'):
        validate_statement({**literal,'literal_value':{'datatype':'boolean','value':'true'}},entities)
    with pytest.raises(ValueError,match='missing statement'):
        validate_statement({k:v for k,v in r.items() if k!='statement_id'},entities)


def test_span_exact_hash_locator_and_forbidden_semantics():
    text='  exact excerpt\n'
    r={'evidence_span_id':'e','source_revision_id':'sr','source_artifact_id':'sa','exact_text':text,'content_hash':hashlib.sha256(text.encode()).hexdigest(),'locator':{'kind':'section','value':'Methods/2'},'schema_version':'design'}
    validate_span(r)  # HTML/API source needs no fabricated page.
    with pytest.raises(ValueError,match='non-excerpt'):
        validate_span({**r,'review_status':'trusted'})
    with pytest.raises(ValueError,match='exact text hash'):
        validate_span({**r,'exact_text':text.strip()})
    with pytest.raises(ValueError,match='PDF page'):
        validate_span({**r,'locator':{'kind':'pdf_page','value':'page 1'}})
    with pytest.raises(ValueError,match='offset pair'):
        validate_span({**r,'start_offset':2})


def test_simultaneous_support_contradiction_and_fail_closed_alignment():
    base={'assessment_id':'a','statement_revision_id':'s','evidence_span_id':'e1','support_type':'DIRECT_SUPPORT','assessment_method':'synthetic-test','assessor_ref':'test-agent','created_at':'2026-09-20T00:00:00Z','status':'completed','subject_aligned':True,'predicate_aligned':True,'object_aligned':True,'scope_alignment':'aligned','rationale':'synthetic fixture only'}
    records=[base,{**base,'assessment_id':'b','evidence_span_id':'e2','support_type':'CONTRADICTS'}]
    for r in records: validate_assessment(r,{'s'},{'e1','e2'})
    assert {r['support_type'] for r in records}=={'DIRECT_SUPPORT','CONTRADICTS'}
    with pytest.raises(ValueError,match='alignment'):
        validate_assessment({**base,'scope_alignment':'narrower'},{'s'},{'e1'})
    with pytest.raises(ValueError,match='dangling'):
        validate_assessment({**base,'evidence_span_id':'missing'},{'s'},{'e1'})
    with pytest.raises(ValueError,match='confidence'):
        validate_assessment({**base,'confidence':float('nan')},{'s'},{'e1'})


def validate_numeric_constraints(rows):
    """Check synthetic interval consistency for one field/unit, without coercion."""
    groups = {}
    shape = load('property_registry')['embedded_value_shapes']['numeric_constraint']
    for r in rows:
        if not set(shape['required']) <= r.keys() or r['operator'] not in shape['operator']:
            raise ValueError('numeric shape')
        v = r['value']
        if r['datatype'] not in shape['datatype'] or type(v) not in {int, float} or not math.isfinite(v):
            raise ValueError('finite numeric datatype')
        if r['datatype'] == 'integer' and type(v) is not int:
            raise ValueError('integer datatype')
        groups.setdefault((r['field'], r.get('unit')), []).append(r)
    for group in groups.values():
        lower, upper = -math.inf, math.inf
        lower_closed = upper_closed = True
        for r in group:
            v, op = r['value'], r['operator']
            if op in {'ge', 'gt', 'eq'}:
                closed = op != 'gt'
                if v > lower: lower, lower_closed = v, closed
                elif v == lower: lower_closed = lower_closed and closed
            if op in {'le', 'lt', 'eq'}:
                closed = op != 'lt'
                if v < upper: upper, upper_closed = v, closed
                elif v == upper: upper_closed = upper_closed and closed
        if lower > upper or lower == upper and not (lower_closed and upper_closed):
            raise ValueError('contradictory bounds')


def test_numeric_constraints_preserve_type_unit_and_consistency():
    low={'field':'synthetic_count','operator':'ge','value':3,'datatype':'integer','unit':'items'}
    high={**low,'operator':'lt','value':7}
    validate_numeric_constraints([low,high])
    with pytest.raises(ValueError,match='contradictory'):
        validate_numeric_constraints([low,{**high,'value':3}])
    with pytest.raises(ValueError,match='datatype'):
        validate_numeric_constraints([{**low,'value':True}])
    with pytest.raises(ValueError,match='datatype'):
        validate_numeric_constraints([{**low,'value':float('inf')}])
    assert load('object_type_registry')['structural_constraints']['numeric_constraints']


def test_source_and_operator_identity_chains_reject_cross_family_bindings():
    def validate_chains(op_revision, span, operator_packages, release_packages, artifact_revisions):
        if operator_packages[op_revision['operator_id']] != release_packages[op_revision['package_release_id']]:
            raise ValueError('release package mismatch')
        if artifact_revisions[span['source_artifact_id']] != span['source_revision_id']:
            raise ValueError('source revision mismatch')
    op={'operator_id':'op-a','package_release_id':'release-a'}
    span={'source_artifact_id':'artifact-a','source_revision_id':'source-a'}
    pkgs={'op-a':'package-a'}; releases={'release-a':'package-a','release-b':'package-b'}
    artifacts={'artifact-a':'source-a'}
    validate_chains(op,span,pkgs,releases,artifacts)
    with pytest.raises(ValueError,match='package mismatch'):
        validate_chains({**op,'package_release_id':'release-b'},span,pkgs,releases,artifacts)
    with pytest.raises(ValueError,match='source revision mismatch'):
        validate_chains(op,{**span,'source_revision_id':'source-b'},pkgs,releases,artifacts)
    rules=load('object_type_registry')['structural_constraints']
    assert rules['release_family'] and rules['source_binding'] and rules['port_ownership']


def test_mapping_and_review_packet_do_not_disagree_with_dispositions():
    canonical={r['predicate_id']:r for r in load('link_type_registry')['design1_review']}
    for r in load('v1_v2_mapping_draft')['predicate_dispositions']:
        for key in ('disposition','replacement','reason'):
            assert r[key]==canonical[r['predicate_id']][key]
    with (CORE/'ontology_v2_core_human_review.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            if r['item_type']=='LINK_TYPE' and r['item_id'] in canonical:
                expected=canonical[r['item_id']]
                assert r['proposed_5c_status']==expected['disposition']
                assert r['definition']==expected['definition'] and r['reason']==expected['reason']


@pytest.fixture
def semantic_context():
    resources={
        's':'ScientificStatement', 'method':'Method', 'type':'RepresentationType',
        'operator':{'record_type':'Operator','package_id':'package'},
        'op':{'record_type':'OperatorRevision','operator_id':'operator','package_release_id':'release','version':'1.2.0'},
        'op-other':{'record_type':'OperatorRevision','operator_id':'operator','version':'1.2.0'},
        'release':{'record_type':'PackageRelease','version':'1.2.0'},
        'source':{'record_type':'SourceRevision','version':'1.2.0'},
        'constraint':'RepresentationConstraint',
        'reference':'ReferenceArtifact',
        'reference-rev':{'record_type':'ReferenceArtifactRevision','artifact_id':'reference','version':'1.0.0','content_hash':'a'*64},
        'output':'OutputPort', 'requirement':'Requirement'}
    parameters={'p':{'owner_operator_id':'operator','allowed_operator_revision_ids':['op'],'datatype':'integer','unit':'items'},
                'flavor':{'owner_operator_id':'operator','allowed_operator_revision_ids':['op'],'datatype':'string','unit':None,'allowed_values':['a','b']}}
    return {'resources':resources,'parameters':parameters,'subject_id':'op'}


def example_condition():
    return {'parameter_id':'p','operator':'equals','datatype':'integer','values':[3],'unit':'items'}


def example_requirement(**changes):
    return {'strength':'REQUIRED','activation_status':'unknown','combination':'ALL_OF','targets':['constraint'],**changes}


def example_statement(**changes):
    return {'record_type':'StatementRevision','statement_revision_id':'r','statement_id':'s','subject_id':'op','predicate':'implements_method','object_id':'method','polarity':'POSITIVE','qualifiers':{},'scope_status':'unknown','epistemic_status':'asserted','schema_version':'design','ontology_version':'design','assertion_kind':'capability',**changes}


@pytest.mark.parametrize('strength',['REQUIRED','RECOMMENDED','OPTIONAL','DISCOURAGED'])
@pytest.mark.parametrize('status',['unknown','unconditional','specified'])
def test_n01_strength_condition_orthogonality(strength,status,semantic_context):
    when=[example_condition()] if status=='specified' else []
    row=example_requirement(strength=strength,activation_status=status,when=when)
    result=validate_requirement(row,**semantic_context)
    assert row['strength']==strength
    assert result=={'unknown':None,'unconditional':'unconditional','specified':'conditioned'}[status]
    assert 'CONDITIONAL' not in properties()['strength']['enum']
    assert 'level' not in properties()


@pytest.mark.parametrize('changes,reason',[
    ({'strength':'CONDITIONAL'},'strength'), ({'strength':'requires_input'},'strength'),
    ({'activation_status':None},'activation'),
    ({'activation_status':'specified','when':[]},'activation'),
    ({'activation_status':'unconditional','when':[example_condition()]},'activation'),
    ({'when':{}},'activation'),
    ({'activation_status':'specified','when':['not-a-condition']},'activation'),
    ({'level':'REQUIRED'},'legacy level')])
def test_n01_n05_invalid_strength_or_activation_rejected(changes,reason,semantic_context):
    with pytest.raises(ValueError,match=reason):validate_requirement(example_requirement(**changes),**semantic_context)


@pytest.mark.parametrize('targets',[['constraint'],['reference-rev'],['constraint','reference-rev']])
@pytest.mark.parametrize('combination',['ALL_OF','ANY_OF'])
def test_n02_representation_reference_and_mixed_requirements(targets,combination,semantic_context):
    validate_requirement(example_requirement(targets=targets,combination=combination),**semantic_context)
    validate_link('revision_of','ReferenceArtifactRevision','ReferenceArtifact')
    assert set(object_types()['Requirement']['required_link_groups'][0]['any_of'])=={'requires_constraint','requires_reference'}
    assert object_types()['Requirement']['required_links']==[]


@pytest.mark.parametrize('target',['reference','source','release','absent'])
def test_n02_invalid_reference_target_family_rejected(target,semantic_context):
    with pytest.raises(ValueError,match='target/reference family'):
        validate_requirement(example_requirement(targets=[target]),**semantic_context)


def test_n02_reference_pin_and_identity_must_resolve(semantic_context):
    resources=semantic_context['resources']
    for changes,reason in [({'artifact_id':'release'},'family'),({'content_hash':'bad'},'digest'),({'version':''},'pin')]:
        with pytest.raises(ValueError,match=reason):
            validate_reference_revision({**resources['reference-rev'],**changes},resources)
    with pytest.raises(ValueError,match='at least one'):
        validate_requirement(example_requirement(targets=[]),**semantic_context)
    with pytest.raises(ValueError,match='combination'):
        validate_requirement(example_requirement(combination='XOR'),**semantic_context)


def test_n03_effect_description_is_display_only_and_cannot_satisfy_gate(semantic_context):
    prop=properties()['effect_description']
    assert prop['assertion_allowed'] is False and prop['decision_gate_allowed'] is False
    assert set(prop['forbidden_uses'])=={'Planner gate','blocking','applicability decision','capability authorization','derived scientific truth','trusted statement projection'}
    record=example_statement(subject_id='output',predicate='effect_description',literal_value={'datatype':'string','value':'invalidate downstream graph'})
    record.pop('object_id')
    with pytest.raises(ValueError,match='assertion forbidden'):
        validate_statement(record,semantic_context['resources'])
    with pytest.raises(ValueError,match='requires StatementRevision'):
        validate_effect_evidence({'record_type':'OutputPort','effect_description':'block this run'})


def test_n03_machine_readable_effect_requires_statement_and_assessment_without_authorization(semantic_context):
    record=example_statement(predicate='has_requirement',object_id='requirement',assertion_kind='requirement')
    with pytest.raises(ValueError,match='requires EvidenceAssessment'):
        validate_effect_evidence(record,entities=semantic_context['resources'])
    assessment={'assessment_id':'a','statement_revision_id':'r','evidence_span_id':'e','support_type':'DIRECT_SUPPORT','assessment_method':'synthetic','assessor_ref':'test','created_at':'2026-09-20T00:00:00Z','status':'completed','subject_aligned':True,'predicate_aligned':True,'object_aligned':True,'scope_alignment':'aligned','rationale':'synthetic only'}
    result=validate_effect_evidence(record,entities=semantic_context['resources'],assessments=[assessment])
    assert result=={'required_evidence_structure_valid':True,'decision_authorized':False}


def example_scope(combination='ALL_OF',**changes):
    return {'id':'scope-a','scope_status':'explicit','combination':combination,'qualifiers':{'assay':'a','observation_unit':'cell'},**changes}


@pytest.mark.parametrize('combination,expected',[('ALL_OF',False),('ANY_OF',True)])
def test_n04_preserve_all_of_any_of_not_interchangeable(combination,expected):
    expression=combine_scope({},example_scope(combination),['assay','observation_unit'],terms={'assay':['a','b']})
    assert expression['shared']['combination']==combination
    actual=scope_truth(expression,{'assay':'b','observation_unit':'cell'})
    assert actual is expected
    assert actual is not (not expected)  # Reject swapping AND/OR for this distinguishing case.


def test_n04_duplicate_scope_values_deduplicate_without_flattening_any_of():
    expression=combine_scope({'assay':'a'},example_scope('ANY_OF'),['assay','observation_unit'],terms={'assay':['a','b']})
    assert expression['inline']=={}
    assert expression['shared']['qualifiers']['assay']=='a'
    assert scope_truth(expression,{'assay':'b','observation_unit':'cell'}) is True
    with pytest.raises(ValueError,match='scope conflict'):
        combine_scope({'assay':'b'},example_scope('ANY_OF'),['assay','observation_unit'],terms={'assay':['a','b']})


def test_n04_inline_new_dimension_is_conjoined_outside_shared_any_of():
    expression=combine_scope({'organism_taxon':'NCBITaxon:9606'},example_scope('ANY_OF'),['assay','observation_unit','organism_taxon'],terms={'assay':['a','b']})
    assert scope_truth(expression,{'assay':'b','observation_unit':'cell','organism_taxon':'NCBITaxon:10090'}) is False
    assert scope_truth(expression,{'assay':'b','observation_unit':'cell'}) is None


def test_n04_shared_status_is_validated_at_statement_boundary(semantic_context):
    statement=example_statement(predicate='has_requirement',object_id='requirement',scope_status='explicit',scope_ref='scope-a')
    with pytest.raises(ValueError,match='context forbidden'):
        validate_statement(statement,semantic_context['resources'],{'scope-a':example_scope(scope_status='unknown')},terms={'assay':['a']})
    with pytest.raises(ValueError,match='scope combination'):
        validate_statement(statement,semantic_context['resources'],{'scope-a':example_scope('XOR')},terms={'assay':['a']})


def test_n04_unknown_partial_and_immutable_scope_semantics():
    allowed=['assay','observation_unit'];terms={'assay':['a']}
    unknown=example_scope(scope_status='unknown',qualifiers={})
    expr=combine_scope({},unknown,allowed,terms=terms)
    assert scope_truth(expr,{'assay':'a','observation_unit':'cell'}) is None
    partial=example_scope(scope_status='partially_known',qualifiers={'assay':'a'},unknown_dimensions=['observation_unit'])
    expr=combine_scope({},partial,allowed,terms=terms)
    assert scope_truth(expr,{'assay':'a'}) is None
    with pytest.raises(ValueError,match='partial scope'):
        validate_shared_scope({k:v for k,v in partial.items() if k!='unknown_dimensions'},allowed,terms=terms)
    with pytest.raises(ValueError,match='immutable scope'):
        validate_shared_scope(example_scope('ANY_OF'),allowed,previous=example_scope(),terms=terms)
    validate_shared_scope(example_scope('ANY_OF',id='scope-b'),allowed,previous=example_scope(),terms=terms)


@pytest.mark.parametrize('changes,reason',[
    ({'epistemic_status':'trusted'},'epistemic_status'),
    ({'assertion_kind':'arbitrary_effect'},'assertion_kind'),
    ({'polarity':'MAYBE'},'polarity'),
    ({'literal_value':{'datatype':'string','value':'also'}},'object XOR'),
    ({'object_id':None},'object XOR')])
def test_n05_statement_semantic_negatives(changes,reason,semantic_context):
    with pytest.raises(ValueError,match=reason):validate_statement(example_statement(**changes),semantic_context['resources'])


@pytest.mark.parametrize('changes,reason',[
    ({'parameter_id':'missing'},'unknown ParameterDefinition'),
    ({'operator':'greater-ish'},'comparison operator'),
    ({'datatype':'float32'},'datatype'),
    ({'values':['3']},'datatype/value'),
    ({'values':[True]},'datatype/value'),
    ({'unit':'seconds'},'unit/value'),
    ({'unit':None},'unit/value'),
    ({'values':[]},'comparison values'),
    ({'operator':'present'},'present condition')])
def test_n05_invalid_parameter_condition_rejected(changes,reason,semantic_context):
    with pytest.raises(ValueError,match=reason):
        validate_parameter_condition({**example_condition(),**changes},**semantic_context)


def test_n05_parameter_revision_ownership_and_controlled_values(semantic_context):
    with pytest.raises(ValueError,match='wrong OperatorRevision'):
        validate_parameter_condition(example_condition(),**{**semantic_context,'subject_id':'op-other'})
    validate_parameter_condition({'parameter_id':'p','operator':'present'},**semantic_context)
    validate_parameter_condition({'parameter_id':'flavor','operator':'in','datatype':'string','values':['a','b']},**semantic_context)
    with pytest.raises(ValueError,match='enum'):
        validate_parameter_condition({'parameter_id':'flavor','operator':'equals','datatype':'string','values':['c']},**semantic_context)


@pytest.mark.parametrize('value,reason',[
    ({'subject_id':'op','status':'latest'},'version state'),
    ({'subject_id':'op','status':'exact','expression':'latest'},'version pin'),
    ({'subject_id':'op','status':'exact','expression':'1.*'},'version pin'),
    ({'subject_id':'op','status':'exact','expression':'1.3.0'},'pin conflicts'),
    ({'subject_id':'op','status':'range','expression':'[1,2]'},'version pin'),
    ({'subject_id':'source','status':'exact','expression':'1.2.0'},'cross-family'),
    ({'subject_id':'op-other','status':'exact','expression':'1.2.0'},'unrelated version'),
    ({'subject_id':'op','status':'unknown','expression':'1.2.0'},'forbids pin'),
    ({'subject_id':'op','status':'exact'},'version pin')])
def test_n05_invalid_version_conditions_rejected(value,reason,semantic_context):
    with pytest.raises(ValueError,match=reason):
        validate_version_condition(value,'software_version',resources=semantic_context['resources'],subject_id='op')


def test_n05_valid_version_condition_shapes(semantic_context):
    for value in [
        {'subject_id':'op','status':'exact','expression':'1.2.0'},
        {'subject_id':'release','status':'range','expression':'>=1.0.0,<2.0.0'},
        {'subject_id':'op','status':'unknown'}]:
        validate_version_condition(value,'software_version',resources=semantic_context['resources'],subject_id='op')


@pytest.mark.parametrize('value,reason',[
    ({'observation_unit':'galaxy'},'enum'),
    ({'observation_unit':['cell']},'value shape'),
    ({'assay':'unregistered'},'enum'),
    ({'organism_taxon':'human'},'taxon'),
    ({'parameter_condition':'p=3'},'activation condition shape'),
    ({'software_version':'1.2.0'},'version condition shape')])
def test_n05_qualifier_allowed_name_invalid_value_is_rejected(value,reason,semantic_context):
    with pytest.raises(ValueError,match=reason):
        validate_qualifiers(value,list(value),**semantic_context,terms={'assay':['a']})


def test_n05_parameter_and_qualifier_validation_cannot_be_bypassed_by_statement(semantic_context):
    for value,reason in [({'parameter_condition':{**example_condition(),'unit':'seconds'}},'unit/value'),
                         ({'software_version':{'subject_id':'source','status':'unknown'}},'cross-family'),
                         ({'flavor':{'unexpected':'dict'}},'value shape')]:
        with pytest.raises(ValueError,match=reason):
            validate_statement(example_statement(qualifiers=value,scope_status='explicit'),semantic_context['resources'],parameters=semantic_context['parameters'])


def test_n01_n05_requirement_condition_validation_cannot_be_bypassed(semantic_context):
    with pytest.raises(ValueError,match='unknown ParameterDefinition'):
        validate_requirement(example_requirement(activation_status='specified',when=[{**example_condition(),'parameter_id':'missing'}]),**semantic_context)
