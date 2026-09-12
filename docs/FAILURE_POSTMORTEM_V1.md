# scKG-Agent Failure Postmortem v1

**Evidence baseline:** `feature/method-kg-expansion-v1@fb6b503f737645153be223e7665f1df310b85a40`

**Scope:** Architecture, knowledge construction, product integration and development process

**Purpose:** Explain observed rework without blaming it on generic “requirements changed” or treating all iteration as unavoidable

## 1. Incident statement

During the long scKG-Agent 2.0 iteration, the system’s knowledge architecture became more principled while the project temporarily felt less stable and less demonstrable. The contradiction was real but explainable: schema breadth, claim counts, governance artifacts and review machinery increased faster than the small production loop that could consume and validate them.

This produced four misleading signals:

1. A larger candidate KG looked like more product capability even though it was not connected to the production planner.
2. Schema-valid, source-bound records looked decision-ready even when their scope, endpoint identity or proposition support was incomplete.
3. Passing component tests looked like end-to-end safety even though the real Research → Stepwise route had not been replayed.
4. Fixing evaluation failures case by case improved aggregate metrics while introducing regressions in previously passing claims.

The project did not fail because knowledge graphs are inherently impractical. It lost focus because several different definitions of “done” were allowed to overlap.

## 2. Architecture mistakes

### 2.1 The Scientific KG initially sat beside the Agent

`eval/scientific_action_space_demo_v1.py` proved four decisions using a frozen candidate and then called the existing planner only after its own applicability gate. This was a useful evaluation harness, but it was not evidence that production planning consumed KG semantics.

The architecture became complete only at `fb6b503`, when the bounded adapter was inserted into `CapabilityPlanCompiler.compile()/ensure()`. Before that, both the KG and planner could be individually correct while the product ignored the KG.

**Consequence:** extensive knowledge work could not improve the actual plan, and product demonstrations could not show the value of the new model.

### 2.2 Early identity models were too flat for scientific planning

The repository historically used “tool” labels for retrieval and catalogue behavior. The v1.1 specification had to establish separate `SoftwareProject → PackageRelease → OperatorRevision → Method/MethodVariant` identities. Scanpy, PCA, neighbors, UMAP and Leiden cannot be peer tools: Scanpy exports operators that implement methods.

**Consequence:** claims could attach to the wrong identity level, version semantics could drift, and package membership could be mistaken for scientific compatibility.

### 2.3 Derived workflow edges were treated too much like authored truth

The cross-domain inventory exposes many `CAN_FEED` records, including core-candidate edges with empty `derived_from_claim_revision_ids`. The v1.1 contract correctly reclassifies ports and requirements as canonical, with `CAN_FEED` and `REQUIRES_BEFORE` as reviewed derivations.

**Consequence:** a convenient workflow sequence could silently become a mandatory scientific prerequisite.

### 2.4 Route and answer shape remained a separate architectural axis

A correct planner cannot help if Research classifies an explicit planning request as `evidence_qa`. The Product Mainline Replay exposed exactly this boundary. `cee2fc1` added a narrow workflow-intent signal rather than changing the planner or KG.

**Consequence:** the product stopped before state inspection, creating the impression that planner/KG integration had failed when the first causal failure was routing.

## 3. Knowledge-construction mistakes

### 3.1 Common practice was promoted into universal requirements

The Scanpy decision-rule correction had to scope PCA log/HVG assumptions as project profiles rather than universal Scanpy requirements. Similarly, Leiden does not require UMAP; both may consume the neighbor graph independently.

**Failure mode:** observations about a familiar workflow became `REQUIRES_BEFORE` facts.

**Correct rule:** a prerequisite is mandatory only when an operator requirement or scoped scientific claim proves it. Frequency in tutorials is not proof.

### 3.2 Representation type equality was mistaken for compatibility

Earlier `CAN_FEED` construction could infer compatibility from matching output/input types. The corrected UAT slice requires, where relevant, observation and feature identity, lineage, semantic parameter compatibility, representation state and staleness.

**Failure mode:** two artifacts named “embedding” or “neighbor graph” were treated as interchangeable.

**Consequence:** stale, misaligned or semantically incompatible representations could be reused.

### 3.3 `CAN_FEED` was over-generated

The inventory includes 80 `CAN_FEED` relations across frozen layers. Some exploratory/core relations lack complete claim premises. The corrected UAT slice removed type-equality-only automatic derivation and retained only explicit claim-scoped proofs.

