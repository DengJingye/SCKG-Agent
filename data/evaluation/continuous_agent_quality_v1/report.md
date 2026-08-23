# scKG-Agent Continuous Quality Report

- Evaluation: `continuous-agent-quality-20260725T034316Z`
- Release signal: `watch`
- Measured metrics: `44/51`
- Zero-tolerance violations: `0`
- Regression status: `compared`

## Category scorecard

| Category | Signal | Measured | Not run | Insufficient | Watch | Blocked |
|---|---:|---:|---:|---:|---:|---:|
| effectiveness | watch | 21 | 2 | 0 | 0 | 0 |
| efficiency | healthy | 8 | 1 | 0 | 0 | 0 |
| stability | healthy | 3 | 2 | 0 | 0 | 0 |
| compliance | watch | 12 | 2 | 0 | 0 | 0 |

## Business capability waterline

| Domain | Signal | Measured | Total | Release coverage |
|---|---|---:|---:|---:|
| knowledge_qa | healthy | 18 | 21 | 1.000 |
| workflow_planning | healthy | 6 | 6 | 1.000 |
| doublet_detection_execution | healthy | 6 | 6 | 1.000 |
| batch_integration_execution | healthy | 1 | 1 | 1.000 |
| bounded_repair | healthy | 3 | 3 | 1.000 |
| authorization_and_safety | watch | 7 | 8 | 0.875 |
| reproducibility | healthy | 3 | 3 | 1.000 |
| user_trial | watch | 0 | 3 | 0.000 |

## Metrics

