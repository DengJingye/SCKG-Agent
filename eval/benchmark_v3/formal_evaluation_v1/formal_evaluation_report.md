# scKG-Agent V3 formal evaluation report

## 1. Dataset scale and composition

The frozen pilot contains 36 evaluation scenarios: K=24 (12 paired-condition families), O=8 independent public-issue triage scenarios, and W=4 project-owned read-only validation fixtures. The analysis unit for paired contrasts is the 24 independent families after aggregation across conditions and three repetitions.

## 2. Freeze and leakage checks

Freeze timestamp: `2026-09-20T21:41:43.188487+00:00`. Manifest SHA256: `156a41b777a4d75991d3cfb455d80fb2569ac3e8b9a17d05587253278b658cd7`. DEV case, family, and source-thread exact-overlap checks passed. Two isolated AI-assisted reviews and a separate AI-assisted adjudication were completed; they are not represented as human review. Public issue exposure remains recorded and rewriting is not treated as decontamination.

## 3. Four-lane formal results

| Lane | K pass | O useful | W success | Runs completed |
|---|---:|---:|---:|---:|
| llm_only | 25.0% | 45.8% | 25.0% | 108/108 |
| generic_rag | 34.7% | 29.2% | 33.3% | 108/108 |
| legacy_kg | 27.8% | 12.5% | 58.3% | 108/108 |
| scientific_kg | 26.4% | 33.3% | 41.7% | 108/108 |

## 4. K/O/W track detail

K reports condition-correct task pass, critical-fact recall, condition/scope error, paired-family pass, and unsupported scientific claims:

| Lane | Task pass | Critical-fact recall | Scope error | Paired families passed | Unsupported claims |
|---|---:|---:|---:|---:|---:|
| llm_only | 18/72 (25.0%) | 25.0% | 0/72 | 0/12 | 0/72 |
| generic_rag | 25/72 (34.7%) | 34.7% | 0/72 | 0/12 | 0/72 |
| legacy_kg | 20/72 (27.8%) | 27.8% | 0/72 | 0/12 | 0/72 |
| scientific_kg | 19/72 (26.4%) | 26.4% | 0/72 | 0/12 | 0/72 |

O reports useful triage, specific clarification, answerable-case resolution, over-refusal, and unsupported diagnosis:

| Lane | Useful response | Targeted clarification | Answerable resolution | Over-refusal | Unsupported diagnosis |
|---|---:|---:|---:|---:|---:|
| llm_only | 11/24 (45.8%) | 9/12 (75.0%) | 4/12 (33.3%) | 0/24 | 0/24 |
| generic_rag | 7/24 (29.2%) | 3/12 (25.0%) | 6/12 (50.0%) | 0/24 | 0/24 |
| legacy_kg | 3/24 (12.5%) | 3/12 (25.0%) | 2/12 (16.7%) | 0/24 | 0/24 |
| scientific_kg | 8/24 (33.3%) | 6/12 (50.0%) | 5/12 (41.7%) | 0/24 | 0/24 |

W reports contract success, state/plan validity, artifact validation, approval violations, and unauthorized execution:

| Lane | Workflow success | Plan validity | State correctness | Artifact validation | Approval violations | Unauthorized execution |
|---|---:|---:|---:|---:|---:|---:|
| llm_only | 3/12 (25.0%) | 3/12 | 3/12 | 3/12 | 0/12 | 0/12 |
| generic_rag | 4/12 (33.3%) | 4/12 | 4/12 | 4/12 | 0/12 | 0/12 |
| legacy_kg | 7/12 (58.3%) | 7/12 | 7/12 | 7/12 | 0/12 | 0/12 |
| scientific_kg | 5/12 (41.7%) | 5/12 | 5/12 | 5/12 | 0/12 | 0/12 |

No cross-track weighted score is constructed. Full run- and family-level values are in `metrics/metrics.json` and `metrics/family_results.jsonl`.

## 5. Scientific KG vs Generic RAG

Family-level paired difference: -0.014; bootstrap 95% CI [-0.1388888888888889, 0.11111111111111112].

## 6. Scientific KG vs Legacy KG

Family-level paired difference: 0.035; bootstrap 95% CI [-0.09027777777777779, 0.16666666666666666].

## 7. Scientific KG vs LLM-only

Supplemental family-level paired difference: -0.007; bootstrap 95% CI [-0.1527777777777778, 0.13211805555555306].

## 8. Condition, scope, and evidence

| Lane | K scope error | Unsupported scientific claims | Evidence reliability |
|---|---:|---:|---:|
| llm_only | 0.0% | 0.0% | n/a |
| generic_rag | 0.0% | 0.0% | 100.0% |
| legacy_kg | 0.0% | 0.0% | 100.0% |
| scientific_kg | 0.0% | 0.0% | 100.0% |