**Failure mode:** graph connectivity was optimized before semantic validity.

**Consequence:** the graph looked rich while decision paths became less trustworthy.

### 3.4 Source-bound did not always mean claim-supported

The cross-domain audit found that a source/version link could exist while the cited span did not prove the full scientific proposition. README or publication-index text was sometimes sufficient for discovery but insufficient for high-risk input, output, limitation or compatibility claims.

**Failure mode:** document provenance was used as a substitute for proposition-level evidence.

**Correct rule:** `AtomicClaimRevision ↔ exact EvidenceSpan` must be explicit, content-hashed and scoped.

### 3.5 Candidate knowledge was treated psychologically as decision-ready

The consolidated inventory reports 380 candidate claims and zero promoted/trusted scientific claims. The 14-ecosystem core contains 236 claims, but its readiness matrix still contains risk-review and evidence-gap statuses.

**Failure mode:** record count, schema validity and deterministic generation were allowed to imply trust.

**Consequence:** the project felt close to broad completion when it had actually completed a candidate construction phase.

### 3.6 Breadth hid uneven depth

The 19-ecosystem expansion had only 12 operator revisions across seven ecosystems, six parameter claims, five limitation claims, no ReferenceArtifact and no benchmark-result layer. The cross-domain audit correctly concluded that the data could often say what a package “does” but not whether a concrete operator was applicable now.

**Consequence:** catalogue coverage grew faster than Scientific Action Space coverage.

## 4. Product-integration mistakes

### 4.1 End-to-end replay happened too late

The schema, candidate expansion, semantic audit, corrected subset and Action Space demo all preceded the final product replay. The replay immediately found an ASK/PLAN routing defect that no amount of KG review would have repaired.

**Consequence:** effort continued downstream while the real user path was blocked upstream.

### 4.2 Evaluation-only success was conflated with product success

The four Action Space demo scenarios were correct at `47b12d9`, but the production compiler did not yet consume them. This distinction was closed only by the focused integration commit `fb6b503` and its real planner tests.

**Consequence:** the project had an impressive proof artifact without a corresponding product behavior.

### 4.3 Research ASK/PLAN routing regressed at a semantic boundary

Explicit phrases such as “分析计划”, `plan`, `notebook` and `stepwise` were not recognized by the existing workflow classifier. The request was answered as evidence QA instead of creating a handoff. `tests/test_governed_route_fusion.py::test_explicit_planning_deliverables_route_to_workflow` now fixes the exact answer-shape boundary while preserving ordinary evidence QA.

**Consequence:** both raw and processed product replays initially stopped before RepresentationLedger and falsely implicated later stages.

### 4.4 Grounding optimization became benchmark-driven

The archived branches `wip/multi-claim-grounding-20260903@318c684` and `wip/product-consistency-grounding-20260908@e5f15be` preserve NO-GO experiments. They improved some evidence-selection counts but regressed previously passing cases and widened entity associations in retrieval.

**Consequence:** online answer architecture, corpus association and evaluation behavior changed together, obscuring the first causal owner.

## 5. Process mistakes

### 5.1 Breadth was expanded before a trusted vertical slice was closed

The project moved from Scanpy candidates to 19 ecosystems, then to a 14-ecosystem core, before proving that four corrected knowledge decisions could influence the real planner.

**Consequence:** review workload, risk registers and migration questions expanded without improving the mainline demonstration.

### 5.2 Ontology, curation, governance and integration were mixed

These are different responsibilities:

- ontology defines what can be represented;
- curation asserts scoped propositions;
- governance decides review/promotion status;
- integration makes a runtime decision consume those facts.

When handled in one mental checkpoint, a schema correction could trigger data regeneration, review questions, retrieval changes and product retesting.

**Consequence:** every local correction appeared to reopen the whole project.

### 5.3 Checkpoints multiplied without a single stop condition

Several phases correctly used narrow instructions, but the overall sequence repeatedly moved from diagnosis into another enhancement before freezing the demonstrated value. “One more tool”, “one more evidence relation” and “one more benchmark repair” remained available escape routes.

**Consequence:** accepted milestones did not reliably create psychological or engineering closure.

### 5.4 Promotion completeness was treated as a prerequisite for showing value

The project delayed integrating a small candidate subset because broad review and promotion remained incomplete. The final adapter demonstrates the better boundary: candidate knowledge can drive a clearly labeled, bounded evaluation without pretending to be canonical.

**Consequence:** an achievable demonstration was blocked by an unnecessarily global definition of trust.

