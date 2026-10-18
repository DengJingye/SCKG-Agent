"""Read-only, source-bound configuration checks beside the v1 input catalog.

Rules are explicit developer interpretations, not inferred scientific facts.
They never promote candidates, measure inputs, execute tools or call models.
The existing input/chat contracts and historical hashes are left unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from .contracts import Contract
from .storage import canonical_json, content_hash
from .workflow_inputs import (Digest, Identifier, Label, SourceInputBinding,
                              WorkflowInputService)


class WorkflowMethodError(ValueError):
    pass


Scalar = StrictBool | StrictInt | str


class CatalogReference(Contract):
    record_id: str = Field(min_length=1, max_length=180)
    catalog_hash: Digest


class Visibility(Contract):
    field_id: Identifier
    value: Scalar


class ReportField(Contract):
    field_id: Identifier
    label: Label
    scope: Literal['method', 'protocol']
    kind: Literal['boolean', 'integer', 'choice']
    choices: list[Label] = Field(max_length=12)
    show_when: Visibility | None

    @model_validator(mode='after')
    def valid_choices(self):
        if ((self.kind == 'choice') != bool(self.choices)
                or len(set(self.choices)) != len(self.choices)):
            raise ValueError('Only choice fields have distinct nonempty choices')
        return self


class Atom(Contract):
    field_id: Identifier
    op: Literal['eq', 'gt']
    value: Scalar | None
    other_field: Identifier | None

    @model_validator(mode='after')
    def rhs(self):
        if (self.value is None) == (self.other_field is None):
            raise ValueError('An atom needs exactly one literal or field operand')
        if self.op == 'eq' and self.other_field is not None:
            raise ValueError('Equality uses an explicit typed literal')
        return self


class Expression(Contract):
    mode: Literal['all', 'any']
    atoms: list[Atom] = Field(min_length=1, max_length=4)


class MethodSourceBinding(SourceInputBinding):
    attribute_kind: Literal['workflow.input', 'workflow.action', 'workflow.limit', 'workflow.validation']


class MethodRule(Contract):
    rule_id: Identifier
    label: Label
    kind: Literal['precondition', 'option_scope', 'advisory']
    when: Expression | None
    expect: Expression | None
    reported_requirement_id: Identifier | None
    source_bindings: list[MethodSourceBinding] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def role(self):
        if (self.kind == 'advisory') != (self.expect is None):
            raise ValueError('Advisories have no assertion; other rules require one')
        allowed = {'precondition': {'workflow.input'},
                   'option_scope': {'workflow.action', 'workflow.limit'},
                   'advisory': {'workflow.action', 'workflow.limit', 'workflow.validation'}}[self.kind]
        if any(b.attribute_kind not in allowed for b in self.source_bindings):
            raise ValueError('Source attribute role does not match the rule role')
        if self.reported_requirement_id is not None and self.kind != 'precondition':
            raise ValueError('Only input preconditions can reconcile an existing input report')
        return self


class ProtocolCheck(Contract):
    rule_id: Identifier
    label: Label
    protocol_rule_id: Identifier
    expect: Expression


class MethodRoute(Contract):
    route_id: Identifier
    method_scope: Label
    version_scope: Label
    rules: list[MethodRule] = Field(max_length=8)
    local_policy_checks: list[ProtocolCheck] = Field(max_length=4)


class WorkflowMethodCatalog(Contract):
    schema_version: Literal['development-workflow-method-catalog-v1']
    authority: Literal['developer_source_interpretation_not_human_review']
    base_catalog: CatalogReference
    protocol: CatalogReference | None
    fields: list[ReportField] = Field(max_length=24)
    routes: list[MethodRoute] = Field(min_length=1, max_length=12)

    @model_validator(mode='after')
    def bindings(self):
        fields = {f.field_id: f for f in self.fields}
        if len(fields) != len(self.fields) or len({r.route_id for r in self.routes}) != len(self.routes):
            raise ValueError('Field and route identifiers must be distinct')
        for field in self.fields:
            if field.show_when is not None:
                parent = fields.get(field.show_when.field_id)
                if (parent is None or parent.scope != field.scope or parent.show_when is not None
                        or not _typed_value(parent, field.show_when.value)):
                    raise ValueError('Visibility needs a typed, unconditional controller in the same scope')
        for route in self.routes:
            ids = [r.rule_id for r in route.rules] + [r.rule_id for r in route.local_policy_checks]
            if len(set(ids)) != len(ids):
                raise ValueError('Rule identifiers must be distinct within each route')
            if route.local_policy_checks and self.protocol is None:
                raise ValueError('Local checks need a separately bound investigator protocol')
            for rule in route.rules:
                for expression in (rule.when, rule.expect):
                    _validate_expression(expression, fields, 'method')
            for rule in route.local_policy_checks:
                _validate_expression(rule.expect, fields, 'protocol')
        return self


def _typed_value(field, value):
    return ((field.kind == 'boolean' and type(value) is bool)
        or (field.kind == 'integer' and type(value) is int and 0 <= value <= 10_000_000)
        or (field.kind == 'choice' and type(value) is str and value in field.choices))


def _validate_expression(expression, fields, scope):
    if expression is None:
        return
    for atom in expression.atoms:
        field = fields.get(atom.field_id)
        if field is None or field.scope != scope:
            raise ValueError('Rule fields must exist in their declared authority scope')
        if atom.other_field is not None:
            other = fields.get(atom.other_field)
            if other is None or other.scope != scope or other.kind != 'integer' or field.kind != 'integer':
                raise ValueError('Numeric comparisons need two integer fields in the same scope')
        elif not _typed_value(field, atom.value):
            raise ValueError('Rule literal does not match its field type')
        if atom.op == 'gt' and field.kind != 'integer':
            raise ValueError('Greater-than is limited to bounded integer reports')


def _predicate(expression, values):
    if expression is None:
        return True, []
    outcomes, missing = [], []
    for atom in expression['atoms']:
        left = values.get(atom['field_id'])
        right = values.get(atom['other_field']) if atom['other_field'] is not None else atom['value']
        if left is None or right is None:
            outcomes.append(None)
            missing.extend([key for key in [atom['field_id'], atom['other_field']]
                if key is not None and values.get(key) is None])
        else:
            outcomes.append(left == right if atom['op'] == 'eq' else left > right)
    if expression['mode'] == 'all':
        outcome = False if False in outcomes else (None if None in outcomes else True)
    else:
        outcome = True if True in outcomes else (None if None in outcomes else False)
    return outcome, list(dict.fromkeys(missing)) if outcome is None else []


class WorkflowMethodService:
    def __init__(self, ledger, catalog, *, expected_catalog_hash):
        value = WorkflowMethodCatalog.model_validate(catalog).model_dump(mode='json')
        if content_hash(value) != expected_catalog_hash:
            raise WorkflowMethodError('Method catalog changed')
        self.ledger, self.catalog_hash = ledger, expected_catalog_hash
        self._catalog = canonical_json(value)
        self._configured_reference = None
        base = value['base_catalog']
        # This explicit record binding is independent of the legacy chat's
        # active input-catalog pointer. Adding methods must not expand or
        # silently replace an already qualified conversation's context.
        record = ledger.get_record('workflow_input_catalog', base['record_id'])
        if (not record or record.get('id') != base['record_id']
                or record.get('catalog_hash') != base['catalog_hash']):
            raise WorkflowMethodError('Bound input catalog is absent or changed')
        self.inputs = WorkflowInputService(ledger, record['catalog'], expected_catalog_hash=base['catalog_hash'])
        routes = {r['route_id']: r for r in self.inputs.catalog['routes']}
        for route in value['routes']:
            if route['route_id'] not in routes:
                raise WorkflowMethodError('Method route is absent from the bound input catalog')
            requirements = {r['requirement_id']: r for r in routes[route['route_id']]['requirements']}
            for rule in route['rules']:
                rid = rule['reported_requirement_id']
                if rid is not None:
                    def identity(binding):
                        return tuple(binding[k] for k in ('candidate_id', 'candidate_hash', 'attribute_index', 'attribute_hash'))
                    if (rid not in requirements or not {identity(b) for b in rule['source_bindings']}.intersection(
                            identity(b) for b in requirements[rid]['source_bindings'])):
                        raise WorkflowMethodError('Report reconciliation needs the same source input attribute')

    @property
    def catalog(self):
        return json.loads(self._catalog)

    def _protocol(self, catalog, conn):
        ref = catalog['protocol']
        if ref is None:
            return None
        record = self.ledger.get_record('workflow_local_protocol', ref['record_id'], conn=conn)
        if (not record or record.get('id') != ref['record_id']
                or record.get('protocol_hash') != ref['catalog_hash']
                or content_hash(record.get('protocol')) != ref['catalog_hash']
                or record['protocol'].get('authority') != 'investigator_experimental_protocol_not_literature_claim'):
            raise WorkflowMethodError('Separate investigator protocol binding changed')
        rules = record['protocol'].get('rules')
        if not isinstance(rules, list) or any(not isinstance(r, dict) or not isinstance(r.get('rule_id'), str) for r in rules):
            raise WorkflowMethodError('Investigator protocol rules are invalid')
        if len({r['rule_id'] for r in rules}) != len(rules):
            raise WorkflowMethodError('Investigator protocol rule identifiers repeat')
        return deepcopy(record['protocol'])

    def evaluate(self, route_ids, profile, *, include_local_protocol=False):
        if type(include_local_protocol) is not bool:
            raise WorkflowMethodError('Protocol checking must be explicitly selected')
        catalog = self.catalog
        if (not isinstance(route_ids, list) or not 1 <= len(route_ids) <= 4
                or any(type(r) is not str for r in route_ids) or len(set(route_ids)) != len(route_ids)):
            raise WorkflowMethodError('Choose one to four distinct method routes')
        routes = {r['route_id']: r for r in catalog['routes']}
        if any(r not in routes for r in route_ids):
            raise WorkflowMethodError('Method route is absent from the bound catalog')
        if not isinstance(profile, dict) or set(profile) - {'reported_inputs', 'reported_config', 'reported_protocol'}:
            raise WorkflowMethodError('An explicit bounded report profile is required')
        try:
            raw = canonical_json(profile)
        except (TypeError, ValueError):
            raise WorkflowMethodError('Reports must be finite JSON data') from None
        if len(raw.encode()) > 12000:
            raise WorkflowMethodError('Method report exceeds the bounded profile size')
        profile = json.loads(raw)
        fields = {f['field_id']: f for f in catalog['fields']}
        for key, scope in [('reported_config', 'method'), ('reported_protocol', 'protocol')]:
            values = profile.get(key, {})
            if not isinstance(values, dict) or any(k not in fields or fields[k]['scope'] != scope for k in values):
                raise WorkflowMethodError('Unknown or cross-scope report field')
            for key, value in values.items():
                if value is not None and not _typed_value(ReportField.model_validate(fields[key]), value):
                    raise WorkflowMethodError('Report value does not match its explicit field type')
        values = profile.get('reported_config', {})
        protocol_values = profile.get('reported_protocol', {})
        # The existing source/input service owns candidate provenance checks.
        # One read transaction keeps its view and the new rule sources aligned.
        with self.ledger.connect() as conn:
            conn.execute('BEGIN')
            if (self._configured_reference is not None and
                    self.ledger.get_state('workflow_method_catalog', conn=conn) != self._configured_reference):
                raise WorkflowMethodError('Configured method catalog selection changed')
            current = self.ledger.get_record('workflow_input_catalog', catalog['base_catalog']['record_id'], conn=conn)
            if (not current or current.get('catalog') != self.inputs.catalog
                    or current.get('catalog_hash') != self.inputs.catalog_hash):
                raise WorkflowMethodError('Bound input catalog record changed')
            protocol = self._protocol(catalog, conn)
            base = self.inputs.evaluate(route_ids, {'reported_inputs': profile.get('reported_inputs', {})},
                                        _connection=conn)
            results = []
            for input_route in base['route_results']:
                route = routes[input_route['route_id']]
                records = {r['candidate_id']: r for r in input_route['source_records']}
                checks, conflicts = [], []
                for rule in route['rules']:
                    bindings = []
                    for binding in rule['source_bindings']:
                        source = records.get(binding['candidate_id'])
                        if source is None:
                            raise WorkflowMethodError('Rule source is outside its own input route')
                        # Reuse the same integrity/governance validator, within
                        # this transaction; never trust a cached candidate.
                        source = self.inputs._candidate(binding['candidate_id'], conn)
                        attrs = source['claim']['typed_attributes']
                        if binding['attribute_index'] >= len(attrs):
                            raise WorkflowMethodError('Rule source attribute is absent')
                        attr = attrs[binding['attribute_index']]
                        if (source['candidate_hash'] != binding['candidate_hash']
                                or attr['name'] != binding['attribute_kind'] or content_hash(attr) != binding['attribute_hash']):
                            raise WorkflowMethodError('Rule source attribute identity, role or content changed')
                        bindings.append({**binding, 'attribute': deepcopy(attr), 'evidence': [
                            deepcopy(source['evidence'][i]) for i in attr['evidence_anchor_indices']]})
                    active, missing = _predicate(rule['when'], values)
                    truth = None
                    if active is False:
                        status = 'not_applicable'
                    elif active is None:
                        status = 'needs_information'
                    elif rule['kind'] == 'advisory':
                        status = 'advisory'
                    else:
                        truth, missing = _predicate(rule['expect'], values)
                        status = ('needs_information' if truth is None else 'reported_met' if truth else
                            'option_not_applicable' if rule['kind'] == 'option_scope' else 'reported_unmet')
                    rid = rule['reported_requirement_id']
                    if rid is not None and active is True and truth is not None:
                        report = next(r for r in input_route['requirements'] if r['requirement_id'] == rid)
                        if report['reported_value'] is not None and report['reported_value'] != truth:
                            conflicts.append({'rule_id': rule['rule_id'], 'requirement_id': rid,
                                'input_report': report['reported_value'], 'configuration_report_result': truth})
                    checks.append({**deepcopy(rule), 'source_bindings': bindings, 'status': status,
                        'condition_report_result': active, 'assertion_report_result': truth,
                        'missing_field_ids': missing, 'independent_verification': 'not_established'})
                state = input_route['assessment']['decision_check']['preconditions_status']
                if conflicts:
                    decision = 'needs_clarification'
                elif state == 'reported_unmet' or any(c['status'] == 'reported_unmet' for c in checks):
                    decision = 'blocked'
                elif state == 'unknown' or any(c['status'] == 'needs_information' and c['kind'] != 'advisory' for c in checks):
                    decision = 'needs_information'
                else:
                    decision = 'conditional_plan'
                local = []
                for check in route['local_policy_checks'] if include_local_protocol else []:
                    policy = next((r for r in protocol['rules'] if r['rule_id'] == check['protocol_rule_id']), None)
                    if policy is None:
                        raise WorkflowMethodError('Local check is absent from the bound protocol')
                    truth, missing = _predicate(check['expect'], protocol_values)
                    local.append({**deepcopy(check), 'policy': deepcopy(policy), 'reported_result': truth,
                        'status': 'unknown' if truth is None else 'reported_met' if truth else 'reported_unmet',
                        'missing_field_ids': missing})
                protocol_state = ('not_requested' if not include_local_protocol else 'no_route_checks' if not local else
                    'blocked' if any(r['reported_result'] is False for r in local) else
                    'needs_information' if any(r['reported_result'] is None for r in local) else 'reported_met')
                results.append({'route_id': route['route_id'], 'label': input_route['label'],
                    'method_scope': route['method_scope'], 'version_scope': route['version_scope'],
                    'input_review': input_route, 'configuration_checks': checks,
                    'report_conflicts': conflicts, 'method_decision': decision,
                    'local_protocol': {'state': protocol_state, 'checks': local,
                        'authority': 'investigator_experimental_protocol_not_literature_claim'},
                    'requirements_complete': False, 'complete_scientific_applicability_established': False,
                    'local_execution': input_route['local_execution']})
        result = {'schema_version': 'development-workflow-method-review-v1',
            'authority': 'development_candidate_only', 'catalog_hash': self.catalog_hash,
            'base_catalog_hash': self.inputs.catalog_hash, 'namespace': self.ledger.workspace.namespace,
            'input_profile': profile, 'profile_hash': content_hash(profile), 'route_results': results,
            'separate_local_protocol': protocol, 'source_semantics_reassessed': False,
            'report_origin': 'explicit_structured_user_report_not_measurement',
            'recommendation_eligible': False, 'provider_calls': 0, 'scientific_fits': 0}
        return {**result, 'result_hash': content_hash(result)}


def configured_method_service(ledger):
    state = ledger.get_state('workflow_method_catalog')
    if state is None:
        return None
    reference = CatalogReference.model_validate(state).model_dump(mode='json')
    record = ledger.get_record('workflow_method_catalog', reference['record_id'])
    if (not record or record.get('id') != reference['record_id']
            or record.get('catalog_hash') != reference['catalog_hash']):
        raise WorkflowMethodError('Configured method catalog is absent or changed')
    service = WorkflowMethodService(ledger, record['catalog'], expected_catalog_hash=reference['catalog_hash'])
    service._configured_reference = deepcopy(reference)
    return service
