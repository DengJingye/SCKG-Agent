# Independent Retrieval Validation v1

Status: **COMPLETE**. The 42 parent scientific information needs, gold alternatives, 28/14 split, profiles, SUT, index, and KG identities were frozen before the single SEALED execution. SEALED was not used for tuning.

- Frozen SUT Git HEAD: `af8fa06ed3bd779662ee4b98ab30cf4dd708d42b`
- Query count: 42
- SEALED query count: 14
- SEALED validation used for tuning: `false`
- SEALED run count: `1`

## Midterm table

Hit@k and MRR@10 use the evidence-available parent queries: DEV 24 and SEALED 12. The six missing-evidence questions are assessed through abstention metrics.

| Profile | Dev Hit@5 | Dev Hit@10 | Dev MRR | Sealed Hit@5 | Sealed Hit@10 | Sealed MRR |
|---|---:|---:|---:|---:|---:|---:|
| A_bm25 | 0.667 | 0.708 | 0.464 | 0.583 | 0.667 | 0.338 |
| B_bm25_dense | 0.708 | 0.708 | 0.608 | 0.667 | 0.667 | 0.503 |
| C_scikg_bm25 | 0.667 | 0.708 | 0.464 | 0.583 | 0.667 | 0.338 |
| D_scikg_bm25_dense | 0.708 | 0.708 | 0.608 | 0.667 | 0.667 | 0.503 |
| E_scikg_bm25_dense_governance | 0.708 | 0.708 | 0.594 | 0.667 | 0.667 | 0.528 |

## Evidence quality and missing knowledge

An exact accepted EvidenceSpan in the top 10 is the frozen binding rule; the same adjudicated span carries the source and scope condition. Version correctness is reported only for category C.

| Profile | Split | Source | Scope | Version | Binding | Abstention | False certainty |
|---|---|---:|---:|---:|---:|---:|---:|
| A_bm25 | ALL | 0.694 (25/36) | 0.694 (25/36) | 1.000 (6/6) | 0.694 (25/36) | 0.167 | 5 |
| A_bm25 | DEV_CHECK | 0.708 (17/24) | 0.708 (17/24) | 1.000 (4/4) | 0.708 (17/24) | 0.000 | 4 |
| A_bm25 | SEALED | 0.667 (8/12) | 0.667 (8/12) | 1.000 (2/2) | 0.667 (8/12) | 0.500 | 1 |
| B_bm25_dense | ALL | 0.694 (25/36) | 0.694 (25/36) | 1.000 (6/6) | 0.694 (25/36) | 0.167 | 5 |
| B_bm25_dense | DEV_CHECK | 0.708 (17/24) | 0.708 (17/24) | 1.000 (4/4) | 0.708 (17/24) | 0.000 | 4 |
| B_bm25_dense | SEALED | 0.667 (8/12) | 0.667 (8/12) | 1.000 (2/2) | 0.667 (8/12) | 0.500 | 1 |
| C_scikg_bm25 | ALL | 0.694 (25/36) | 0.694 (25/36) | 1.000 (6/6) | 0.694 (25/36) | 0.167 | 5 |
| C_scikg_bm25 | DEV_CHECK | 0.708 (17/24) | 0.708 (17/24) | 1.000 (4/4) | 0.708 (17/24) | 0.000 | 4 |
| C_scikg_bm25 | SEALED | 0.667 (8/12) | 0.667 (8/12) | 1.000 (2/2) | 0.667 (8/12) | 0.500 | 1 |
| D_scikg_bm25_dense | ALL | 0.694 (25/36) | 0.694 (25/36) | 1.000 (6/6) | 0.694 (25/36) | 0.167 | 5 |
| D_scikg_bm25_dense | DEV_CHECK | 0.708 (17/24) | 0.708 (17/24) | 1.000 (4/4) | 0.708 (17/24) | 0.000 | 4 |
| D_scikg_bm25_dense | SEALED | 0.667 (8/12) | 0.667 (8/12) | 1.000 (2/2) | 0.667 (8/12) | 0.500 | 1 |
| E_scikg_bm25_dense_governance | ALL | 0.694 (25/36) | 0.694 (25/36) | 1.000 (6/6) | 0.694 (25/36) | 0.167 | 5 |
| E_scikg_bm25_dense_governance | DEV_CHECK | 0.708 (17/24) | 0.708 (17/24) | 1.000 (4/4) | 0.708 (17/24) | 0.000 | 4 |
| E_scikg_bm25_dense_governance | SEALED | 0.667 (8/12) | 0.667 (8/12) | 1.000 (2/2) | 0.667 (8/12) | 0.500 | 1 |

The retrieval API has no native abstain field, so zero returned hits is the strict observable proxy. Returning any candidate for an unsupported query is a false-certainty event.

## Scientific KG

- Hybrid B→D: HELPED 0, NEUTRAL 36, HURT 0.
- BM25 A→C: HELPED 0, NEUTRAL 36, HURT 0.
- Actual graph participation: 40/42 overall and 13/14 SEALED.
- KG fallback count: 0.
- False-filter events: 0.
- Direct graph EvidenceSpan resolution: 0. The frozen SUT used KG-derived tool candidates as a hard filter; its direct graph evidence resolver was inactive. This explains why high graph participation did not produce rank gains.

Dense still helped after the KG filter: C→D improved 11/36 answerable queries overall and 4/12 SEALED, with no regressions; the SEALED Hit@10 stayed equal while MRR rose from 0.338 to 0.503.

## Failure interpretation

Across all query-profile records, failure families were ranking=43, entity/operator resolution=12, and abstention=25. There were no corpus-gap failures because every answerable gold span existed in the frozen corpus. Scientific KG caused no new false filtering.

## Retrieval funnel boundary

Each row in `per_query_results.jsonl` records gold availability, observed sparse and dense candidate provenance, direct graph-evidence status, merged-pool observation, eligibility policy, and final top-5/top-10 outcome. Candidate booleans are observable within the frozen top-10 response; v1 did not persist candidates ranked below 10, and those fields are not retroactively reconstructed. `graph_participation.jsonl` records expected tool resolution, accepted EvidenceSpan IDs, mapped chunks, conditions, fallback reason, and whether the graph-filtered pool placed gold in the final top 10.

## Reproducibility boundary

`manifest.json` is the pre-run freeze record. `run_completed.json` records the only SEALED execution. The reporting finalizer performed no retrieval and changed no metric. Gold was manually adjudicated from frozen corpus records without using C7 production retrieval output. Accepted spans within a query are OR alternatives; the parent query remains the statistical unit.
