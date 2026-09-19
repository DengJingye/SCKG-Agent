# scKG-Eval v1 Specification

Status: specification and metric registry complete; no new benchmark campaign was run.

scKG-Eval evaluates nine distinct layers. It does not combine them into a global score. Scale describes coverage and workload; it does not establish scientific correctness.

## Statistical and interpretation rules

- Use the declared primary unit for denominators and uncertainty. Nested atoms, mutations, paraphrases, and repeated calls are not independent samples.
- Report development, regression, sealed, and external evidence separately.
- Deterministic governance correction, actual tool calls, and final task state remain separate from the LLM proposal.
- Engineering execution and scientific or human terminal completion remain separate.
- A BLOCKED scientific terminal is not SUCCESS.
- Regression test counts describe engineering stability and must not be presented as scientific accuracy.

## Split taxonomy

| Split | Definition | May inform changes | Independent claim |
| --- | --- | --- | --- |
| DEV | Visible during development and repeatable for diagnosis or tuning. | true | false |
| REGRESSION | Known expected answer retained to prevent recurrence of a fixed defect. | true | false |
| SEALED | Hidden before the formal run, immutable after freeze, and unavailable for post-run tuning. | false | true |
| EXTERNAL | External benchmark, new dataset, or new user independent from local development. | false | true |

A disclosed SEALED case is quarantined from future post-fix validation. Its already completed historical run remains historical evidence for the frozen SUT.

## KG-Eval

Scientific KG structure, semantic completeness, evidence grounding, governance, and readiness.

Primary unit: **node, relation, AtomicClaimRevision, claim-evidence pair, OperatorRevision**.
Current status: **CURRENT_MEASURED**.
Strongest evidence: Scientific KG Inventory Snapshot v1.
Main gap: No canonical cross-layer identity merge; correctness metrics remain partial.

Metrics:

- `kg_total_nodes` — Physical nodes in the declared Scientific KG layer set.
- `kg_total_edges` — Physical edges in the declared Scientific KG layer set.
- `kg_entity_type_count` — Distinct node record types in the inventory view.
- `kg_relation_type_count` — Distinct edge predicates in the inventory view.
- `kg_invalid_endpoint_count` — Relations whose source or target cannot be resolved in their layer.
- `kg_orphan_claim_count` — Claims whose subject identity is missing from the same layer.
- `kg_claim_without_scope_count` — Claims lacking a resolvable ApplicabilityScope.
- `kg_claim_without_evidence_count` — Claims lacking a supporting EvidenceAssessment reference.
- `kg_dangling_evidence_span_count` — Materialized spans not referenced by an EvidenceAssessment.
- `kg_unresolved_source_revision_count` — Evidence spans whose SourceRevision cannot be resolved.
- `kg_broken_rag_mapping_count` — Evidence-bound units without an exact frozen-corpus mapping.
- `kg_duplicate_canonical_identity_count` — Adjudicated canonical identities with more than one active canonical record.
- `kg_candidate_count` — Scientific claim revisions in candidate state.
- `kg_reviewed_count` — Scientific claim revisions with a completed review decision.
- `kg_trusted_canonical_count` — Scientific claim revisions promoted to trusted or canonical state.
- `kg_rejected_count` — Scientific claim revisions rejected by governance review.
- `kg_superseded_count` — Scientific claim revisions superseded by a governed successor.
- `kg_schema_conformance_rate` — Fraction of records that validate against the declared ontology schema.
- `kg_claim_evidence_binding_precision` — Fraction of evaluated bindings that directly support the bound claim.
- `kg_evidence_resolvability` — Fraction of evidence references resolving through span and source identity.
- `kg_source_correctness` — Fraction of evaluated evidence bindings pointing to the adjudicated source work or revision.
- `kg_scope_correctness` — Fraction of evaluated claims whose explicit applicability scope matches gold.
- `kg_version_correctness` — Fraction of evaluated claims and evidence bindings with the correct version boundary.
- `kg_readiness_l0_count` — OperatorRevisions whose highest exclusive readiness is L0.
- `kg_readiness_l0_rate` — Fraction of audited OperatorRevisions whose highest exclusive readiness is L0.
- `kg_readiness_l1_count` — OperatorRevisions whose highest exclusive readiness is L1.
- `kg_readiness_l1_rate` — Fraction of audited OperatorRevisions whose highest exclusive readiness is L1.
- `kg_readiness_l2_count` — OperatorRevisions whose highest exclusive readiness is L2.
- `kg_readiness_l2_rate` — Fraction of audited OperatorRevisions whose highest exclusive readiness is L2.
- `kg_readiness_l3_count` — OperatorRevisions whose highest exclusive readiness is L3.
- `kg_readiness_l3_rate` — Fraction of audited OperatorRevisions whose highest exclusive readiness is L3.
- `kg_readiness_l4_count` — OperatorRevisions whose highest exclusive readiness is L4.
- `kg_readiness_l4_rate` — Fraction of audited OperatorRevisions whose highest exclusive readiness is L4.

