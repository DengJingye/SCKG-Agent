"""Saved-artifact regressions and attempts to cross approval/scope boundaries."""
import copy
from collections import Counter
import json

import pytest

from reconstruction.common import digest, save_new
from .promotion import (CANDIDATE_HASH, HOLD, INPUT, SCRUBLET_CAUTION, SCRUBLET_REMOVED,
                        SNAPSHOT, read, validate_promotion, validate_structure, verify_snapshot)


@pytest.fixture(scope='module')
def package():
    return dict(candidate=read(INPUT / 'candidate_kg.json'), approved=read(SNAPSHOT / 'approved_kg.json'),
                held=read(SNAPSHOT / 'held_out_statements.json'), decision=read(SNAPSHOT / 'human_review_decision.json'),
                cautions=read(SNAPSHOT / 'caution_context_index.json'),
                original_cautions=read(INPUT / 'caution_context_index.json'))


def test_exact_121_approved_and_real_human_authority(package):
    result = validate_promotion(**package)
    assert result['approved_statement_count'] == 121
    assert package['decision']['authority'] == 'explicit_human_user_message'
    assert package['decision']['review_03']['status'] == 'PASS_WITH_REVISIONS'
    g = package['approved']['governance']
    assert len(g) == 121 and len({r['record_id'] for r in g}) == 121
    assert all(r['human_review_status'] == r['knowledge_status'] == 'approved'
               and r['trusted'] is True and r['production_retrieval_eligible'] is True for r in g)


def test_hold_absent_from_all_production_records_and_retrieval_set(package):
    approved = package['approved']
    assert HOLD not in json.dumps(approved)
    manifest = read(SNAPSHOT / 'promotion_manifest.json')
    assert len(manifest['production_retrieval_statement_revision_ids']) == 121
    assert HOLD not in manifest['production_retrieval_statement_revision_ids']
    assert manifest['excluded_hold_statement_ids'] == [HOLD]
    archive = package['held']['original_candidate_records']
    assert archive['statements'] == [s for s in package['candidate']['statements'] if s['statement_revision_id'] == HOLD]
    assert len(archive['evidence_assessments']) == 1
    assert package['held']['disposition'] == 'HOLD'


def test_no_execution_permission_anywhere(package):
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'execution_authorized':
                    assert item is False
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(package)
    walk(read(SNAPSHOT / 'promotion_manifest.json'))


def test_cautions_preserved_and_scrublet_not_reasserted(package):
    assert (SNAPSHOT / 'caution_context_index.json').read_bytes() == (INPUT / 'caution_context_index.json').read_bytes()
    original = [e for e in package['candidate']['entities'] if e['record_type'] == 'EvidenceGap']
    approved = [e for e in package['approved']['entities'] if e['record_type'] == 'EvidenceGap']
    assert len(approved) == 166 and approved == original
    assert SCRUBLET_CAUTION in {c['caution_id'] for c in package['cautions']}
    assert SCRUBLET_REMOVED not in {s['statement_revision_id'] for s in package['approved']['statements']}
    assert not {c['caution_id'] for c in package['cautions']} & {g['record_id'] for g in package['approved']['governance']}


def test_unknown_and_partially_known_scopes_unchanged(package):
    old = {s['statement_revision_id']: s for s in package['candidate']['statements']}
    new = package['approved']['statements']
    assert Counter(s['scope_status'] for s in new) == {'explicit': 89, 'unknown': 9, 'partially_known': 23}
    assert all(s == old[s['statement_revision_id']] for s in new)
    policy = read(SNAPSHOT / 'promotion_manifest.json')['scope_policy']
    assert policy['unknown_is_wildcard'] is False
    assert policy['partially_known_is_wildcard'] is False
    assert policy['approval_implies_applicability'] is False


def test_no_dangling_refs_and_complete_source_text_chains(package):
    before = digest(package['approved'])
    result = validate_structure(package['approved'])
    assert result['candidate_policy_projection_result']['valid']
    assert digest(package['approved']) == before
    b = package['approved']
    entities = {e['id']: e for e in b['entities']}
    spans = {s['evidence_span_id']: s for s in b['evidence_spans']}
    source = {p['source_artifact_id']: p for p in b['provenance'] if 'source_artifact_id' in p}
    for assessment in b['evidence_assessments']:
        span = spans[assessment['evidence_span_id']]
        chain = source[span['source_artifact_id']]
        assert span['source_revision_id'] == chain['source_revision_id']
        assert all(identifier in entities for identifier in (chain['source_work_id'], chain['source_revision_id'], chain['source_artifact_id']))