### 5.5 Unrelated failures competed with the mainline

During planner integration, the full suite reported nine failures. Reproducing those same failures at clean parent `47b12d9` proved they were not caused by the four-file change. Earlier, similar unrelated artifacts could have invited opportunistic fixes.

**Consequence:** scope expanded and provenance of regressions became unclear.

## 6. Why tests did not prevent all regressions

The project now has a useful regression pyramid, but the layers answer different questions.

| Test layer | What it proves | What it cannot prove | Project example |
| --- | --- | --- | --- |
| Unit/schema test | Model shape, validation, deterministic helper behavior | Scientific meaning or product reachability | v1.1 conformance fixtures validated ports/scope/supersession but could not prove a planner would consume them |
| Semantic decision UAT | A specific scientific decision is correct for a governed fixture | The production planner invokes it | `decision_uat_results.json` passed nine cases while the KG was still candidate-only |
| Production planner integration | The real `CapabilityPlanCompiler` changes schedule/reuse/block behavior | Research can reach that planner or Notebook executes | `tests/test_scientific_kg_planner_integration_v1.py` proves the four locked behaviors |
| Browser/product replay | The user-visible route and handoff reach state inspection and compilation | Kernel execution correctness | Product replay found the missing planning keywords before Stepwise |
| Jupyter execution validation | Generated code runs in the bound kernel and produces outputs | Scientific qualification or controlled execution authority | Raw 17/17 cells, five PNG; processed 2/2; source hashes unchanged |

The Research routing regression passed lower-level planner and KG tests because they started below the broken entry boundary. It was discovered only when the real user wording was replayed from Research Chat.

Earlier Scanpy incidents make the same point:

- `INC-2026-08-24-031`: a small-feature dataset exposed QC `percent_top` defaults that exceeded available genes. Static or large-data tests did not cover that shape boundary.
- `INC-2026-08-24-032`: Streamlit hot reload produced a Pydantic class-identity conflict that ordinary process-fresh tests did not expose.
- `INC-2026-08-24-033`: cells completed but browser-visible diagnostic plots and explicit Scale semantics were wrong. Batch execution alone was not equivalent to interactive product evidence.

Tests did not “fail.” The project had temporarily asked one test layer to stand in for another.

## 7. What actually worked

### 7.1 Trace-based causal localization

Canonical `ROUTING`, `STATE_INSPECTION`, `PLANNING`, `NOTEBOOK_COMPILE` and `RUNTIME_BIND` spans made it possible to locate the first missing stage. Trace was used as correlation evidence without duplicating business records.

### 7.2 EDD and earliest-failure reasoning

`eval/evaluation_evaluators.py` projects canonical traces and attributes the earliest failed stage. This prevented later answer, planner or runtime behavior from being blamed for an upstream route failure.

### 7.3 Frozen baselines and archive branches

Narrow accepted commits and explicit WIP branches preserved both successful and NO-GO states. That made clean-parent reproduction possible and prevented experimental grounding changes from contaminating the formal branch.

### 7.4 Narrow corrections

The successful routing repair touched only Research classification and focused tests. The planner integration touched one model file, the existing compiler, one adapter and one test file. Neither repair expanded the KG or weakened governance.

### 7.5 One production planner

Keeping `CapabilityPlanCompiler` as the sole compiler avoided a second workflow engine. The KG contributes applicability, requirements, reuse decisions and evidence; Capability Pack/StepContract still define executable plan construction.

### 7.6 Scientific knowledge and runtime state remained separate

RepresentationLedger owns the actual neighbor graph, Harmony embedding and expression matrices. The KG owns constraints over such instances. The adapter evaluates the former against the latter without writing user-specific instances into the KG.

## 8. Root-cause summary

> **We optimized breadth and governance before closing a small trusted KG-driven product loop.**

Concrete consequences:

1. Candidate counts were mistaken for usable decision coverage.
2. Review workload expanded faster than product value.
3. Evaluation-only success was mistaken for production integration.
4. A simple Research routing defect blocked sophisticated downstream work.
5. Case-driven grounding changes coupled multiple responsibility layers and created regressions.
6. Schema and source checks passed while semantic compatibility remained unsafe.
7. Unrelated baseline failures repeatedly threatened to distract the mainline.

The recovery was not a broader redesign. It was to freeze the architecture, isolate a corrected candidate subset, prove four scientific decisions, connect that subset to the existing planner, replay the real product path and stop when the locked acceptance criteria passed.