## Ingestion-Eval

PDF or authoritative source to Candidate Scientific KG extraction quality.

Primary unit: **document**.
Current status: **PLANNED_PILOT_NOT_RUN**.
Strongest evidence: Specification only.
Main gap: Freeze gold for 3-5 manually annotated authoritative PDFs before extraction.

Metrics:

- `ingestion_entity_precision` — Gold-aligned entity precision for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_entity_recall` — Gold-aligned entity recall for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_entity_f1` — Gold-aligned entity f1 for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_relation_precision` — Gold-aligned relation precision for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_relation_recall` — Gold-aligned relation recall for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_relation_f1` — Gold-aligned relation f1 for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_claim_precision` — Gold-aligned atomicclaim precision for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_claim_recall` — Gold-aligned atomicclaim recall for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_claim_f1` — Gold-aligned atomicclaim f1 for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_evidence_span_exact_match` — Gold-aligned evidencespan exact match for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_evidence_span_overlap` — Gold-aligned evidencespan overlap for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_claim_evidence_alignment` — Gold-aligned claim-evidence alignment accuracy for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_scope_accuracy` — Gold-aligned scope accuracy for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_version_accuracy` — Gold-aligned version accuracy for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_duplicate_detection_accuracy` — Gold-aligned duplicate detection accuracy for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_hallucinated_candidate_rate` — Gold-aligned hallucinated candidate rate for PDF or authoritative-source extraction into Candidate Scientific KG.
- `ingestion_admin_review_acceptance_rate` — Gold-aligned admin review acceptance rate for PDF or authoritative-source extraction into Candidate Scientific KG.

Baselines or ablations: manual gold, candidate extractor.

## Retrieval-Eval

Retrieval, grounding, abstention, and Scientific KG contribution per information need.

Primary unit: **parent scientific information need**.
Current status: **PARTIAL_CURRENT_AND_HISTORICAL**.
Strongest evidence: Independent Retrieval Validation v1 plus current direct-evidence audits.
Main gap: Disclosed SEALED cases are quarantined from future post-fix validation.

Metrics:

- `retrieval_hit_at_5` — Hit@5 at the parent scientific information-need level.
- `retrieval_hit_at_10` — Hit@10 at the parent scientific information-need level.
- `retrieval_mrr_at_10` — MRR@10 at the parent scientific information-need level.
- `retrieval_source_correctness` — Source correctness at the parent scientific information-need level.
- `retrieval_scope_correctness` — Scope correctness at the parent scientific information-need level.
- `retrieval_version_correctness` — Version correctness at the parent scientific information-need level.
- `retrieval_evidence_binding_correctness` — Evidence-binding correctness at the parent scientific information-need level.
- `retrieval_abstention_accuracy` — Abstention accuracy at the parent scientific information-need level.
- `retrieval_false_certainty_rate` — False-certainty rate at the parent scientific information-need level.
- `retrieval_scientific_kg_participation` — Scientific KG participation at the parent scientific information-need level.
- `retrieval_helped_rate` — HELPED rate at the parent scientific information-need level.
- `retrieval_neutral_rate` — NEUTRAL rate at the parent scientific information-need level.
- `retrieval_hurt_rate` — HURT rate at the parent scientific information-need level.
- `retrieval_false_filter_event_count` — Accepted evidence removed by a filter for an invalid reason.

Baselines or ablations: BM25, Dense, Hybrid, Scientific KG + Hybrid.

## Agent-Eval

Intent, action, tool, parameter, binding, clarification, blocking, and terminal behavior.

Primary unit: **conversation task**.
Current status: **DEVELOPMENT_RESULT**.
Strongest evidence: 36-case Agent Tool Selection Eval v1.
Main gap: Development cases are visible and are not independent validation.

Metrics:

- `agent_intent_accuracy` — Intent accuracy for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_action_selection_accuracy` — Action selection accuracy for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_tool_trigger_precision` — Tool trigger precision for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_tool_trigger_recall` — Tool trigger recall for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_parameter_correctness` — Parameter correctness for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_data_binding_accuracy` — Data binding accuracy for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_clarification_accuracy` — Clarification accuracy for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_block_accuracy` — Block accuracy for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_unnecessary_tool_call_rate` — Unnecessary tool call rate for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_unauthorized_execution_rate` — Unauthorized execution rate for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.
- `agent_false_terminal_completion_rate` — Declared-complete-with-terminal-unmet rate for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.

