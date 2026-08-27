# Scanpy Core Capability Pack Development Log

This log is append-only. It records implemented behavior and verification, not planned capability.

## 2026-08-23 - S0 Capability Pack Contract and Registry

- Status: `PASSED`
- Added typed Capability Pack, Representation requirement/production, compatibility and readiness gate schemas.
- Registered `scanpy_core:1.0.0` as a draft planning pack and `mock_r_capability:1.0.0` as a non-Python architecture fixture.
- Added Scanpy 1.11.2 draft ToolContract; `enabled_for_execution=false`, wrapper missing, execution untested.
- Preserved `StepContract` v1 compatibility and required typed transitions for v2.
- Corrected Decision Graph projection so a registered contract cannot create a formal Action unless its planning gate passes.
- Focused/regression: `28 passed`.
- Full regression: `511 passed`, 6 dependency warnings.
- `git diff --check`: passed.
- Limitations: the Scanpy pack has no trusted renderer, adapter qualification, controlled execution, scientific validation, or final Action.

## 2026-08-23 - S1 Canonical Method Graph v0

- Status: `PASSED`
- Added deterministic Capability Pack to Method Graph projection with typed nodes, edges, quality report and manifest hashes.
- PRECEDES edges are derived from Representation production/consumption, not notebook or UI ordering.
- Confirmed UMAP and Leiden independently consume the neighbor graph; neither is the predecessor of the other.
- Kept runtime run/artifact/index hashes outside the canonical graph and made Neo4j an explicit optional one-way adapter.
- Included the Rscript mock binding in the same graph/query schema.
- Focused/regression: `27 passed`.
- Full regression: `516 passed`, 6 dependency warnings.
- `git diff --check`: passed.
- Limitations: Method Graph is a local canonical projection; it is not yet consumed by the data-aware planner or UI.

## 2026-08-23 - S2 Representation State Machine and Generic Planning

- Status: `PASSED`
- Added a coexisting-state `RepresentationLedger` with typed slots, schema/value state, provenance, cell/gene hashes, parent lineage and current/stale status.
- Extended deterministic AnnData profiling across `X`, `raw.X`, layers, `obsm`, `obsp`, `obs` and `var` without mutating the source artifact.
- Added a registry-driven `CapabilityPlanCompiler` with transactional candidate backtracking; no tool or Scanpy method names are used by the planner.
- Added a validated `integrated_representation -> neighbor_graph` binding while unreviewed integration provenance remains blocked.
- Added 14 workflow-state gold cases and explicit marker-source tests; marker planning cannot consume scaled, PCA, integrated, neighbor or UMAP representations.
- Split Method Graph scientific validators from reusable generic validation primitives to remove false projection drift.
- Focused: `46 passed`.
- Related regression: `66 passed`.
- Full regression: `533 passed`, 6 dependency warnings.
- `git diff --check`: passed.
- Limitations: plans remain dry-run and execution-ineligible; fixed renderer, controlled Scanpy adapter and scientific execution validation start in S3.

## 2026-08-24 - S3 Generic Notebook, Execution Adapter and Validation Pipeline

- Status: `PASSED`
- Added a renderer registry and generic `WorkflowPlan + StepContract -> Notebook` compiler; compilation remains editable shadow output with `ExecutionRequest=0`.
- Kept the existing Scrublet Notebook Shadow API intact and added reviewed, step-readable Scanpy templates through a renderer binding.
- Added one control-plane adapter protocol with fixed Python-module and Rscript implementations; both emit argv lists and never accept shell strings.
- Added reusable execution-success, required-artifact and artifact-hash primitives plus a capability scientific validator pipeline using the existing `ValidationResult`.
- Added a fixed Scanpy 1.11.2 wrapper and ran Scale on/off synthetic workflows through `LocalControlledExecutor`; each run produced seven checkpoints, a Representation ledger, QC/PCA/UMAP/marker plots and a final h5ad.
- Marker validation requires `full_gene_unscaled_log1p`; scaled values are isolated to the HVG PCA branch.
- Fixed a pre-existing Decision Graph stale-`action_id` risk by adding the generic `action_space_registration` gate. Scanpy remains `candidate` until S6.
- Scanpy contract status after engineering smoke: wrapper/environment `smoke_passed`, execution `integration_passed`, scientific validation `not_evaluated`, `enabled_for_execution=false`.
- Focused: `26 passed`.
- Related regression: `51 passed`; Decision Graph regression after gate fix: `28 passed`.
- Full regression: `537 passed`, 6 dependency warnings.
- `git diff --check`: passed.
- Limitations: qualification is synthetic engineering evidence only; editable notebooks are not trusted execution sources and the pack is not yet a formal Decision Action.

