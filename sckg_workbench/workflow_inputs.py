"""Source-bound developer input checks over explicit boolean user reports.

This service never infers assay semantics from file/layer names, judges source
entailment, promotes candidates, calls a model, or grants execution. The mapping
from a source attribute to a report field is an explicit development artifact.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import Contract, OpenClaim
from .evidence_answers import (CompactAssessment, CompactCheck, CompactStepCheck,
    _normalize_compact_assessment, _validate_compact_assessment)
from .external_evidence import _ReadOnlyKnowledge
from .retrieval_planning import _pointer_value, RetrievalPlanningError
from .storage import canonical_json, content_hash


Identifier = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')]
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Label = Annotated[str, Field(min_length=1, max_length=240)]
REPORTED_INPUT_STATE_VERSION = 'reported_input_state_v2'


class WorkflowInputError(ValueError):
    pass


class SourceInputBinding(Contract):
    candidate_id: str = Field(min_length=1, max_length=180)
    candidate_hash: Digest
    attribute_index: int = Field(ge=0)
    attribute_hash: Digest


class ReportedInputRequirement(Contract):
    requirement_id: Identifier
    label: Label
    report_pointer: str = Field(pattern=r'^/reported_inputs/[a-z][a-z0-9_]{0,79}$')
    source_bindings: list[SourceInputBinding] = Field(min_length=1, max_length=3)


class WorkflowInputRoute(Contract):
    route_id: Identifier
    label: Label
    requirements: list[ReportedInputRequirement] = Field(min_length=1, max_length=4)
    context_candidate_ids: list[str] = Field(max_length=8)
    requirements_complete: Literal[False]
    scope_notes: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(max_length=12)

    @model_validator(mode='after')
    def distinct(self):
        ids = [r.requirement_id for r in self.requirements]
        pointers = [r.report_pointer for r in self.requirements]
        if (len(ids) != len(set(ids)) or len(pointers) != len(set(pointers))
                or len(self.context_candidate_ids) != len(set(self.context_candidate_ids))):
            raise ValueError('Route requirements, report pointers and context IDs must be distinct')
        return self


class WorkflowInputCatalog(Contract):
    schema_version: Literal['development-workflow-input-catalog-v1']
    authority: Literal['developer_source_interpretation_not_human_review']
    routes: list[WorkflowInputRoute] = Field(min_length=1, max_length=12)

    @model_validator(mode='after')
    def distinct(self):
        ids = [r.route_id for r in self.routes]
        if len(ids) != len(set(ids)):
            raise ValueError('Workflow route identifiers must be distinct')
        return self


def _check(status, *, review_version=None):
    actions = {'reported_met': 'conditional_plan', 'reported_unmet': 'blocked',
               'unknown': 'needs_evidence'}
    reasons = {'reported_met': '用户报告具备已列输入；未独立测量，也未检查全部科学前提。',
               'reported_unmet': '用户明确报告缺少至少一项已列输入；本路线保持阻断。',
               'unknown': '至少一项已列输入尚未明确报告；需补充信息。'}
    if review_version == REPORTED_INPUT_STATE_VERSION:
        # A present null is a submitted unknown state, not proof of a quote,
        # measured observations, or an absent user report. Text provenance is
        # checked separately by the opt-in workflow conversation adapter.
        reasons['unknown'] = '至少一项已列输入状态未确认；需补充信息。'
    return CompactCheck(f='no_claim', p=status, a=actions[status], r=reasons[status], q=[])


def _aggregate(statuses):
    if 'reported_unmet' in statuses:
        return 'reported_unmet'
    return 'reported_met' if all(s == 'reported_met' for s in statuses) else 'unknown'


class WorkflowInputService:
    """No initializer for knowledge indices; every source is rechecked on use."""

    def __init__(self, ledger, catalog, *, expected_catalog_hash):
        validated = WorkflowInputCatalog.model_validate(catalog).model_dump(mode='json')
        if content_hash(validated) != expected_catalog_hash:
            raise WorkflowInputError('Development workflow catalog changed')
        self.ledger = ledger
        self.knowledge = _ReadOnlyKnowledge(ledger)
        self._catalog_json = canonical_json(validated)
        self.catalog_hash = expected_catalog_hash

    @property
    def catalog(self):
        return json.loads(self._catalog_json)

    def _candidate(self, candidate_id, conn):
        candidate = self.ledger.get_record('candidate', candidate_id, conn=conn)
        if candidate is None or candidate.get('status') != 'candidate':
            raise WorkflowInputError('Unknown development candidate')
        claim = OpenClaim.model_validate(candidate['claim']).model_dump(mode='json')
        payload = {**{k:candidate[k] for k in ('source_ids','source_revision_ids')}, 'claim':claim}
        digest = content_hash(payload)
        if (candidate['id'] != candidate_id or candidate_id != 'candidate-' + digest
                or candidate['content_hash'] != digest or claim['assertion_kind'] != 'source_assertion'):
            raise WorkflowInputError('Candidate identity or source assertion changed')
        if self.knowledge._suspended(candidate, conn):
            raise WorkflowInputError('Candidate or source is currently suspended')
        evidence = self.knowledge._anchors(claim, conn)
        if (sorted({e['source_id'] for e in evidence}) != candidate['source_ids']
                or sorted({e['source_revision_id'] for e in evidence}) != candidate['source_revision_ids']):
            raise WorkflowInputError('Candidate source provenance changed')
        return {'candidate_id':candidate_id, 'candidate_hash':digest,
                'claim':claim, 'evidence':evidence,
                'authority':'development_candidate_only', 'recommendation_eligible':False}

    def evaluate(self, route_ids, reported_profile, *, report_origin='explicit_structured_user_report_not_measurement',
                 review_version=None, _connection=None):
        if review_version not in (None, REPORTED_INPUT_STATE_VERSION):
            raise WorkflowInputError('Unknown reported input review version')
        if report_origin not in {'explicit_structured_user_report_not_measurement',
                                 'model_extracted_user_text_not_independently_verified'}:
            raise WorkflowInputError('Unknown input report origin')
        if (not isinstance(route_ids, list) or not 1 <= len(route_ids) <= 4
                or any(not isinstance(i, str) for i in route_ids)
                or len(set(route_ids)) != len(route_ids)):
            raise WorkflowInputError('Choose one to four distinct declared workflow routes')
        if not isinstance(reported_profile, dict):
            raise WorkflowInputError('An explicit input report dictionary is required')
        try:
            profile_json = canonical_json(reported_profile)
        except (TypeError, ValueError):
            raise WorkflowInputError('Input reports must be finite JSON data') from None
        if len(profile_json.encode()) > 12000:
            raise WorkflowInputError('Input report exceeds the bounded profile size')
        profile = json.loads(profile_json)
        if 'reported_inputs' in profile and not isinstance(profile['reported_inputs'], dict):
            raise WorkflowInputError('reported_inputs must be an explicit dictionary')
        available = {r['route_id']:r for r in self.catalog['routes']}
        if any(r not in available for r in route_ids):
            raise WorkflowInputError('Workflow route is absent from the bound development catalog')
        results = []
        # A composing read-only service may borrow its own read transaction;
        # standalone v1 callers retain the same data contract and behavior.
        with (nullcontext(_connection) if _connection is not None else self.ledger.connect()) as conn:
            # A read transaction keeps governance and source records consistent.
            if not conn.in_transaction:
                conn.execute('BEGIN')
            for route_id in route_ids:
                route = available[route_id]
                ids = list(dict.fromkeys([b['candidate_id'] for r in route['requirements']
                    for b in r['source_bindings']] + route['context_candidate_ids']))
                records = {cid:self._candidate(cid,conn) for cid in ids}
                requirements, checks = [], []
                for index, requirement in enumerate(route['requirements'],1):
                    bindings = []
                    for binding in requirement['source_bindings']:
                        record = records[binding['candidate_id']]
                        attrs = record['claim']['typed_attributes']
                        if binding['attribute_index'] >= len(attrs):
                            raise WorkflowInputError('Input attribute is absent from its exact candidate')
                        attribute = attrs[binding['attribute_index']]
                        if (record['candidate_hash'] != binding['candidate_hash']
                                or content_hash(attribute) != binding['attribute_hash']
                                or attribute['name'] != 'workflow.input'):
                            raise WorkflowInputError('Source input attribute identity, kind or content changed')
                        bindings.append({**binding, 'attribute':deepcopy(attribute),
                            'evidence':[deepcopy(record['evidence'][i])
                                        for i in attribute['evidence_anchor_indices']]})
                    present = True
                    try:
                        value = _pointer_value(profile, requirement['report_pointer'])
                    except RetrievalPlanningError:
                        present, value = False, None
                    if value is not None and type(value) is not bool:
                        raise WorkflowInputError('Input availability must be explicit true, false or null; metadata names are not reports')
                    status = 'unknown' if value is None else ('reported_met' if value else 'reported_unmet')
                    check = _check(status, review_version=review_version)
                    checks.append(CompactStepCheck(i=f's{index}',**check.model_dump()))
                    requirements.append({**deepcopy(requirement), 'source_bindings':bindings,
                        'report_present':present, 'reported_value':value,
                        'reported_value_hash':content_hash(value) if present else None,
                        'report_origin':report_origin})
                wire = CompactAssessment(d=_check(_aggregate([c.p for c in checks]),
                    review_version=review_version),s=checks)
                assessment = _normalize_compact_assessment(wire,{'bindings':[]})
                # There is no newly judged scientific factual claim in this
                # deterministic check. Full original candidate facts stay below.
                answer = {'steps':[{'step_id':c.i,'factual_claim':'','evidence_ids':[]}
                                    for c in checks]}
                _validate_compact_assessment(assessment,answer,{'records':list(records.values())})
                for requirement, check in zip(requirements,assessment['step_checks']):
                    requirement['check'] = deepcopy(check)
                results.append({'route_id':route_id,'label':route['label'],
                    'route_hash':content_hash(route), 'requirements':requirements,
                    'assessment':assessment,'source_records':list(records.values()),
                    'scope_notes':list(route['scope_notes']), 'requirements_complete':False,
                    'source_semantics_reassessed':False,
                    'complete_scientific_applicability_established':False,
                    'local_execution':{'state':'unbound','execution_authorized':False,'execution_attempted':False}})
        result = {'schema_version':'workflow-reported-input-review-v1',
            'authority':'development_candidate_only','namespace':self.ledger.workspace.namespace,
            'catalog_hash':self.catalog_hash,'profile_hash':content_hash(profile),
            'input_profile':profile,'route_results':results,
            'model_calls':0,'scientific_fits':0,'recommendation_eligible':False,
            'report_mapping_origin':'developer_source_interpretation_not_human_review',
            'independent_input_verification':'not_established'}
        if review_version == REPORTED_INPUT_STATE_VERSION:
            result['schema_version'] = 'workflow-reported-input-review-v2'
            result['reported_input_state_version'] = review_version
        return {**result,'result_hash':content_hash(result)}
