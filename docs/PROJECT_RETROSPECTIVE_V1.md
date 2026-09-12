# scKG-Agent Project Retrospective v1

**Evidence baseline:** `feature/method-kg-expansion-v1@fb6b503f737645153be223e7665f1df310b85a40`

**Date:** 2026-09-12

**Status:** Repository-grounded retrospective; documentation only

**Release posture:** `NOT_READY_FOR_RC / ARCHITECTURE_RELEASE_GATE_BLOCKED`

**Execution posture:** `ExecutionPolicy=disabled`

This document describes what scKG-Agent has actually become, what has been demonstrated, and where the evidence boundary still lies. It is not a release announcement and does not promote candidate scientific knowledge.

## 1. Project goal

scKG-Agent is intended to be a local-first scientific agent that constructs a governed, dataset-specific action space instead of merely generating plausible analysis prose or arbitrary code.

```text
Scientific intent
+ current data state
+ scientific knowledge
+ executable contracts
→ Scientific Action Space
→ Planning
→ Notebook
→ Execution
→ Trace
```

The product question is therefore not only “which method sounds relevant?” It is:

1. What does the user intend to learn or do?
2. What representations already exist in the selected dataset, and are they valid for reuse?
3. What scientific requirements, limitations and compatibility rules apply?
4. Which reviewed implementation can realize an applicable action?
5. Which prerequisites must be scheduled, reused, skipped or blocked?
6. Can the resulting plan be rendered and executed without changing the source data?
7. Can the complete decision and execution trajectory be reconstructed afterward?

## 2. Current architecture

The current system keeps scientific truth, dataset state, implementation contracts, execution authority and observed history separate.

| Component | Actual responsibility | Must not own |
| --- | --- | --- |
| Research routing | Classifies each request, preserves clarification, selects ASK/PLAN/RUN answer shape, and creates the Research handoff | Dataset-state inference, scientific execution, or a second plan compiler |
| RepresentationLedger | Records current dataset-specific representation instances, hashes, lineage, validation and stale/current state | Universal scientific requirements or canonical method knowledge |
| Scientific KG | Represents versioned packages/operators/methods, ports, constraints, scoped atomic claims and exact evidence provenance | User data, runtime instances, permission to execute, or execution history |
| Scientific KG applicability | Binds selected candidate knowledge constraints to current ledger instances and returns applicable/blocked, reusable representations, missing requirements, reasons and evidence references | Global ranking, workflow compilation, execution, or silent canonical promotion |
| Capability Pack / StepContract | Defines reviewed implementation steps, representation contracts, parameters, renderer bindings and validation expectations | Universal scientific truth or request-specific current state |
| `CapabilityPlanCompiler` | Remains the single production planner; performs reuse, producer selection, dependency compilation and plan construction | A parallel KG planner or authorization bypass |
| Notebook generation | Renders the compiled plan using reviewed maintainer templates and records cell-source digests | Arbitrary LLM code generation or trusted execution |
| Jupyter/runtime | Binds the reviewed Notebook to an installed runtime pack after explicit user action | Scientific eligibility, plan authority, or automatic execution permission |
| Trace | Correlates real Research, Stepwise, Jupyter and controlled-execution stages with bounded IDs and references | Duplicating approval, validation, package, runtime or scientific records |

The normative knowledge boundary is defined by `docs/SCIENTIFIC_AGENT_KG_SPEC_V1_1.md`. In particular:

- `Package`, `OperatorRevision`, `Method` and `MethodVariant` are distinct identities.
- `InputPort`/`OutputPort` plus requirements are canonical operation semantics.
- `CONSUMES`, `PRODUCES`, `CAN_FEED` and `REQUIRES_BEFORE` are projections or reviewed derivations.
- `RepresentationType` and `RepresentationConstraint` belong to knowledge; a runtime `RepresentationInstance` belongs to RepresentationLedger.
- source identity is not enough: every decision-bearing scientific proposition requires an exact claim-to-evidence binding.
- canonical facts are versioned JSONL/manifest records; query graphs and indexes are rebuildable projections. Neo4j is not required.

