# Scientific KG Development Playbook v1

**Applies from:** `feature/method-kg-expansion-v1@fb6b503f737645153be223e7665f1df310b85a40`

**Purpose:** Operational rules for constructing, extending, validating and integrating the scKG-Agent Scientific KG without reopening settled architecture or losing the product mainline

**Default governance:** `ExecutionPolicy=disabled`; candidate scientific knowledge is not canonical promotion

**Scope boundary:** This playbook governs Scientific KG construction, expansion, semantic validation and bounded integration. It supplements—and does not replace—the project-wide requirements and architecture contract in `docs/DEV_SPEC_2.0.md`.

## 1. How to use this playbook

Every nontrivial task must begin with a checkpoint contract containing:

```text
Goal
Primary owner
Allowed files/layers
Forbidden scope
Evidence baseline
Focused acceptance
Mainline acceptance
Stop condition
Commit boundary
```

If the first reproducible failure belongs to another owner, stop and report that owner. Do not repair it opportunistically.

## A. Mainline-first rule

Every substantial product change must preserve:

```text
Research
→ Stepwise
→ RepresentationLedger
→ CapabilityPlanCompiler
→ Notebook
→ Jupyter
→ Trace
```

Before implementation, identify which arrow can change. After focused tests, replay from the highest affected upstream boundary. A change below the planner is not complete merely because the compiler test passes; a routing change must be exercised from Research.

Minimum mainline evidence:

- one explicit request and route;
- handoff and parent IDs;
- DataProfile and ledger state;
- actual plan and reuse/skip/block reasons;
- Notebook compile status;
- Jupyter execution only when execution-facing behavior changed;
- canonical Trace stages and links;
- source input digest before/after when real data is used.

## B. One checkpoint, one responsibility layer

A checkpoint has one primary owner:

- routing;
- KG semantics/content;
- RepresentationLedger/profile adapter;
- planner;
- Notebook renderer/composer;
- runtime/execution;
- evaluator/gold.

Adjacent files may change only to expose a typed interface or add tests. If the proposed fix changes two decision owners—for example retrieval ranking and grounding—split it.

Required audit question:

> If this checkpoint fails, can one class/function or one data layer be named as the first causal owner?

If not, the scope is too broad.

## C. Applicability before ranking

Never rank scientifically incompatible actions.

The order is:

```text
resolve intent and state
→ evaluate mandatory applicability
→ block/clarify/profile missing requirements
→ construct eligible action set
→ rank eligible alternatives
→ compile the chosen action
```

Ranking score must never compensate for failed mandatory representation, reference, scope or safety requirements.

## D. Unknown is not incompatible

Use three-valued reasoning where the scientific contract permits it:

- `compatible`: evidence and runtime state satisfy the requirement;
- `incompatible`: a governed contradiction or failed mandatory condition exists;
- `unknown`: required facts are absent or insufficient.

Unknown mandatory requirements trigger clarification, profiling or a bounded blocker. They must not become arbitrary rejection, a large ranking penalty or silent acceptance.

Example: a coarse `claim_type` mismatch is insufficient metadata unless an authoritative contradiction exists.

## E. KG knowledge is not runtime state

The Scientific KG may define:

- `RepresentationType`;
- `RepresentationConstraint`;
- ports and requirements;
- scoped method/operator facts;
- limitations and evidence.

RepresentationLedger exclusively owns:

- runtime `RepresentationInstance` records;
- cell/feature hashes;
- artifact slots/locators;
- realized lineage and parameters;
- current/stale/validated state.

Never place user-specific paths, matrices, notebook outputs or instance state into the KG. Never make the ledger the authority for universal scientific requirements.

## F. Candidate is not trusted

Every scientific record carries an explicit status. At minimum distinguish:

- extracted/candidate;
- candidate pending review;
- accepted/promoted;
- superseded/deprecated;
- evidence gap.

Candidate knowledge may drive a bounded test or explicitly labeled product experiment only when:

1. the candidate artifact and manifest are digest-verified;
2. the allowed action/decision scope is enumerated;
3. the result exposes `knowledge_status="candidate"`;
4. fallback outside that scope preserves existing production behavior;
5. integration is not described as canonical promotion.

## G. Scientific prerequisite rules

Never infer `REQUIRES_BEFORE` from:

