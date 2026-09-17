from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_pipeline.build_midterm_core_seed_v0 import (
    CONTRACT_SHA256,
    OUTPUT,
    REVIEW_DATE,
    REVIEW_DECISION,
    REVIEWER_REASON,
    REVIEWER_ROLE,
    build,
)
from eval.midterm_core_benchmark_v2_1_models import (
    BenchmarkSeedBundle,
    EvaluationRecord,
    EvidenceGold,
    LearningEpisode,
    ParentScenario,
    RequirementExpectation,
    RequirementGold,
    WorkflowGold,
    aggregate_requirement_action,
)


ROOT = Path(__file__).resolve().parents[1]
GOLD = OUTPUT / "gold" / "midterm_core_seed_v0"
MANIFESTS = OUTPUT / "manifests"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(scope="module", autouse=True)
def built_seed():
    return build()


def test_six_required_schemas_validate_seed_records():
    scenarios = [ParentScenario.model_validate(x) for x in _jsonl(GOLD / "parent_scenarios.jsonl")]
    records = [EvaluationRecord.model_validate(x) for x in _jsonl(GOLD / "evaluation_records.jsonl")]
    workflows = [WorkflowGold.model_validate(x) for x in _jsonl(GOLD / "workflow_gold.jsonl")]
    requirements = [RequirementGold.model_validate(x) for x in _jsonl(GOLD / "requirement_gold.jsonl")]
    evidence = [EvidenceGold.model_validate(x) for x in _jsonl(GOLD / "evidence_gold.jsonl")]
    learning = [LearningEpisode.model_validate(x) for x in _jsonl(GOLD / "learning_episodes.jsonl")]
    assert len(scenarios) == 9
    assert len(records) == 55
    assert len(workflows) == 12
    assert len(requirements) == 12
    assert len(evidence) == 26
    assert len(learning) == 3


def test_seed_budget_and_historical_new_mix():
    manifest = _json(MANIFESTS / "midterm_core_seed_v0.json")
    counts = manifest["counts"]
    assert counts["parent_scenarios"] == 9
    assert counts["historical_anchors"] == 4
    assert counts["new_development_scenarios"] == 5
    assert counts["evidence_atoms"] == 26
    assert counts["evidence_decisions"] == 8
    assert counts["real_data_studies"] == 3
    assert counts["real_data_paths"] == 4
    assert counts["acquisition_episodes"] == 3
    assert counts["learning_episodes"] == 3
    assert counts["governance_boundary_cases"] == 4
    assert counts["fault_injections"] == 8
    assert counts["records_by_track"]["G0"] == 7
    assert counts["records_by_track"]["T1"] == 9
    assert counts["records_by_track"]["T2"] == 9
    assert counts["records_by_track"]["T3"] == 8


def test_parent_child_split_inheritance_and_no_holdout():
    parents = {
        row["scenario_id"]: row for row in _jsonl(GOLD / "parent_scenarios.jsonl")
    }
    descendants = []
    for name in (
        "workflow_gold.jsonl",
        "requirement_gold.jsonl",
        "evidence_gold.jsonl",
        "learning_episodes.jsonl",
        "evaluation_records.jsonl",
    ):
        descendants.extend(_jsonl(GOLD / name))
    for row in descendants:
        assert row["split"] == parents[row["parent_scenario_id"]]["split"]
    assert {row["split"] for row in parents.values()} == {"development"}
    assert _json(MANIFESTS / "midterm_core_seed_v0.json")[
        "formal_holdout_constructed"
    ] is False


def test_bundle_rejects_cross_split_derived_records():
    payload = {
        "parent_scenarios": _jsonl(GOLD / "parent_scenarios.jsonl"),
        "evaluation_records": _jsonl(GOLD / "evaluation_records.jsonl"),
        "workflow_gold": _jsonl(GOLD / "workflow_gold.jsonl"),
        "requirement_gold": _jsonl(GOLD / "requirement_gold.jsonl"),
        "evidence_gold": _jsonl(GOLD / "evidence_gold.jsonl"),
        "learning_episodes": _jsonl(GOLD / "learning_episodes.jsonl"),
    }
    payload["workflow_gold"][0]["split"] = "frozen_holdout"
    with pytest.raises(ValidationError, match="crossed parent split"):
        BenchmarkSeedBundle.model_validate(payload)


def test_workflow_gold_has_equivalence_contract_not_unique_dag():
    rows = _jsonl(GOLD / "workflow_gold.jsonl")
    assert all(row["required_final_states"] for row in rows)
    assert all(row["acceptable_terminal_states"] for row in rows)
    assert any(row["acceptable_method_alternatives"] for row in rows)
    invalid = dict(rows[0], expected_dag=["pca", "neighbors", "leiden"])
    with pytest.raises(ValidationError):
        WorkflowGold.model_validate(invalid)


