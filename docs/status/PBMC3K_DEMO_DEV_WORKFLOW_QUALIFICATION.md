# PBMC3k DEMO/DEV workflow qualification

Qualification date: 2026-09-20–21 (Asia/Shanghai).
Runtime under test: `5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee`.
Branch: `feature/candidate-kg-demo-v1`; worktree was clean before qualification.

**Result: upload, binding, deterministic inspection and PLAN qualified; governed
RUN is blocked. ASK → PLAN → RUN → state update is not a completed loop.**

This is a DEMO/DEV qualification, not Agent Gain or Gold evaluation. This change
records findings only. No runtime implementation, execution policy, ToolContract,
KG content, frozen ontology, Planner safety contract, viewer or 08 evaluation was
modified. No execution allowance or PBMC3k approval was issued. No biological
analysis process or notebook cell was executed.

## Data identity and browser upload

The requested `/Users/lris/scKG_data/pbmc3k/pbmc3k_raw.h5ad` did not exist.
The prepared input was found at `../demo-data/pbmc3k/pbmc3k_raw.h5ad`, relative to
this repository. Before using it, a read-only comparison against the existing
Downloads raw file verified identical dimensions, cell order, gene order and
every count value. Both have unique cell and gene identifiers. The H5AD encodings
and file hashes differ; this was not a switch to a processed dataset.

The prepared file was selected through the browser's **＋ → Browse files** file
chooser at `http://127.0.0.1:8501/`. No hardcoded-path substitute was used for this
upload test. Its original bytes were unchanged.

- File size: 21,594,848 bytes.
- SHA256: `ed002d29d5d01f513b4426e0937d42814c8e8a0771827b8676bb62a4cc35e5a1`.
- Browser-created artifact: `data-ed002d29d5d0-c7c25bb2`.
- Binding source: `user_upload`; owner: `local-user`.
- UI displayed `pbmc3k_raw.h5ad · 2,700 cells × 32,738 genes`.

## Deterministic state and zero-execution plan

The browser handoff used `CapabilityWorkspaceService`, `AnnDataProfiler` and
`AnnDataRepresentationProfiler`. These existing DataProfile and
RepresentationLedger objects provide the measured dataset state for the planner;
the chat model did not invent a measured DatasetState.

| Inspected field | Actual result |
| --- | --- |
| n_obs / n_vars | 2700 / 32738 |
| X | float32 CSC sparse matrix |
| raw / layers | absent / empty |
| obs keys / var keys | empty / `gene_ids` |
| Count source | X |
| Count-like inference | raw_counts, high confidence; deterministic evenly spaced sample of 100,000 stored values, integer fraction 1.0, negative/NaN/Inf fractions 0 |
| Embeddings / neighbor matrices | obsm and obsp empty; no PCA or neighbors |
| Clustering | neither Leiden nor Louvain detected |
| Reusable representations | `registered_anndata`, `raw_counts` only |

Count-like is an inspector inference with recorded sampling evidence, not proof
of biological provenance or a conclusion inferred from the filename. Batch
metadata was not provided; the inspector preserved that warning.

The UI generated plan `cap-plan-8237add7f569d820`:

| Step | Why this raw state needs it for the requested outputs | Preview parameters |
| --- | --- | --- |
| calculate_qc | QC metrics are absent | none |
| filter_counts | Produce filtered counts after QC | min_genes=1, min_cells=1 |
| normalize_total | Library-size-normalized representation is absent | target_sum=10000 |
| log1p | The selected HVG/PCA path consumes log-normalized expression | none |
| highly_variable_genes | No HVG selection exists | n_top_genes=2000 |
| pca_log_hvg | No PCA exists; consumes log expression and HVG selection | n_comps=50 |
| neighbors | No graph exists; consumes PCA | n_neighbors=15 |
| leiden | No cluster labels exist; consumes graph | resolution=1.0, random_state=0 |
| umap | No UMAP exists; consumes graph | random_state=0 |

The UI displays existing representations and the consumes/produces dependency
table. The table above explains that dependency chain in prose. These are plan
preview values from existing defaults/rules, not approved PBMC3k QC thresholds or
claims of optimal parameters. No experimental configuration was executed.

The generated UI notebook is
`.sckg_exec/research-workspace/local-user/capability-notebooks/scanpy_core-43af3d63248b.ipynb`,
SHA256 `f9cba1ec0d827883e5b88e7928f44be6c2441f1661a1f9d0b70b9225d5a5959d`.
All code cells have null execution counts and empty outputs. A notebook export is
not a derived biological artifact. The page explicitly shows PLAN, DISABLED and
ExecutionRequest=0.

## RUN blockers and approval boundary

A live chat request limited execution to QC, normalization, HVG and PCA, and
explicitly excluded neighbors, Leiden and UMAP. The UI returned WAITING with
`domain_or_task_clarification_required`: the additional stage constraints were
not bound to executable plan parameters. It did not execute anything.

An additional read-only service qualification requested target `pca` in RUN mode.
The resulting six-step plan contained QC, filtering, normalize_total, log1p, HVG
and PCA only. The service returned `blocked`, `execution_policy_disabled`, zero
ExecutionRequests. No executor was called.

Independent deterministic gates confirmed:

1. `CapabilityWorkspaceResult.execution_policy` is fixed to `disabled`; its
   execution request count is fixed to zero. The capability workspace currently
   supports planning/notebook generation rather than governed Scanpy execution.
2. `contracts/tools/scanpy/1.11.2.json` has `enabled_for_execution=false`.
   `ToolContractRegistry.execution_gate` returns `contract_execution_disabled`.
