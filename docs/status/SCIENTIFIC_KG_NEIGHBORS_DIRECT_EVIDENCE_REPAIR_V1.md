# Scientific KG Neighbors Direct-Evidence Repair v1

Status: **PASS**

This checkpoint repairs one production-path ownership defect without changing Scientific KG content, frozen corpus bytes, indexes, retrieval weights, Planner, ToolContract, Capability Pack, or SingleR behavior.

## Earliest divergence

The exact neighbors input EvidenceSpan already mapped to the exact frozen chunk by span identity, SourceRevision, locator, content hash, excerpt, source-bound status, and retrieval status. The frozen chunk carries legacy `tool_name/tool_names=Harmony`. The first behavior-changing divergence occurred when the public eligibility filter treated that legacy retrieval label as the Scientific KG proposition owner and rejected the exact claim-bound chunk.

Owner: `engine/hybrid_retrieval.py::HybridRetrievalService` public eligibility interpretation.

## One-layer repair

For the Scientific KG graph channel only, exact chunks returned by the governed `OperatorRevision → AtomicClaim → EvidenceAssessment → EvidenceSpan` binding use that proposition ownership during public filtering. Scientific scope is enforced before this filter. Sparse, dense, and unbound chunks continue to use their original chunk metadata, so unrelated Harmony evidence remains excluded.

## Requalification

- NEIGHBORS_BEFORE: `PARTIAL`
- NEIGHBORS_AFTER: `PASS`
- EVIDENCE_SPAN_RESOLUTION: `2/2`
- RAG_CHUNK_MAPPING: `2/2`
- PUBLIC_ELIGIBILITY: `2/2`
- ANSWERABILITY: `3/3`
- SUPPORTED_CORRECTNESS: `2/2`
- FALSE_SUPPORTED: `0/1`

## Regression

- HVG: `PASS`
- LEIDEN: `PASS`
- PCA: `PASS`
- UMAP: `PASS`
- SingleR changed: `false`
- Full 18-case qualification rerun: `false`
- Focused tests: `PASS` (59 tests)
- Research Chat regression: `PASS` (56 tests)
- One historical preflight was deselected because its frozen hash guard already rejects preexisting `agent/research_chat_reasoner.py` drift unrelated to this repair.

## Integrity

- Original qualification data and report byte-identical: `true`
- Scientific content added: `false`
- Corpus changed: `false`
- Index changed: `false`
- Retrieval weights changed: `false`
- KG content changed: `false`
- Planner changed: `false`
- Promotion: `none`
- C7 SEALED accessed: `false`
- C7 validation rerun: `false`

C7 SEALED bytes were intentionally not opened for hashing; the stronger no-access boundary takes precedence. No repair code or runner imports a C7 loader or path.