def test_requirement_states_overlap_and_aggregation_is_deterministic():
    satisfied = RequirementExpectation(
        requirement_id="requirement-gold:test:satisfied",
        expected_state="SATISFIED",
        rationale="present",
        evidence_required=False,
        criticality="hard",
        resolution_mode="none",
    )
    unknown = RequirementExpectation(
        requirement_id="requirement-gold:test:unknown",
        expected_state="UNKNOWN",
        rationale="not known",
        evidence_required=True,
        criticality="hard",
        resolution_mode="ask_user",
    )
    missing = RequirementExpectation(
        requirement_id="requirement-gold:test:missing",
        expected_state="MISSING",
        rationale="absent",
        evidence_required=False,
        criticality="hard",
        resolution_mode="provide_resource",
    )
    schedulable = RequirementExpectation(
        requirement_id="requirement-gold:test:schedulable",
        expected_state="MISSING",
        rationale="absent now but derivable in the plan",
        evidence_required=True,
        criticality="hard",
        resolution_mode="schedule_prerequisite",
    )
    violated = RequirementExpectation(
        requirement_id="requirement-gold:test:violated",
        expected_state="VIOLATED",
        rationale="incompatible",
        evidence_required=True,
        criticality="hard",
        resolution_mode="select_other",
    )
    assert aggregate_requirement_action([satisfied]) == "ALLOW"
    assert aggregate_requirement_action([satisfied, unknown]) == "CLARIFY"
    assert aggregate_requirement_action([satisfied, missing]) == "BLOCK"
    assert aggregate_requirement_action([satisfied, schedulable]) == "ALLOW"
    assert aggregate_requirement_action([unknown, violated]) == "BLOCK"


def test_requirement_gold_rejects_inconsistent_action():
    row = _jsonl(GOLD / "requirement_gold.jsonl")[0]
    with pytest.raises(ValidationError):
        RequirementGold.model_validate(dict(row, expected_action="BLOCK"))


def test_independent_gold_boundary_and_runtime_citation_abstention():
    provenance = _json(GOLD / "gold_provenance.json")
    assert provenance["generated_from_current_kg"] is False
    assert provenance["generated_from_current_planner"] is False
    assert provenance["generated_from_current_evaluator"] is False
    assert provenance["human_review_complete"] is True
    assert provenance["review_decision"] == REVIEW_DECISION
    assert provenance["reviewer_role"] == REVIEWER_ROLE
    assert provenance["review_date"] == REVIEW_DATE
    assert provenance["reviewer_reason"] == REVIEWER_REASON
    assert provenance["independent_external_expert_review"] is False
    rows = [EvidenceGold.model_validate(x) for x in _jsonl(GOLD / "evidence_gold.jsonl")]
    assert all(row.gold_origin == "independent_source_adjudication_draft" for row in rows)
    runtime = [row for row in rows if row.owner == "RepresentationLedger"]
    assert runtime
    assert all(not row.evidence_required and not row.allowed_evidence_spans for row in runtime)


def test_allowed_evidence_spans_resolve_in_existing_source_bound_artifacts():
    resolved = set()
    for path in (
        ROOT
        / "data/evidence_candidates/scientific_kg_v1_uat_decision_rules"
        / "authoritative_evidence_spans.jsonl",
        ROOT
        / "data/evidence_candidates/scientific_kg_content_expansion_v1"
        / "evidence_span_references.jsonl",
        GOLD / "scientific_source_provenance.jsonl",
    ):
        resolved.update(row["evidence_span_id"] for row in _jsonl(path))
    allowed = {
        span
        for row in _jsonl(GOLD / "evidence_gold.jsonl")
        for span in row["allowed_evidence_spans"]
    }
    assert len(allowed) == 18
    assert allowed <= resolved


def test_evidence_required_needs_span_or_explicit_gap():
    row = _jsonl(GOLD / "evidence_gold.jsonl")[0]
    with pytest.raises(ValidationError):
        EvidenceGold.model_validate(
            dict(row, allowed_evidence_spans=[], evidence_gap_ids=[])
        )