3. Even the existing allowlisted-local-user policy rejects Scanpy with
   `tool_environment_pair_not_allowlisted` and `contract_execution_disabled`.
4. The fixed Scanpy wrapper runs the full workflow. The contract does not offer a
   reviewed partial-stage operation or stop-after-PCA parameter;
   `validate_parameters({"stop_after": "pca"})` raises
   `unknown parameters: stop_after`.
5. A router call with a valid data-access validation and no execution approval
   returns `WAITING_EXECUTION_APPROVAL`, `execution_allowed=false`.

Approval boundary PASS therefore means negative controls held. It does not mean
a real PBMC3k execution approval was issued or consumed. The existing maintainer
scientific-pilot route and manually executable Jupyter notebook were not used as
substitutes for the requested approval/ToolContract/guard chain.

## Follow-up and stale binding

The literal live follow-up **“接下来呢？”** returned a PLAN handoff for the
still-unexecuted QC-through-PCA targets, explicitly stating that execution had not
occurred. This is not the requested post-PCA adaptive replan: no completed stage
or new biological artifact existed to reuse. Derived-state update and post-run
adaptive replanning remain unqualified, not falsely marked successful.

For a live upstream-binding change, the other raw encoding was uploaded through
the same browser chooser. Its SHA256 is
`89a96f1beaa2dd83a687666d3f19a4513ac27a2a2d12581fcd77afed7ea653a1`, and its new
artifact ID is `data-89a96f1beaa2-59f0e3a7`. The count data and identities match the
first file; the file/artifact binding identity changed.

Both old handoffs then displayed “这条历史任务绑定的是另一份输入。请为当前数据重新发送计划请求，不能沿用旧交接。”
Browser `isEnabled()` results were `[false, false, true]`: the old two handoffs
were disabled and only the new binding's handoff remained enabled. Existing unit
tests also verified stale propagation to PCA, rejection of stale PCA reuse and
hash/context invalidation. A real run-produced PCA/downstream artifact was not
available for the full stale-artifact test, so its overall status is PARTIAL.
The browser was left showing this stale-binding evidence, with the second raw
encoding as its current test binding. Neither source file was changed.

## Validation and evidence

85 existing unit/regression tests passed in 9.22 seconds; two expected warnings
come from the duplicate-name profiler fixture. The suite covers deterministic
inspection, representation reuse/staleness, upload identity, conversation-bound
state, zero-execution plans and approval scope/consumption. These small synthetic
unit fixtures do not create a Gold set or run a formal evaluation.

```bash
/opt/anaconda3/bin/python -m pytest -q \
  tests/test_data_profiler.py tests/test_representation_ledger.py \
  tests/test_research_input_binding.py tests/test_research_pca_binding.py \
  tests/test_capability_workspace_service.py tests/test_scanpy_adaptive_notebook.py \
  tests/test_execution_approval.py tests/test_approval_consumption.py
```

Five application traces recorded the four chat requests and one Stepwise plan;
none contains an EXECUTION span. A separate service replay recorded the full
PLAN and blocked partial RUN. No new run or approval files were produced. The
approved-v2 adapter reloaded the pinned package, verified its hash and 121-entry
allowlist, and remained unchanged.

Local receipts are in `.sckg_exec/pbmc3k-demo-dev-20260920/`:

- `qualification-result.json`, `input-identity.json`, `browser-upload-record.json`.
- `deterministic-profile.json`, `representation-ledger.json`, `full-plan-replay.json`.
- `partial-run-block.json`, `execution-gates.json`, `ui-notebook-receipt.json`.
- `runtime-trace-receipt.json`, `qualification-traces.jsonl`, `smoke-tests.json`.
- `approved-kg-receipt.json`, `ui-plan.txt`, `ui-run.txt`, `ui-follow-up.txt`,
  `ui-stale-binding.txt`, `ui-stale-button-status.json`.

The browser download button was exercised, but no usable download-event receipt
was obtained; download transport is not claimed qualified. The saved UI state,
actual generated notebook and separately labelled service replay provide the
inspection/plan evidence without claiming a downloaded UI audit payload.

The three most useful defense screenshots are:

1. `screenshots/01-upload-bind.png`: real browser-selected H5AD and bound shape.
2. `screenshots/02-inspected-state-and-plan.png`: measured raw state, dependencies,
   the full plan and the explicit no-execution boundary.
3. `screenshots/05-stale-binding-block.png`: changed binding disables old handoffs.

They demonstrate the qualified front half and safety boundary, not a successful
RUN. `screenshots/04-run-waiting.png` additionally records the live RUN waiting
state. Completing the Demo requires a reviewed bounded Scanpy execution contract
and wrapper, integration through existing plan-specific approval/guards, then
real derived-artifact registration, reinspection and post-run replan testing.
Simply toggling the global policy or running the exported notebook is not a fix.

```makefile
PBMC3K_UPLOAD_PASS=true
DATASET_BIND_PASS=true
DETERMINISTIC_INSPECTION_PASS=true
RAW_STATE_IDENTIFIED=true
PLAN_ONLY_ZERO_EXECUTION=true
APPROVAL_BOUNDARY_PASS=true
GOVERNED_RUN_PASS=false
DERIVED_ARTIFACT_CREATED=false
STATE_UPDATE_PASS=NOT_RUN_BLOCKED
ADAPTIVE_REPLAN_PASS=NOT_RUN_BLOCKED
STALE_STATE_BLOCK_PASS=PARTIAL
SCREENSHOT_READY=true
TESTS=85_passed_plus_live_browser_and_read_only_gate_qualification
RUNTIME_COMMIT=5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee
```