## 2026-08-24 - S4 Doublet and Batch Integration Composition

- Status: `PASSED`
- Added generic composed-Action bindings so the existing qualified Doublet Detection and Batch Integration ActionBundles can occupy typed positions in a Scanpy Core plan without importing their wrappers or validators.
- Doublet detection consumes filtered raw counts and produces validated score/call annotations; cell exclusion remains a separate human-review method bound to a selection hash.
- A confirmed exclusion derives a new cell-index hash, marks every downstream representation stale and invalidates the old approval before reconstruction.
- Batch integration consumes PCA plus a reviewed batch key and at least two batches, then produces the integrated representation consumed by the existing integrated-neighbor path.
- Verified the no-option, doublet-only, integration-only and combined paths; all plans remain dry-run and `execution_eligible=false`.
- Focused: `34 passed`.
- Related doublet/batch/planner/executor/validator/Pareto/package regression: `70 passed`.
- Full regression: `543 passed`, 6 dependency warnings.
- `git diff --check`: passed.
- Limitations: composition delegates to existing ActionBundles but does not bypass their policy, authorization, approval, environment, qualification or validation gates.

## 2026-08-24 - S5 Dual-path Cell Type Annotation

- Status: `PASSED`
- Recast marker/evidence-based and reference-based annotation as method-family abstractions rather than Scanpy API calls.
- Added atomic marker-evidence candidates with explicit evidence IDs, conflict/unknown handling and deterministic candidate-set hashes.
- Added an explicit human confirmation record; incomplete cluster coverage, empty labels or unconfirmable candidate sets are rejected.
- Registered CellTypist 1.7.1 and SingleR 2.14.0 as concrete reference-method bindings with their own contracts and environments.
- Both reference bindings remain `planning_only`, `execution_eligible=false` and produce zero ExecutionRequests while environment/reference/wrapper/scientific gates remain incomplete.
- Preserved low-overlap, species mismatch, gene-ID mismatch, missing marker and missing evidence blockers.
- Focused: `25 passed`.
- Related Annotation profiler/reference/wrapper/validator/qualification/scientific regression: `41 passed`.
- Full regression: `550 passed`, 6 dependency warnings.
- `git diff --check`: passed.
- Limitations: no reference annotation tool is promoted or executed in S5; marker-based candidates remain hypotheses until explicit human confirmation.

## 2026-08-24 - S6 Unified Product Closure and Acceptance

- Status: `PASSED`
- Added a thin `CapabilityWorkspaceService` for registry-driven `ASK / PLAN / RUN` application handoff. `PLAN` profiles registered AnnData, composes typed methods and writes an editable notebook; `RUN` remains `BLOCKED` with `ExecutionPolicy=disabled` and `ExecutionRequest=0`.
- Added read-only `discover_capabilities` to the existing Research Chat tool registry. The returned capability/readiness/blocker context is included in the audited Agent response and cannot install or execute a tool.
- Made the generic notebook compiler renderer-language aware. The non-Python Rscript mock now performs a real `mock_r_input -> mock_r_table` transition and reaches discovery, planning, an R notebook, shared execution-adapter resolution, validation and evaluation binding without changes to Planner, ResearchChatService or ExecutionOrchestrator control logic.
- Extended the existing `ReproducibilityPackager` with a capability Level 2 package path containing Pack, ToolContract, Environment, Evidence, RepresentationLedger, WorkflowPlan, trace, ValidationResult, plots, limitations and hashes. The source matrix is referenced by artifact ID/hash and is not copied.
- Added three product cases: minimal Scanpy Core plan, Scanpy Core with Doublet Detection and Batch Integration ActionBundles, and Annotation waiting for human confirmation / blocked by unqualified reference binding. Ordinary RUN remains correctly blocked with zero requests.
- Ran `scripts/run_scanpy_core_capability_smoke.py`: fixed Scanpy 1.11.2 executed through `LocalControlledExecutor`, validation passed, 15 artifacts and four diagnostic plots were produced, and package `scanpy-core-s6-20260823T172025Z` passed completeness and hash verification.
- During S6, two defects were found and fixed: enum readiness values were incorrectly treated as enum instances at the application boundary, and the R mock's self-consuming state could not prove planning. The direct script entrypoint also required the repository-root bootstrap used by existing smoke scripts.
- Focused capability/annotation/chat/package regression: `105 passed`.
- Related execution, authorization, UI, Decision Graph and safety regression: `85 passed`, 2 dependency warnings.
- Full regression: `556 passed`, 6 dependency warnings.
- `git diff --check`: passed.
- Limitations: Scanpy qualification is synthetic engineering evidence, not broad biological validation. CellTypist and SingleR remain planning-only. The existing interactive Stepwise Preview surface remains the previously qualified Scrublet path; registry-driven Scanpy produces audited plans/notebooks/packages but ordinary user execution stays disabled.