Baselines or ablations: LLM proposal, deterministic governance correction, actual tool call.

## Planner-Eval

State-aware reuse, recompute, block, action, and dependency decisions.

Primary unit: **data-state scenario**.
Current status: **PILOT_PARTIAL**.
Strongest evidence: Four paired KG/planner scenarios and PBMC raw/processed replay evidence.
Main gap: No frozen broad planner benchmark yet.

Metrics:

- `planner_action_precision` — Action precision over frozen data-state scenarios.
- `planner_action_recall` — Action recall over frozen data-state scenarios.
- `planner_reuse_accuracy` — Reuse accuracy over frozen data-state scenarios.
- `planner_recompute_accuracy` — Recompute accuracy over frozen data-state scenarios.
- `planner_block_accuracy` — Block accuracy over frozen data-state scenarios.
- `planner_invalid_reuse_rate` — Invalid reuse rate over frozen data-state scenarios.
- `planner_unnecessary_step_rate` — Unnecessary step rate over frozen data-state scenarios.
- `planner_dependency_correctness` — Dependency correctness over frozen data-state scenarios.

Baselines or ablations: pre-KG planner, current KG-enabled planner, frozen state gold.

Required case schema: `case_id`, `input_artifact`, `current_representation_records`, `representation_status`, `identity_hashes`, `target_state`, `gold_reuse`, `gold_recompute`, `gold_block`, `required_actions`, `forbidden_actions`.

## Justification-Eval

Decision-local evidence ownership, fidelity, resolvability, and robustness.

Primary unit: **DecisionJustificationAtom**.
Current status: **FROZEN_HISTORICAL**.
Strongest evidence: 12 atoms, 8 single-fault mutations, and 4 behavior-invariance pairs.
Main gap: Strong formal historical evidence; not new independent validation.

Metrics:

- `justification_scientific_evidence_recall` — Scientific evidence recall at DecisionJustificationAtom level.
- `justification_decision_evidence_precision` — Decision-evidence precision at DecisionJustificationAtom level.
- `justification_extra_nondecision_evidence_rate` — Extra non-decision evidence rate at DecisionJustificationAtom level.
- `justification_runtime_citation_abstention` — Runtime citation abstention at DecisionJustificationAtom level.
- `justification_ownership_fidelity` — Ownership fidelity at DecisionJustificationAtom level.
- `justification_scope_fidelity` — Scope fidelity at DecisionJustificationAtom level.
- `justification_epistemic_fidelity` — Epistemic fidelity at DecisionJustificationAtom level.
- `justification_representation_linkage` — Representation linkage at DecisionJustificationAtom level.
- `justification_evidence_resolvability` — Evidence resolvability at DecisionJustificationAtom level.
- `justification_negative_control_pass_rate` — Negative-control pass rate at DecisionJustificationAtom level.
- `justification_behavior_invariance` — Behavior invariance at DecisionJustificationAtom level.

Baselines or ablations: global evidence bag, decision-local evidence projection.

## E2E-Eval

Engineering, data-state, scientific terminal, and human terminal outcomes.

