# Retrieval Benchmark v1.1 — Development Campaign

Status: **COMPLETE**. This is a frozen development comparison, not the formal Midterm holdout.

- Query-set SHA-256: `224384015f0df2155c55478b432941c8fb899157352b1e27d29af22aff6e3773`
- Gold SHA-256: `d84aff99acc9d7a4d5f0d55fb9c5c052a8eb31a9fd8d8e24797cbc3b9b14fbaa`
- Strengthened corpus digest: `8d8990ec75f25c598f467b0da0ca2ad81ce9f0931efadff7f70acec4b7a47436`
- Dense build: `retrieval-foundation-v1-ff5b4829bc5943f4`

## v1.1 metrics

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

## Frozen cohort results

- **original_governance_hurt**: 12 queries
  - v1.1 governance: `{'NEUTRAL': 7, 'HURT': 5}`
- **previous_gold_source_not_indexed**: 21 queries
- **repaired**: 17 queries
- **still_blocked**: 4 queries
- **unaffected_r1**: 24 queries

## Causal diagnostics

- KG R2→R3: `{'NEUTRAL': 55, 'HELPED': 2}`
- Governance R3→R4: `{'NEUTRAL': 43, 'HURT': 6, 'HELPED': 8}`
- Failure first causes: `{'BM25_RANKING': 13, 'DENSE_RANKING': 17, 'DIVERSIFICATION_RANKED_OUT': 3, 'ENTITY_ASSOCIATION_OR_FILTER_MISMATCH': 5, 'GOLD_SOURCE_NOT_INDEXED': 20, 'GOVERNANCE_RERANK': 31, 'INITIAL_RETRIEVAL_MISS': 15, 'RRF_RANKED_OUT': 1, 'TOOL_NORMALIZATION': 10}`
- OTHER: 0

No corpus, gold, queries, KG, Planner, thresholds, or ranking configuration was changed after observing the v1.1 result.