def test_learning_conditions_are_isolated_and_hidden_query_is_unseen():
    episodes = [
        LearningEpisode.model_validate(x)
        for x in _jsonl(GOLD / "learning_episodes.jsonl")
    ]
    for episode in episodes:
        assert episode.original_query != episode.hidden_related_query
        assert episode.hidden_related_query not in episode.claim_construction_visible_queries
        assert [item.condition for item in episode.conditions] == ["S0", "S1", "S2"]
        assert len({item.knowledge_snapshot_id for item in episode.conditions}) == 3
        assert episode.conditions[1].evidence_artifact_id == episode.conditions[2].evidence_artifact_id
        assert episode.conditions[0].evidence_artifact_id is None
        assert episode.conditions[1].candidate_claim_id is None
        assert episode.conditions[2].candidate_claim_id


def test_hidden_query_leak_is_rejected():
    row = _jsonl(GOLD / "learning_episodes.jsonl")[0]
    row["claim_construction_visible_queries"].append(row["hidden_related_query"])
    with pytest.raises(ValidationError):
        LearningEpisode.model_validate(row)


def test_every_record_declares_baseline_and_denominator_metadata():
    records = [
        EvaluationRecord.model_validate(x)
        for x in _jsonl(GOLD / "evaluation_records.jsonl")
    ]
    for record in records:
        assert record.baseline_eligibility.eligible_baselines
        assert record.baseline_eligibility.shared_inputs
        assert record.baseline_eligibility.intentionally_varied_capability
        assert record.denominator.denominator_id
    excluded = [record for record in records if not record.denominator.included]
    assert {record.record_id for record in excluded} == {
        "record:v2.1:t4:pancreas-reference-annotation",
        "record:v2.1:t4:pancreas-batch-aware",
    }
    assert all(
        record.denominator.exclusion_reason == "CANDIDATE_REAL_DATA_NOT_FROZEN"
        for record in excluded
    )
    assert all(record.track == "T4" for record in excluded)


def test_real_data_candidates_are_distinct_and_not_both_pbmc():
    studies = _json(MANIFESTS / "real_data_studies_seed_v0.json")["studies"]
    assert len(studies) == 3
    assert len({row["study_id"] for row in studies}) == 3
    assert studies[0]["role"] == "PBMC historical anchor"
    assert all("non-PBMC" in row["role"] for row in studies[1:])
    assert all(row["artifact_status"] == "candidate_not_acquired" for row in studies[1:])
    assert sum(len(row["workflow_paths"]) for row in studies) == 4


def test_scientific_adjudication_revisions_are_explicit_and_remain_draft():
    workflows = {row["workflow_gold_id"]: row for row in _jsonl(GOLD / "workflow_gold.jsonl")}
    requirements = {
        row["requirement_gold_id"]: row
        for row in _jsonl(GOLD / "requirement_gold.jsonl")
    }
    evidence = {row["evidence_gold_id"]: row for row in _jsonl(GOLD / "evidence_gold.jsonl")}

    assert "governed" not in evidence[
        "evidence-gold:v2.1:neighbor-graph-reuse-leiden:leiden-input"
    ]["claim"]
    assert "composition inference" in requirements[
        "requirement-gold-set:v2.1:harmony-embedding-neighbors"
    ]["requirements"][2]["rationale"]

    scrublet_ids = {key for key in evidence if ":scrublet-transformed-input:" in key}
    assert scrublet_ids == {
        "evidence-gold:v2.1:scrublet-transformed-input:raw-input",
    }
    assert all("sample" not in evidence[key]["claim"].lower() for key in scrublet_ids)

    hvg_sets = {
        key: value for key, value in requirements.items() if ":hvg-flavor-" in key
    }
    assert set(hvg_sets) == {
        "requirement-gold-set:v2.1:hvg-flavor-seurat",
        "requirement-gold-set:v2.1:hvg-flavor-seurat-v3",
        "requirement-gold-set:v2.1:hvg-flavor-default-seurat",
    }
    assert hvg_sets["requirement-gold-set:v2.1:hvg-flavor-default-seurat"]["expected_action"] == "ALLOW"
    assert hvg_sets["requirement-gold-set:v2.1:hvg-flavor-seurat"]["expected_action"] == "ALLOW"
    assert all(row["expected_action"] != "CLARIFY" for row in hvg_sets.values())
    assert hvg_sets["requirement-gold-set:v2.1:hvg-flavor-default-seurat"]["requirements"][1]["resolution_mode"] == "schedule_prerequisite"
    assert workflows["workflow-gold:v2.1:hvg-flavor-default-seurat"]["acceptable_terminal_states"] == ["completed", "plan_only"]

    assert workflows["workflow-gold:v2.1:mofa2-sample-alignment"]["optional_operations"] == []
    assert workflows[
        "workflow-gold:v2.1:mofa2-sample-alignment"
    ]["required_prerequisites"] == [
        "multiple_omics_matrices",
        "same_or_overlapping_samples_supported",
        "explicit_sample_identity_alignment",
    ]
    assert all(row["review_status"] == "reviewed" for row in evidence.values())

    celltypist = {
        key: row for key, row in evidence.items() if ":celltypist-model-feature-alignment:" in key
    }
    assert celltypist[
        "evidence-gold:v2.1:celltypist-model-feature-alignment:feature-overlap-guidance"
    ]["owner"] == "ScientificKG"
    assert celltypist[
        "evidence-gold:v2.1:celltypist-model-feature-alignment:resolved-model-artifact"
    ]["owner"] == "ToolContract"
    assert celltypist[
        "evidence-gold:v2.1:celltypist-model-feature-alignment:model-feature-alignment"
    ]["owner"] == "ToolContract"
    assert not celltypist[
        "evidence-gold:v2.1:celltypist-model-feature-alignment:model-feature-alignment"
    ]["allowed_evidence_spans"]

    mofa = {key: row for key, row in evidence.items() if ":mofa2-sample-alignment:" in key}
    assert mofa[
        "evidence-gold:v2.1:mofa2-sample-alignment:overlapping-samples-supported"
    ]["owner"] == "ScientificKG"
    assert mofa[
        "evidence-gold:v2.1:mofa2-sample-alignment:sample-identity-alignment"
    ]["owner"] == "RepresentationLedger"
    assert not mofa[
        "evidence-gold:v2.1:mofa2-sample-alignment:sample-identity-alignment"
    ]["allowed_evidence_spans"]


