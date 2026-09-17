from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from core.execution_models import StrictModel


SCHEMA_VERSION = "sckg-midterm-core-benchmark-v2.1"

Split = Literal["development", "validation", "frozen_holdout"]
Track = Literal["G0", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
RequirementState = Literal[
    "SATISFIED", "VIOLATED", "UNKNOWN", "MISSING", "NOT_APPLICABLE"
]
ActionOutcome = Literal["ALLOW", "BLOCK", "CLARIFY"]
ReviewStatus = Literal["draft", "reviewed", "rejected"]


class ParentScenario(StrictModel):
    schema_version: Literal["sckg-parent-scenario-v2.1"] = (
        "sckg-parent-scenario-v2.1"
    )
    scenario_id: str = Field(pattern=r"^scenario:v2\.1:")
    task_family: str = Field(min_length=1)
    scientific_question: str = Field(min_length=1)
    study_id: str | None = None
    dataset_id: str | None = None
    source_group: str = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"]
    split: Split
    capabilities_under_test: list[str] = Field(min_length=1)
    historical_anchor: bool
    review_status: ReviewStatus = "draft"


class BaselineEligibility(StrictModel):
    eligible_baselines: list[Literal["B0", "B1", "B2", "B3", "B4", "S0", "S1", "S2"]] = (
        Field(min_length=1)
    )
    shared_inputs: list[str] = Field(min_length=1)
    intentionally_varied_capability: str = Field(min_length=1)
    not_applicable_metrics: list[str] = Field(default_factory=list)


class DenominatorMetadata(StrictModel):
    included: bool
    denominator_id: str = Field(min_length=1)
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def validate_exclusion(self) -> "DenominatorMetadata":
        if self.included and self.exclusion_reason:
            raise ValueError("included records cannot carry an exclusion reason")
        if not self.included and not self.exclusion_reason:
            raise ValueError("excluded records require an exclusion reason")
        return self


class EvaluationRecord(StrictModel):
    schema_version: Literal["sckg-evaluation-record-v2.1"] = (
        "sckg-evaluation-record-v2.1"
    )
    record_id: str = Field(pattern=r"^record:v2\.1:")
    parent_scenario_id: str = Field(pattern=r"^scenario:v2\.1:")
    study_id: str | None = None
    dataset_id: str | None = None
    source_work_id: str | None = None
    mutation_parent_id: str | None = None
    replicate_id: str = Field(min_length=1)
    track: Track
    split: Split
    record_kind: Literal[
        "semantic_gateway",
        "planning",
        "applicability",
        "evidence_decision",
        "real_data_path",
        "acquisition",
        "learning_episode",
        "governance_boundary",
        "fault_injection",
    ]
    gold_ref: str = Field(min_length=1)
    baseline_eligibility: BaselineEligibility
    denominator: DenominatorMetadata


class PartialOrderConstraint(StrictModel):
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_distinct(self) -> "PartialOrderConstraint":
        if self.before == self.after:
            raise ValueError("partial-order endpoints must differ")
        return self


class MethodAlternativeSet(StrictModel):
    goal: str = Field(min_length=1)
    methods: list[str] = Field(min_length=1)


class WorkflowGold(StrictModel):
    schema_version: Literal["sckg-workflow-gold-v2.1"] = (
        "sckg-workflow-gold-v2.1"
    )
    workflow_gold_id: str = Field(pattern=r"^workflow-gold:v2\.1:")
    parent_scenario_id: str = Field(pattern=r"^scenario:v2\.1:")
    split: Split
    required_final_states: list[str] = Field(min_length=1)
    required_prerequisites: list[str] = Field(default_factory=list)
    forbidden_operations: list[str] = Field(default_factory=list)
    optional_operations: list[str] = Field(default_factory=list)
    partial_order_constraints: list[PartialOrderConstraint] = Field(default_factory=list)
    acceptable_method_alternatives: list[MethodAlternativeSet] = Field(default_factory=list)
    acceptable_terminal_states: list[str] = Field(min_length=1)
    review_status: ReviewStatus = "draft"
    gold_origin: Literal["independent_source_adjudication_draft"] = (
        "independent_source_adjudication_draft"
    )
    generated_from_sut: Literal[False] = False


class RequirementExpectation(StrictModel):
    requirement_id: str = Field(pattern=r"^requirement-gold:")
    expected_state: RequirementState
    rationale: str = Field(min_length=1)
    evidence_required: bool
    criticality: Literal["hard", "soft"]
    resolution_mode: Literal[
        "provide_resource",
        "ask_user",
        "acquire_evidence",
        "select_other",
        "schedule_prerequisite",
        "none",
    ]


def aggregate_requirement_action(
    requirements: list[RequirementExpectation],
) -> ActionOutcome:
    applicable = [
        item for item in requirements if item.expected_state != "NOT_APPLICABLE"
    ]
    if any(
        item.criticality == "hard" and item.expected_state == "VIOLATED"
        for item in applicable
    ):
        return "BLOCK"
    hard_missing = [
        item
        for item in applicable
        if item.criticality == "hard" and item.expected_state == "MISSING"
    ]
    if any(
        item.resolution_mode not in {"ask_user", "schedule_prerequisite"}
        for item in hard_missing
    ):
        return "BLOCK"
    if any(item.resolution_mode == "ask_user" for item in hard_missing):
        return "CLARIFY"
    if any(
        item.criticality == "hard" and item.expected_state == "UNKNOWN"
        for item in applicable
    ):
        return "CLARIFY"
    return "ALLOW"


class RequirementGold(StrictModel):
    schema_version: Literal["sckg-requirement-gold-v2.1"] = (
        "sckg-requirement-gold-v2.1"
    )
    requirement_gold_id: str = Field(pattern=r"^requirement-gold-set:v2\.1:")
    parent_scenario_id: str = Field(pattern=r"^scenario:v2\.1:")
    split: Split
    requirements: list[RequirementExpectation] = Field(min_length=1)
    expected_action: ActionOutcome
    review_status: ReviewStatus = "draft"
    gold_origin: Literal["independent_source_adjudication_draft"] = (
        "independent_source_adjudication_draft"
    )
    generated_from_sut: Literal[False] = False

    @model_validator(mode="after")
    def validate_aggregation(self) -> "RequirementGold":
        expected = aggregate_requirement_action(self.requirements)
        if self.expected_action != expected:
            raise ValueError(
                f"expected_action {self.expected_action} does not match aggregation {expected}"
            )
        return self


class EvidenceGold(StrictModel):
    schema_version: Literal["sckg-evidence-gold-v2.1"] = (
        "sckg-evidence-gold-v2.1"
    )
    evidence_gold_id: str = Field(pattern=r"^evidence-gold:v2\.1:")
    parent_scenario_id: str = Field(pattern=r"^scenario:v2\.1:")
    split: Split
    decision_id: str = Field(pattern=r"^decision:v2\.1:")
    claim: str = Field(min_length=1)
    owner: Literal[
        "ScientificKG",
        "RepresentationLedger",
        "CapabilityPack",
        "ToolContract",
        "Policy",
        "UserClarification",
    ]
    scope: str = Field(min_length=1)
    version: str = Field(min_length=1)
    evidence_required: bool
    source_work_ids: list[str] = Field(default_factory=list)
    allowed_evidence_spans: list[str] = Field(default_factory=list)
    forbidden_evidence_spans: list[str] = Field(default_factory=list)
    evidence_gap_ids: list[str] = Field(default_factory=list)
    expected_epistemic_state: Literal[
        "source_bound_draft",
        "candidate",
        "runtime_observed",
        "unknown",
        "not_applicable",
    ]
    review_status: ReviewStatus = "draft"
    gold_origin: Literal["independent_source_adjudication_draft"] = (
        "independent_source_adjudication_draft"
    )
    generated_from_sut: Literal[False] = False

    @model_validator(mode="after")
    def validate_evidence_boundary(self) -> "EvidenceGold":
        if self.evidence_required and not (
            self.allowed_evidence_spans or self.evidence_gap_ids
        ):
            raise ValueError("required evidence needs allowed spans or an explicit gap")
        if not self.evidence_required and self.allowed_evidence_spans:
            raise ValueError("non-scientific/runtime atoms cannot carry scientific evidence")
        overlap = set(self.allowed_evidence_spans) & set(self.forbidden_evidence_spans)
        if overlap:
            raise ValueError("evidence spans cannot be both allowed and forbidden")
        return self


class LearningCondition(StrictModel):
    condition: Literal["S0", "S1", "S2"]
    knowledge_snapshot_id: str = Field(min_length=1)
    added_evidence: bool
    structured_candidate: bool
    evidence_artifact_id: str | None = None
    candidate_claim_id: str | None = None

    @model_validator(mode="after")
    def validate_condition(self) -> "LearningCondition":
        if self.condition == "S0" and (
            self.added_evidence
            or self.structured_candidate
            or self.evidence_artifact_id
            or self.candidate_claim_id
        ):
            raise ValueError("S0 must be the untouched pre-acquisition snapshot")
        if self.condition == "S1" and (
            not self.added_evidence
            or self.structured_candidate
            or not self.evidence_artifact_id
            or self.candidate_claim_id
        ):
            raise ValueError("S1 requires RAG evidence without a candidate claim")
        if self.condition == "S2" and (
            not self.added_evidence
            or not self.structured_candidate
            or not self.evidence_artifact_id
            or not self.candidate_claim_id
        ):
            raise ValueError("S2 requires evidence and a structured candidate")
        return self


class LearningEpisode(StrictModel):
    schema_version: Literal["sckg-learning-episode-v2.1"] = (
        "sckg-learning-episode-v2.1"
    )
    episode_id: str = Field(pattern=r"^learning-episode:v2\.1:")
    parent_scenario_id: str = Field(pattern=r"^scenario:v2\.1:")
    split: Split
    source_work_id: str = Field(min_length=1)
    original_query: str = Field(min_length=1)
    hidden_related_query: str = Field(min_length=1)
    claim_construction_visible_queries: list[str] = Field(min_length=1)
    conditions: list[LearningCondition] = Field(min_length=3, max_length=3)
    review_status: ReviewStatus = "draft"

    @model_validator(mode="after")
    def validate_isolation(self) -> "LearningEpisode":
        if self.original_query == self.hidden_related_query:
            raise ValueError("hidden related query must differ from the original")
        if self.hidden_related_query in self.claim_construction_visible_queries:
            raise ValueError("hidden query leaked into claim construction")
        if self.original_query not in self.claim_construction_visible_queries:
            raise ValueError("original query must be visible during claim construction")
        if [item.condition for item in self.conditions] != ["S0", "S1", "S2"]:
            raise ValueError("learning conditions must be ordered S0/S1/S2")
        snapshot_ids = [item.knowledge_snapshot_id for item in self.conditions]
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError("learning conditions require independent cloned states")
        if (
            self.conditions[1].evidence_artifact_id
            != self.conditions[2].evidence_artifact_id
        ):
            raise ValueError("S1 and S2 must use the same evidence artifact")
        return self


class BenchmarkSeedBundle(StrictModel):
    parent_scenarios: list[ParentScenario]
    evaluation_records: list[EvaluationRecord]
    workflow_gold: list[WorkflowGold]
    requirement_gold: list[RequirementGold]
    evidence_gold: list[EvidenceGold]
    learning_episodes: list[LearningEpisode]

    @model_validator(mode="after")
    def validate_references_and_split_inheritance(self) -> "BenchmarkSeedBundle":
        parents = {item.scenario_id: item for item in self.parent_scenarios}
        if len(parents) != len(self.parent_scenarios):
            raise ValueError("parent scenario IDs must be unique")
        descendants = [
            *self.evaluation_records,
            *self.workflow_gold,
            *self.requirement_gold,
            *self.evidence_gold,
            *self.learning_episodes,
        ]
        for item in descendants:
            parent = parents.get(item.parent_scenario_id)
            if parent is None:
                raise ValueError(f"unknown parent scenario: {item.parent_scenario_id}")
            if item.split != parent.split:
                raise ValueError(
                    f"derived record crossed parent split: {item.parent_scenario_id}"
                )
        record_ids = {item.record_id for item in self.evaluation_records}
        if len(record_ids) != len(self.evaluation_records):
            raise ValueError("evaluation record IDs must be unique")
        for item in self.evaluation_records:
            if item.mutation_parent_id and item.mutation_parent_id not in record_ids:
                raise ValueError(
                    f"unknown mutation parent record: {item.mutation_parent_id}"
                )
        return self