- tutorial order;
- workflow frequency;
- package dependency;
- matching representation type names;
- the fact that one output often feeds another operator.

A genuine prerequisite requires a scoped mandatory requirement with exact provenance. Otherwise use:

- port compatibility;
- reviewed/derived `CAN_FEED`;
- optional upstream reuse;
- project workflow profile;
- or `EvidenceGap`.

Leiden consuming a valid neighbor graph does not imply UMAP must run first.

## H. Compatibility rules

Representation reuse must consider the dimensions relevant to that representation:

- observation identity/order;
- feature identity/order;
- lineage and producing operation;
- semantic parameter compatibility;
- freshness/staleness;
- modality and biological scope;
- value/transformation state;
- component roles and required metadata.

Do not require irrelevant dimensions. A neighbor graph may not require feature alignment in the same way an expression matrix does. Compatibility logic must be representation-specific, not one universal hash-equality test.

Every rejection returns bounded reason codes and the rejected record IDs. Every reuse returns the exact representation record IDs.

## I. Production planner ownership

`CapabilityPlanCompiler` is the single production planner unless a separately approved architecture decision replaces it.

The Scientific KG supplies:

- applicability;
- constraints;
- reusable representation references;
- missing requirements;
- incompatibility reasons;
- evidence/provenance references.

Capability Pack/StepContract and `CapabilityPlanCompiler` continue to own:

- implementation selection;
- recursive producer scheduling;
- dependency graph compilation;
- parameter resolution;
- workflow plan construction.

Do not build a second “Scientific KG planner” in eval, UI, Research or retrieval code. Eval harnesses may demonstrate an interface but cannot become production authority by implication.

## J. Evidence discipline

A claim is not source-supported merely because its document, DOI, package version or repository is known.

Decision-bearing claims require:

```text
AtomicClaimRevision
↔ exact bounded EvidenceSpan
↔ SourceRevision
↔ content hash and locator
↔ ApplicabilityScope
```

Metadata can confirm identity and scope; it cannot create direct proposition support absent from the evidence text.

High-impact requirements, incompatibilities, limitations, version-sensitive facts and execution-blocking claims require stronger review than low-risk administrative identity facts.

## K. EDD debugging protocol

Always locate the first causal failure before changing code or data.

Trace the real path:

```text
query
→ route
→ state inspection
→ retrieval/knowledge
→ applicability
→ planning
→ policy/approval
→ runtime
→ execution/notebook
→ validation
→ answer/package
```

Protocol:

1. Freeze the failing request, inputs, configuration and artifact digests.
2. Reproduce once on the current branch.
3. Identify the earliest incorrect transition, not the most visible downstream symptom.
4. Reproduce the same case on the clean parent/baseline when regression ownership is uncertain.
5. Name one owner and one root cause.
6. Add a focused regression at that boundary.
7. Apply the smallest repair.
8. Re-run focused validation, then the required higher layers.
9. Stop when acceptance passes.

Do not change gold, thresholds, ranking or corpus to make an implementation failure disappear.

## L. Regression pyramid

For meaningful product changes, validate in this order:

1. **Focused unit/contract tests** — local models, validation and boundary behavior.
2. **Semantic decision UAT** — the scientific applicability/reuse/block decision.
3. **Real planner path** — the existing `CapabilityPlanCompiler`, not an eval-only planner.
4. **Raw/processed product replay** — Research, handoff, state inspection, actual plan and Notebook.
5. **Jupyter execution** — only when plan, renderer, parameters, runtime binding or generated code changed.

Additional rules:

- Run a fixed benchmark only once after code and tests are frozen.
- Do not patch after viewing the final evaluator result in the same checkpoint.
- Previously passing cases are a hard regression set.
- Record failed, blocked and `not_run` separately.
- A full-suite failure that reproduces at the clean parent is not authorization to expand scope.

## M. Stop conditions

Every task must declare:

- goal;
- primary owner;
- allowed scope/files;
- forbidden scope;
- acceptance criteria;
- explicit stop condition.

Mandatory stop examples:

- the required integration point does not exist;
- the fix requires replacing the production planner;
- the candidate scientific rule conflicts with a reviewed Capability Pack contract;
- an upstream owner, not the current layer, is first causal;
- a benchmark result exposes a new failure after the single authorized run;
- clean-parent reproduction shows the failure is unrelated;
- acceptance has passed.