def test_pinned_source_provenance_closes_targeted_gaps_without_claiming_review():
    provenance = _jsonl(GOLD / "scientific_source_provenance.jsonl")
    by_span = {row["evidence_span_id"]: row for row in provenance}
    assert set(by_span) == {
        "gold-span:scanpy:hvg-default-flavor:1.11.2",
        "gold-span:singler:reference-choice:3.22",
        "gold-span:celltypist:normalized-input:1.7.1",
        "gold-span:celltypist:default-model:1.7.1",
        "gold-span:scvelo:spliced-unspliced-input:0.3.3",
        "gold-span:mofa2:input-output:ec2ee6d",
    }
    assert all(row["review_status"] == "reviewed" for row in provenance)
    assert all(row["candidate_only"] is True for row in provenance)
    assert all("/Users/" not in row["immutable_uri"] for row in provenance)

    evidence = _jsonl(GOLD / "evidence_gold.jsonl")
    scvelo = next(
        row for row in evidence if row["evidence_gold_id"].endswith(":scvelo-layer-availability:layer-requirement")
    )
    assert scvelo["evidence_gap_ids"] == []
    assert scvelo["allowed_evidence_spans"] == [
        "gold-span:scvelo:spliced-unspliced-input:0.3.3"
    ]


def test_learning_utility_query_is_application_level_and_hidden():
    soupx = next(
        row
        for row in _jsonl(GOLD / "learning_episodes.jsonl")
        if row["episode_id"].endswith(":soupx-input-semantics")
    )
    assert "unfiltered droplet-by-gene matrix" in soupx["hidden_related_query"]
    assert "filtered cell-by-gene matrix" in soupx["hidden_related_query"]
    assert soupx["hidden_related_query"] not in soupx["claim_construction_visible_queries"]

    singler = next(
        row
        for row in _jsonl(GOLD / "learning_episodes.jsonl")
        if row["episode_id"].endswith(":singler-reference-suitability")
    )
    assert singler["source_work_id"] == "source-work:bioconductor:SingleRBook"
    assert singler["conditions"][1]["evidence_artifact_id"] == (
        "gold-span:singler:reference-choice:3.22"
    )
    assert singler["conditions"][2]["evidence_artifact_id"] == (
        "gold-span:singler:reference-choice:3.22"
    )


def test_unfrozen_scientific_scenarios_are_not_falsely_assigned_to_one_study():
    parents = {
        row["scenario_id"]: row for row in _jsonl(GOLD / "parent_scenarios.jsonl")
    }
    for slug in (
        "singler-reference-compatibility",
        "celltypist-model-feature-alignment",
        "scvelo-layer-availability",
        "mofa2-sample-alignment",
    ):
        assert parents[f"scenario:v2.1:{slug}"]["study_id"] is None


def test_governance_seed_does_not_claim_promotion_implementation():
    cases = _json(MANIFESTS / "governance_boundary_cases_seed_v0.json")["cases"]
    assert len(cases) == 4
    assert all(case["canonical_promotion"] is False for case in cases)
    assert {case["transition"] for case in cases} <= {"NOT_RUN", "NOT_IMPLEMENTED"}


