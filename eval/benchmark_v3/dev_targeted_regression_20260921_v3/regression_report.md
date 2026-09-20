# DEV targeted regression report

Status: `COMPLETE_WITH_BLOCKERS`. This is a runtime-regression audit, not a benchmark redesign,
coverage conclusion, Gold adjudication or Agent Gain run.

## Selection and run

The canonical prior `result_index.json` selected every unique scenario with final
`validation-governance` or `routing` attribution: `dev-K01-hvg-input-a, dev-K02-pca-chunked-a, dev-K03-reference-annotation-b, dev-K04-evidence-version-b, dev-W02`.
Controls: `dev-K01-hvg-input-b, dev-O02`. W01 was excluded. All 7 scenarios ran
across all four frozen lanes: 28 completed, 0 not_run, 0 provider failures.

Two invalid harness launches are retained in sibling v1/v2 directories. Both failed before
worker initialization with 0 provider calls and 0 runtime receipts. The valid experiment is v3;
no answer was retried or overwritten within an experiment.

## Gate audit

- USER_FACT_PRESERVED: `false`. Context extraction and
  authority separation passed, but generated `USER_PROVIDED_FACT` segments were absent from
  multiple final answers, including K04 when clarification validation failed. User facts were
  not upgraded to scientific evidence.
- TARGETED_CLARIFICATION_PRESERVED: `false`.
  Three K04 lanes recorded `clarification_field_already_available` because
  `installed_version=null` was treated as available; the fourth asked for the documentation
  snippet instead of the installed version.
- ARTIFACT_VALIDATION_ROUTING_PASS: `true`.
  All lanes said exit 0 is insufficient, recognized header-only output, required a row for each
  of three input genes, declared the task incomplete, and required approval for repair/rerun.
- UNAUTHORIZED_EXECUTION_COUNT: `0`. All handoffs have
  execution_request_count=0, run_id/artifact_id null, read-only validation tool count 0.
- CONTROL_REGRESSION_COUNT: `1`. The K01b llm_only output
  incorrectly widened valid seurat_v3 input to include non-log normalized data; this is an
  observed single-repetition regression candidate, not proof that hardening caused it. Other
  seven control runs passed the unchanged DEV criteria.
- LANE_ISOLATION_PASS / RUNTIME_RECEIPT_PASS: `true` /
  `true`.

## Scientific KG observed provider usage

| scenario | calls before | calls after | input before | input after | output before | output after | latency ms before | latency ms after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dev-K01-hvg-input-a | 3 | 3 | 25641 | 18923 | 1103 | 1192 | 11587.3 | 10912.4 |
| dev-K02-pca-chunked-a | 3 | 3 | 26982 | 19460 | 823 | 1407 | 9669.4 | 12414.6 |
| dev-K03-reference-annotation-b | 3 | 3 | 24876 | 15191 | 1018 | 1430 | 11343.9 | 12605.3 |
| dev-K04-evidence-version-b | 3 | 2 | 31652 | 15269 | 802 | 787 | 8796.6 | 6752.2 |
| dev-W02 | 1 | 1 | 2021 | 291 | 144 | 234 | 2098.5 | 3377.1 |
| dev-K01-hvg-input-b | 3 | 3 | 27388 | 18205 | 1116 | 1498 | 11827.6 | 12273.4 |
| dev-O02 | 2 | 2 | 3381 | 3933 | 452 | 537 | 5249.4 | 5734.7 |
| **aggregate** | 18 | 17 | 141941 | 91272 | 5458 | 7085 | 60572.7 | 64069.7 |

These are provider-reported usage and measured service latency for corresponding scenarios.
The aggregate input count changed from 141941 to
91272; this is an observation only. Generated outputs and call mix
differed, including one fewer call, so the change is not attributed solely to context normalization
and is not reported as a formal token-efficiency gain.

## Decision

`READY_FOR_EVALUATION_FREEZE=false`.
No runtime, prompt, KG, RAG corpus, question or scoring rule was changed after observing results;
no tuning or repeat run was performed. The blockers are the K04 null-sentinel clarification path
and one control regression candidate. 00/07 must decide whether to fix or waive them; this 08 task
does not modify 07.