Once acceptance passes, stop. Do not add the fifth case, next ecosystem, cleanup refactor or adjacent documentation unless explicitly requested.

## N. KG expansion protocol

Future ecosystem expansion follows:

```text
small source-bound slice
→ correct Package/Operator/Method identity
→ canonical ports and constraints
→ exact atomic claim evidence
→ decision UAT
→ production usefulness
→ risk review/promotion
→ only then breadth expansion
```

For each new slice:

1. Select one or two decisions the Agent must make.
2. Pin authoritative source revisions.
3. Model only the operators, methods, ports, constraints and scope needed for those decisions.
4. Record unsupported knowledge as `EvidenceGap`.
5. Prove compatibility and prerequisite semantics with decision UATs.
6. Demonstrate that the existing planner or answer path uses the result.
7. Measure whether the slice changes a useful product outcome.
8. Expand breadth only after that loop passes.

Never repeat breadth-first expansion before usefulness is demonstrated.

## O. Branch and commit hygiene

Before any Git write:

```bash
git rev-parse --show-toplevel
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git status --short
git diff --check
```

Rules:

- Freeze validated milestones into narrow logical commits.
- Stage explicit paths; do not use blind `git add -A` for audited checkpoints.
- Keep code, generated artifacts, runtime outputs, traces and documentation in separate commits when they have different review semantics.
- Never commit `.sckg_exec`, executed Notebook outputs, PBMC data, caches, tokens, secrets or absolute local user paths.
- Preserve NO-GO experiments on named WIP/archive branches; do not merge them into the formal baseline.
- After commit, verify commit paths, remote HEAD and a clean working tree.
- Do not tag or release unless a separate release audit authorizes it.

## P. Definitions of Done

The following DoDs are independent. Passing one must never imply another.

### P1. KG content DoD

- identity and schema valid;
- exact evidence resolvable and hash-valid;
- scope explicit or explicitly unknown;
- risk registered;
- contradictions resolved or blocked;
- review status explicit;
- candidate/promotion state explicit;
- no dangling endpoint or unsupported derived relation.

This does not prove runtime applicability or product use.

### P2. Scientific decision behavior DoD

- one decision and its admissible states are defined;
- positive, negative and unknown cases are tested;
- representation-specific compatibility is enforced;
- missing requirements and incompatibilities are explainable;
- exact evidence references accompany the decision;
- no incompatible action enters ranking/planning.

This does not prove the production planner consumes the result.

### P3. Production integration DoD

- the existing owner calls the decision interface;
- no parallel planner/state store is created;
- real production tests show scheduling/reuse/block behavior changed as intended;
- behavior outside the bounded scope is unchanged;
- candidate status is not hidden;
- failure isolation preserves the primary business outcome.

This does not prove the browser/Jupyter mainline.

### P4. End-to-end product capability DoD

- Research routes the real user wording correctly;
- Stepwise inspects the intended data;
- RepresentationLedger state is observable;
- the production planner emits the correct plan;
- Notebook compiles from reviewed templates;
- when execution-facing behavior changed, all code cells run in the supported kernel with zero errors;
- expected diagnostics appear;
- source hashes remain unchanged;
- Trace parent/child topology is intact;
- policy, approval, validation and evidence gates remain unchanged.

This proves an engineering capability for the tested scope. It does not by itself prove broad scientific qualification or release readiness.

## 2. Checkpoint review template

Use this compact report at the end of future work:

```text
Checkpoint:
Baseline commit:
Primary owner:
Files changed:
Behavior changed:
Behavior explicitly unchanged:
Focused tests:
Semantic UAT:
Planner/product replay:
Jupyter execution:
Trace evidence:
Input/artifact integrity:
Known baseline failures:
Candidate/trusted boundary:
GO or NO-GO:
Stop condition reached:
```

## 3. Non-negotiable architectural invariants

1. Canonical scientific knowledge is stable, versioned and source-backed.
2. RepresentationLedger is the current dataset state.
3. Runtime/execution records are actual execution history.
4. Trace is request correlation and observability.
5. ToolContract/StepContract define reviewed executable interfaces.
6. Policy and Approval authorize actions; knowledge does not.
7. `CapabilityPlanCompiler` is the single production planner.
8. Candidate is never silently promoted.
9. Unknown is never silently converted into compatible or incompatible.
10. A passed checkpoint ends the checkpoint.