Evidence reliability is separate from scientific correctness. LLM-only answers are not marked scientifically wrong solely for lacking citations.

## 9. Failure attribution

{"correct_clarification":12,"correct_stop":11,"coverage_gap":96,"retrieval":6,"synthesis":50,"unresolved":121,"validation-governance":29}

Attributions are bound to captured output, context, receipt, coverage review, or fixture. When the records did not support a narrower cause, the stage is `unresolved`.

## 10. Latency, tokens, and calls

| Lane | Calls | Observed input tokens | Observed output tokens | Runs with complete usage | Mean latency ms |
|---|---:|---:|---:|---:|---:|
| llm_only | 186 | 212251 | 38522 | 58/108 | 3975.0 |
| generic_rag | 192 | 202519 | 36881 | 56/108 | 3960.2 |
| legacy_kg | 186 | 174360 | 31762 | 54/108 | 4648.9 |
| scientific_kg | 210 | 488188 | 45099 | 60/108 | 4654.9 |

Token totals are lower bounds over runs for which the provider returned complete usage; they are not complete-lane totals and should not be used for normalized token-efficiency claims. Latency is calculated across all completed runs. No monetary cost is inferred because the frozen provider receipt exposes no authoritative price schedule.

## 11. Representative successes

The first passing K run in sorted run-ID order for each lane is shown to avoid outcome-favorable selection:

- `eval-K01-harmony-embedding-b--llm_only--r0`; answer hash `67c2e547aa75`.
- `eval-K01-harmony-embedding-b--generic_rag--r0`; answer hash `d56f196aa848`.
- `eval-K02-scvi-count-input-b--legacy_kg--r1`; answer hash `4d81fdb0d1fc`.
- `eval-K01-harmony-embedding-b--scientific_kg--r1`; answer hash `aab09db46f31`.

## 12. Representative failures

The first failing K run in sorted run-ID order for each lane is shown using the same mechanical rule:

- `eval-K01-harmony-embedding-a--llm_only--r0`; answer hash `cba31d432be1`.
- `eval-K01-harmony-embedding-a--generic_rag--r0`; answer hash `bf3b0ede716c`.
- `eval-K01-harmony-embedding-a--legacy_kg--r0`; answer hash `6d2a1c7df500`.
- `eval-K01-harmony-embedding-a--scientific_kg--r0`; answer hash `46f568950f66`.

The evidence-backed attribution table records a narrower stage only where the captured trace supports it; otherwise the failure remains `unresolved`.

## 13. Limitations

This is a 36-scenario pilot, not evidence of broad scientific generalization. The formal reference review is AI-assisted rather than the originally preferred two-human Gold process. Scoring uses a frozen deterministic semantic checklist and can miss valid paraphrases or accept keyword-compatible weak prose. K topics are concentrated in the approved snapshot's scientific scope, O uses title-only public issues with explicitly synthetic context, and W uses small project-authored read-only fixtures. Provider sampling has no deterministic seed. Coverage presence is based on exact source-bound evidence and may undercount semantically equivalent corpus passages. Provider token usage is incomplete and the observed totals are lower bounds. The four product lanes differ in both corpora and answer-governance behavior, so product contrasts do not isolate graph structure alone.

## 14. Scientific KG gain conclusion

This pilot does **not** show a robust aggregate Scientific KG advantage. The primary family-level contrast was -1.4 percentage points versus Generic RAG (95% CI -13.9 to +11.1) and +3.5 points versus Legacy KG (95% CI -9.0 to +16.7); both intervals include zero. The supplemental contrast versus LLM-only was -0.7 points (95% CI -15.3 to +13.2).

The point estimates show localized differences, not an established KG-specific gain. Scientific KG was higher on O triage than Generic RAG and Legacy KG (33.3% versus 29.2% and 12.5%), and higher on W than Generic RAG and LLM-only (41.7% versus 33.3% and 25.0%). It did not lead K (26.4% versus 34.7% Generic RAG and 27.8% Legacy KG), and no lane passed an entire paired K family under the strict frozen criterion. Legacy KG led W at 58.3%, while LLM-only led O at 45.8%. Because W measures shared runtime behavior and the product lanes differ in more than corpus structure, these local differences cannot be attributed uniquely to Scientific KG.

Coverage subgroups also do not establish a Scientific KG advantage: for signature `100`, Scientific KG scored 25.8% versus 31.8% Generic RAG, 22.7% Legacy KG, and 25.8% LLM-only; for `111`, it scored 33.3% versus 66.7%, 83.3%, and 16.7%, respectively. These subgroup sample sizes are small (`n=66` and `n=6` run units per lane), and no post-hoc favorable subset is used as the primary result.
