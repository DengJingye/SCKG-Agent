"""One authorized promotion, with immutable outputs and no runtime integration.

Reuses the existing read-only source resolver, frozen structural validator and
immutable writer. The candidate validator's publication policy is deliberately
separate from the external human approval policy validated here.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
import subprocess

from reconstruction.common import ROOT, digest, save_new
from reconstruction.contract import validate_bundle
from reconstruction.hardening_06b.build import protected_check
from reconstruction.hardening_06b.patch import duplicate_groups, resolve_sources

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / 'snapshots/approved-v2-01'
INPUT = ROOT / 'reconstruction/hardening_06b/runs/semantic-06b-01'
CANDIDATE_HASH = 'a494e5e132a131b107c68ed19d48f307294f59b7c6295c28e0e31d5498903210'
HOLD = 'statement-revision:d0d887b96b7a1cf45e2c47bf:1'
SCRUBLET_REMOVED = 'statement-revision:e00845df2c8d639f4cc892e3:1'
SCRUBLET_CAUTION = 'evidence-gap:06b:scrublet-parent-singlet-detectability'
REVIEW = dict(status='PASS_WITH_REVISIONS', statements_to_accept=121,
              statements_to_revise=1, statements_to_reject=0, new_structural_blockers=0,
              provenance='03 Independent QA result explicitly reported by the requesting human user; no separate QA artifact supplied.')
HUMAN_QUOTE = ('接受 03 建议的 121 条最终 ScientificStatement。\n'
               'scVelo worksheet #21：\nstatement-revision:d0d887b96b7a1cf45e2c47bf:1\n'
               '本轮不批准、不进入 production snapshot。\n保留为 HOLD / ontology-next backlog。\n'
               '不修改 frozen ontology。\n不要求本轮创建 latent-time / pseudotime 新 task。\n'
               'Scrublet 原 #18 继续保持 caution，不恢复为 ScientificStatement。')
SCOPE_POLICY = dict(preserve_scope_verbatim=True, unknown_is_wildcard=False,
                    partially_known_is_wildcard=False, approval_implies_applicability=False,
                    known_qualifiers_must_match=True, missing_context_result='unknown',
                    unknown_dimensions_result='unknown', mismatched_context_result='exclude',
                    downstream_adapter_must_enforce=True)
CAUTION_POLICY = dict(context_retrieval_eligible=True, scientific_assertion=False,
                      trusted=False, production_retrieval_eligible=False,
                      execution_authorized=False, execution_gate=False,
                      routing_is_applicability=False)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def governance(identifier):
    return dict(record_id=identifier, human_review_status='approved',
                knowledge_status='approved', trusted=True,
                production_retrieval_eligible=True, execution_authorized=False)


def make_decision(candidate, timestamp):
    approved = sorted(s['statement_revision_id'] for s in candidate['statements']
                      if s['statement_revision_id'] != HOLD)
    return dict(authority='explicit_human_user_message', reviewer_identifier='requesting_user',
                reviewer_name_not_supplied=True, decision_time_not_supplied=True,
                recorded_at=timestamp, source_candidate_sha256=CANDIDATE_HASH,
                review_03=REVIEW, human_decision_quote=HUMAN_QUOTE,
                approved_statement_revision_ids=approved,
                held_statement_revision_ids=[HOLD], approved_statement_count=121,
                execution_authorized=False, machine_recommendations_are_not_authority=True)


def validate_decision(candidate, decision):
    ids = [s['statement_revision_id'] for s in candidate['statements']]
    require(len(ids) == len(set(ids)) == 122 and HOLD in ids, 'Unexpected 06b revision set')
    require(SCRUBLET_REMOVED not in ids, 'Scrublet caution must not become an assertion')
    require(decision['source_candidate_sha256'] == CANDIDATE_HASH, 'Decision candidate hash mismatch')
    require(decision['authority'] == 'explicit_human_user_message'
            and decision['human_decision_quote'] == HUMAN_QUOTE, 'Explicit human authority required')
    require(decision['approved_statement_revision_ids'] == sorted(set(ids) - {HOLD}),
            'Approval must enumerate exactly the 121 authorized revisions')
    require(decision['held_statement_revision_ids'] == [HOLD], 'Exact HOLD required')
    require(decision['approved_statement_count'] == 121 and decision['review_03'] == REVIEW,
            'Human approval / 03 result mismatch')
    require(decision['execution_authorized'] is False, 'Human approval never authorizes execution')


def partition(candidate, decision):
    validate_decision(candidate, decision)
    hold_row = next(s for s in candidate['statements'] if s['statement_revision_id'] == HOLD)
    held_identity = hold_row['statement_id']
    approved = copy.deepcopy(candidate)
    filters = {
        'statements': lambda x: x['statement_revision_id'] == HOLD,
        'entities': lambda x: x['id'] == held_identity,
        'evidence_assessments': lambda x: x['statement_revision_id'] == HOLD,
        'utility': lambda x: x['statement_revision_id'] == HOLD,
        'governance': lambda x: x['record_id'] == HOLD,
    }
    archived = {}
    for collection, held_filter in filters.items():
        archived[collection] = [copy.deepcopy(x) for x in candidate[collection] if held_filter(x)]
        approved[collection] = [x for x in approved[collection] if not held_filter(x)]
    approved['governance'] = [governance(s['statement_revision_id']) for s in approved['statements']]
    held = dict(disposition='HOLD', reason='Human reviewer did not approve scVelo worksheet #21; ontology-next backlog.',
                statement_revision_ids=[HOLD], original_candidate_records=archived,
                source_candidate_sha256=CANDIDATE_HASH, human_approval_granted=False,
                trusted=False, production_retrieval_eligible=False, execution_authorized=False,
                ontology_change_authorized=False, new_task_creation_authorized=False,
                shared_evidence_and_source_records='Resolve against approved_kg.json; all source entities and spans retained.')
    return approved, held


def validate_promotion(candidate, approved, held, decision, cautions, original_cautions):
    """Validate real approved governance before any structural-only projection."""
    validate_decision(candidate, decision)
    expected, expected_held = partition(candidate, decision)
    require(approved == expected, 'Approved payload differs from the exact authorized partition/governance')
    require(held == expected_held, 'HOLD archive differs from the original records / non-approval policy')
    require(all(g['trusted'] is True and g['production_retrieval_eligible'] is True
                and g['execution_authorized'] is False for g in approved['governance']),
            'Approved governance requires strict booleans; execution remains false')
    require(held['trusted'] is False and held['production_retrieval_eligible'] is False
            and held['execution_authorized'] is False, 'HOLD must have no trust, retrieval or execution permission')
    require(cautions == original_cautions, 'Caution context must be preserved verbatim')
    ids = {s['statement_revision_id'] for s in approved['statements']}
    require(len(ids) == 121 and HOLD not in ids and SCRUBLET_REMOVED not in ids, 'Invalid approved set')
    gap_ids = {e['id'] for e in approved['entities'] if e['record_type'] == 'EvidenceGap'}
    require(len(gap_ids) == 166 and {c['caution_id'] for c in cautions} == gap_ids,
            'Every EvidenceGap must remain available as caution context')
    require(SCRUBLET_CAUTION in gap_ids, 'Scrublet #18 caution missing')
    require(all(c['execution_authorized'] is False and c['supports_positive_claim'] is False
                and c['supports_negative_claim'] is False for c in cautions), 'Caution elevated to assertion/gate')
    require(not duplicate_groups(approved), 'Semantic duplicates in approved set')
    return dict(valid=True, approved_statement_count=len(ids), held_statement_count=1,
                evidence_gap_count=len(gap_ids), semantic_duplicate_count=0,
                scope_payloads_unchanged=True, evidence_and_source_payloads_unchanged=True,
                human_authority='explicit_user_decision', execution_authorized=False)


def validate_structure(approved):
    """Use existing candidate validator on a disposable external-policy view.

    No scientific record is transformed. This is NOT a validation of approved
    governance by the candidate-only validator; validate_promotion does that.
    """
    structural_view = copy.deepcopy(approved)
    structural_view['governance'] = [dict(g, knowledge_status='candidate', human_review_status='pending',
                                        trusted=False, production_retrieval_eligible=False)
                                   for g in approved['governance']]
    texts, artifacts = resolve_sources(approved)
    result = validate_bundle(structural_view, texts, artifacts)
    require(result['valid'], 'Frozen structure/provenance validation: ' + str(result['errors']))
    return dict(validation_method='Read-only governance projection to reuse candidate-only structural validator; approved governance validated separately.',
                scientific_records_changed_by_projection=False, candidate_policy_projection_result=result)


def capture_protected():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    paths = {ROOT / p for p in tracked if p}
    paths.update(p for p in (ROOT / 'reconstruction').rglob('*') if p.is_file()
                 and not {'__pycache__', '.pytest_cache'} & set(p.parts))
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(paths)
            if not p.is_relative_to(HERE)}


def verify_protected(baseline):
    historical = protected_check()
    changed = [p for p, sha in baseline.items()
               if not (ROOT / p).is_file() or digest((ROOT / p).read_bytes()) != sha]
    require(not changed and historical['passed'], 'Protected files changed: ' + str(changed or historical))
    return dict(passed=True, existing_workspace_files_checked=len(baseline), changed_paths=[],
                historical_source_and_runtime_check=historical)


def verify_snapshot(snapshot=SNAPSHOT):
    manifest = read(snapshot / 'promotion_manifest.json')
    for name, sha in manifest['output_sha256'].items():
        require(digest((snapshot / name).read_bytes()) == sha, 'Immutable output hash mismatch: ' + name)
    for name, sha in manifest['implementation_sha256'].items():
        require(digest((ROOT / name).read_bytes()) == sha, 'Packaging implementation changed: ' + name)
    require(manifest['scope_policy'] == SCOPE_POLICY and manifest['caution_policy'] == CAUTION_POLICY,
            'Scope/caution policy mismatch')
    decision = read(snapshot / 'human_review_decision.json')
    require(manifest['approved_statement_count'] == 121 and manifest['held_statement_count'] == 1
            and manifest['excluded_hold_statement_ids'] == [HOLD]
            and manifest['approved_statement_revision_ids'] == decision['approved_statement_revision_ids']
            and manifest['production_retrieval_statement_revision_ids'] == decision['approved_statement_revision_ids'],
            'Manifest approved/retrieval/HOLD set mismatch')
    require(manifest['execution_authorized'] is False
            and manifest['research_chat_integration_ready'] is False
            and manifest['production_kg_artifact_ready'] is True
            and manifest['approved_governance_policy'] == {k: v for k, v in governance('unused').items() if k != 'record_id'},
            'Manifest authorization mismatch')
    require(manifest['approved_kg_sha256'] == digest((snapshot / 'approved_kg.json').read_bytes()), 'KG digest mismatch')
    require(manifest['source_candidate_sha256'] == CANDIDATE_HASH
            and digest((INPUT / 'candidate_kg.json').read_bytes()) == CANDIDATE_HASH, 'Candidate digest mismatch')
    result = validate_promotion(read(INPUT / 'candidate_kg.json'), read(snapshot / 'approved_kg.json'),
                               read(snapshot / 'held_out_statements.json'), read(snapshot / 'human_review_decision.json'),
                               read(snapshot / 'caution_context_index.json'), read(INPUT / 'caution_context_index.json'))
    result['protected'] = verify_protected(read(snapshot / 'protected_input_hashes.json'))
    return result


def build():
    require(digest((INPUT / 'candidate_kg.json').read_bytes()) == CANDIDATE_HASH, 'Candidate hash does not match human decision')
    if (SNAPSHOT / 'promotion_manifest.json').exists():
        return verify_snapshot()
    baseline = capture_protected()
    verify_protected(baseline)
    candidate = read(INPUT / 'candidate_kg.json')
    source_texts, artifacts = resolve_sources(candidate)
    candidate_validation = validate_bundle(candidate, source_texts, artifacts)
    require(candidate_validation['valid'], '06b candidate validation failed')
    timestamp_path = SNAPSHOT / 'promotion_timestamp.json'
    timestamp = read(timestamp_path)['promotion_timestamp'] if timestamp_path.exists() else dt.datetime.now(dt.timezone.utc).isoformat()
    decision = make_decision(candidate, timestamp)
    approved, held = partition(candidate, decision)
    cautions = read(INPUT / 'caution_context_index.json')
    validation = validate_promotion(candidate, approved, held, decision, cautions, cautions)
    validation['candidate_input_validation'] = candidate_validation
    validation['approved_structure_validation'] = validate_structure(approved)
    save_new(timestamp_path, dict(promotion_timestamp=timestamp))
    for name, value in [('approved_kg.json', approved), ('held_out_statements.json', held),
                        ('human_review_decision.json', decision), ('validation.json', validation),
                        ('protected_input_hashes.json', baseline)]:
        save_new(SNAPSHOT / name, value)
    save_new(SNAPSHOT / 'caution_context_index.json', (INPUT / 'caution_context_index.json').read_bytes())
    protected = verify_protected(baseline)
    save_new(SNAPSHOT / 'protected_verification.json', protected)
    kg_hash = digest((SNAPSHOT / 'approved_kg.json').read_bytes())
    report = f'''# Approved Scientific KG v2 promotion

Packaged only the 121 exact revisions explicitly approved by the requesting human user. Source candidate: `{CANDIDATE_HASH}`. Approved KG: `{kg_hash}`. Promotion recorded at `{timestamp}`.

03 Independent QA: PASS_WITH_REVISIONS, accept 121 / revise 1 / reject 0 / new structural blockers 0, as supplied by the user. The user's decision is recorded in human_review_decision.json with all 121 exact revision IDs. No reviewer name, signature, decision timestamp, or independent QA artifact was invented. Machine recommendations were not used as human authority.

The 06b candidate has 122 statements; this snapshot has 121. scVelo worksheet #21 `{HOLD}` is HOLD / ontology-next and absent from the approved statement and retrieval sets. Its identity, statement, assessment, original pending governance and utility are archived in held_out_statements.json. No new scientific statement, task, predicate, or ontology schema was created. Scrublet original #18 remains caution.

Approved governance is exactly human_review_status=approved, knowledge_status=approved, trusted=true, production_retrieval_eligible=true, execution_authorized=false. The frozen property registry externalizes knowledge lifecycle and trust; approved is the explicit human decision value in this package's external governance policy, not a new scientific ontology property or a v1 runtime status. Governance covers only the 121 revisions. Historical utility.production_authorized=false remains unchanged and grants no runtime authority; retrieval eligibility is specified by external governance only.

All 166 EvidenceGap entities and all 166 caution context entries remain unchanged, untrusted, and non-assertive. The manifest allows caution context retrieval but forbids treating cautions as scientific claims or execution gates. All 249 spans, 61 source artifacts, 48 source revisions, 47 source works, structural links and source provenance remain unchanged. One held assessment is archived; 138 approved assessments remain. All 9 unknown and 23 partially_known scopes remain exactly unchanged, and the 89 remaining explicit scopes also remain unchanged. Approval never proves applicability; unknown and partially_known cannot mean wildcard. Future consumers must enforce the manifest's scope and caution policies before integration.

Validation checks the exact approved partition and its real governance, full source hashes/text offsets, evidence/source chains and references. The existing validator publishes pending candidates only; its read-only structural reuse resets only external governance in a disposable copy. That projection is labeled in validation.json and is not an approval test. No scientific content is altered by validation.

Immutable publishing uses exclusive creation and rejects different bytes at an existing path. The manifest records every output digest (other than itself) and implementation digests; Git records the manifest. Re-running the build verifies the existing package without rewriting it. Any changed decision or content requires a different snapshot. This is application-level immutability plus content hashes and Git history, not a claim of filesystem or storage WORM enforcement.

Protected checks cover {protected['existing_workspace_files_checked']} pre-existing workspace files plus the prior 06b audit of 1817 tracked protected files, 935 original 06 files and 205 original source copies. No protected file changed. The short promotion regressions and existing reconstruction/06b tests are run separately before commit; their result is recorded in reconstruction/promotion_v2/test_results.json outside this immutable snapshot. Snapshot verification additionally checks the candidate is still byte-identical and pending.

PRODUCTION_KG_ARTIFACT_READY=true. RESEARCH_CHAT_INTEGRATION_READY=false: no Chat/Planner/RAG/UI or production runtime adapter, configuration, import, database, or current-production pointer was changed. No reconstruction, new extraction, corpus expansion, formal evaluation, Agent Gain, or evaluation dataset freeze ran. Frozen ontology remains 2.0.0-core-review.1. Full reconstruction remains PARTIAL; no scientific-validation pass is claimed.

This independent commit contains only reconstruction/promotion_v2. Rebuild/full-source tests reuse the existing local 06b candidate, reconstruction modules, and archived source files; those earlier untracked deliverables are not silently included in this commit. approved_kg.json and the caution/HOLD sidecars carry the graph, exact evidence quotations and source provenance, while complete source bytes stay in the existing source archive. See README.md for verification commands. No push is performed.
'''
    save_new(SNAPSHOT / 'promotion_report.md', report.encode())
    manifest = dict(snapshot_id='approved-scientific-kg-v2-01', artifact_type='Approved Scientific KG v2',
                    packaging_policy_version='sckg-human-approved-promotion-1', ontology_version=approved['ontology_version'],
                    scientific_bundle_schema_version=approved['schema_version'],
                    promotion_timestamp=timestamp, source_candidate_path=str((INPUT / 'candidate_kg.json').relative_to(ROOT)),
                    source_candidate_sha256=CANDIDATE_HASH, review_03=REVIEW,
                    human_reviewer_decision='human_review_decision.json', excluded_hold_statement_ids=[HOLD],
                    candidate_statement_count=122, approved_statement_count=121, held_statement_count=1,
                    approved_statement_revision_ids=decision['approved_statement_revision_ids'],
                    production_retrieval_statement_revision_ids=decision['approved_statement_revision_ids'],
                    approved_governance_policy={k: v for k, v in governance('unused').items() if k != 'record_id'},
                    execution_authorized=False, caution_policy=CAUTION_POLICY, scope_policy=SCOPE_POLICY,
                    approved_kg_sha256=kg_hash, production_kg_artifact_ready=True,
                    research_chat_integration_ready=False, production_runtime_modified=False,
                    agent_gain_run=False, ontology_modified=False,
                    base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
                    implementation_sha256={str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(HERE.glob('*.py'))},
                    output_sha256={p.name: digest(p.read_bytes()) for p in sorted(SNAPSHOT.iterdir())
                                   if p.is_file() and p.name != 'promotion_manifest.json'})
    save_new(SNAPSHOT / 'promotion_manifest.json', manifest)
    return verify_snapshot()


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False, indent=2))