## 2026-08-24 - Post-S6 Status Reconciliation

- Status: `PASSED`
- Reconciled the current DEV_SPEC and project status with the implemented S0-S6 code path.
- The four independent status axes are now explicit: `implemented=true`, `engineering_smoke_passed=true`, `scientifically_validated=false`, `user_executable=false`.
- Historical S0-S5 entries remain unchanged as append-only stage snapshots; their earlier limitations do not override the current S6 state.
- Global `ExecutionPolicy=disabled` remains unchanged.

## 2026-08-24 - Post-S6 Synthetic User Journey

- Status: `PASSED`
- Added a versioned, deterministic `180 cells x 240 genes` synthetic count fixture with three planted cell groups, group-specific marker programs, two batches, library-size variation, mitochondrial signal and nine low-quality cells.
- Ran Scale disabled and Scale enabled routes through the existing registry-driven planner, generic notebook compiler, `LocalControlledExecutor`, capability validator and `ReproducibilityPackager`.
- Both routes filtered `180 -> 171` cells, preserved 239 genes, passed artifact/hash/lineage validation and recovered marker candidates for all three planted groups.
- PCA consumed `log_hvg` when Scale was disabled and `scaled_hvg` when enabled. UMAP and Leiden independently consumed `neighbor_graph`; marker testing consumed `full_gene_unscaled_log1p`.
- Annotation A produced evidence-bound candidates only. No final `cell_type` label was written before the human-confirmation boundary.
- The source h5ad hash remained unchanged. The Level 2 package references the source artifact by ID/hash and does not copy it.
- Generated eight route-scoped plots: QC diagnostics, PCA variance, UMAP clusters and marker diagnostics for each route.
- Focused journey/runtime/workspace tests: `8 passed`.
- Related executor/package/annotation/composition/qualification regression: `24 passed`.
- Full regression: `560 passed`, 6 dependency warnings.
- `git diff --check`: passed.
- Limitations: this is engineering qualification on structured synthetic data, not biological or broad scientific validation; ordinary user execution remains disabled.

## 2026-08-24 - Post-S6 Intermediate-state Resume

- Status: `PASSED`
- Derived three versioned h5ad states from the same synthetic source hash: log-normalized ready, PCA ready and cluster ready. Each derivative records its own file hash, shape, expected representations and derivation purpose.
- The log-normalized state reused validated `log1p_normalized` and skipped QC, filtering, normalization and log1p.
- The PCA state reused validated PCA and began at neighbors without recomputing PCA.
- The cluster state reused cluster labels and skipped neighbors, UMAP and Leiden while planning only marker ranking and Annotation A candidates.
- A stale PCA record was not reused and was deterministically rebuilt from a valid predecessor. A mismatched PCA cell-index hash was blocked.
- Intermediate fixture derivation is explicitly recorded as NumPy/scikit-learn/UMAP/leidenalg engineering preparation; it is not represented as Scanpy scientific execution.
- Focused: `2 passed`.
- Related profiler/ledger/planner/workspace regression: `43 passed`, 2 dependency warnings.
- Full regression: `562 passed`, 8 dependency warnings.
- `git diff --check`: passed.
- Limitation: resume validation proves state-aware planning and lineage safety on synthetic data; it is not a scientific equivalence claim for arbitrary partially processed h5ad files.

## 2026-08-24 - Post-S6 Product Handoff

