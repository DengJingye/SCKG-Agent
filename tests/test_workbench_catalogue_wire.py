"""Lossless lexical wire and native planner boundaries, using synthetic sources.

The real ModelService uses an in-memory transport. Source publication/assessment
records are explicitly synthetic governance fixtures from public test helpers;
they are not human review, provider observations or scientific-quality evidence.
No private eval package, real corpus, credentials or external network is used.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from sckg_workbench.evidence_wire import (
    CATALOGUE_WIRE_SCHEMA, COLUMNAR_CATALOGUE_ENCODING,
    COLUMNAR_CATALOGUE_INSTRUCTIONS, LITERAL_CATALOGUE_ENCODING,
    EvidenceWireError, decode_catalogue_entries, encode_catalogue_entries,
)
from sckg_workbench.model_service import ModelService, ModelServiceError
from sckg_workbench.retrieval_planning import (
    CATALOG_INSTRUCTIONS, GOAL_PATH_INSTRUCTIONS, LEGACY_SYSTEM, RESPONSE_FORMAT,
    MAX_QUERY_INPUT_TOKENS, EvidenceSnapshotChanged, RetrievalPlanningError,
    _material, _planning_messages, build_evidence_term_catalog,
    plan_evidence_queries, retrieve_planned_evidence,
)
from sckg_workbench.storage import canonical_json, content_hash
from tests.test_workbench_knowledge import approved, kb, publish


BUDGET = {'max_input_tokens': 16000, 'max_output_tokens': 1536,
          'timeout_seconds': 5, 'allow_unknown_cost': True}
QUESTION = '合成检索夹具：细胞对应关系未知，请找输入与适用条件。'
PROFILE = {'pairing': 'unknown', 'unknowns': ['Synthetic pairing not measured']}
PASSPHRASE = 'synthetic-catalogue-fixture-passphrase'


def _output():
    return {'goal': 'Synthetic retrieval plan only', 'stated_premises': [
        {'source': 'question', 'pointer': '', 'quote': '细胞对应关系未知'},
        {'source': 'dataset_profile', 'pointer': '/pairing', 'quote': 'unknown'}],
        'unknowns': list(PROFILE['unknowns']),
        'queries': [{'language': 'en', 'text': 'Synthetic'},
                    {'language': 'zh', 'text': '合成'}],
        'evidence_checks': ['Synthetic applicability remains unverified']}


@pytest.fixture
def planner(kb):
    calls = []
    setting = {'output': _output(), 'finish': 'stop', 'during_call': None, 'timeout': False}

    def transport(url, headers, payload, timeout):
        calls.append(deepcopy(payload))
        if setting['timeout']:
            raise TimeoutError('Synthetic planner timeout; never retry')
        if setting['during_call'] is not None:
            setting['during_call']()
        return {'model': 'synthetic-planner-model', 'id': 'synthetic-planner-response',
            'usage': {'prompt_tokens': 200, 'completion_tokens': 70, 'total_tokens': 270},
            'choices': [{'finish_reason': setting['finish'],
                'message': {'content': json.dumps(setting['output'], ensure_ascii=False)}}]}

    models = ModelService(kb.ledger.workspace, kb.ledger, transport=transport)
    connection = models.create_connection('synthetic catalogue fixture',
        'https://provider.example/v1', 'synthetic-not-a-real-key', PASSPHRASE)
    profile = models.create_profile('synthetic query planner', 'evaluation',
        connection['id'], 'synthetic-planner-model', options={'temperature': 0})
    first, first_source, _ = approved(kb,
        text='Synthetic catalogue A is a fictional source-binding fixture.',
        filename='synthetic-catalogue-a.txt', claim_updates={
            'subject': 'Synthetic Ω "甲"', 'proposed_terms': ['synthetic \\ path', 'e\u0301 / é']})
    second, _, _ = approved(kb,
        text='Synthetic catalogue B is another fictional source-binding fixture.',
        filename='synthetic-catalogue-b.txt', claim_updates={
            'subject': '合成乙', 'proposed_terms': []})
    release = publish(kb, [first, second])
    catalog = build_evidence_term_catalog(kb.knowledge,
        allowed_candidate_ids=[first['id'], second['id']])
    return SimpleNamespace(**vars(kb), models=models, calls=calls, setting=setting,
        profile=profile, first=first, first_source=first_source, second=second,
        release=release, catalog=catalog)


def _plan(planner, *, dataset_profile=None, **updates):
    options = {'profile_id': planner.profile['id'], 'passphrase': PASSPHRASE,
        'outbound_authorized': True, 'budget': deepcopy(BUDGET),
        'term_catalog': planner.catalog}
    options.update(updates)
    return plan_evidence_queries(planner.models, QUESTION,
        deepcopy(PROFILE if dataset_profile is None else dataset_profile), **options)


def _snapshot(ledger):
    with ledger.connect() as conn:
        return {
            'records': [tuple(r) for r in conn.execute(
                'SELECT kind,record_id,digest FROM records ORDER BY kind,record_id')],
            'state': [tuple(r) for r in conn.execute('SELECT key,value FROM state ORDER BY key')],
            'events': [tuple(r) for r in conn.execute('SELECT * FROM events ORDER BY sequence')],
        }


def _rehash_run(run):
    run['input_hash'] = content_hash(run['input_material'])
    run['plan_hash'] = content_hash(run['plan'])
    run['binding_hash'] = content_hash({k: v for k, v in run.items() if k != 'binding_hash'})


def test_codec_preserves_unicode_empty_hints_duplicates_order_and_input_objects():
    original = [{'label': '乙 "引号"\n\\路径 🧬', 'term_hints': ['z', 'e\u0301', 'é', 'z']},
                {'label': '', 'term_hints': []},
                {'label': '乙 "引号"\n\\路径 🧬', 'term_hints': []}]
    before = deepcopy(original)
    wire = encode_catalogue_entries(original)
    assert wire == {'schema_version': CATALOGUE_WIRE_SCHEMA,
        'fields': ['label', 'term_hints'],
        'rows': [[row['label'], row['term_hints']] for row in original]}
    wire_before = deepcopy(wire)
    decoded = decode_catalogue_entries(wire)
    assert decoded == original == before
    assert canonical_json(decoded) == canonical_json(original)
    assert wire == wire_before
    wire['rows'][0][1].append('wire-only mutation')
    decoded[2]['term_hints'].append('decoded-only mutation')
    assert original == before  # Neither direction returns shared mutable lists.
    assert decode_catalogue_entries(encode_catalogue_entries([])) == []


@pytest.mark.parametrize('change', [
    {'schema_version': 'published-lexical-columnar-v999'},
    {'schema_version': False},
    {'fields': ['term_hints', 'label']},
    {'fields': ('label', 'term_hints')},
    {'fields': ['label', 'unknown_column']},
    {'extra': 'not part of the envelope'},
    {'rows': {'0': ['label', []]}},
    {'rows': [['missing hint column']]},
    {'rows': [['label', [], 'extra column']]},
    {'rows': [('tuple is not a JSON row', [])]},
    {'rows': [[True, []]]},
    {'rows': [['label', [False]]]},
])
def test_decoder_rejects_wrong_versions_columns_shapes_and_scalar_types(change):
    wire = {'schema_version': CATALOGUE_WIRE_SCHEMA,
            'fields': ['label', 'term_hints'], 'rows': [['label', []]]}
    wire.update(deepcopy(change))
    with pytest.raises(EvidenceWireError):
        decode_catalogue_entries(wire)


@pytest.mark.parametrize('entries', [
    {'label': 'not an entry list', 'term_hints': []},
    ({'label': 'tuple container', 'term_hints': []},),
    [['not an entry object', []]],
    [{'label': 'label', 'term_hints': [], 'extra': 'unbound'}],
    [{'label': 1, 'term_hints': []}],
    [{'label': 'label', 'term_hints': 'not a list'}],
    [{'label': 'label', 'term_hints': [None]}],
])
def test_encoder_refuses_non_JSON_or_non_native_entry_fields(entries):
    with pytest.raises(EvidenceWireError):
        encode_catalogue_entries(entries)


def test_actual_gateway_native_source_binding_and_stored_run_readonly_replay(planner):
    original_catalog = deepcopy(planner.catalog)
    run = _plan(planner, catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING)
    request = planner.ledger.get_record('model_request', run['call_id'])
    body = planner.calls[0]
    wire_material = json.loads(body['messages'][1]['content'])
    assert request['payload'] == body
    assert request['request_hash'] == run['call_request_hash'] == content_hash(body)
    assert run['call_receipt'] == planner.ledger.get_record('model_call', run['call_id'])
    assert run['catalogue_encoding'] == COLUMNAR_CATALOGUE_ENCODING
    assert COLUMNAR_CATALOGUE_INSTRUCTIONS in body['messages'][0]['content']
    assert GOAL_PATH_INSTRUCTIONS in body['messages'][0]['content']
    assert body['response_format'] == RESPONSE_FORMAT
    assert decode_catalogue_entries(wire_material['available_term_catalog']) == original_catalog['entries']
    assert {k: v for k, v in wire_material.items() if k != 'available_term_catalog'} == {
        'question': QUESTION, 'dataset_profile': PROFILE, 'supplied_unknowns': PROFILE['unknowns']}
    assert run['input_material']['available_term_catalog'] == original_catalog['entries']
    assert run['term_catalog'] == planner.catalog == original_catalog
    package = planner.knowledge.resolve(original_catalog['basis_ids'])
    assert {u['candidate_id']: content_hash(u) for u in package.units} == original_catalog['full_unit_hashes']
    assert run['scientific_facts_verified'] is False and run['auto_retry'] is False
    planner.ledger.put_record('synthetic_query_plan_run', 'columnar-roundtrip', run)
    before = _snapshot(planner.ledger)
    saved = planner.ledger.get_record('synthetic_query_plan_run', 'columnar-roundtrip')
    first = retrieve_planned_evidence(planner.knowledge, saved)
    second = retrieve_planned_evidence(planner.knowledge, saved)
    assert first == second
    assert first['full_unit_hashes'] == original_catalog['full_unit_hashes']
    assert all(row['status'] == 'not_evaluated' for row in first['evidence_checks'])
    assert _snapshot(planner.ledger) == before and len(planner.calls) == 1


@pytest.mark.parametrize('prompt_version', ['legacy_v1', 'goal_path_v2'])
def test_default_and_explicit_literal_keep_legacy_body_and_unencoded_run_replay(planner, prompt_version):
    default = _plan(planner, prompt_version=prompt_version)
    literal = _plan(planner, prompt_version=prompt_version,
                    catalogue_encoding=LITERAL_CATALOGUE_ENCODING)
    assert planner.calls[0] == planner.calls[1]
    assert 'catalogue_encoding' not in default and 'catalogue_encoding' not in literal
    assert default['input_material'] == literal['input_material']
    material = json.loads(planner.calls[0]['messages'][1]['content'])
    assert material['available_term_catalog'] == planner.catalog['entries']
    assert COLUMNAR_CATALOGUE_INSTRUCTIONS not in planner.calls[0]['messages'][0]['content']
    assert planner.calls[0]['messages'] == _planning_messages(default['input_material'],
                                                            prompt_version=prompt_version)
    if prompt_version == 'legacy_v1':
        assert planner.calls[0]['messages'][0]['content'] == LEGACY_SYSTEM + CATALOG_INSTRUCTIONS
        default.pop('planning_prompt_version')  # The older saved run omitted this field too.
        _rehash_run(default)
    planner.ledger.put_record('synthetic_query_plan_run', 'unencoded-legacy-run', default)
    before = _snapshot(planner.ledger)
    saved = planner.ledger.get_record('synthetic_query_plan_run', 'unencoded-legacy-run')
    assert retrieve_planned_evidence(planner.knowledge, saved)['query_plan'] == saved
    assert _snapshot(planner.ledger) == before and len(planner.calls) == 2


class _NoServiceAccess:
    @property
    def ledger(self):
        pytest.fail('Invalid encoding must stop before ledger/profile access')

    def invoke(self, *args, **kwargs):
        pytest.fail('Invalid encoding must not reach a model')


@pytest.mark.parametrize('encoding', [None, False, {}, 'columnar_v999'])
def test_unknown_encoding_stops_before_any_service_access(encoding):
    with pytest.raises(RetrievalPlanningError, match='catalogue encoding'):
        plan_evidence_queries(_NoServiceAccess(), QUESTION, PROFILE, budget=BUDGET,
            outbound_authorized=True, catalogue_encoding=encoding)


def test_columnar_without_published_catalogue_stops_before_any_service_access():
    with pytest.raises(RetrievalPlanningError, match='requires a published lexical catalogue'):
        plan_evidence_queries(_NoServiceAccess(), QUESTION, PROFILE, budget=BUDGET,
            outbound_authorized=True, catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING)


@pytest.mark.parametrize('change', ['rehashed_hint', 'paused_source'])
def test_native_catalogue_source_gate_still_rejects_before_dispatch(planner, change):
    catalog = deepcopy(planner.catalog)
    if change == 'rehashed_hint':
        catalog['entries'][0]['term_hints'].append('synthetic invented alias')
        catalog['context'] = canonical_json(catalog['entries'])
        catalog['context_hash'] = content_hash(catalog['context'])
        catalog['context_bytes'] = len(catalog['context'].encode())
        catalog['result_hash'] = content_hash({k: v for k, v in catalog.items() if k != 'result_hash'})
    else:
        planner.knowledge.suspend('source', planner.first_source['id'],
            actor='synthetic-fixture-reviewer', reason='Synthetic source withdrawal')
    before = _snapshot(planner.ledger)
    with pytest.raises(EvidenceSnapshotChanged):
        _plan(planner, term_catalog=catalog, catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING)
    assert not planner.calls and _snapshot(planner.ledger) == before


def test_source_change_during_actual_stub_call_keeps_receipt_and_never_retries(planner):
    planner.setting['during_call'] = lambda: planner.knowledge.suspend('source',
        planner.first_source['id'], actor='synthetic-fixture-reviewer', reason='Synthetic race')
    with pytest.raises(RetrievalPlanningError) as error:
        _plan(planner, catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING)
    assert len(planner.calls) == 1
    assert error.value.call_id and error.value.receipt['status'] == 'succeeded'
    assert error.value.receipt == planner.ledger.get_record('model_call', error.value.call_id)


@pytest.mark.parametrize('damage', ['remove_encoding', 'literal_encoding', 'native_entry', 'full_unit_hash'])
def test_rehashing_saved_run_cannot_change_wire_or_native_source_binding(planner, damage):
    run = _plan(planner, catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING)
    if damage == 'remove_encoding':
        run.pop('catalogue_encoding')
    elif damage == 'literal_encoding':
        run['catalogue_encoding'] = LITERAL_CATALOGUE_ENCODING
    elif damage == 'native_entry':
        run['input_material']['available_term_catalog'][0]['term_hints'].append('unbound hint')
    else:
        key = next(iter(run['term_catalog']['full_unit_hashes']))
        run['term_catalog']['full_unit_hashes'][key] = 'f' * 64
        run['term_catalog']['result_hash'] = content_hash({k: v for k, v in run['term_catalog'].items()
                                                        if k != 'result_hash'})
    _rehash_run(run)
    planner.ledger.put_record('synthetic_query_plan_run', 'tampered-local-run', run)
    before = _snapshot(planner.ledger)
    with pytest.raises(RetrievalPlanningError):
        retrieve_planned_evidence(planner.knowledge,
            planner.ledger.get_record('synthetic_query_plan_run', 'tampered-local-run'))
    assert _snapshot(planner.ledger) == before and len(planner.calls) == 1


def test_unchanged_16000_bound_admits_boundary_and_rejects_16001_without_dispatch(planner, monkeypatch):
    assert MAX_QUERY_INPUT_TOKENS == BUDGET['max_input_tokens'] == 16000
    profile = {**deepcopy(PROFILE), 'padding': ''}

    def estimated_gateway_input(value):
        material = _material(QUESTION, value)
        material['available_term_catalog'] = deepcopy(planner.catalog['entries'])
        payload = {'messages': _planning_messages(material,
            catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING), 'response_format': deepcopy(RESPONSE_FORMAT)}
        # Existing gateway's declared conservative estimate, not measured model tokens.
        return len(json.dumps(payload, ensure_ascii=False).encode()) + 256

    padding = 16000 - estimated_gateway_input(profile)
    assert 0 < padding < 12000
    profile['padding'] = 'x' * padding
    assert estimated_gateway_input(profile) == 16000
    boundary = _plan(planner, dataset_profile=profile,
                     catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING)
    assert boundary['call_receipt']['estimated_input_tokens'] == 16000
    assert boundary['call_receipt']['input_estimate_method'] == 'utf8_bytes_plus_256_not_tokenizer'
    assert boundary['call_receipt']['budget'] == BUDGET
    before = _snapshot(planner.ledger)
    monkeypatch.setattr(planner.models, '_credential',
        lambda *a, **k: pytest.fail('Over-budget planner must not read credentials'))
    with pytest.raises(RetrievalPlanningError, match='max_input_tokens'):
        _plan(planner, budget={**BUDGET, 'max_input_tokens': 16001},
              catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING)
    profile['padding'] += 'x'
    assert estimated_gateway_input(profile) == 16001
    with pytest.raises(ModelServiceError, match='Estimated input exceeds'):
        _plan(planner, dataset_profile=profile, catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING)
    assert len(planner.calls) == 1 and _snapshot(planner.ledger) == before


@pytest.mark.parametrize('failure', ['partial', 'invalid_schema', 'timeout'])
def test_columnar_gateway_failures_preserve_actual_receipt_without_retry(planner, failure):
    if failure == 'partial':
        planner.setting['finish'] = 'length'
    elif failure == 'invalid_schema':
        planner.setting['output'] = {'wrong': 'Synthetic invalid planner object'}
    else:
        planner.setting['timeout'] = True
    before_ids = {r['call_id'] for r in planner.ledger.list_records('model_call')
                  if 'call_id' in r}
    with pytest.raises(RetrievalPlanningError) as error:
        _plan(planner, catalogue_encoding=COLUMNAR_CATALOGUE_ENCODING)
    assert len(planner.calls) == 1 and error.value.call_id
    assert error.value.receipt == planner.ledger.get_record('model_call', error.value.call_id)
    assert error.value.receipt['status'] != 'succeeded'
    after_ids = {r['call_id'] for r in planner.ledger.list_records('model_call') if 'call_id' in r}
    assert after_ids - before_ids == {error.value.call_id}


def test_catalogue_capacity_never_truncates_entries_or_mutates_the_release(planner):
    before = _snapshot(planner.ledger)
    with pytest.raises(RetrievalPlanningError, match='explicit smaller evidence scope'):
        build_evidence_term_catalog(planner.knowledge, max_context_bytes=2)
    assert build_evidence_term_catalog(planner.knowledge,
        allowed_candidate_ids=planner.catalog['basis_ids']) == planner.catalog
    assert _snapshot(planner.ledger) == before and not planner.calls
