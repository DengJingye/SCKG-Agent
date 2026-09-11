from __future__ import annotations

from eval.scientific_action_space_demo_v1 import run_demo


def _by_scenario() -> dict[str, dict]:
    return {item["scenario_id"]: item for item in run_demo()}


def test_valid_neighbor_graph_enables_leiden_without_rerunning_upstream_steps() -> None:
    result = _by_scenario()["valid-neighbor-graph-to-leiden"]

    assert [item["action_id"] for item in result["applicable_actions"]] == [
        "scanpy_core.leiden"
    ]
    assert result["blocked_actions"] == []
    assert [
        item["representation_id"] for item in result["reused_representations"]
    ] == ["neighbor_graph"]
    projection = result["applicable_actions"][0]["planner_projection"]
    assert projection["status"] == "planned"
    assert projection["planned_method_ids"] == ["scanpy_core.leiden"]
    assert projection["reused_representation_ids"] == ["neighbor_graph"]
    assert not any(
        "pca" in method_id or "neighbors" in method_id
        for method_id in projection["planned_method_ids"]
    )
    assert "derived-relation:uat:can-feed:b6a052e7eb55205e" in result[
        "kg_facts_requirements_consulted"
    ]["derived_relation_ids"]


def test_stale_and_observation_misaligned_graph_reuse_is_explicitly_blocked() -> None:
    result = _by_scenario()["stale-or-misaligned-graph"]

    assert result["applicable_actions"] == []
    assert result["reused_representations"] == []
    assert [item["action_id"] for item in result["blocked_actions"]] == [
        "scanpy_core.leiden"
    ]
    reasons = set(result["blocked_actions"][0]["reason_codes"])
    assert "representation_stale" in reasons
    assert "observation_identity_mismatch" in reasons
    assert "missing_compatible_representation" in reasons
    rejected = {
        item["representation_record_id"]: set(item["reason_codes"])
        for item in result["missing_requirements"][0]["rejected_records"]
    }
    assert "representation_stale" in rejected["rep:demo:neighbor-graph:stale"]
    assert "observation_identity_mismatch" in rejected[
        "rep:demo:neighbor-graph:misaligned"
    ]


def test_harmony_embedding_enables_neighbors_without_forcing_pca() -> None:
    result = _by_scenario()["harmony-embedding-to-neighbors"]

    assert result["blocked_actions"] == []
    assert [
        item["representation_id"] for item in result["reused_representations"]
    ] == ["integrated_representation"]
    projection = result["applicable_actions"][0]["planner_projection"]
    assert projection["planned_method_ids"] == ["scanpy_core.neighbors_integrated"]
    assert projection["reused_representation_ids"] == ["integrated_representation"]
    assert all("pca" not in method_id for method_id in projection["planned_method_ids"])
    consulted = result["kg_facts_requirements_consulted"]
    assert "derived-relation:uat:can-feed:b40562c4d5040f73" in consulted[
        "derived_relation_ids"
    ]
    assert "claim-revision:uat:harmony-output:v1" in consulted[
        "claim_revision_ids"
    ]


def test_scrublet_blocks_transformed_inputs_and_requests_preserved_raw_counts() -> None:
    result = _by_scenario()["scrublet-rejects-transformed-expression"]

    assert result["applicable_actions"] == []
    assert result["reused_representations"] == []
    assert result["blocked_actions"][0]["action_id"] == "scrublet.scrub_doublets"
    missing = result["missing_requirements"][0]
    assert missing["requirement_ids"] == ["requirement:uat:scrublet:raw-counts"]
    assert missing["constraint_ids"] == [
        "representation-constraint:uat:scrublet-raw"
    ]
    assert missing["required_representation_type_ids"] == [
        "representation-type:raw_umi_counts"
    ]
    reasons = {
        reason
        for item in missing["rejected_records"]
        for reason in item["reason_codes"]
    }
    assert "forbidden_transformation:normalized" in reasons
    assert (
        "representation_type_mismatch:representation-type:raw_umi_counts" in reasons
    )
    assert "claim-revision:uat:scrublet-input:v1" in result[
        "kg_facts_requirements_consulted"
    ]["claim_revision_ids"]


def test_every_explanation_is_bound_to_exact_authoritative_candidate_evidence() -> None:
    results = _by_scenario().values()

    for result in results:
        assert result["evidence_provenance"]
        assert all(item["source_bound"] is True for item in result["evidence_provenance"])
        assert all(item["evidence_span_id"] for item in result["evidence_provenance"])
        assert all(item["source_revision_id"] for item in result["evidence_provenance"])
        assert all(item["locator"] for item in result["evidence_provenance"])
        assert all(len(item["content_hash"]) == 64 for item in result["evidence_provenance"])


def test_demo_reports_candidate_only_boundary_without_mutating_production_state() -> None:
    results = _by_scenario()

    assert set(results) == {
        "valid-neighbor-graph-to-leiden",
        "stale-or-misaligned-graph",
        "harmony-embedding-to-neighbors",
        "scrublet-rejects-transformed-expression",
    }
    for result in results.values():
        assert result["kg_facts_requirements_consulted"]["scope"]["version_constraints"]