- Status: `PASSED`
- Connected registry-discovered Capability Packs to the existing Research Chat handoff and Stepwise Analysis page; no second UI page or execution system was created.
- The handoff carries pack/version, target representations and task context into the existing DataRegistry, AnnData profiler, generic planner, notebook renderer and local Jupyter service.
- A real browser replay registered the versioned Scanpy synthetic h5ad, displayed `180 cells x 240 genes`, resolved `layers/counts`, generated the Representation-aware WorkflowPlan and tutorial notebook, and displayed four diagnostic plot classes, Validation and Level 2 package integrity.
- The page remains PLAN-only with `ExecutionPolicy=disabled` and `ExecutionRequest=0`; opening Jupyter requires an explicit user action and does not convert editable notebook code into trusted execution.
- Fixed a capability-routing regression found by related tests: an unrelated Doublet Detection PLAN can no longer be captured by the Scanpy pack; matching uses governed capability identity/title rather than a first-candidate fallback.
- Fixed the synthetic handoff's selected-artifact binding and hid Streamlit's Deploy control after it overlapped the return action on a small viewport.
- Focused product handoff/workspace/Jupyter tests: `9 passed`.
- Related Research Chat, workspace, Jupyter, UI permission and approval regression: `98 passed`, 2 dependency warnings.
- Full regression: `566 passed`, 8 dependency warnings.
- `git diff --check`: passed before documentation reconciliation.
- Limitations: the primary prose answer can still report the broad task as non-qualified while offering the planning-ready Capability Workspace handoff; this is an answer-state presentation gap, not an execution bypass. Real-data scientific validation and ordinary user execution remain incomplete.

## 2026-08-24 - Post-S6 Final Acceptance

- Status: `PASSED`
- Re-ran the complete user journey after the product-handoff fixes as `post-s6-scanpy-20260824T054951Z`.
- Scale off/on both passed validation, emitted four plots per route, preserved the source h5ad hash and produced marker candidates for all three planted groups.
- Marker provenance remained `full_gene_unscaled_log1p`; PCA provenance was `log_hvg` without Scale and `scaled_hvg` with Scale. No confirmed annotation label was emitted.
- Intermediate resume fixtures remain versioned as `log_normalized_ready`, `pca_ready` and `cluster_ready`; stale PCA rebuild and cell-hash mismatch blocking remain covered by tests.
- Level 2 package `.sckg_exec/packages/post-s6-scanpy-20260824T054951Z/` passed completeness and hash validation.
- Global `ExecutionPolicy=disabled`; `scientific_claim_allowed=false`; this acceptance does not claim real-data scientific validity.
- Final focused acceptance: `10 passed`; related product regression: `98 passed`; fresh full regression: `566 passed`, 8 dependency warnings.

## 2026-08-24 - Scanpy Official PBMC3k Real-data Engineering Pilot

- Status: `PASSED_DATASET_SCOPED_ENGINEERING_PILOT`; scientific validation remains `not_evaluated` because no independent gold labels were used.
- Registered exact public inputs from `.sckg_exec/approved-inputs/pbmc3k-scanpy-official/1.0.0/`: raw `2700 x 32738` (`89a96f...53a1`) and processed `2638 x 1838` (`0db367...fe38`). Original hashes remained unchanged.
- Fixed RepresentationLedger blocking scope exposed by the processed file: missing validated raw counts now blocks only raw-dependent transitions; finite existing log-normalized/PCA/neighbor/cluster/marker/UMAP states remain eligible for resume. NaN, Inf and empty matrices remain global blockers.
- A deterministic 300-cell real-data smoke passed first in `26.69 s` with `575.72 MB` peak memory before full execution.
- Full raw workflow passed through ToolContract, deterministic qualification route, `LocalControlledExecutor` and the composed Validation pipeline in `30.08 s`, with `926.59 MB` peak memory. Output shape was `2643 x 13697` with 9 Leiden clusters.
- Scientific-state checks passed: UMAP and Leiden consumed the neighbor graph; marker testing consumed full-gene unscaled log1p expression; all checkpoint hashes, cell hash, lineage and required artifacts were valid.
- Processed-file planning reused `log1p_normalized`, PCA, neighbor graph, cluster labels, marker result and UMAP, planning only `scanpy_core.marker_evidence_annotation`.
- Annotation A produced one review record per cluster: 8 marker-supported candidates and 1 explicit `unknown/Unresolved` candidate. No `cell_type` final label was emitted; human confirmation remains mandatory.
- Four plots were visually checked: QC distributions, PCA variance, UMAP/Leiden and marker diagnostics.
- Level 2 package `.sckg_exec/packages/scanpy-pbmc3k-20260824T070044Z/` passed completeness and manifest hash validation. It records source hashes and metadata but does not copy the PBMC3k matrices.
- Focused pilot/routing/ledger regression: `24 passed`; final full regression: `570 passed`, 8 dependency warnings; `ExecutionPolicy=disabled` and ordinary user execution remain unchanged.

## 2026-08-24 - Product Integration Incidents 031-033 and Repository Handoff

