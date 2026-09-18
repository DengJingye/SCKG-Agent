# Retrieval Benchmark v1.1.1 — Development Campaign

Status: **COMPLETE**. The evaluation-only attribution repair was frozen before this single run. This is not a formal holdout.

- Query SHA: `224384015f0df2155c55478b432941c8fb899157352b1e27d29af22aff6e3773`
- Gold SHA: `d84aff99acc9d7a4d5f0d55fb9c5c052a8eb31a9fd8d8e24797cbc3b9b14fbaa`
- Runner SHA: `1bd0a5b97627f3406a3c106bc265a8a6a6cdd821afbcc708c9cba3af4845fe63`
- Snapshot: `retrieval-foundation-v1-ff5b4829bc5943f4`

## Primary results

| Profile | Track | Recall@5 | Recall@10 | MRR | nDCG@10 | Authoritative hit | Irrelevant context |
|---|---|---:|---:|---:|---:|---:|---:|
| R0_bm25_only | R1_scientific_evidence | 26/45 (0.578) | 31/45 (0.689) | 0.382 | 0.398 | 35/45 (0.778) | 0.796 |
| R0_bm25_only | R2_tool_method_discovery | 3/12 (0.250) | 3/12 (0.250) | 0.188 | 0.203 | 3/12 (0.250) | 0.892 |
| R1_dense_only | R1_scientific_evidence | 19/45 (0.422) | 25/45 (0.556) | 0.338 | 0.328 | 28/45 (0.622) | 0.824 |
| R1_dense_only | R2_tool_method_discovery | 5/12 (0.417) | 5/12 (0.417) | 0.176 | 0.235 | 5/12 (0.417) | 0.866 |
| R2_bm25_dense_rrf | R1_scientific_evidence | 22/45 (0.489) | 31/45 (0.689) | 0.340 | 0.367 | 35/45 (0.778) | 0.807 |
| R2_bm25_dense_rrf | R2_tool_method_discovery | 4/12 (0.333) | 4/12 (0.333) | 0.250 | 0.272 | 4/12 (0.333) | 0.883 |
| R3_kg_bm25_dense_rrf | R1_scientific_evidence | 22/45 (0.489) | 31/45 (0.689) | 0.340 | 0.367 | 35/45 (0.778) | 0.807 |
| R3_kg_bm25_dense_rrf | R2_tool_method_discovery | 5/12 (0.417) | 5/12 (0.417) | 0.312 | 0.338 | 5/12 (0.417) | 0.829 |
| R4_kg_bm25_dense_rrf_governance | R1_scientific_evidence | 23/45 (0.511) | 31/45 (0.689) | 0.381 | 0.388 | 35/45 (0.778) | 0.807 |
| R4_kg_bm25_dense_rrf_governance | R2_tool_method_discovery | 4/12 (0.333) | 4/12 (0.333) | 0.229 | 0.255 | 4/12 (0.333) | 0.838 |

## Cohorts and causal diagnostics

- Repaired cohort: 17 queries
- Still-blocked cohort: 4 queries
- Unaffected R1 cohort: 24 queries
- KG R2→R3: `{'NEUTRAL': 55, 'HELPED': 2}`; false-filter rate `0.0`
- Governance R3→R4: `{'NEUTRAL': 43, 'HURT': 6, 'HELPED': 8}`
- Valid first-cause register: `{'BM25_RANKING': 9, 'DENSE_RANKING': 15, 'DIVERSIFICATION_RANKED_OUT': 3, 'ENTITY_ASSOCIATION_OR_FILTER_MISMATCH': 5, 'GOLD_SOURCE_NOT_INDEXED': 20, 'GOVERNANCE_RERANK': 1, 'INITIAL_RETRIEVAL_MISS': 21, 'RRF_RANKED_OUT': 31, 'TOOL_NORMALIZATION': 10}`
- Profile/stage attribution violations: 0

The top-k outputs are byte/semantic-equivalent to the preserved invalid v1.1 campaign. Only evaluation attribution changed; invalid v1.1 observations were not used to tune retrieval behavior.