## 3. Milestone timeline

This is an architectural timeline, not a complete commit log.

| Milestone | Repository evidence | What changed |
| --- | --- | --- |
| State-aware Scanpy product path | `40a18a8` | Froze the generic Capability Pack, RepresentationLedger, planner, reviewed Notebook renderer, validation and reproducibility path after raw/processed PBMC3k UAT. |
| Canonical Trace core | `8a85f31` | Added strict canonical Trace v0 records, privacy/schema validation, safe instrumentation and legacy compatibility. |
| Research, Stepwise, Jupyter and controlled trajectory | `9416f42`, `b5304f8`, `3d8f4b0` | Established one Research root, real semantic spans, parent/child request topology and controlled execution stage references. |
| Trace-driven EDD and fixed ablation | `4ecb7af`, `4fb5545` | Connected canonical trajectories to expected-stage/order checks, earliest failure attribution and release-gate evaluation. |
| Governed Notebook parameter resolution and authorization | `373e51a`, `933221b` | Added the bounded Scanpy parameter slice and formal scoped authorization without enabling ordinary execution. |
| Atomic answer grounding experiments | accepted `46cfa3a`; NO-GO work preserved on `318c684` and `e5f15be` | Proved claim/evidence locality concepts and also demonstrated that benchmark-oriented patching can regress previously passing cases. |
| Scientific KG v1.1 architecture | `b9bfc23` | Replaced flat “tool” thinking with package/operator/method identities, structured scopes, ports, representation constraints, evidence, risk and lifecycle rules. |
| Schema conformance and legacy crosswalk | `e4f7a3e` | Materialized candidate schemas and fixtures without changing canonical knowledge or retrieval. |
| Candidate knowledge construction | `90ebedd`, `ecd9e0f`, `22489bd` | Built Scanpy, broad expansion and 14-ecosystem core candidate layers. The core contains 236 atomic claims and 171 derived relations, but remains unpromoted. |
| Cross-domain semantic audit | `22489bd` includes `docs/SCIENTIFIC_KG_V1_CROSS_DOMAIN_AUDIT.md` | Found that breadth and schema conformance did not imply planning depth, endpoint resolution, scope correctness or semantic safety. |
| Corrected decision subset | `25d0cff` | Created a separate candidate-only Scanpy/Harmony/Scrublet/SingleR correction slice with explicit decision UATs; canonical KG and indexes remained unchanged. |
| Scientific Action Space Demo v1 | `47b12d9` | Demonstrated four applicability decisions against ledger states, still outside production planning. |
| Product Mainline Baseline Replay | runtime evidence on 2026-09-12 | Replayed processed/raw Research → Stepwise → Notebook and exposed an ASK/PLAN routing defect before planner assessment. |
| Research ASK/PLAN routing repair | `cee2fc1` | Added bounded deterministic workflow signals for “分析计划”, `plan`, `notebook` and `stepwise`; ordinary evidence questions remain ASK. |
| Scientific KG → Existing Planner Integration v1 | `fb6b503` | Inserted the smallest candidate applicability adapter at `CapabilityPlanCompiler.compile()/ensure()`, preserving the existing compiler as the sole planner. |

## 4. Knowledge assets and their status

The repository now contains multiple deliberately separated layers:

- `scientific_knowledge_schema_v1_1`: schema/conformance candidates; manifest says `candidate_only_not_promoted`.
- `scientific_kg_content_expansion_v1`: 19-ecosystem exploratory expansion with 92 atomic claims and 72 evidence gaps; useful for coverage analysis, not a production truth set.
- `scientific_kg_v1_core`: 14 ecosystems, 236 atomic claims, 44 operator revisions, 61 representation constraints, 171 derived relations and 5 explicit evidence gaps; still pending risk review.
- `scientific_kg_v1_uat_decision_rules`: corrected candidate overlay for selected Scanpy Core, Harmony, Scrublet and SingleR decisions; it records unchanged canonical/index/runtime hashes.
- `scientific_kg_v1_inventory`: consolidated view over 22 ecosystems and frozen layers. It counts 380 candidate claims, 256 candidate derived relations and 77 evidence gaps, while explicitly reporting **zero promoted or trusted scientific claims**.