- Status: `PRODUCT_INTEGRATION_STABILIZED / FULL_REGRESSION_PENDING`
- This entry records only work that was reproduced and verified. It does not promote Scanpy Core to scientific qualification or ordinary user execution.

### INC-2026-08-24-031 - Small-feature QC default overflow

- Real Jupyter execution on the versioned `180 x 240` synthetic fixture failed in `sc.pp.calculate_qc_metrics` because Scanpy's default `percent_top` included 500, which exceeded `adata.n_vars=240`.
- The reviewed QC template now filters requested top-N values against the current feature count and passes `None` when no legal value remains.
- Verification: focused regression=`8 passed`; a clean-kernel run completed all 11 then-current generated code cells with error output=0 and effective `percent_top=[50, 100, 200]`.
- Root cause and prevention are preserved in `ISSUE_RETROSPECTIVE_LOG.md`; no ToolContract, Method Graph or policy gate was relaxed.

### INC-2026-08-24-032 - Streamlit hot-reload model identity conflict

- The real Capability Workspace failed while rebuilding `CapabilityWorkspaceResult.data_profile`: a cached service returned a Pydantic model instance from the pre-reload class identity while the UI validated against the reloaded class.
- The cache boundary now exchanges a JSON-compatible payload and reconstructs the current model. The backend implementation digest was expanded to cover capability models, planner/composer, profilers, notebook compiler and Scanpy renderer.
- Verification: focused UI/workspace regression=`17 passed, 2 warnings`; real browser Research Chat -> synthetic handoff -> Stepwise Analysis -> profile/workflow/notebook completed with validation error=0 and `ExecutionRequest=0`.
- Current handoff digest over 20 backend implementation files=`dae5e44f10d988db84582866bfc9b34f0ba70caf84e223757214bf2020948a97`.

### INC-2026-08-24-033 - Interactive Notebook plots and explicit Scale preference

- Source/runtime/UI triage showed that the old browser Notebook executed without errors but emitted only `text/plain` figure representations; PNG side artifacts existed, while inline `image/png=0`. Earlier `nbconvert` evidence did not prove the interactive browser state.
- The Scanpy renderer now explicitly enables `%matplotlib inline` and uses reviewed Scanpy plotting APIs: `sc.pl.violin`, `sc.pl.highly_variable_genes`, `sc.pl.pca_variance_ratio`, `sc.pl.rank_genes_groups` and `sc.pl.umap`.
- Reproducibility PNG copies are retained under hidden `.sckg_notebook_artifacts/<notebook>`; they are no longer the primary visual interface.
- Research Chat preserves explicit Scale/skip-Scale preference in governed method IDs; Chinese negation such as “不要跳过 Scale” no longer resolves to the skip route.
- Latest real browser Notebook=`.sckg_exec/research-workspace/local-user/capability-notebooks/scanpy_core-9c4b2b7978f6.ipynb`, SHA256=`e8eb5dadbf32598d785b481a9882ff4fd21c96cf0c1bbf912cb0c1428cf7b2a5`.
- Verification: all 17 generated non-empty code cells executed in JupyterLab, error output=0, inline `image/png=5`; Marker and UMAP figures were visually confirmed directly below their code cells. Four additional blank code cells were user-created and are not generated-step failures.
- Latest related Scanpy regression after this browser fix=`35 passed, 4 warnings`; `git diff --check=passed`.

### Handoff state and limits

- Capability Pack gate: `discovered / planning_ready / notebook_ready / validation_ready`, content digest valid, blocker=0, `qualification_claimed=false`, `execution_eligible=false`.
- Scanpy ToolContract: wrapper/environment smoke passed, execution integration passed, scientific validation not evaluated, `enabled_for_execution=false`.
- Runtime binding: fixed Python adapter -> `scRNAseq` -> Python 3.12.2 / Scanpy 1.11.2. The reused kernel is still displayed as `scKG Doublet Python`; renaming is a deferred product task, not a runtime blocker.
- At handoff, Streamlit `127.0.0.1:8501` is healthy and JupyterLab `127.0.0.1:59340` has one connected idle kernel. Access tokens are intentionally not recorded.
- Last fresh full regression remains `570 passed, 8 warnings` from the PBMC3k pilot checkpoint. It predates the final 031-033 browser changes; a new full pytest is required before RC/commit claims.
- Global `ExecutionPolicy=disabled`; ordinary trusted execution, broad biological validation, automatic parameter resolution and LLM-generated arbitrary code execution remain unavailable.

