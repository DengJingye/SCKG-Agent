# Scientific KG Admin Workspace Read-only V1

## Exit report

```text
STATUS=PASS
CHANGED_FILES=app.py; engine/scientific_kg_admin.py; eval/scientific_kg_admin_workspace_readonly_v1.py; tests/test_scientific_kg_admin_workspace_readonly_v1.py; docs/status/SCIENTIFIC_KG_ADMIN_SURFACE_AUDIT_V1.md; docs/status/SCIENTIFIC_KG_ADMIN_WORKSPACE_READONLY_V1.md; data/evaluation/scientific_kg_admin_workspace_readonly_v1/*
FOCUSED_TESTS=14 passed in 2.60s
REGRESSION_TESTS=110 passed, 5 verified-baseline failures deselected in 35.19s
REAL_RUN=PASS: Streamlit server health 200 and root page 200 on localhost:8765; six existing/new admin entries rendered without exceptions
ARTIFACT_INTEGRITY=PASS: Scientific KG, Legacy Tool KG, Decision Graph, retrieval corpus/index, planner, gold, and contracts identities matched

PRIMARY_RESULT=Existing Streamlit app now has a read-only Admin · Scientific KG page with Overview, bounded Scientific Graph, and Readiness & Integrity tabs backed by the frozen Checkpoint-1 fact source.
CURRENT_LIMITATION=This page does not review or promote candidates; broad expansion/reference layers retain declared unmaterialized evidence references, and physical layer counts intentionally retain overlapping identities.
NEXT_EARLIEST_DIVERGENCE=Checkpoint 4 PDF Ingestion Capability Audit; no ingestion implementation should begin before that audit.

CORPUS_CHANGED=false
KG_CONTENT_CHANGED=false
PLANNER_CHANGED=false
GOLD_CHANGED=false
CANONICAL_PROMOTION=false

STOPPED=true
```

## Result

The new page reports the frozen Scientific KG as 1,651 nodes and 2,429 edges. It keeps 380 candidate claims separate from 0 reviewed and 0 trusted/canonical claims. The page also reports 170 physical EvidenceSpan records, 77 EvidenceGap records, 8 audited UAT OperatorRevisions, readiness of 6 at L4 and 2 at L2, 0 hard integrity issues, and 43 declared warnings.

The three graph substrates remain explicit:

- Legacy Tool KG: 7,537 nodes / 17,667 edges.
- Decision Graph: 1,058 nodes / 1,318 edges.
- Scientific KG: 1,651 nodes / 2,429 edges.

The interface uses `DO_NOT_SUM_ACROSS_LAYERS` and never presents these as one total.

## Scientific Graph behavior

The graph tab defaults to a bounded real PCA subgraph and also provides neighbors and Leiden examples. Search can filter by actual node type, expands one or two hops, and caps the canvas at 50, 75, or 100 nodes. Node details preserve graph identity, canonical record ID, frozen layer, candidate/source status, and the original record. SourceRevision nodes are field-backed display projections from frozen source manifests, clearly marked and excluded from the 1,651 physical-node total.

Atomic claims expose a drilldown from claim to EvidenceAssessment, EvidenceSpan, and SourceRevision. Complete UAT chains resolve normally. Frozen expansion/reference bindings whose spans are not materialized remain visible as incomplete chains with explicit reasons.

## Readiness and integrity

The readiness tab uses the Checkpoint-1 UAT scope and its L0-L4 definitions. It shows SourceRevision as 6 physical records and 5 distinct IDs because frozen layers overlap and were not identity-merged. Warnings describe retained evidence coverage boundaries; they are not counted as hard failures or silently converted to successes.

## Validation

- Focused: `tests/test_scientific_kg_admin_workspace_readonly_v1.py` — 14 passed.
- Bounded regression: 110 passed with an isolated test home. Five unrelated assertions were deselected after reproducing the same failures at clean commit `2f7b3ab`: two Research Agent handoff/UI wording assertions and three Decision Graph readiness/hierarchy assertions.
- Real run: `streamlit run app.py --server.headless true --server.port 8765`; `/_stcore/health` and `/` both returned HTTP 200. Separate AppTest runs opened Graph Explorer, Knowledge Review, Evidence & RAG, Evaluation, Architecture, and Scientific KG without exceptions.
- Integrity: all 84 protected Checkpoint-1 files matched their frozen hashes, and Decision Graph nodes, edges, and ActionBundles matched its manifest.

## Generated artifacts

The reproducible artifact bundle is in `data/evaluation/scientific_kg_admin_workspace_readonly_v1/`:

- `manifest.json`
- `ui_metric_binding.json`
- `graph_examples.json`
- `readiness_binding.json`
- `integrity_binding.json`
- `focused_test_summary.json`
- `regression_summary.json`
- `integrity.json`

Checkpoint 3 remains uncommitted for human review. No PDF ingestion, Admin Review mutation, Trace Explorer, Planner-Eval, or later checkpoint work was started.
