# Existing UMAP cluster-label display

Date: 2026-09-21. Scope: DEMO/UI visualization only.

The reused-UMAP notebook cell passed `color=None`, so existing labels were never
displayed. The separate diagnostic for newly computed UMAP checks `leiden`;
neither path previously read the inspector's generic cluster-label binding.

The reuse renderer now resolves `cluster_labels` from current, validated
RepresentationLedger records and uses each record's `obs/<actual key>` slot.
It accepts arbitrary inspector-bound column names, with no `louvain`/`leiden`
name allowlist. Duplicate bindings are collapsed; multiple valid bindings get
separate color panels. Missing, stale or unvalidated bindings remain explicitly
unlabelled rather than guessing another obs column. The heading, printed message
and plot title say **Reusing existing UMAP; no recomputation**.

Planner, inspector detection rules, state reuse, KG, ontology, execution policy,
and the raw workflow's computation/diagnostic cells are unchanged. Existing
exported notebooks were preserved. Regenerate a notebook to obtain the updated
display cell; reuse-only notebooks contain loading and plotting cells only.

## Actual processed PBMC3k validation

The existing `../demo-data/pbmc3k/pbmc3k_processed.h5ad` was inspected read-only:

- Shape: 2638 × 1838.
- SHA256: `4451252b97b25441d720e9d3b9b830c418b12ba77be8d1e88151c0ea40b3a943`.
- Inspector binding: `cluster_labels` → `obs/louvain`.
- Reuse-only plan: zero scientific steps, zero ExecutionRequests.
- Actual plot: eight distinct point colors and eight existing label categories.
- Title: `Reusing existing UMAP; no recomputation`.
- Source file hash, X, PCA/UMAP coordinates, neighbor matrices and obs unchanged.

Only the generated loading and UMAP-inspection cells were exercised. Patches
that raise on calls to UMAP, Leiden, Louvain, PCA and neighbors computation were
active during verification; all five call counts were zero. Plot colors and
legend categories were checked from the actual Matplotlib figure, and the PNG
was visually inspected. No processed data was recomputed or written back.

Local evidence: `.sckg_exec/umap-visualization-fix-20260921/`, including
`workspace-result.json`, `input.json`, `render-receipt.json`, `test-receipt.json`,
the new `processed-umap-reuse.ipynb`, and
`.sckg_notebook_artifacts/processed-umap-reuse/existing_umap.png`.

## Regression checks

13 new cases pass: Louvain, Leiden, arbitrary/escaped column names, inspector
binding priority, stale/unvalidated/missing bindings, multiple panels and the
actual inspector → workspace → notebook handoff. No scientific steps or input
mutation are allowed in these checks.

```bash
/opt/anaconda3/bin/python -m pytest -q \
  tests/test_reused_umap_visualization.py tests/test_research_pca_binding.py \
  tests/test_capability_workspace_service.py tests/test_capability_product_handoff.py \
  tests/test_scanpy_adaptive_notebook.py
```

Result: 45 passed, 1 pre-existing failure. The failing
`test_research_ui_distinguishes_workflow_evidence_and_execution_states` asserts
the literal `EXECUTION NOT REQUESTED` in `app.py`. Both that test and `app.py`
match pre-change HEAD `67eaecc85340e55a876e7b277498abf20ae7ccc9`, whose UI no longer
contains that literal. This unrelated UI wording assertion was not changed.
