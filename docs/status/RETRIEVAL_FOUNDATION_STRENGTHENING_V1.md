# Retrieval Foundation Strengthening v1

Status: **PASS_WITH_REMAINING_GAPS**

The frozen Retrieval Benchmark v1 DEV was not overwritten or rerun. This checkpoint repairs demonstrated retrieval-foundation gaps and preserves unresolved gaps rather than weakening source-binding rules.

## Missing gold-source coverage

- Profile-level GOLD_SOURCE_NOT_INDEXED records: 105
- Unique affected queries: 21
- Unique EvidenceSpans: 21
- Unique SourceRevisions: 5
- Resolved SourceWorks: 7
- Exact governed spans newly indexed in separate snapshot: 17
- Untouched evidence gaps: 4

## Governance rerank

- Frozen HURT cases examined: 12
- HURT after bounded-signal regression audit: 5
- HELPED after repair: 0
- NEUTRAL after repair: 7

The defect was architectural: absolute governance additions overwhelmed RRF scores. Existing signals are now bounded multipliers; no benchmark-specific IDs or new scoring features were introduced.

## New candidate retrieval snapshot

- Build ID: `retrieval-foundation-v1-ff5b4829bc5943f4`
- Sources: 63 → 68
- Evidence chunks: 783 → 800
- Eligible source chunks / vectors: 773 → 790
- Corpus digest before: `7c8545721cd73a47fc0849ccc240ba2e150a064e07005de5f11ac26ab1213fd0`
- Corpus digest after: `8d8990ec75f25c598f467b0da0ca2ad81ce9f0931efadff7f70acec4b7a47436`
- Index manifest SHA-256: `0afc019e7c4cb5b52ea89dbccdb70b2d1e40cf3100efbd4562e0966d2a78d92a`
- Candidate-only: true
- Canonical promotion: none

## Remaining gaps

Four frozen gold spans remain outside the index because their candidate records lack an independently resolvable exact SourceArtifact/SourceRevision: Scanpy normalize_total, edgeR DGEList, Slingshot primary evidence, and pySCENIC primary evidence.

## Boundaries

No Seed v1, formal holdout, candidate promotion, KG mutation, Planner change, or Retrieval Benchmark v1 rerun occurred.
