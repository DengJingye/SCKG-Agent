"""Real SQLite and synthetic originals; no model calls or scientific gold data."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from sckg_workbench.knowledge import KnowledgeError, KnowledgeService
from sckg_workbench.sources import SourceService
from sckg_workbench.storage import Ledger, Workspace, canonical_json, content_hash, new_id
from sckg_workbench.tasks import InvalidTransition, LeaseLost, TaskQueue
from sckg_workbench.worker import Worker


@pytest.fixture
def kb(tmp_path):
    ledger = Ledger(Workspace(tmp_path / "isolated-knowledge-fixture"))
    profiles = {}
    for purpose in ("extraction", "assessment", "chat"):
        profile = {"id": "synthetic-" + purpose, "purpose": purpose, "model": "fixture-not-a-real-model"}
        ledger.put_record("model_profile", profile["id"], profile)
        profiles[purpose] = profile["id"]
    return SimpleNamespace(ledger=ledger, sources=SourceService(ledger), knowledge=KnowledgeService(ledger), profiles=profiles)


def candidate(kb, *, text="SyntheticTool supports a fixture workflow.", filename="synthetic.txt", claim_updates=None, run_id="fixture-run-1"):
    source = kb.sources.register_bytes(filename, text.encode("utf-8"))
    ir = kb.sources.parse(source["id"])
    block = ir["blocks"][0]
    claim = {"proposition": text, "subject": "SyntheticTool", "predicate": "supports", "object": "fixture workflow",
             "polarity": "positive", "conditions": ["Synthetic fixture only"], "unknowns": ["No scientific validity is implied"],
             "assertion_kind": "source_assertion", "model_self_score": 0.85,
             "anchors": [{"ir_id": ir["id"], "block_id": block["id"], "start": 0, "end": len(block["exact_text"]), "quote": block["exact_text"]}]}
    claim.update(claim_updates or {})
    unit = kb.knowledge.add_candidate(claim, run_id=run_id, profile_id=kb.profiles["extraction"])
    return unit, source, ir


def assess(kb, unit, *, relation="support", extent="full", status="succeeded", purpose="assessment", call_id=None, lease_guard=None):
    call_id = call_id or new_id("synthetic-model-call")
    result = {"relation": relation, "extent": extent, "rationale": "Synthetic receipt for governance tests only.", "limitations": ["Not scientific evidence"]}
    payload = {"messages": [{"role": "user", "content": canonical_json(kb.knowledge.assessment_input(unit["id"]))}]}
    kb.ledger.put_record("model_request", call_id, {"payload": payload})
    receipt = {"call_id": call_id, "profile_id": kb.profiles[purpose], "status": status,
               "requested_model": "fixture-not-a-real-model", "synthetic_fixture": True,
               "structured_output_hash": content_hash(result)}
    kb.ledger.put_record("model_call", call_id, receipt)
    return kb.knowledge.assess(unit["id"], result,
                               run_id="synthetic-assessment-run", profile_id=kb.profiles[purpose], call_id=call_id, lease_guard=lease_guard)


def review(kb, unit, *, decision="approve", uses=None, expected_hash=None):
    return kb.knowledge.review(unit["id"], actor="fixture-reviewer", decision=decision,
        allowed_uses=(uses if uses is not None else (["explanation", "recommendation"] if decision == "approve" else [])),
        reason="Synthetic governance test; not scientific validation", expected_hash=expected_hash or unit["content_hash"],
        expected_assessment_id=kb.ledger.get_state("assessment:" + unit["id"]))


def approved(kb, **kwargs):
    unit, source, ir = candidate(kb, **kwargs)
    assess(kb, unit)
    review(kb, unit)
    return unit, source, ir


def publish(kb, units, expected=None):
    return kb.knowledge.publish([unit["id"] for unit in units], actor="fixture-reviewer", expected_release_id=expected)


def test_unreviewed_and_unpublished_candidates_never_enter_search(kb):
    unit, _, _ = candidate(kb)
    assert not kb.knowledge.search("SyntheticTool").units
    assert not kb.knowledge.resolve([unit["id"]]).units
    assess(kb, unit)
    assert not kb.knowledge.search("SyntheticTool").units
    with pytest.raises(KnowledgeError):
        publish(kb, [unit])
    review(kb, unit)
    assert not kb.knowledge.search("SyntheticTool").units
    assert not kb.knowledge.resolve([unit["id"]]).units
    release = publish(kb, [unit])
    package = kb.knowledge.search("SyntheticTool")
    assert package.release_id == release["id"]
    assert [row["candidate_id"] for row in package.units] == [unit["id"]]
    assert package.units[0]["confidence"] == {"model_self_score": 0.85, "calibrated_probability": None}
    assert package.retrieval["semantic_relevance"] == "not_verified"
    assert kb.knowledge.resolve([unit["id"]]).units == package.units


def test_chinese_paraphrase_recall_keeps_release_and_suspension_gates(kb):
    unit, source, _ = approved(
        kb,
        text="甲方法要求同一细胞配对测量两种模态。",
        claim_updates={"proposition": "甲方法要求同一细胞配对测量两种模态。", "subject": "甲方法",
                       "conditions": ["同一细胞配对测量"], "unknowns": ["其他输入尚未验证"]},
    )
    query = "同一细胞的两种模态需要配对吗"
    assert not kb.knowledge.search(query).units
    publish(kb, [unit])
    result = kb.knowledge.search(query)
    assert [entry["candidate_id"] for entry in result.units] == [unit["id"]]
    assert result.retrieval["method"] == "sqlite_fts5_bm25_then_cjk_ngrams"
    assert result.retrieval["semantic_relevance"] == "not_verified"
    kb.knowledge.suspend("source", source["id"], actor="fixture-reviewer", reason="Synthetic withdrawal")
    assert not kb.knowledge.search(query).units


def test_optional_source_bound_attribute_is_searchable_without_new_node_migration(kb):
    unit, _, _ = approved(
        kb, text="SyntheticTool requires MATCHED_CELL_PAIRING in this fixture.",
        claim_updates={"typed_attributes": [{"name": "pairing_requirement",
                                              "value": "MATCHED_CELL_PAIRING",
                                              "evidence_anchor_indices": [0],
                                              "qualifiers": ["synthetic fixture"]}]},
    )
    publish(kb, [unit])
    assert [item["candidate_id"] for item in kb.knowledge.search("MATCHED_CELL_PAIRING").units] == [unit["id"]]
    with pytest.raises(ValidationError, match="attribute evidence"):
        candidate(kb, claim_updates={"typed_attributes": [{"name": "pairing_requirement",
                                                          "value": "unknown", "evidence_anchor_indices": [1]}]})


def test_exact_resolution_retains_eligible_evidence_below_top_100(kb):
    original, source, _ = approved(kb)
    previous = publish(kb, [original])
    initial_unit = kb.knowledge.search("SyntheticTool").units[0]
    units = [original]
    for index in range(100):
        claim = deepcopy(original["claim"])
        claim["proposition"] = ("SyntheticTool " * 30) + f"synthetic fixture {index}"
        unit = kb.knowledge.add_candidate(claim, run_id="synthetic-ranking-fixture", profile_id=kb.profiles["extraction"])
        assess(kb, unit)
        review(kb, unit)
        units.append(unit)
    current = publish(kb, units, expected=previous["id"])
    assert original["id"] not in {u["candidate_id"] for u in kb.knowledge.search("SyntheticTool", limit=100).units}
    resolved = kb.knowledge.resolve([original["id"]])
    assert resolved.units == [initial_unit]
    assert resolved.release_id == current["id"]
    assert resolved.governance_version == kb.ledger.get_state("governance_version")
    assert resolved.retrieval["method"] == "exact_candidate_ids"
    # Exact lookup has no ranking cutoff, preserves order and never substitutes
    # another candidate for an unknown ID or for a source ID.
    requested = [u["id"] for u in reversed(units)]
    assert [u["candidate_id"] for u in kb.knowledge.resolve(requested).units] == requested
    partial = kb.knowledge.resolve(["candidate-not-present", source["id"], original["id"]])
    assert partial.units == [initial_unit] and partial.gaps
    publish(kb, units[1:], expected=current["id"])
    assert not kb.knowledge.resolve([original["id"]]).units


@pytest.mark.parametrize("ids,purpose", [("candidate-id", "explanation"), ([None], "explanation"),
    ([{}], "explanation"), ([" "], "explanation"), (["a", "a"], "explanation"), ([], "execution")])
def test_exact_resolution_requires_explicit_distinct_ids_and_supported_purpose(kb, ids, purpose):
    with pytest.raises(KnowledgeError):
        kb.knowledge.resolve(ids, purpose=purpose)


@pytest.mark.parametrize("mutation", ["wrong_quote", "missing_block", "out_of_range", "wrong_ir"])
def test_bad_anchor_rejected_before_candidate_storage(kb, mutation):
    good, _, _ = candidate(kb)
    claim = deepcopy(good["claim"])
    anchor = claim["anchors"][0]
    if mutation == "wrong_quote":
        anchor["quote"] = "Z" * len(anchor["quote"])
    elif mutation == "missing_block":
        anchor["block_id"] = "missing-block"
    elif mutation == "out_of_range":
        anchor["start"] += 10000
        anchor["end"] += 10000
    else:
        anchor["ir_id"] = "missing-ir"
    with pytest.raises(KnowledgeError):
        kb.knowledge.add_candidate(claim, run_id="bad-run", profile_id=kb.profiles["extraction"])
    assert len(kb.ledger.list_records("candidate")) == 1


def test_invalid_anchor_contract_is_rejected(kb):
    good, _, _ = candidate(kb)
    claim = deepcopy(good["claim"])
    claim["anchors"][0]["start"] = -1
    with pytest.raises(ValidationError):
        kb.knowledge.add_candidate(claim, run_id="bad-run", profile_id=kb.profiles["extraction"])


def test_approval_requires_assessment_and_matching_successful_model_receipt(kb):
    unit, _, _ = candidate(kb)
    with pytest.raises(KnowledgeError, match="assessment"):
        review(kb, unit)
    result = {"relation": "support", "extent": "full", "rationale": "Fixture"}
    with pytest.raises(KnowledgeError, match="model_call"):
        kb.knowledge.assess(unit["id"], result, run_id="run", profile_id=kb.profiles["assessment"], call_id="missing")
    for status in ("partial", "invalid_response", "budget_exceeded", "failed"):
        with pytest.raises(KnowledgeError, match="successful"):
            assess(kb, unit, status=status)
    with pytest.raises(KnowledgeError, match="assessment profile"):
        assess(kb, unit, purpose="chat")
    assert not kb.ledger.list_records("assessment")
    assessment = assess(kb, unit)
    reviewed = review(kb, unit)
    assert reviewed["assessment_id"] == assessment["id"]


def test_receipt_from_different_profile_is_rejected(kb):
    unit, _, _ = candidate(kb)
    kb.ledger.put_record("model_call", "wrong-profile-call", {"profile_id": kb.profiles["chat"], "status": "succeeded"})
    with pytest.raises(KnowledgeError, match="matching model call"):
        kb.knowledge.assess(unit["id"], {"relation": "support", "extent": "full", "rationale": "Fixture"},
            run_id="run", profile_id=kb.profiles["assessment"], call_id="wrong-profile-call")


@pytest.mark.parametrize("relation,extent,kind", [("neutral", "full", "source_assertion"), ("support", "partial", "source_assertion"),
                                                ("indeterminate", "unknown", "source_assertion"), ("support", "full", "synthesis"), ("support", "full", "hypothesis")])
def test_recommendation_requires_full_support_for_source_assertion(kb, relation, extent, kind):
    unit, _, _ = candidate(kb, claim_updates={"assertion_kind": kind})
    assess(kb, unit, relation=relation, extent=extent)
    with pytest.raises(KnowledgeError, match="Recommendation requires"):
        review(kb, unit, uses=["recommendation"])
    review(kb, unit, uses=["explanation"])
    publish(kb, [unit])
    assert kb.knowledge.search("SyntheticTool", purpose="explanation").units
    assert not kb.knowledge.search("SyntheticTool", purpose="recommendation").units


def test_purpose_scope_and_latest_narrowed_review_take_effect(kb):
    unit, _, _ = approved(kb)
    publish(kb, [unit])
    assert kb.knowledge.search("SyntheticTool", purpose="recommendation").units
    assert kb.knowledge.resolve([unit["id"]], purpose="recommendation").units
    review(kb, unit, uses=["explanation"])
    assert not kb.knowledge.search("SyntheticTool", purpose="recommendation").units
    assert not kb.knowledge.resolve([unit["id"]], purpose="recommendation").units
    assert kb.knowledge.search("SyntheticTool", purpose="explanation").units[0]["allowed_uses"] == ["explanation"]
    assert kb.knowledge.resolve([unit["id"]], purpose="explanation").units[0]["allowed_uses"] == ["explanation"]
    assert kb.knowledge.current_release()["units"][0]["allowed_uses"] == ["explanation", "recommendation"]
    with pytest.raises(KnowledgeError):
        kb.knowledge.search("SyntheticTool", purpose="execution")


def test_failed_publish_is_atomic_after_projection_and_pointer_writes(kb, monkeypatch):
    first, _, _ = approved(kb)
    previous = publish(kb, [first])
    second, _, _ = approved(kb, text="SyntheticSecond supports another fixture workflow.")
    releases_before = kb.ledger.list_records("release")
    events_before = kb.ledger.events()
    with kb.ledger.connect() as conn:
        fts_before = [tuple(row) for row in conn.execute("SELECT * FROM release_search")]
    original_set_state = kb.ledger.set_state
    def injected_failure(key, value, *, conn=None):
        original_set_state(key, value, conn=conn)
        if key == "current_release":
            raise RuntimeError("Synthetic interruption after pointer write")
    monkeypatch.setattr(kb.ledger, "set_state", injected_failure)
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        publish(kb, [first, second], expected=previous["id"])
    assert kb.knowledge.current_release()["id"] == previous["id"]
    assert kb.ledger.list_records("release") == releases_before
    assert kb.ledger.events() == events_before
    with kb.ledger.connect() as conn:
        assert [tuple(row) for row in conn.execute("SELECT * FROM release_search")] == fts_before
    assert [unit["candidate_id"] for unit in kb.knowledge.search("").units] == [first["id"]]


def test_publish_manifest_replaces_not_accumulates_units(kb):
    first, _, _ = approved(kb)
    second, _, _ = approved(kb, text="SyntheticSecond has a different fixture purpose.")
    previous = publish(kb, [first, second])
    release = publish(kb, [second], expected=previous["id"])
    assert [unit["candidate_id"] for unit in release["units"]] == [second["id"]]
    assert [unit["candidate_id"] for unit in kb.knowledge.search("").units] == [second["id"]]


@pytest.mark.parametrize("kind", ["source", "candidate"])
def test_governance_suspension_survives_rollback(kb, kind):
    unit, source, _ = approved(kb)
    old = publish(kb, [unit])
    publish(kb, [], expected=old["id"])
    baseline_governance = kb.ledger.get_state("governance_version", 0)
    target = source["id"] if kind == "source" else unit["id"]
    kb.knowledge.suspend(kind, target, actor="fixture-reviewer", reason="Synthetic withdrawal")
    kb.knowledge.rollback(old["id"], actor="fixture-reviewer", reason="Synthetic rollback")
    package = kb.knowledge.search("SyntheticTool")
    assert not package.units
    assert package.governance_version == baseline_governance + 1
    exact = kb.knowledge.resolve([unit["id"]])
    assert not exact.units and exact.governance_version == baseline_governance + 1
    assert not kb.knowledge.graph()["nodes"]
    with pytest.raises(KnowledgeError, match="Suspended"):
        review(kb, unit)
    with pytest.raises(KnowledgeError, match="Suspended"):
        publish(kb, [unit], expected=old["id"])
    kb.knowledge.suspend(kind, target, actor="fixture-reviewer", reason="Synthetic restoration", suspended=False)
    assert kb.knowledge.search("SyntheticTool").units
    assert kb.knowledge.resolve([unit["id"]]).units
    assert kb.knowledge.search("SyntheticTool").governance_version == baseline_governance + 2


@pytest.mark.parametrize("decision", ["reject", "defer"])
def test_later_rejection_or_defer_invalidates_older_release(kb, decision):
    unit, _, _ = approved(kb)
    old = publish(kb, [unit])
    publish(kb, [], expected=old["id"])
    review(kb, unit, decision=decision)
    kb.knowledge.rollback(old["id"], actor="fixture-reviewer", reason="Synthetic rollback")
    assert not kb.knowledge.search("SyntheticTool").units
    assert not kb.knowledge.resolve([unit["id"]]).units
    assert not kb.knowledge.graph()["nodes"]


def test_reassessment_requires_fresh_review_and_release_even_after_rollback(kb):
    unit, _, _ = approved(kb)
    old = publish(kb, [unit])
    new_assessment = assess(kb, unit, relation="indeterminate", extent="unknown")
    assert not kb.knowledge.search("SyntheticTool").units
    assert not kb.knowledge.resolve([unit["id"]]).units
    with pytest.raises(KnowledgeError, match="reassessed"):
        publish(kb, [unit], expected=old["id"])
    review(kb, unit, uses=["explanation"])
    assert not kb.knowledge.search("SyntheticTool").units
    current = publish(kb, [unit], expected=old["id"])
    assert current["units"][0]["assessment_id"] == new_assessment["id"]
    assert kb.knowledge.search("SyntheticTool").units
    kb.knowledge.rollback(old["id"], actor="fixture-reviewer", reason="Synthetic rollback")
    assert not kb.knowledge.search("SyntheticTool").units


def test_graph_contains_only_published_eligible_evidence_neighborhood(kb):
    unit, source, _ = approved(kb)
    unseen, unseen_source, _ = candidate(kb, text="Unpublished fixture statement.")
    release = publish(kb, [unit])
    graph = kb.knowledge.graph()
    assert graph["scope"] == "evidence_graph"
    assert graph["limit"] == 100
    assert graph["release_id"] == release["id"]
    ids = {node["id"] for node in graph["nodes"]}
    assert ids == {unit["id"], source["id"]}
    assert unseen["id"] not in ids and unseen_source["id"] not in ids
    assert graph["edges"] == [{"source": source["id"], "target": unit["id"], "relation": "support"}]


def test_exact_repeated_candidate_records_each_run_without_destroying_source(kb):
    first, source, ir = candidate(kb)
    second = kb.knowledge.add_candidate(first["claim"], run_id="fixture-run-2", profile_id=kb.profiles["extraction"])
    assert first == second
    assert len(kb.ledger.list_records("candidate")) == 1
    events = [row for row in kb.ledger.events(first["id"]) if row["event_type"] == "candidate_observed"]
    assert [row["detail"]["run_id"] for row in events] == ["fixture-run-1", "fixture-run-2"]
    assert kb.ledger.get_record("source", source["id"]) == source
    assert kb.ledger.get_record("document_ir", ir["id"]) == ir
    assert kb.knowledge.evidence(first["id"])[0]["quote"] == first["claim"]["anchors"][0]["quote"]


def test_same_or_similar_claims_from_different_acquisitions_are_not_auto_merged(kb):
    first, first_source, _ = candidate(kb)
    same, same_source, _ = candidate(kb)
    similar, _, _ = candidate(kb, text="SyntheticTool supports an example workflow.")
    assert first_source["blob_sha256"] == same_source["blob_sha256"]
    assert len({unit["id"] for unit in (first, same, similar)}) == 3
    assert first["source_ids"] == [first_source["id"]]
    assert same["source_ids"] == [same_source["id"]]
    assert len(kb.ledger.list_records("candidate")) == 3


@pytest.mark.parametrize("damage", ["changed", "missing", "symlink"])
def test_corrupt_or_missing_original_excluded_at_query_time(kb, damage, tmp_path):
    unit, source, _ = approved(kb)
    publish(kb, [unit])
    blob = kb.sources.blob_dir / source["blob_sha256"]
    if damage == "changed":
        blob.write_bytes(b"Tampered synthetic fixture")
    else:
        content = blob.read_bytes()
        blob.unlink()
        if damage == "symlink":
            outside = tmp_path / "outside-original.txt"
            outside.write_bytes(content)
            blob.symlink_to(outside)
    package = kb.knowledge.search("SyntheticTool")
    assert not package.units
    assert any("损坏" in gap for gap in package.gaps)
    exact = kb.knowledge.resolve([unit["id"]])
    assert not exact.units and any("损坏" in gap for gap in exact.gaps)
    assert not kb.knowledge.graph()["nodes"]


def test_optimistic_revision_conflicts_do_not_change_review_or_release(kb):
    unit, _, _ = approved(kb)
    previous_review = kb.ledger.get_state("review:" + unit["id"])
    with pytest.raises(KnowledgeError, match="Candidate changed"):
        review(kb, unit, expected_hash="stale-candidate-hash")
    assert kb.ledger.get_state("review:" + unit["id"]) == previous_review
    release = publish(kb, [unit])
    with pytest.raises(KnowledgeError, match="Release changed"):
        publish(kb, [], expected=None)
    assert kb.knowledge.current_release() == release
    assert kb.knowledge.search("SyntheticTool").units


@pytest.mark.parametrize("actor,reason", [("", "reason"), ("actor", ""), (" ", "reason")])
def test_human_actions_require_actor_and_reason(kb, actor, reason):
    unit, _, _ = candidate(kb)
    with pytest.raises(KnowledgeError, match="human actor"):
        kb.knowledge.review(unit["id"], actor=actor, reason=reason, decision="reject", allowed_uses=[], expected_hash=unit["content_hash"])


def test_query_syntax_is_not_interpreted_as_raw_fts_expression(kb):
    unit, _, _ = approved(kb)
    publish(kb, [unit])
    package = kb.knowledge.search('SyntheticTool\" OR near(foo,bar) --')
    assert [row["candidate_id"] for row in package.units] == [unit["id"]]
    assert not kb.knowledge.search("zzzznonexistentterm").units
    for limit in (0, 101, True):
        with pytest.raises(KnowledgeError):
            kb.knowledge.search("SyntheticTool", limit=limit)


def test_successful_receipt_for_other_candidate_cannot_be_reused(kb):
    first, _, _ = candidate(kb)
    second, _, _ = candidate(kb, text="SyntheticSecond has unrelated fixture evidence.")
    assessment = assess(kb, first)
    with pytest.raises(KnowledgeError, match="input|candidate|evidence"):
        kb.knowledge.assess(second["id"], assessment["result"], run_id="attempted-reuse",
            profile_id=kb.profiles["assessment"], call_id=assessment["call_id"])
    assert kb.ledger.get_state("assessment:" + second["id"]) is None


def test_assessment_output_cannot_be_changed_after_model_call(kb):
    unit, _, _ = candidate(kb)
    original = assess(kb, unit, relation="indeterminate", extent="unknown")
    altered = {**original["result"], "relation": "support", "extent": "full"}
    with pytest.raises(KnowledgeError, match="output|response|result"):
        kb.knowledge.assess(unit["id"], altered, run_id="attempted-output-rewrite",
            profile_id=kb.profiles["assessment"], call_id=original["call_id"])
    assert kb.ledger.get_state("assessment:" + unit["id"]) == original["id"]


def test_optimistic_assessment_conflict_rejects_stale_review(kb):
    unit, _, _ = candidate(kb)
    previous = assess(kb, unit)
    latest = assess(kb, unit, relation="indeterminate", extent="unknown")
    with pytest.raises(KnowledgeError, match="assessment|Assessment"):
        kb.knowledge.review(unit["id"], actor="fixture-reviewer", decision="approve", allowed_uses=["explanation"],
            reason="Stale screen", expected_hash=unit["content_hash"], expected_assessment_id=previous["id"])
    assert kb.ledger.get_state("review:" + unit["id"]) is None
    assert kb.ledger.get_state("assessment:" + unit["id"]) == latest["id"]


def test_assessment_replay_preserves_published_review_and_governance(kb):
    unit, _, _ = approved(kb)
    release = publish(kb, [unit])
    assessment_id = kb.ledger.get_state("assessment:" + unit["id"])
    assessment = kb.ledger.get_record("assessment", assessment_id)
    review_id = kb.ledger.get_state("review:" + unit["id"])
    governance = kb.ledger.get_state("governance_version", 0)
    events = kb.ledger.events()
    replay = kb.knowledge.assess(unit["id"], assessment["result"], run_id="retry-run",
        profile_id=kb.profiles["assessment"], call_id=assessment["call_id"])
    assert replay == assessment
    assert kb.ledger.get_state("assessment:" + unit["id"]) == assessment_id
    assert kb.ledger.get_state("review:" + unit["id"]) == review_id
    assert kb.ledger.get_state("governance_version", 0) == governance
    assert kb.ledger.events() == events
    assert kb.knowledge.current_release() == release
    assert [row["candidate_id"] for row in kb.knowledge.search("SyntheticTool").units] == [unit["id"]]


def test_old_assessment_replay_cannot_rollback_latest_judgment(kb):
    unit, _, _ = candidate(kb)
    old = assess(kb, unit)
    latest = assess(kb, unit, relation="indeterminate", extent="unknown")
    review(kb, unit, uses=["explanation"])
    release = publish(kb, [unit])
    review_id = kb.ledger.get_state("review:" + unit["id"])
    governance = kb.ledger.get_state("governance_version", 0)
    events = kb.ledger.events()
    replay = kb.knowledge.assess(unit["id"], old["result"], run_id="late-retry",
        profile_id=kb.profiles["assessment"], call_id=old["call_id"])
    assert replay == old
    assert kb.ledger.get_state("assessment:" + unit["id"]) == latest["id"]
    assert kb.ledger.get_state("review:" + unit["id"]) == review_id
    assert kb.ledger.get_state("governance_version", 0) == governance
    assert kb.ledger.events() == events
    assert kb.knowledge.current_release() == release
    package = kb.knowledge.search("SyntheticTool")
    assert package.units[0]["assessment"]["relation"] == "indeterminate"
    assert not kb.knowledge.search("SyntheticTool", purpose="recommendation").units


@pytest.mark.parametrize("lease_state", ["expired", "cancel_requested"])
@pytest.mark.parametrize("mutation", ["candidate", "assessment"])
def test_invalid_worker_lease_cannot_mutate_knowledge_or_old_review(kb, lease_state, mutation):
    unit, _, _ = approved(kb)
    release = publish(kb, [unit])
    clock = [1000.0]
    queue = TaskQueue(kb.ledger.workspace, clock=lambda: clock[0])
    queued = queue.submit("synthetic-ingestion", {}, {}, {"max_calls": 2, "max_tokens": 1000, "max_cost": 1.0}, "synthetic-lease-task")
    task = queue.claim("synthetic-worker", lease_seconds=10)
    assert task["task_id"] == queued["task_id"]
    if lease_state == "expired":
        clock[0] = 1011.0
        error_type = LeaseLost
    else:
        queue.request_cancel(task["task_id"])
        error_type = InvalidTransition

    # Exercise the real Worker's guard against the real task row. The guard
    # receives the same SQLite transaction used by KnowledgeService writes.
    guard_context = SimpleNamespace(queue=queue)
    def guard(conn):
        Worker._guard(guard_context, task, conn)

    before_candidates = kb.ledger.list_records("candidate")
    before_assessments = kb.ledger.list_records("assessment")
    before_events = kb.ledger.events()
    before_assessment_id = kb.ledger.get_state("assessment:" + unit["id"])
    before_review_id = kb.ledger.get_state("review:" + unit["id"])
    before_governance = kb.ledger.get_state("governance_version", 0)
    with pytest.raises(error_type):
        if mutation == "candidate":
            changed = deepcopy(unit["claim"])
            changed["proposition"] = "An additional synthetic candidate from a stale worker."
            kb.knowledge.add_candidate(changed, run_id=task["task_id"], profile_id=kb.profiles["extraction"], lease_guard=guard)
        else:
            assess(kb, unit, relation="indeterminate", extent="unknown", lease_guard=guard)
    assert kb.ledger.list_records("candidate") == before_candidates
    assert kb.ledger.list_records("assessment") == before_assessments
    assert kb.ledger.events() == before_events
    assert kb.ledger.get_state("assessment:" + unit["id"]) == before_assessment_id
    assert kb.ledger.get_state("review:" + unit["id"]) == before_review_id
    assert kb.ledger.get_state("governance_version", 0) == before_governance
    assert kb.knowledge.current_release() == release
    assert kb.knowledge.search("SyntheticTool", purpose="recommendation").units


def test_concurrently_changed_review_manifest_rejects_publication(kb):
    unit, _, _ = approved(kb)
    old_release = publish(kb, [unit])
    expected_reviews = {unit["id"]: kb.ledger.get_state("review:" + unit["id"])}
    new_review = review(kb, unit, uses=["explanation"])
    assert new_review["id"] != expected_reviews[unit["id"]]
    before_events = kb.ledger.events()
    before_releases = kb.ledger.list_records("release")
    with pytest.raises(KnowledgeError, match="Review manifest changed"):
        kb.knowledge.publish([unit["id"]], actor="fixture-reviewer", expected_release_id=old_release["id"], expected_review_ids=expected_reviews)
    assert kb.knowledge.current_release() == old_release
    assert kb.ledger.list_records("release") == before_releases
    assert kb.ledger.events() == before_events
    fresh = kb.knowledge.publish([unit["id"]], actor="fixture-reviewer", expected_release_id=old_release["id"],
        expected_review_ids={unit["id"]: new_review["id"]})
    assert fresh["units"][0]["review_id"] == new_review["id"]
    assert fresh["units"][0]["allowed_uses"] == ["explanation"]


def test_later_broader_review_does_not_advertise_an_unpublished_use(kb):
    unit, _, _ = candidate(kb)
    assess(kb, unit)
    review(kb, unit, uses=["explanation"])
    release = publish(kb, [unit])
    review(kb, unit, uses=["explanation", "recommendation"])
    assert kb.knowledge.resolve([unit["id"]]).units[0]["allowed_uses"] == ["explanation"]
    assert kb.knowledge.search("SyntheticTool").units[0]["allowed_uses"] == ["explanation"]
    assert not kb.knowledge.resolve([unit["id"]], purpose="recommendation").units
    assert kb.knowledge.current_release() == release