| Metric | Domain | Stage | Lane | Status | Value | Signal |
|---|---|---|---|---|---:|---|
| `effectiveness.task_completion_rate` | knowledge_qa | gateway_intent | deterministic_offline | measured | 1.0 | healthy |
| `effectiveness.task_routing_accuracy` | workflow_planning | gateway_intent | deterministic_offline | measured | 1.0 | healthy |
| `effectiveness.intent_accuracy` | knowledge_qa | gateway_intent | deterministic_offline | measured | 1.0 | healthy |
| `effectiveness.tool_correctness` | workflow_planning | tool_contract_action_bundle | deterministic_offline | measured | 1.0 | healthy |
| `effectiveness.workflow_correctness` | workflow_planning | workflow_planner | deterministic_offline | measured | 1.0 | healthy |
| `effectiveness.blocker_correctness` | authorization_and_safety | router_approval | deterministic_offline | measured | 1.0 | healthy |
| `effectiveness.source_coverage_rate` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 1.0 | healthy |
| `effectiveness.retrieval_recall_at_10` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 0.931818 | healthy |
| `effectiveness.retrieval_precision_at_10` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 0.89862 | healthy |
| `effectiveness.retrieval_mrr` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 0.980114 | healthy |
| `effectiveness.retrieval_source_span_hit_rate` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 0.988636 | healthy |
| `effectiveness.operational_scenario_pass_rate` | doublet_detection_execution | controlled_executor | controlled_execution | measured | 1.0 | healthy |
| `effectiveness.data_profile_gate` | workflow_planning | data_profiler | controlled_execution | measured | 1 | healthy |
| `effectiveness.tool_invocation_success_rate` | doublet_detection_execution | controlled_executor | controlled_execution | measured | 1.0 | healthy |
| `effectiveness.validation_pass_rate` | doublet_detection_execution | validator | controlled_execution | measured | 1.0 | healthy |
| `effectiveness.repair_success_rate` | bounded_repair | repair_policy | controlled_execution | measured | 1.0 | healthy |
| `effectiveness.package_integrity_rate` | reproducibility | reproducibility_packager | controlled_execution | measured | 1.0 | healthy |
| `effectiveness.candidate_decision_eligibility` | doublet_detection_execution | candidate_pareto_decision | controlled_execution | measured | 1.0 | healthy |
| `effectiveness.batch_integration_pilot_ready` | batch_integration_execution | candidate_pareto_decision | controlled_execution | measured | 1 | healthy |
| `effectiveness.workflow_code_smoke` | workflow_planning | validator | controlled_execution | measured | 1 | healthy |
| `effectiveness.human_task_completion_rate` | user_trial | ui_trial_telemetry | human_trial | not_run | - | unknown |
| `effectiveness.ragas_faithfulness` | knowledge_qa | kg_rag_retrieval | external_llm | not_run | - | unknown |
| `efficiency.agent_latency_p50_ms` | knowledge_qa | gateway_intent | deterministic_offline | measured | 47.382 | healthy |
| `efficiency.agent_latency_p95_ms` | knowledge_qa | gateway_intent | deterministic_offline | measured | 159.751 | healthy |
| `efficiency.retrieval_latency_p50_ms` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 12.826 | healthy |
| `efficiency.retrieval_latency_p95_ms` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 36.258 | healthy |
| `efficiency.execution_runtime_seconds` | doublet_detection_execution | controlled_executor | controlled_execution | measured | 17.3842125 | healthy |
| `efficiency.execution_peak_memory_mb` | doublet_detection_execution | controlled_executor | controlled_execution | measured | 1340.5 | healthy |
| `efficiency.repair_run_count` | bounded_repair | repair_policy | controlled_execution | measured | 4.0 | healthy |
| `efficiency.external_llm_token_usage` | knowledge_qa | gateway_intent | external_llm | measured | 132975 | healthy |
| `efficiency.external_llm_estimated_cost_usd` | knowledge_qa | gateway_intent | external_llm | not_run | - | unknown |
| `stability.deterministic_outcome_stability` | knowledge_qa | gateway_intent | deterministic_offline | measured | 1.0 | healthy |
| `stability.trace_completeness` | reproducibility | ui_trial_telemetry | deterministic_offline | measured | 1.0 | healthy |
| `stability.operational_trace_completeness` | reproducibility | ui_trial_telemetry | controlled_execution | measured | 1.0 | healthy |
| `stability.external_llm_repeat_variance` | knowledge_qa | gateway_intent | external_llm | not_run | - | unknown |
| `stability.human_task_variance` | user_trial | ui_trial_telemetry | human_trial | not_run | - | unknown |
| `compliance.hallucination_rate` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 0.0 | healthy |
| `compliance.compliance_pass_rate` | authorization_and_safety | router_approval | deterministic_offline | measured | 1.0 | healthy |
| `compliance.false_support_rate` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 0.0 | healthy |
| `compliance.parameter_legality_rate` | workflow_planning | tool_contract_action_bundle | deterministic_offline | measured | 1.0 | healthy |
| `compliance.governance_leakage_count` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 0 | healthy |
| `compliance.unauthorized_execution_count` | authorization_and_safety | router_approval | controlled_execution | measured | 0 | healthy |
| `compliance.path_escape_count` | authorization_and_safety | controlled_executor | controlled_execution | measured | 0 | healthy |
| `compliance.approval_replay_violation_count` | authorization_and_safety | router_approval | controlled_execution | measured | 0 | healthy |
| `compliance.cross_user_access_violation_count` | authorization_and_safety | router_approval | controlled_execution | measured | 0 | healthy |
| `compliance.untrusted_code_execution_count` | authorization_and_safety | controlled_executor | controlled_execution | measured | 0 | healthy |
| `compliance.repair_budget_violation_count` | bounded_repair | repair_policy | controlled_execution | measured | 0 | healthy |
| `compliance.evidence_boundary_violation_count` | knowledge_qa | tool_contract_action_bundle | controlled_execution | measured | 0 | healthy |
| `compliance.os_level_isolation` | authorization_and_safety | controlled_executor | controlled_execution | not_run | - | unknown |
| `compliance.real_user_incorrect_claim_count` | user_trial | ui_trial_telemetry | human_trial | not_run | - | unknown |
| `effectiveness.dense_retrieval_gate` | knowledge_qa | kg_rag_retrieval | deterministic_offline | measured | 1 | healthy |

## Warnings

- `external_llm_repeat_variance_not_measured`
- `real_user_trial_not_completed`
- `ragas_not_run_or_not_authorized`

## Optimization priorities

- **P1 / product_validation / real_user_usability**: No qualifying 3-5 participant trial evidence is available. Run the frozen Level 1 task bank and supervised Level 2 synthetic execution; do not substitute automated rehearsal.
- **P1 / agent_evaluation / stochastic_agent_stability**: Repeated stochastic sampling for the configured external model has not been run. After explicit disclosure authorization, repeat a frozen paraphrase set across seeds and report variance and confidence intervals.
- **P2 / security_and_runtime / execution_isolation**: Native execution remains network_not_os_isolated. Keep arbitrary generated code disabled; qualify a container backend before claiming OS-level isolation.

## Limitations

- Deterministic repeated cases measure regression stability, not full stochastic LLM variance.
- Scientific pilots remain dataset-scoped and do not prove universal tool superiority.
- Automated UI and maintainer rehearsal do not substitute for real participant evidence.
- Native controlled execution is not an OS-level sandbox.
- This report augments hard safety gates; it cannot authorize execution or change release state.