def test_all_evidence_source_and_structural_content_preserved(package):
    before, after = package['candidate'], package['approved']
    for key in ['evidence_spans', 'links', 'provenance', 'term_registry']:
        assert after[key] == before[key]
    assert len(after['evidence_spans']) == 249
    assert len(after['evidence_assessments']) == 138
    assert after['evidence_assessments'] == [a for a in before['evidence_assessments'] if a['statement_revision_id'] != HOLD]
    for kind, count in [('SourceWork', 47), ('SourceRevision', 48), ('SourceArtifact', 61)]:
        assert len([e for e in after['entities'] if e['record_type'] == kind]) == count
        assert [e for e in after['entities'] if e['record_type'] == kind] == [e for e in before['entities'] if e['record_type'] == kind]


def test_candidate_and_historical_review_remain_pending(package):
    assert digest((INPUT / 'candidate_kg.json').read_bytes()) == CANDIDATE_HASH
    assert all(g['human_review_status'] == 'pending' and g['trusted'] is False for g in package['candidate']['governance'])
    worksheet = read(INPUT / 'review_worksheet_127.json')
    assert len(worksheet) == 127 and all(r['reviewer_decision'] == 'pending' for r in worksheet)


def test_hashes_and_protected_paths_unchanged():
    result = verify_snapshot()
    assert result['protected']['passed'] and result['protected']['changed_paths'] == []


@pytest.mark.parametrize('field,value', [
    ('execution_authorized', True), ('execution_authorized', 0),
    ('trusted', False), ('trusted', 1), ('production_retrieval_eligible', False),
    ('human_review_status', 'pending'), ('knowledge_status', 'candidate')])
def test_reject_governance_changes(package, field, value):
    bad = copy.deepcopy(package)
    bad['approved']['governance'][0][field] = value
    with pytest.raises(ValueError):
        validate_promotion(**bad)


def test_reject_held_statement_even_with_approved_governance(package):
    bad = copy.deepcopy(package)
    s = bad['held']['original_candidate_records']['statements'][0]
    bad['approved']['statements'].append(s)
    g = copy.deepcopy(bad['approved']['governance'][0])
    g['record_id'] = HOLD
    bad['approved']['governance'].append(g)
    with pytest.raises(ValueError):
        validate_promotion(**bad)


@pytest.mark.parametrize('scope', ['unknown', 'partially_known'])
def test_reject_scope_upgrade(package, scope):
    bad = copy.deepcopy(package)
    next(s for s in bad['approved']['statements'] if s['scope_status'] == scope)['scope_status'] = 'explicit'
    with pytest.raises(ValueError):
        validate_promotion(**bad)


def test_reject_caution_as_execution_gate(package):
    bad = copy.deepcopy(package)
    bad['cautions'][0]['execution_authorized'] = True
    with pytest.raises(ValueError):
        validate_promotion(**bad)


def test_reject_dangling_scientific_reference(package):
    bad = copy.deepcopy(package['approved'])
    bad['statements'][0]['subject_id'] = 'method:missing'
    with pytest.raises(ValueError, match='structure/provenance'):
        validate_structure(bad)


def test_reject_broken_exact_evidence(package):
    bad = copy.deepcopy(package['approved'])
    bad['evidence_spans'][0]['exact_text'] += ' changed'
    with pytest.raises(ValueError, match='structure/provenance'):
        validate_structure(bad)


def test_machine_recommendation_cannot_substitute_human_authority(package):
    bad = copy.deepcopy(package)
    bad['decision']['authority'] = 'machine_recommendation'
    with pytest.raises(ValueError, match='human authority'):
        validate_promotion(**bad)


def test_immutable_writer_rejects_overwrite(tmp_path):
    target = tmp_path / 'immutable.json'
    save_new(target, {'approved': 121})
    original = target.read_bytes()
    save_new(target, {'approved': 121})
    with pytest.raises(FileExistsError):
        save_new(target, {'approved': 122})
    assert target.read_bytes() == original