The current production adapter does not consume all of these layers. It verifies the frozen UAT candidate manifest and digests, then exposes only four validated planner behaviors with `knowledge_status="candidate"`.

## 5. Current validated state

### 5.1 Product mainline

The current end-to-end product loop has been demonstrated as:

```text
Research request
→ routed PLAN
→ Research handoff
→ Stepwise data inspection
→ RepresentationLedger
→ CapabilityPlanCompiler
→ reviewed Notebook compilation
→ Jupyter runtime binding
→ real kernel execution
```

Processed PBMC3k:

- input shape `2638 × 1838`;
- source SHA-256 `0db367b991dd95809732b218539ede489bea99113807f62ebd7ccc970025fe38`, unchanged after execution;
- existing log1p, PCA, neighbor graph, UMAP, cluster and marker states were reused;
- only `scanpy_core.marker_evidence_annotation` was scheduled;
- plan `cap-plan-39567af880c3cd1f`;
- Notebook `scanpy_core-bd6bee853bbd.ipynb`, 2/2 code cells executed, error output 0;
- Stepwise trace `trace_a88722e6a6704889ac7c28b41af4afb1` linked to Jupyter trace `trace_3894a7aec30a4feaa219b9471afa394f`.

Raw PBMC3k:

- input shape `2700 × 32738`;
- source SHA-256 `89a96f1beaa2dd83a687666d3f19a4513ac27a2a2d12581fcd77afed7ea653a1`, unchanged after execution;
- current state exposed raw counts and registered AnnData;
- the existing 11-step DAG remained intact: QC, filtering, normalization, log1p, HVG, PCA, neighbors, Leiden, markers, annotation candidates and UMAP;
- plan `cap-plan-060f3fdd8e1664bf`;
- Notebook `scanpy_core-34f2575e0082.ipynb`, 17/17 code cells executed, error output 0, five inline PNG figures;
- Stepwise trace `trace_6c675c0e4c59475086b4e04543832815` linked to Jupyter trace `trace_e761dc608afa4dbf91fe79e2c1b70daf`.

These executions validate engineering behavior. They do not turn an editable Notebook into a trusted controlled execution, and they do not establish broad biological qualification.

### 5.2 Production KG applicability

`tests/test_scientific_kg_planner_integration_v1.py` proves through the real `CapabilityPlanCompiler` that:

1. A current, observation-aligned neighbor graph is reused directly for Leiden; PCA and neighbors are not rescheduled.
2. A stale or observation-misaligned graph is rejected with structured incompatibility reasons.
3. A valid Harmony embedding can feed neighbor construction without forcing PCA.
4. Scrublet is blocked when only normalized/integrated expression is available, and preserved raw UMI counts are reported as missing.

The checkpoint passed its five focused integration tests. The larger planner/workspace/ledger/Notebook compatibility selection passed 50 tests. The contemporaneous full suite reported 836 passed and nine failures; the same nine failures reproduced on clean parent `47b12d9`, so they were recorded as unrelated baseline failures rather than repaired inside the integration checkpoint.

### 5.3 Trace and governance

- Canonical Trace records the real Research, Stepwise, Jupyter and controlled-execution boundaries.
- `tests/test_trace_context.py` covers one root, monotonic spans, immutable finalized snapshots, atomic collection and failure isolation.
- `tests/test_trace_v0_privacy.py` verifies forbidden payloads never reach persisted canonical JSONL.
- `tests/test_stepwise_trace_integration.py` verifies Research → Stepwise → Jupyter parent/child linkage and that trace failures do not change business outcomes.
- EDD can project canonical trace spans, validate required/forbidden/order expectations and attribute the earliest failed stage (`eval/evaluation_evaluators.py`).
- Policy remains disabled for ordinary controlled execution. Notebook execution is exploratory and user-triggered.

