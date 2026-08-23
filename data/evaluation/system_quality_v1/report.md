# scKG-Agent System Quality Report

- Evaluation: `system-quality-20260721T160910Z`
- Status: `PHASE6_TRIAL_READY`
- Engineering gate: `true`
- Phase 6 completion eligible: `false`

## Dimensions

| Dimension | Status | Key metrics |
| --- | --- | --- |
| functional_correctness | passed | agent_task_completion_rate=1.0; agent_tool_correctness=1.0; operational_scenario_pass_rate=1.0; tool_invocation_success_rate=1.0; validation_pass_rate=1.0 |
| safety_and_isolation | passed | unauthorized_execution_count=0; path_escape_count=0; approval_replay_violation_count=0; cross_user_access_violation_count=0; untrusted_generated_code_execution_count=0 |
| knowledge_quality | passed | retrieval_case_count=96; recall_at_10=0.931818; precision_at_10=0.89862; mrr=0.980114; source_span_hit_rate=0.988636 |
| usability | partial | participant_count=0; level_1_participant_count=0; level_2_participant_count=0; human_task_completion_rate=None; human_help_rate=None |
| reproducibility | passed | package_integrity_rate=1.0; reproducibility_level=Level 2; input_data_copied=False |
| performance | passed | agent_latency_p50_ms=14.425; agent_latency_p95_ms=1124.327; kg_bm25_latency_p50_ms=13.6195; kg_bm25_latency_p95_ms=40.696; execution_runtime_seconds_mean_per_tool_smoke=17.3842125 |
| auditability | passed | applicable_stage_completeness=1.0; failure_queue_coverage=1.0; captured_failure_count=2; expected_failure_count=2; repair_lineage_complete=True |
| change_risk | partial | regression_status=baseline_not_provided; regression_count=0; portfolio_a4_hard_gate_passed=True; portfolio_completed_model_calls=48 |

## Operational scenarios

- `success-closure`: PASS - completed
- `bounded-repair`: PASS - repaired_and_completed
- `correctly-blocked`: PASS - BLOCKED
- `approval-replay`: PASS - blocked
- `parameter-change`: PASS - blocked
- `cancellation`: PASS - cancelled

## Blockers

- real_group_trial_not_completed

## Limitations

- Agent Quality v1 is a 12-case deterministic regression suite, not open-world proof.
- Fresh user execution smoke covers the two doublet tools; batch tools rely on their existing qualification and scientific-pilot artifacts.
- Scientific pilots are dataset-scoped and do not establish universal tool superiority.
- Maintainer rehearsal and automated UI smoke cannot substitute for 3-5 real participants.
- Native LocalControlledExecutor is not an OS sandbox and cannot run arbitrary generated code.
