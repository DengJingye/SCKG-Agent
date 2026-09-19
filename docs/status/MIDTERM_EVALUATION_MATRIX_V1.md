# Midterm Evaluation Matrix v1

| Suite | Current test set | Primary metric | Current status | Current strongest evidence | Main gap |
| --- | --- | --- | --- | --- | --- |
| KG-Eval | Inventory Snapshot v1; 8 audited OperatorRevisions | integrity + L0-L4 readiness | CURRENT_MEASURED | kg_inventory_snapshot_v1 | No canonical cross-layer identity merge; correctness metrics remain partial. |
| Ingestion-Eval | SoupX bounded pilots; formal 3-5 PDF gold not frozen | entity/relation/claim F1 + evidence alignment | PLANNED_PILOT_NOT_RUN | soupx_candidate_deposition_reuse_pilot | Freeze gold for 3-5 manually annotated authoritative PDFs before extraction. |
| Retrieval-Eval | Development benchmarks, historical sealed C7, current direct-evidence regression | Hit@5/10, MRR@10, abstention, false certainty | PARTIAL_CURRENT_AND_HISTORICAL | neighbors_direct_evidence_repair_v1 | Disclosed SEALED cases are quarantined from future post-fix validation. |
| Agent-Eval | 36 visible development conversation tasks | action/tool/binding/clarification/block accuracy | DEVELOPMENT_RESULT | agent_tool_selection_eval_v1 | Development cases are visible and are not independent validation. |
| Planner-Eval | Raw/Processed PBMC3k and four state-aware synthetic scenarios | reuse/recompute/block + invalid reuse | PILOT_PARTIAL | scientific_kg_contribution_paired_ablation | No frozen broad planner benchmark yet. |
| Justification-Eval | 12 atoms, 8 mutations, 4 paired scenarios | decision-evidence precision and evidence recall | FROZEN_HISTORICAL | decision_local_projection_v1_2 | Strong formal historical evidence; not new independent validation. |
| E2E-Eval | Raw and Processed PBMC3k current-version replay v2 | terminal completion separated from execution | CURRENT_MEASURED_PARTIAL | pbmc3k_replay_v2 | Annotation terminals remain BLOCKED; execution is not full scientific completion. |
| Trace-Eval | No formal injected-failure set | first causal failure and owner attribution | SPEC_DEFINED_BENCHMARK_NOT_RUN | none | No frozen injected-failure campaign has been run. |
| Regression-Eval | Checkpoint-focused unit/integration/regression selections | pass rates and artifact integrity | CURRENT_MEASURED_ENGINEERING | neighbors_regression_checkpoint | Overlapping test counts must not be summed or called scientific accuracy. |

No suite contributes to a global score. Each status and denominator must be reported independently.