def test_fault_injections_reference_existing_unmutated_records():
    records = _jsonl(GOLD / "evaluation_records.jsonl")
    record_ids = {row["record_id"] for row in records}
    mutations = _json(MANIFESTS / "fault_injections_seed_v0.json")["mutations"]
    assert len(mutations) == 8
    assert all(row["single_variable_mutation"] is True for row in mutations)
    assert all(row["mutation_parent_id"] in record_ids for row in mutations)
    assert all(
        not row["mutation_parent_id"].startswith("record:v2.1:t8:")
        for row in mutations
    )


def test_manifest_pins_contract_and_declares_development_only():
    manifest = _json(MANIFESTS / "midterm_core_seed_v0.json")
    assert manifest["contract"]["sha256"] == CONTRACT_SHA256
    assert manifest["status"] == "frozen_seed_v0"
    assert manifest["formal_benchmark"] is False
    assert manifest["formal_holdout_constructed"] is False
    assert manifest["gold_boundary"]["independent_of_sut"] is True
    assert manifest["gold_boundary"]["human_review_required"] is False
    assert manifest["gold_boundary"]["human_review_complete"] is True
    assert manifest["gold_boundary"]["review_decision"] == REVIEW_DECISION
    assert manifest["gold_boundary"]["reviewer_role"] == REVIEWER_ROLE
    assert manifest["gold_boundary"]["independent_external_expert_review"] is False


def test_project_owner_adjudication_is_complete_for_every_required_item():
    checklist = _json(
        ROOT / "docs/status/MIDTERM_CORE_SEED_V0_REVIEW_CHECKLIST.json"
    )
    assert checklist["human_review_complete"] is True
    assert checklist["review_decision"] == REVIEW_DECISION
    assert checklist["reviewer_role"] == REVIEWER_ROLE
    assert checklist["review_date"] == REVIEW_DATE
    assert checklist["reviewer_reason"] == REVIEWER_REASON
    assert checklist["independent_external_expert_review"] is False
    assert len(checklist["parent_scenarios"]) == 9
    assert all(
        row["review_decision"] == REVIEW_DECISION
        and row["reviewer_role"] == REVIEWER_ROLE
        and row["review_date"] == REVIEW_DATE
        and row["reviewer_reason"] == REVIEWER_REASON
        for row in checklist["parent_scenarios"]
    )
    required_nested = [
        item
        for parent in checklist["parent_scenarios"]
        for item in parent["evidence_gold"]
    ] + checklist["learning_episodes"]
    assert required_nested
    assert all(item["review_decision"] == REVIEW_DECISION for item in required_nested)
    assert not any(
        item["review_decision"] in {None, "REVISE", "REJECT"}
        for item in required_nested
    )

    for name in (
        "parent_scenarios.jsonl",
        "workflow_gold.jsonl",
        "requirement_gold.jsonl",
        "evidence_gold.jsonl",
        "learning_episodes.jsonl",
    ):
        assert all(row["review_status"] == "reviewed" for row in _jsonl(GOLD / name))
    assert all(
        row["review_status"] == "reviewed"
        for row in _jsonl(GOLD / "scientific_source_provenance.jsonl")
    )


def test_freeze_manifest_is_complete_and_all_digests_resolve():
    import hashlib

    freeze = _json(MANIFESTS / "midterm_core_seed_v0.freeze.json")
    assert freeze["status"] == "frozen"
    assert freeze["immutable"] is True
    assert freeze["benchmark_run"] is False
    assert freeze["formal_holdout_constructed"] is False
    assert freeze["human_review_complete"] is True
    assert freeze["review_decision"] == REVIEW_DECISION
    assert freeze["reviewer_role"] == REVIEWER_ROLE
    assert freeze["independent_external_expert_review"] is False
    assert set(freeze["artifact_sha256"]) == {
        "evaluation_contract",
        "seed_manifest",
        "parent_scenarios",
        "workflow_gold",
        "requirement_gold",
        "evidence_gold",
        "scientific_source_provenance",
        "learning_episodes",
        "review_checklist",
    }
    assert len(freeze["schema_sha256"]) == 6
    for section in ("artifact_sha256", "schema_sha256"):
        for item in freeze[section].values():
            path = ROOT / item["path"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_generated_artifact_digests_are_current():
    manifest = _json(MANIFESTS / "midterm_core_seed_v0.json")
    import hashlib

    for relative, expected in manifest["artifact_sha256"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected
