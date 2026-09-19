# Scientific KG Narrow Direct-Evidence Qualification v1

Status: **PARTIAL**
Scope: production-path qualification of the six existing L4 candidate operators. This is not an independent benchmark or a generalization result.

## Frozen design

- 18 repository-derived parent cases, three per operator.
- Production entry: `ResearchToolRegistry.execute` with one `search_evidence` call.
- Only `query` was supplied as scientific input; expected IDs and answerability were retained outside the production call.
- Sparse retrieval used the existing frozen `retrieval_foundation_v1`; dense retrieval was disabled. No corpus, index, KG content, weights, Planner, ToolContract, Capability Pack, or policy was changed.
- Candidate status remained candidate; qualification performed no promotion.

## Primary metrics

| Metric | Result | Rate |
|---|---:|---:|
| OPERATOR_SUBJECT_RESOLUTION | 18/18 | 100.0% |
| OPERATOR_REVISION_RESOLUTION | 18/18 | 100.0% |
| DIRECT_CLAIM_RESOLUTION | 13/14 | 92.9% |
| DIRECT_EVIDENCE_SPAN_RESOLUTION | 13/13 | 100.0% |
| RAG_CHUNK_MAPPING | 11/12 | 91.7% |
| ANSWERABILITY_CORRECTNESS | 17/18 | 94.4% |
| SUPPORTED_CORRECTNESS | 11/11 | 100.0% |
| CLAIM_TYPE_FIDELITY | 17/18 | 94.4% |
| SOURCE_BINDING_CORRECTNESS | 13/13 | 100.0% |
| SCOPE_VERSION_CORRECTNESS | 6/6 | 100.0% |
| UNRELATED_CLAIM_LEAKAGE | 1/18 | 5.6% |
| FALSE_SUPPORTED | 0/6 | 0.0% |

Observed answerability: `{"CLARIFICATION_REQUIRED": 1, "SUPPORTED": 11, "UNRESOLVED": 6}`.

## Operator results

| Operator | Status | Correct answerability | Available information needs | Failure classes |
|---|---|---:|---|---|
| HVG | PASS | 3/3 | input_requirement, output | none |
| LEIDEN | PASS | 3/3 | input_requirement, output | none |
| NEIGHBORS | PARTIAL | 2/3 | input_requirement, output | EVIDENCE_MAPPING_ERROR |
| PCA | PASS | 3/3 | input_requirement | none |
| SINGLER | PARTIAL | 3/3 | compatibility, input_requirement | CLAIM_SELECTION_ERROR |
| UMAP | PASS | 3/3 | input_requirement | none |

## Bounded failures

- `qual-neighbors-indirect-input`: **EVIDENCE_MAPPING_ERROR** — expected SUPPORTED, observed UNRESOLVED; fallback `public_eligibility_filter_rejected_graph_evidence`.
- `qual-singler-indirect-compatibility`: **CLAIM_SELECTION_ERROR** — expected SUPPORTED, observed SUPPORTED; fallback `none`.

The neighbors input claim resolves through OperatorRevision, claim, scope, EvidenceSpan, and source binding, but its frozen RAG chunk is labelled `Harmony` in `tool_name/tool_names`. The existing public eligibility filter therefore rejects it. This is recorded as `EVIDENCE_MAPPING_ERROR`; the frozen corpus was not repaired.

The SingleR compatibility query also parses the generic word “require” as an input need, so it returns three unrelated input claims in addition to the correct compatibility claim. Answerability remains supported, but claim-type fidelity fails. This is recorded as `CLAIM_SELECTION_ERROR`; claim-selection semantics were not changed.

## Interpretation

HVG, PCA, UMAP, and Leiden pass this narrow production qualification. Neighbors and SingleR are partial. The result demonstrates that an existing bounded Scientific KG slice is consumable through the real search path, while preserving abstention and exposing two concrete quality limits. It does not establish benchmark accuracy beyond these repository-derived cases.

## Integrity

- Protected artifacts unchanged: `true`
- C7 SEALED accessed: `false`
- C7 rerun: `false`
- Scientific content added: `false`
- Corpus/index rebuild: `false`
- Promotion: `none`
- Focused qualification tests: `PASS` (9/9 passed)
- Research Chat regression: `PASS` (56/56 passed)
