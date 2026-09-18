# Retrieval Benchmark v1.1 DEV — Invalidation Record

Status: **INVALID**

The campaign executed exactly once and its original artifacts are preserved without alteration. The primary top-k ranking outputs and Recall/MRR/nDCG values remain useful as diagnostic observations only; they are not accepted as formal v1.1 conclusions.

The mandatory first-cause attribution was invalid. The frozen harness allowed `GOVERNANCE_RERANK` to be assigned from a diagnostic governance rank even for R2 and R3 profiles that did not execute governance reranking. This corrupted the required failure register and causal decomposition while leaving the already-produced retrieval rankings unchanged.

No corpus, dense index, KG, governance behavior, retrieval weight, query, gold, Planner, ToolContract, Seed, or source eligibility was modified after observing the result. The campaign was not rerun.

- Query-set SHA-256: `224384015f0df2155c55478b432941c8fb899157352b1e27d29af22aff6e3773`
- Gold SHA-256: `d84aff99acc9d7a4d5f0d55fb9c5c052a8eb31a9fd8d8e24797cbc3b9b14fbaa`
- Snapshot: `retrieval-foundation-v1-ff5b4829bc5943f4`
- Corpus digest: `8d8990ec75f25c598f467b0da0ca2ad81ce9f0931efadff7f70acec4b7a47436`
- Original report SHA-256: `9eff682c17b6c77b3bfc7c1e6054e914bb23776e954c5faeba169ab85f26fc2a`
- Run count: `1`

This invalid campaign must never be overwritten. A repaired evaluation-only harness must write a distinct v1.1.1 campaign directory.