## 6. What is not yet proven

- The 380 inventory claims are not 380 trusted facts. The inventory reports zero promoted/trusted scientific claims.
- The 14-ecosystem core candidate is not uniformly reviewed, execution-bound or production-ready.
- All 22 inventoried ecosystems are not available as production planning actions.
- The corrected UAT layer is still candidate knowledge. Integration is a bounded validation bridge, not canonical promotion.
- Only four KG applicability behaviors are production-integrated. SingleR, broader Scanpy semantics and other ecosystems remain outside this checkpoint.
- Citation/grounding release gates documented at `fca9749` remain blocked; later KG/planner work did not rerun or waive them.
- Broad scientific qualification, cross-dataset external validation and real-user evaluation remain incomplete.
- Editable Jupyter execution does not replace ToolContract eligibility, Approval, controlled Validation or reproducibility packaging.
- The nine baseline test failures observed during the integration checkpoint remain unresolved and must be handled only by their own owner.

## 7. Component status matrix

| Component | Implemented | Validated | Candidate | Next-stage |
| --- | --- | --- | --- | --- |
| Research routing | Per-message route fusion and explicit PLAN signals | Focused route tests plus raw/processed handoff replay | Broader language coverage | Extend only from first-cause route failures |
| RepresentationLedger | Typed current-state and lineage records | Processed reuse, stale/mismatch tests, raw/processed profiling | Richer representation metadata | Add metadata only when a decision requires it |
| Scientific KG v1.1 schema | Versioned identity, scope, ports, constraints, claims, evidence and lifecycle model | Conformance fixtures | Schema artifacts remain candidate | Freeze unless a demonstrated contradiction exists |
| Broad KG content | 22-ecosystem inventory; 14-ecosystem core | Structural and semantic reports | 380 candidate claims; 0 promoted | Risk review and narrow promotion, not more breadth |
| Corrected decision slice | Scanpy/Harmony/Scrublet/SingleR candidate rules | Nine decision UATs pass | Most claims/relations await review | Review only when preparing promotion |
| KG applicability adapter | Structured decision interface | Four real planner scenarios | Uses candidate UAT knowledge | Keep bounded; add behavior only with its own UAT |
| `CapabilityPlanCompiler` | Single state-aware production planner | Four KG cases and PBMC3k regressions | Other knowledge falls back to existing behavior | No second planner |
| Capability Pack / StepContract | Reviewed Scanpy implementation and Notebook contracts | Raw/processed Notebook compilation | Other ecosystems vary | Qualify per implementation |
| Notebook/Jupyter | Reviewed renderer and runtime binding | Processed 2/2; raw 17/17, 5 PNG, error 0 | Editable output remains untrusted | Controlled execution remains separate |
| Trace v0 | Canonical request/span/link model | Research/Stepwise/Jupyter/controlled tests and real replay | Cross-system export deferred | Reuse existing records; do not duplicate |
| EDD | ExpectedTrajectory, failure attribution and ReleaseGate | Deterministic/fixed evaluation paths | Some external/live metrics not run | Close existing gates without changing gold |
| Authorization/execution | Scoped authorization controls exist | Replay/scope/resource tests | Ordinary execution disabled | Do not lower gates for demonstrations |

## 8. Current conclusion

The project has crossed an important boundary: a small, source-bound Scientific KG decision layer now changes the behavior of the real production planner without replacing it, and the existing raw/processed product mainline still executes successfully. That is a valid first Scientific KG–driven agent loop.

The correct description is therefore:

> scKG-Agent has a validated, bounded Scientific KG → RepresentationLedger → existing planner integration for four high-value decisions, embedded in a working Research → Notebook → Jupyter product path.

It is not correct to claim that the broader candidate KG is trusted, that all ecosystems are production-ready, or that the project is ready for release.