Primary unit: **dataset x scientific task**.
Current status: **CURRENT_MEASURED_PARTIAL**.
Strongest evidence: Raw and Processed PBMC3k current-version replay v2.
Main gap: Annotation terminals remain BLOCKED; execution is not full scientific completion.

Metrics:

- `e2e_plan_compile_rate` — Plan compile rate for dataset by scientific-task units.
- `e2e_notebook_compile_rate` — Notebook compile rate for dataset by scientific-task units.
- `e2e_execution_success_rate` — Execution success rate for dataset by scientific-task units.
- `e2e_terminal_completion_rate` — Terminal-state completion rate for dataset by scientific-task units.
- `e2e_artifact_integrity_rate` — Artifact integrity rate for dataset by scientific-task units.
- `e2e_input_mutation_rate` — Input mutation rate for dataset by scientific-task units.
- `e2e_scientific_validation_pass_rate` — Scientific validation pass rate for dataset by scientific-task units.
- `e2e_human_confirmation_completion_rate` — Human confirmation completion rate for dataset by scientific-task units.

## Trace-Eval

Trace completeness, causal localization, ownership, ordering, and replay consistency.

Primary unit: **trace or injected-failure scenario**.
Current status: **SPEC_DEFINED_BENCHMARK_NOT_RUN**.
Strongest evidence: Specification only.
Main gap: No frozen injected-failure campaign has been run.

Metrics:

- `trace_stage_coverage` — Trace stage coverage for trace or injected-failure scenarios.
- `trace_referential_integrity` — Referential integrity for trace or injected-failure scenarios.
- `trace_first_causal_failure_accuracy` — First causal failure accuracy for trace or injected-failure scenarios.
- `trace_owner_attribution_accuracy` — Owner attribution accuracy for trace or injected-failure scenarios.
- `trace_missing_span_rate` — Missing span rate for trace or injected-failure scenarios.
- `trace_ordering_accuracy` — Trace ordering accuracy for trace or injected-failure scenarios.
- `trace_replay_consistency` — Replay consistency for trace or injected-failure scenarios.

Baselines or ablations: expected injected first cause, observed first cause.

Future failures include route failure, missing artifact, stale representation, unresolved subject or evidence, public-filter rejection, policy denial, notebook failure, unmet terminal, and rejected review.

## Regression-Eval

Engineering stability and artifact integrity.

Primary unit: **test or deterministic replay**.
Current status: **CURRENT_MEASURED_ENGINEERING**.
Strongest evidence: Checkpoint-focused and regression test artifacts.
Main gap: Overlapping test counts must not be summed or called scientific accuracy.

Metrics:

- `regression_unit_pass_rate` — Engineering-only unit pass rate.
- `regression_integration_pass_rate` — Engineering-only integration pass rate.
- `regression_regression_pass_rate` — Engineering-only regression pass rate.
- `regression_artifact_integrity` — Engineering-only artifact integrity.
- `regression_deterministic_replay` — Engineering-only deterministic replay.
- `regression_cold_reload_consistency` — Engineering-only cold reload consistency.
- `regression_new_regression_count` — Previously passing governed checks that now fail.
- `regression_historical_baseline_failure_count` — Known historical baseline or stale-lock failures retained separately.

Baselines or ablations: previous frozen checkpoint.

## Existing evidence ledger

Mapped records: **19**. Status counts: CURRENT_MEASURED=4, DEVELOPMENT_RESULT=2, FROZEN_HISTORICAL=4, NOT_RUN=2, PARTIAL=2, PILOT=4, QUARANTINED=1.

The machine-readable ledger records artifact tracking state. `UNTRACKED_WORKSPACE` means the artifact exists locally but is not yet committed; it must not be described as repository-frozen evidence.

## Formal justification result

The frozen decision-local projection changed scientific decision-evidence precision from **5/17 to 5/5**, extra non-decision evidence from **12 to 0**, while recall remained **5/5** and behavior invariance remained **4/4**. These are formal historical results over the declared frozen atoms and scenarios.

## Prohibited interpretations

- Do not call node or edge count scientific correctness.
- Do not call governance-corrected Agent behavior LLM accuracy.
- Do not aggregate the nine suites into one accuracy number.
- Do not reuse disclosed C7 cases as future independent validation.
- Do not sum overlapping regression test selections.
