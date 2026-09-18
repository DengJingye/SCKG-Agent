# Retrieval Benchmark v1 — Development Campaign

Status: **COMPLETE**. This is a development experiment, not the formal Midterm holdout. COMPLETE records faithful execution and does not assert that KG or hybrid retrieval outperformed BM25.

- Query-set SHA-256: `224384015f0df2155c55478b432941c8fb899157352b1e27d29af22aff6e3773`
- Gold SHA-256: `d84aff99acc9d7a4d5f0d55fb9c5c052a8eb31a9fd8d8e24797cbc3b9b14fbaa`
- Retrieval-config SHA-256: `d9a3cdce283388dea82d95c3de0368d512c8e62b2b04ce76258e32f049687eec`
- Corpus digest: `7c8545721cd73a47fc0849ccc240ba2e150a064e07005de5f11ac26ab1213fd0`
- R1 scientific evidence queries: 45
- R2 tool/method discovery queries: 12

## Aggregate metrics

R1 and R2 are reported separately; catalog discovery rows never enter R1 scientific-evidence metrics.

| Profile | Track | Recall@5 | Recall@10 | MRR | nDCG@10 | Authoritative hit | Version hit | Scope hit | Irrelevant context |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| R0_bm25_only | R1_scientific_evidence | 0.378 | 0.422 | 0.223 | 0.259 | 0.511 | 0.320 | 0.400 | 0.833 |
| R0_bm25_only | R2_tool_method_discovery | 0.250 | 0.250 | 0.188 | 0.203 | 0.250 | not_applicable | not_applicable | 0.892 |
| R1_dense_only | R1_scientific_evidence | 0.311 | 0.400 | 0.247 | 0.261 | 0.467 | 0.240 | 0.300 | 0.840 |
| R1_dense_only | R2_tool_method_discovery | 0.417 | 0.417 | 0.176 | 0.235 | 0.417 | not_applicable | not_applicable | 0.866 |
| R2_bm25_dense_rrf | R1_scientific_evidence | 0.333 | 0.400 | 0.239 | 0.271 | 0.489 | 0.280 | 0.350 | 0.836 |
| R2_bm25_dense_rrf | R2_tool_method_discovery | 0.333 | 0.333 | 0.250 | 0.272 | 0.333 | not_applicable | not_applicable | 0.883 |
| R3_kg_bm25_dense_rrf | R1_scientific_evidence | 0.333 | 0.400 | 0.239 | 0.271 | 0.489 | 0.280 | 0.350 | 0.836 |
| R3_kg_bm25_dense_rrf | R2_tool_method_discovery | 0.417 | 0.417 | 0.312 | 0.338 | 0.417 | not_applicable | not_applicable | 0.829 |
| R4_kg_bm25_dense_rrf_governance | R1_scientific_evidence | 0.356 | 0.444 | 0.212 | 0.241 | 0.467 | 0.240 | 0.300 | 0.833 |
| R4_kg_bm25_dense_rrf_governance | R2_tool_method_discovery | 0.250 | 0.333 | 0.095 | 0.152 | 0.333 | not_applicable | not_applicable | 0.838 |

## KG paired diagnostic (R2 → R3)

- HELPED: 2
- NEUTRAL: 55
- HURT: 0
- KG positive-utility rate: 0.035088
- KG neutral rate: 0.964912
- KG false-filter rate: 0.0

## Governance diagnostic (R3 → R4)

- HELPED: 11
- NEUTRAL: 34
- HURT: 12

## Failure register

There are 171 failed query-profile records. Earliest attributable causes are preserved in `failure_register.jsonl`; no corpus, KG, gold, or retrieval configuration was changed after observing them.

## Boundaries

The primary statistical unit is the retrieval query/scientific information need. Multiple chunks and accepted spans under a query are nested OR-equivalent evidence alternatives, not independent observations. No aggregate RAG score is produced.