## 2026-08-27 - Scanpy Product Integration Baseline Freeze

- Status: `SCANPY_PRODUCT_INTEGRATION_CLOSURE_VERIFIED`.
- Repository baseline: branch=`phase5a-checkpoint`, HEAD=`d4143a5444983fadcf97cf751933bbf0c96e846f`. The current 20 tracked modifications and 44 untracked status entries match the reviewed closure scope; expanded scope is 37 product-integration files, 26 regression/test files and 4 documentation files, with no non-ignored runtime/generated or unrelated files.

### Implemented

- The existing Research Chat and Stepwise Analysis product path now consumes the generic Capability Pack registry, Method Graph, RepresentationLedger, registry-driven Planner, Capability Workspace, reviewed Scanpy Notebook renderer, fixed runtime adapter, composed Validation and Level 2 Reproducibility Packager.
- Canonical Graph remains stable scientific/domain truth and RepresentationLedger remains current dataset state. Existing runtime execution records, execution history and runtime provenance record actual executions; they are not a completed unified end-to-end Agent Trace system. No Scanpy-specific architecture branch was added to Agent Core, Planner, ResearchChatService or ExecutionOrchestrator.

### Verified

- Gate A closure result: full regression=`572 passed, 8 warnings in 756.11s`. INC-031, INC-032 and INC-033 were not reproduced by that full regression or the PBMC3k browser journeys. The baseline-freeze round did not rerun the full suite; it reran the focused status consistency check and `git diff --check`.
- Gate B raw browser UAT: input `pbmc3k_raw.h5ad` was `2700 x 32738`, SHA256=`89a96f1beaa2dd83a687666d3f19a4513ac27a2a2d12581fcd77afed7ea653a1`, unchanged before/after. Generated Notebook `scanpy_core-d9c99384d66b.ipynb` executed 18/18 code cells with error output=0 and inline PNG=5 on `/opt/anaconda3/envs/scRNAseq/bin/python3.12`.
- The raw plan covered QC, Filter, Normalize, Log1p, HVG, Scale, scaled PCA, Neighbors, Leiden, Wilcoxon Marker, annotation candidates and UMAP. Marker evidence consumed the full-gene unscaled log1p layer; UMAP and Leiden consumed the neighbor graph.
- Controlled pilot `scanpy-pbmc3k-20260824T150133Z` succeeded with output shape `2643 x 13697`, 9 Leiden clusters and 9 annotation candidates. Validation passed; cluster 8 remained unresolved for human confirmation. The Level 2 package was complete, all 15 recorded hashes revalidated, and no `.h5ad` was copied into the package.
- Gate C processed browser UAT: input `pbmc3k.h5ad` was `2638 x 1838`, SHA256=`0db367b991dd95809732b218539ede489bea99113807f62ebd7ccc970025fe38`, unchanged. Existing valid log1p, PCA, neighbor graph, UMAP, cluster and marker representations were reused/skipped; rebuild=none and planning blocker=none. Only `scanpy_core.marker_evidence_annotation` remained in the plan. Notebook `scanpy_core-9f477bc69a9b.ipynb` executed 2/2 code cells with error output=0.
- Notebook execution remains exploratory/untrusted and separate from the controlled Validation/package evidence path. The only execution blocker for the processed handoff remains `capability_pack_execution_not_eligible`.

### Non-blocking known issues

- Research Chat answer prose and the planning-ready capability handoff can still present the qualification boundary unevenly.
- The reused kernel's display name remains `scKG Doublet Python`, although its argv correctly resolves to the `scRNAseq` Python runtime.
- Existing Scanpy/Matplotlib FutureWarnings remain; they were not changed during baseline freeze.

### Deferred / roadmap

- Independent biological/scientific qualification and ordinary trusted user execution remain incomplete.
- Adaptive Parameter Resolver, Adaptive Scientific Notebook, unified end-to-end Agent Trace v0, formal Scoped Authorization v0, KG/Evidence maintenance, Graph Delta, Method Path Search, Runtime Registry redesign, MCP, Sandbox and additional tool onboarding were not started in this closure. Existing Policy, ApprovalService and scoped approval binding remain implemented; the deferred authorization work is the unified Principal / Operation / Resource / Scope model, not a claim that OAuth, RBAC or enterprise IAM already exists.
- Global `ExecutionPolicy=disabled`; ToolContract, Approval, Validation, Evidence and qualification gates were not lowered. No code, generated Notebook, runtime output or execution policy was modified by this baseline-freeze documentation update.
