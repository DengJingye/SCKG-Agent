from __future__ import annotations

import json

from core.knowledge_intelligence_models import HybridRetrievalRequest
from engine.evidence_discovery_index import EvidenceChunk, chunk_to_dict
from engine.hybrid_retrieval import HybridRetrievalService
from engine.scientific_kg_applicability import ScientificKGApplicability
from engine.knowledge_foundation_safety import (
    can_feed_is_actionable,
    candidate_scope_can_be_trusted,
    dense_runtime_status,
    formal_evidence_is_quarantined,
    load_knowledge_foundation_policy,
    version_binding_status,
)
from eval.knowledge_foundation_p0a import evaluate_knowledge_foundation_p0a
from eval.scientific_action_space_demo_v1 import demo_scenarios


def _write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in values),
        encoding="utf-8",
    )


def test_dense_unavailability_is_explicit_and_matches_runtime_artifacts() -> None:
    status = dense_runtime_status()

    assert status["declared_status"] == "unavailable"
    assert status["loadable_dense_index"] is False
    assert status["availability_consistent"] is True
    assert status["fallback"] == "kg_plus_sqlite_fts5_bm25"
    assert all(not value.startswith("/") for value in status["required_runtime_artifacts"])


def test_all_known_unbound_formal_chunks_are_generically_quarantined() -> None:
    policy = load_knowledge_foundation_policy()
    rows = [
        json.loads(line)
        for line in open("data/indexes/evidence_chunks.jsonl", encoding="utf-8")
        if line.strip()
    ]
    discovered = {
        row["chunk_id"]
        for row in rows
        if formal_evidence_is_quarantined(row, policy=policy)
    }

    assert discovered == set(
        policy["formal_evidence_quarantine"]["known_unbound_chunk_ids"]
    )
    assert len(discovered) == 10


def test_unbound_formal_chunk_cannot_be_retrieved_or_inferred_source_bound(
    tmp_path,
) -> None:
    index_dir = tmp_path / "indexes"
    unbound = EvidenceChunk(
        chunk_id="benchmark:unbound",
        evidence_id="benchmark-1",
        source_kind="benchmark",
        source_type="formal_benchmark_tsv",
        source_table="benchmarks.tsv",
        source_record_id="benchmark-1",
        source_id="benchmark-1",
        source_span="A title is not an exact evidence span",
        tool_name="ExampleTool",
        tool_names=["ExampleTool"],
        chunk_text="ExampleTool was benchmarked on a dataset.",
        source_bound=False,
        trust_level="trusted_core",
        retrieval_status="formal_frozen_retrieval_only",
    )
    bound = EvidenceChunk(
        chunk_id="source:bound",
        evidence_id="source-1",
        source_kind="source_document",
        source_type="official_docs_html",
        source_table="sources.jsonl",
        source_record_id="source-1",
        source_id="source-1",
        source_span="section:inputs",
        tool_name="ExampleTool",
        tool_names=["ExampleTool"],
        chunk_text="ExampleTool accepts a source-bound matrix input.",
        source_bound=True,
        retrieval_status="retrieval_only",
    )
    _write_jsonl(
        index_dir / "evidence.jsonl",
        [chunk_to_dict(unbound), chunk_to_dict(bound)],
    )
    _write_jsonl(index_dir / "catalog.jsonl", [])
    (index_dir / "manifest.json").write_text(
        json.dumps({"build_id": "p0a-quarantine"}), encoding="utf-8"
    )
    service = HybridRetrievalService(
        evidence_chunks_path=index_dir / "evidence.jsonl",
        catalog_chunks_path=index_dir / "catalog.jsonl",
        fts_index_path=index_dir / "fts.sqlite",
        index_manifest_path=index_dir / "manifest.json",
        coverage_path=index_dir / "coverage.json",
        graph_dir=tmp_path / "missing",
    )

    result = service.search(
        HybridRetrievalRequest(
            query="ExampleTool benchmark matrix",
            tool_names=["ExampleTool"],
            enable_dense=False,
            use_kg=False,
        )
    )

    assert [hit.chunk_id for hit in result.hits] == ["source:bound"]
    assert result.hits[0].source_bound is True


def test_version_mismatches_are_explicit_unknown_and_execution_blocked() -> None:
    for tool_name, versions in (
        ("Harmony", ("2.0.5", "2.0.0")),
        ("SingleR", ("2.14.1", "2.14.0")),
    ):
        row = version_binding_status(tool_name)
        assert row is not None
        assert (row["scientific_version"], row["contract_version"]) == versions
        assert row["compatibility"] == "unknown"
        assert row["execution_binding"].startswith("blocked_")


def test_candidate_can_feed_requires_acceptance_and_review_decision() -> None:
    pending = {
        "relation": "CAN_FEED",
        "review_status": "candidate_pending_review",
        "review_decision_ids": [],
    }
    accepted_without_decision = {
        "relation": "CAN_FEED",
        "review_status": "accepted",
        "review_decision_ids": [],
    }
    accepted = {
        "relation": "CAN_FEED",
        "review_status": "accepted",
        "review_decision_ids": ["review:compatibility:1"],
    }

    assert can_feed_is_actionable(pending) is False
    assert can_feed_is_actionable(accepted_without_decision) is False
    assert can_feed_is_actionable(accepted) is True


def test_pending_can_feed_is_explanatory_only_not_behavior_actionable() -> None:
    ledger = next(
        ledger
        for scenario_id, _target, ledger in demo_scenarios()
        if scenario_id == "harmony-embedding-to-neighbors"
    )
    adapter = ScientificKGApplicability()
    with_pending_relations = adapter.assess(
        action_id="scanpy_core.neighbors_integrated",
        ledger=ledger,
    )
    adapter.relations = {
        key: relation
        for key, relation in adapter.relations.items()
        if relation.relation != "CAN_FEED"
    }
    without_pending_relations = adapter.assess(
        action_id="scanpy_core.neighbors_integrated",
        ledger=ledger,
    )

    assert with_pending_relations is not None
    assert without_pending_relations is not None
    assert with_pending_relations.applicable == without_pending_relations.applicable
    assert with_pending_relations.blocked == without_pending_relations.blocked
    assert (
        with_pending_relations.reusable_representation_record_ids
        == without_pending_relations.reusable_representation_record_ids
    )
    assert (
        with_pending_relations.missing_requirements
        == without_pending_relations.missing_requirements
    )


def test_candidate_scope_cannot_be_silently_treated_as_trusted() -> None:
    policy = load_knowledge_foundation_policy()

    assert policy["candidate_scope"]["reported_knowledge_status"] == "candidate"
    assert candidate_scope_can_be_trusted(policy=policy) is False
    assert policy["candidate_scope"]["canonical_promotion"] == "none"


def test_p0a_repository_gates_pass_without_promoting_knowledge() -> None:
    result = evaluate_knowledge_foundation_p0a()

    assert result["decision"] == "PASS"
    assert result["dense"]["loadable_dense_index"] is False
    assert result["formal_evidence"]["non_source_bound_scientific_chunks_eligible"] == 0
    assert result["version_identity"]["silent_version_mismatch_count"] == 0
    assert result["candidate_relations"]["candidate_can_feed_count"] == 66
    assert result["candidate_relations"]["actionable_unreviewed_CAN_FEED_count"] == 0
    assert result["candidate_scope"]["candidate_to_trusted_leakage_count"] == 0
