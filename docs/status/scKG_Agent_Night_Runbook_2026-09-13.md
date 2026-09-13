# scKG-Agent 2.0 Night Runbook
## Scientific Justification Fidelity → Decision-local Evidence → KG Self-Evolution

**Date:** 2026-09-13
**Purpose:** Codex overnight execution manual
**Recommended executor:** GPT-5.6 Sol / High reasoning
**Execution style:** checkpointed, trace-driven, EDD-first, fail-closed
**Primary rule:** **Never continue past an unexplained divergence.**

---

# 0. How to use this file

This is **not a roadmap**. It is an **execution runbook**.

When Codex quota is restored, give Codex this entire file and say:

> Execute this runbook exactly as written.
> Work checkpoint by checkpoint.
> You may automatically continue only when the current checkpoint satisfies every GO condition.
> On any NO-GO condition, unexplained divergence, frozen-artifact drift, unexpected behavior mutation, cross-layer repair requirement, or repeated failed repair, stop the run and write the Night Report.
> Do not improvise a new architecture, new KG schema, new planner, new routing system, or new evaluation target.
> Use Trace + EDD to locate first cause before modifying code.
> Preserve every failed formal artifact.
> Do not rewrite gold data to make an evaluation pass.

Codex should first read this file completely, then inspect the repository, then execute **CP0 → CP7** in order.

---

# 1. Tonight's objective

Tonight has **one main scientific/product line**:

```text
Scientific KG already integrated into existing CapabilityPlanCompiler
        ↓
Justification Fidelity measurement is cleaned up
        ↓
Decision-local evidence projection is fixed
        ↓
Planner behavior remains unchanged
        ↓
EvidenceGap can trigger authoritative source acquisition
        ↓
new evidence is deposited into Candidate KG + RAG
        ↓
Admin Review Queue receives governed candidate knowledge
```

The work is successful only if we improve the **scientific justification loop** without corrupting existing Planner behavior or execution governance.

## 1.1 What we are trying to prove

By the end of the night, ideally the system can demonstrate:

1. A Planner decision can be linked to the **specific scientific proposition** that justifies it.
2. Only evidence that supports that **decision-bearing proposition** is projected to the decision.
3. Runtime/Ledger facts are not falsely "proved" by scientific citations.
4. Scientific evidence recall does not decrease while decision-evidence precision improves.
5. When evidence is insufficient, the system can create an `EvidenceGap`.
6. The Agent can use existing source-acquisition infrastructure to discover and acquire authoritative sources.
7. A new source is pinned to a concrete revision/artifact/hash.
8. An exact `EvidenceSpan` can be associated with a candidate claim.
9. Newly acquired knowledge is deposited as **candidate**, not silently promoted to canonical truth.
10. The same source/claim can be reused on a later query without unnecessary reacquisition.
11. The entire process is inspectable through Trace/artifacts and failures are recorded through EDD + the failure log.

---

# 2. Explicit non-goals

Tonight **must not** become another breadth-first expansion.

Do **not**:

- expand to more scientific ecosystems;
- review/promote the whole ~380 candidate claim inventory;
- create a new Scientific KG schema version without a concrete unrepresentable contradiction;
- build a second Planner;
- weaken Capability Pack / ToolContract just to make KG appear behaviorally useful;
- force KG to alter behavior in scenarios where the baseline Planner is already correct;
- add arbitrary LLM code execution;
- redesign RepresentationLedger ownership;
- redesign canonical Trace schema unless current schema is demonstrably unable to represent the required bounded events;
- build a new crawler from scratch when existing source-acquisition code can be composed;
- automatically promote newly acquired knowledge to trusted/canonical;
- patch formal evaluation gold after seeing the result;
- chase unrelated historical full-suite failures;
- mix Semantic Routing v2 implementation into the KG evidence checkpoints.

---

# 3. Authority hierarchy

When documents disagree, use this hierarchy:

1. **Repository current code and tests** for current implementation facts.
2. `docs/DEV_SPEC_2.0.md` for repo-wide architecture authority.
3. `SCIENTIFIC_AGENT_KG_SPEC_V1_1.md` for Scientific KG architecture.
4. This Runbook for tonight's execution protocol.
5. Retrospectives/postmortems/status documents as historical records.

Important:

> This runbook must not silently supersede the repo's architecture authority.

---

# 4. Frozen historical facts that must not be rewritten

Before any work, verify these against the repository / existing artifacts.

## 4.1 Scientific KG → existing Planner integration

Known milestone:

```text
Scientific KG → Existing Planner Integration v1
commit: fb6b503f737645153be223e7665f1df310b85a40
```

The production planner remains:

```text
CapabilityPlanCompiler
```

Scientific KG does **not** become a parallel Planner.

---

## 4.2 Contribution Evaluation

Frozen result:

```text
behavioral contribution:             0/4
explanation/provenance contribution: 4/4
behavioral regressions:              0/4
```

Known freeze commit:

```text
d05e8b71649bb46dba004bfca91fe4d32ea2894b
```

Interpretation:

> In the four frozen scenarios, existing Ledger + Capability Pack + Planner already made the correct behavior decision.
> KG added scientific reasons, representation linkage, scope, evidence/provenance, and epistemic status.

**Do not later claim KG caused the behavior in these four scenarios.**

---

## 4.3 Justification Fidelity v1

Frozen preregistration commit:

```text
e0ab62c368b6a544f077c601e5590e785578fae2
```

Frozen specification SHA:

```text
989bdf9b51a5e0529174a5a7b2da0bfe9735a6142fecbac9d985306cf6f61a85
```

The single v1 formal run is already consumed and must remain immutable.

Known v1 formal result:

```text
FORMAL RUN v1 = FAIL
```

Known scientifically interpretable findings:

```text
Scientific evidence recall:            5/5
Non-scientific evidence abstention:    7/7
Evidence resolvability/binding:        17/17
Decision-evidence precision:           5/17
Epistemic fidelity:                    5/5
Ownership fidelity:                    12/12
Unknown-scope preservation:            PASS
Negative-control first-cause:          8/8
Representation linkage:                6/6 concrete + 1/1 explicit absence
```

Known attribution:

```text
1. BEHAVIOR_MUTATED in two scenarios
   → EVALUATOR_IMPLEMENTATION_ERROR
   collector compared KG output vs no-op,
   not mutated justification vs unmutated justification.

2. Harmony SCOPE_MISMATCH
   → EVALUATOR_SCOPE_CONTEXT_ERROR
   Harmony producer atom was resolved using downstream neighbors consumer context.

3. Representation aggregate 11/6
   → REPORTING_AGGREGATION_ERROR
   scientific and runtime obligations were mixed in numerator.

4. Twelve extra references
   → PRODUCT_JUSTIFICATION_FIDELITY_DEFECT
   references are real and binding-valid,
   but do not support the frozen decision-bearing proposition.
```

Therefore:

> v1 must be preserved as a **failed evaluator run with real product over-grounding exposed**.

Do not rerun v1.

---

# 5. Existing system boundaries to preserve

## 5.1 Responsibility ownership

```text
Canonical Scientific KG
= stable/versioned scientific propositions, scope, methods,
  operator identity, constraints, evidence bindings

RepresentationLedger / Profiler
= actual current dataset state, representation instances,
  current/stale/invalid, hashes, lineage, alignment

Capability Pack / StepContract / ToolContract
= executable interface and execution readiness

Policy / Approval
= authorization

CapabilityPlanCompiler
= single production planner

Trace
= request/decision trajectory and bounded record references

RAG / Evidence Store
= source artifacts, chunks, embeddings, retrieval material
```

Hard rules:

```text
Unknown ≠ incompatible
Candidate ≠ trusted/canonical
Knowledge promotion ≠ execution authorization
RepresentationType ≠ RepresentationInstance
same representation type ≠ compatibility
workflow recommendation ≠ universal scientific prerequisite
```

---

# 6. Tonight's execution state machine

Allowed sequence:

```text
CP0 PRE-FLIGHT / WORKSPACE ISOLATION
        ↓ GO
CP1 JUSTIFICATION FIDELITY v1.1 EVALUATOR CORRECTION
        ↓ GO
CP2 JUSTIFICATION FIDELITY v1.1 FORMAL RUN — EXACTLY ONCE
        ↓ STOP + READ-ONLY ATTRIBUTION
CP3 DECISION-LOCAL EVIDENCE PROJECTION
        ↓ GO
CP4 REGRESSION + TRACE + BEHAVIOR INVARIANCE
        ↓ GO
CP5 EVIDENCEGAP → AUTHORITATIVE SOURCE ACQUISITION PILOT
        ↓ GO
CP6 CANDIDATE KG + RAG SELF-DEPOSITION + REUSE
        ↓ GO
CP7 ADMIN REVIEW QUEUE + NIGHT REPORT + FINAL FREEZE
```

At any checkpoint:

```text
unexplained divergence
        ↓
EDD MODE
        ↓
first-cause attribution
        ↓
one-layer repair maximum
        ↓
retest
        ↓
PASS → continue
FAIL/unclear → STOP_FOR_REVIEW
```

---

# 7. Global execution rules

## 7.1 One checkpoint = one primary responsibility layer

Do not modify multiple responsibility layers simply because it is convenient.

Examples:

- evidence projection problem → do not simultaneously edit KG schema + Ledger + Planner;
- retrieval issue → do not patch ToolContract unless Trace/EDD proves contract ownership;
- runtime stale state → do not "fix" it with scientific claims;
- evaluator bug → do not change production code.

---

## 7.2 One targeted repair per checkpoint

Within one checkpoint:

- allow at most **one targeted repair cycle** for one identified first cause;
- after `fail → patch → fail`, do not make a second speculative patch;
- enter EDD and stop if root owner remains unclear.

---

## 7.3 Formal evaluation artifacts are immutable

After a formal run begins:

- do not edit its input set;
- do not edit the frozen spec;
- do not rewrite expected outputs;
- do not overwrite its output directory;
- do not "clean up" failed artifacts;
- do not rerun under the same version label.

---

## 7.4 Every product-facing checkpoint needs Trace inspection

A green test suite is necessary but not sufficient.

For applicable flows inspect:

```text
REQUEST
ROUTING
RETRIEVAL
STATE_INSPECTION
PLANNING
POLICY
APPROVAL
HANDOFF
NOTEBOOK_COMPILE
RUNTIME_BIND
EXECUTION
VALIDATION
REPAIR
DECISION
PACKAGE
```

Not every request should produce every stage.

Unexpected extra stages are themselves a defect.

---

## 7.5 EDD is mandatory on divergence

EDD template:

```text
Observed failure:
Expected:
Actual:

Earliest observable divergence:
Relevant Trace span:
Expected span state:
Actual span state:

First responsible layer:
Why this layer owns the failure:

Minimal reproduction:
Minimal one-layer repair:

Regression test to add:
Propagation risk if undetected:
```

---

## 7.6 Failure knowledge must be deposited

Prefer the existing append-only historical failure/status log if present, especially:

```text
docs/status/ISSUE_RETROSPECTIVE_LOG.md
```

Use `docs/FAILURE_POSTMORTEM_V1.md` only for stage-level synthesis, not raw per-bug logging.

Each real failure record must contain:

```text
Failure ID
Date
Checkpoint
Commit/worktree

Observed symptom
Expected
Actual

First failing test
First divergent Trace span

Root cause
Responsible layer

Why existing tests missed it
Minimal fix
Files changed
Regression added

Would this propagate if undetected?
Prevention rule

Status:
RESOLVED / OPEN / DEFERRED
```

---

# 8. Development Night Status

Create an **untracked development-state file** unless repo policy says otherwise:

```text
data/development/night_run_status.json
```

Suggested shape:

```json
{
  "run_id": "night-2026-09-13",
  "started_at": "...",
  "baseline_commit": "...",
  "current_checkpoint": "CP0",
  "checkpoint_status": "RUNNING",
  "last_good_commit": "...",
  "v1_formal_run_preserved": true,
  "v1_1_formal_run_consumed": false,
  "failed_checkpoint": null,
  "first_cause": null,
  "next_legal_action": "preflight"
}
```

Optionally append machine-readable events to:

```text
data/development/night_run_events.jsonl
```

Do not treat these as product Trace.

---

# CP0 — PRE-FLIGHT / WORKSPACE ISOLATION

## Objective

Establish one trustworthy starting state before any development.

This checkpoint changes **no production logic**.

---

## CP0.A Inspect repository state

Run at minimum:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git log -n 8 --oneline --decorate
git diff --check
```

Record:

```text
current branch
HEAD
tracked modifications
untracked files
evaluation artifact directories
routing WIP files
```

---

## CP0.B Protect Semantic Routing v2 WIP

Semantic Routing v2 is a separate checkpoint.

If the worktree still contains the known routing WIP:

```text
5 routing-related tracked files
focused tests previously ~117 passed
real DeepSeek smoke blocked by external billing
```

do **not** mix those diffs into tonight's KG evidence commits.

Required action:

1. Identify the routing-only tracked files from `git diff`.
2. Save a patch containing **only** those routing files.
3. Compute SHA-256 of the patch.
4. Record patch path + digest in Night Status.
5. Restore only those routing files to HEAD for tonight's KG mainline.
6. Do not touch untracked evaluation artifacts.

If routing WIP is already separately committed/frozen, record the commit and do not modify it.

### NO-GO

Stop if Codex cannot isolate the routing changes without touching evaluation WIP.

---

## CP0.C Verify frozen Justification v1 artifacts

Check:

- preregistration commit reference;
- frozen spec content;
- frozen spec SHA;
- v1 formal-run artifacts;
- v1 attribution output;
- original v1 outputs have not been rewritten.

Expected SHA:

```text
989bdf9b51a5e0529174a5a7b2da0bfe9735a6142fecbac9d985306cf6f61a85
```

### NO-GO

Stop if any frozen artifact changed unexpectedly.

Do not repair it automatically.

---

## CP0.D Verify current evaluator WIP

Known evaluator-related files from previous work may include:

```text
eval/scientific_decision_justification_fidelity_v1.py
tests/test_scientific_decision_justification_fidelity_v1.py
```

Run existing focused verification if those files are present:

```bash
python -m py_compile <evaluator-file>
pytest -q <focused-evaluator-test-file>
git diff --check
```

Previously known baseline:

```text
23 passed
8/8 negative mutations mapped correctly
```

Do not assume exact test count if repository state legitimately changed; compare against current committed baseline and explain any difference.

---

## CP0 GO criteria

All must pass:

- frozen spec unchanged;
- v1 run preserved;
- no unexplained tracked drift;
- routing WIP isolated;
- evaluator focused tests green;
- `git diff --check` green;
- no production KG/Planner/Ledger/contract drift.

Update Night Status:

```text
CP0 = PASS
next_legal_action = CP1
```

---

# CP1 — JUSTIFICATION FIDELITY v1.1 EVALUATOR CORRECTION

## Objective

Create **v1.1 evaluator-only correction** for exactly three known v1 evaluator defects.

No production behavior changes are allowed in this checkpoint.

---

## CP1.A Preserve v1

Never overwrite:

```text
data/evaluation/scientific_decision_justification_fidelity_v1/
```

Do not rerun v1.

v1 remains:

```text
FORMAL RUN v1 = FAIL
```

---

## CP1.B v1.1 correction #1 — Behavior invariant

Correct invariant:

```text
unmutated justification behavior digest
==
single-fault mutated justification behavior digest
```

Incorrect v1 comparison that must not survive:

```text
KG-enabled output
vs
no-op output
```

Add focused regression proving the evaluator compares the correct pair.

---

## CP1.C v1.1 correction #2 — Producer/consumer scope

For a decision atom, resolve scope from its frozen owner/context.

Required:

```text
Harmony corrected-embedding-output atom
→ Harmony producer/operator context

neighbors named-representation input atom
→ neighbors consumer/action context
```

Never use downstream consumer version/task to evaluate a producer output atom.

Add a regression that would fail if:

```text
Harmony 2.0.x
is compared against
Scanpy neighbors 1.11.x
```

for the Harmony output atom.

---

## CP1.D v1.1 correction #3 — Representation aggregate

Report separately:

```text
concrete representation obligations = 6/6
explicit absence obligations        = 1/1
```

Do not combine scientific atoms into a runtime-only denominator.

Explicitly prohibit aggregate forms like:

```text
11/6
```

---

## CP1.E Frozen items that must not change

Do not change:

- 12 decision atoms;
- 8 negative controls;
- metric definitions;
- first-cause taxonomy;
- source digests;
- v1 frozen spec;
- production evidence references;
- Scientific KG;
- Planner;
- Ledger;
- contracts;
- routing;
- Policy/Approval.

---

## CP1.F Tests

Run in order:

```text
1. v1.1 evaluator unit tests
2. negative-control tests
3. frozen-spec digest verification
4. py_compile
5. git diff --check
```

Then compare production files to CP0 snapshot.

---

## CP1 GO criteria

All must hold:

- all three evaluator defects corrected;
- no frozen gold changed;
- production code unchanged;
- negative controls still map to preregistered first causes;
- frozen spec SHA unchanged;
- v1 artifacts unchanged;
- focused tests green.

Update Night Status:

```text
CP1 = PASS
next_legal_action = CP2_FORMAL_RUN
```

---

# CP2 — JUSTIFICATION FIDELITY v1.1 FORMAL RUN

## Objective

Run the corrected v1.1 formal evaluation **exactly once**.

---

## CP2.A Pre-run gate

Before running:

- record current HEAD;
- record evaluator source SHA;
- record test SHA if applicable;
- record frozen spec SHA;
- record canonical request/input digest;
- verify v1.1 output directory does not already contain a completed formal run.

Use a new output directory, for example:

```text
data/evaluation/scientific_decision_justification_fidelity_v1_1/
```

Do not overwrite v1.

---

## CP2.B Formal-run markers

Create/write-once markers:

```text
formal_run_started.json
formal_run_completed.json
```

The started marker should include:

```text
timestamp
HEAD
evaluator digest
spec digest
input digest
```

The completed marker should include:

```text
timestamp
status
report digest
```

---

## CP2.C Run exactly once

Discover the evaluator's real formal entrypoint from code/tests.

Do not invent a second ad hoc formal runner.

Record the exact command in the Night Report.

---

## CP2.D Immediately after formal run

**STOP FOR READ-ONLY INSPECTION.**

Do not patch anything yet.

Collect:

```text
scenario-level verdicts
12 atom verdicts
5 dimensions
evidence counts
decision-evidence precision
scientific evidence recall
ownership
epistemic status
scope fidelity
representation linkage
unknown-scope preservation
negative-control outcomes
behavior digests
```

---

## CP2.E Interpretation expectations

Possible valid result:

```text
scientific evidence recall        5/5
decision evidence precision       5/17
extra non-decision evidence       12
behavior invariance               4/4
```

If so:

> The evaluator is now clean and the remaining over-grounding is a real production justification defect.

Do not treat this expected result as evaluation failure requiring gold changes.

---

## CP2 NO-GO conditions

Stop the entire overnight run if any of the following occurs:

- formal inputs changed after start;
- formal run executed more than once;
- v1 artifacts were overwritten;
- behavior unexpectedly mutates and first cause is unclear;
- negative controls no longer detect intended failures;
- frozen spec digest changes;
- evaluator reports structurally impossible metrics;
- the evaluator itself is invalid in a new way.

If NO-GO:

```text
failed_checkpoint = CP2
next_legal_action = REVIEW
```

Write EDD + Night Report and stop.

---

# CP2.5 — READ-ONLY ATTRIBUTION GATE

This is not a coding checkpoint.

Before CP3, answer:

1. Is the v1.1 formal run scientifically interpretable?
2. Is the 12-extra-reference finding still present?
3. Is behavior invariant?
4. Is the remaining defect owned by production evidence projection?
5. Are all extra references real/binding-valid but non-decision-bearing?

Only if all five answers support production over-grounding may the run automatically continue to CP3.

Otherwise stop.

---

# CP3 — DECISION-LOCAL EVIDENCE PROJECTION v1

## Objective

Replace **operator-wide evidence projection** with **decision-local evidence projection** without changing Planner behavior.

---

## CP3.A First freeze the projection contract

Before implementation, write a concise internal design note or test-level contract:

```text
Planner decision
    ↓
Decision-bearing proposition
    ↓
matched OperatorRevision / port / constraint
    ↓
matched RepresentationRecord and scope
    ↓
eligible AtomicClaimRevision candidates
    ↓
exact EvidenceSpan references
```

Key principle:

> Evidence projection is centered on the current decision, not all claims associated with the operator.

---

## CP3.B Hard eligibility before ranking

A candidate evidence item must pass hard eligibility.

Suggested dimensions:

```text
decision-bearing proposition match
operator / operator revision match where required
input/output port role match
representation role match
scope compatibility
version compatibility where required
claim-source binding validity
acceptable epistemic state
```

Reject before ranking if the evidence is merely related to the operator but does not support the decision atom.

---

## CP3.C MCDM boundary

The existing repository `MCDMCalculator` is primarily a **tool-ranking** mechanism.

Do **not** blindly reuse its:

```text
benchmark rank
citations
GitHub stars
```

weights for evidence-span ranking.

Tonight:

- preserve the MCDM idea: **eligible first, rank second**;
- if an evidence-specific ranking configuration already exists, use it;
- otherwise implement the decision-local hard filter first;
- do not invent arbitrary evidence weights merely to finish the checkpoint.

If multiple eligible evidence items remain and no frozen evidence-MCDM exists, use a deterministic documented ordering and mark evidence-MCDM weighting as a later checkpoint.

Do not let ranking rescue ineligible evidence.

---

## CP3.D Expected before/after target

Before:

```text
scientific evidence recall        5/5
decision evidence precision       5/17
```

Desired:

```text
scientific evidence recall        5/5
decision evidence precision       materially improved
ideal pilot target                5/5
```

A smaller citation set is **not** success if recall drops.

---

## CP3.E Explicit negative cases

Tests must prove:

- Leiden output evidence does not justify Leiden graph-input requirement;
- neighbors metadata output does not justify Leiden graph-input requirement;
- non-decision Scrublet guardrails do not justify the frozen raw-UMI input proposition;
- Ledger `stale/current/misaligned/raw-absence` facts do not gain scientific citations;
- candidate knowledge remains candidate;
- unknown remains unknown.

---

## CP3.F Do not touch

Do not modify:

- Scientific KG schema;
- RepresentationLedger ownership;
- Planner architecture;
- Capability Pack semantics;
- execution authorization;
- routing;
- canonical Trace schema.

---

## CP3 GO criteria

- decision-local projection implemented;
- all 5 evidence-bearing frozen atoms remain supported;
- 7 runtime atoms remain citation-abstinent;
- precision improves;
- no claim/source mismatch;
- no scope widening;
- focused tests green.

Proceed to CP4.

---

# CP4 — REGRESSION + TRACE + BEHAVIOR INVARIANCE

## Objective

Prove CP3 improved justification fidelity **without silently changing Planner behavior**.

---

## CP4.A Behavior invariant

The four frozen scenarios must retain behavior:

```text
1. valid neighbor graph → Leiden; reuse graph
2. stale / obs-misaligned graph → reject reuse
3. Harmony embedding → neighbors without forced PCA
4. transformed-expression-only → Scrublet blocked for missing qualifying raw UMI
```

Expected:

```text
behavior digest unchanged = 4/4
```

If behavior changes:

```text
BEHAVIOR_MUTATED
→ immediate EDD
```

Do not celebrate unexpected behavior as "smarter KG".

---

## CP4.B Test ladder

Run tests in this order:

```text
1. projection unit tests
2. justification fidelity evaluator tests
3. Scientific KG planner integration tests
4. CapabilityPlanCompiler focused tests
5. Research → Stepwise integration tests
6. representative product replay
7. full pytest
```

Do not jump directly to full pytest.

---

## CP4.C Baseline comparison for full pytest

Classify every failure as:

```text
NEW_FAILURE
PREEXISTING_FAILURE
FLAKY
ENVIRONMENT_FAILURE
```

Only `NEW_FAILURE` belongs to this checkpoint.

Do not chase known historical failures unless they are newly caused by this branch.

---

## CP4.D Trace audit

For representative planning replays inspect expected flow such as:

```text
REQUEST
→ ROUTING
→ RETRIEVAL
→ HANDOFF
→ STATE_INSPECTION
→ PLANNING
→ NOTEBOOK_COMPILE
```

A PLAN-only request must not unexpectedly enter EXECUTION.

Check:

```text
expected stages
actual stages
first missing stage
first unexpected stage
input refs
output refs
decision_type
outcome
reason_code
rule_version
record_ref
parent_trace_id
handoff_id
parent_request_id
original_plan_id
```

---

## CP4 GO criteria

All must hold:

- no unexpected behavior mutation;
- no new unexplained full-suite failure;
- Trace stages match request semantics;
- evidence precision improvement persists;
- evidence recall does not drop;
- frozen ownership boundaries remain intact.

Then proceed to CP5.

---

# CP5 — EVIDENCEGAP → AUTHORITATIVE SOURCE ACQUISITION PILOT

## Objective

Demonstrate that the system can identify missing scientific evidence and acquire an authoritative source **without requiring the user to manually download every PDF**.

This is a **1–2 EvidenceGap pilot**, not a crawler expansion project.

---

## CP5.A Reuse existing acquisition infrastructure

Before writing code, inventory existing repository components for:

```text
official webpage fetch
GitHub README/docs acquisition
DOI resolution
Crossref metadata/PDF discovery
Unpaywall OA discovery
publisher landing-page discovery
PDF download
source ingestion/parsing
RAG indexing
```

Reuse and compose.

Do not write a new generalized crawler unless EDD proves existing infrastructure cannot express the pilot.

---

## CP5.B Source priority

Prefer authoritative / structured acquisition in roughly this order:

```text
1. PMC / Europe PMC XML/full text
2. PubMed metadata / PMID resolution
3. Crossref DOI canonical metadata
4. official software docs / official GitHub
5. arXiv / bioRxiv / medRxiv where applicable
6. public publisher HTML/XML
7. Unpaywall OA location
8. openly accessible PDF
9. restricted source → manual acquisition queue
```

This is a preference order, not a requirement to query every source.

---

## CP5.C EvidenceGap object

For the pilot, an EvidenceGap must carry enough information to act on.

At minimum:

```text
gap_id
decision/task context
missing claim/proposition
target method/operator/version
required evidence type
known source identifiers if any
search terms
acquisition status
resolution status
manual intervention required?
```

Do not redesign the whole KG schema if existing `EvidenceGap` can hold this through metadata/records.

Use existing schema first.

---

## CP5.D Acquisition identity chain

Successful acquisition must establish:

```text
SourceWork
    ↓
SourceRevision
    ↓
SourceArtifact
    ↓
EvidenceSpan
```

At minimum capture:

```text
canonical source identity:
  DOI / PMID / official URL / repository identity

revision/version identity

artifact:
  HTML / XML / PDF / docs
  acquisition URL
  SHA-256

EvidenceSpan:
  section/page/paragraph/offset where available
  span text hash
```

Hard rule:

> A span may never float without a concrete source artifact/revision identity.

---

## CP5.E Acquisition blocked is a valid outcome

If a source is discovered but full text cannot be automatically acquired:

```text
Source discovered = YES
Full text acquired = NO
reason = access_restricted / robots / authentication / unresolved
manual_action = upload/provide artifact
```

Persist that state.

Do not repeatedly rediscover the same blocked source.

---

## CP5.F Pilot source count

Keep the pilot bounded:

```text
1–2 EvidenceGap
1–3 authoritative sources per gap
```

Do not crawl dozens of papers overnight.

---

## CP5.G Trace / audit

Do not necessarily expand Trace enum.

First try to represent acquisition through existing bounded stages / operations / record refs.

Audit operations conceptually equivalent to:

```text
evidence_gap_detected
source_discovery
source_resolution
artifact_acquisition
artifact_integrity
evidence_extraction
```

If current Trace cannot represent a required event without schema abuse, stop and report a schema limitation. Do not casually create Trace v1.

---

## CP5 GO criteria

For at least one pilot gap:

- gap created from a real missing-evidence condition;
- authoritative source discovered;
- source identity resolved;
- artifact acquired **or** access restriction explicitly recorded;
- artifact hash recorded when acquired;
- no duplicate uncontrolled source identity created;
- Trace/artifacts allow reconstructing the acquisition path.

Proceed only if at least one successful acquired artifact exists for CP6.

If all sources are access-restricted, stop with a valid acquisition-blocked report rather than inventing evidence.

---

# CP6 — CANDIDATE KG + RAG SELF-DEPOSITION + REUSE

## Objective

Turn acquired evidence into **governed candidate knowledge** and prove that the system can reuse what it learned.

This is the core self-evolution checkpoint.

---

## CP6.A Evidence extraction

From the acquired artifact:

1. identify a bounded exact span;
2. attach locator;
3. attach span hash;
4. evaluate relation to the candidate proposition.

Allowed assessment labels should use the existing model where possible, conceptually:

```text
supports
refutes
partial
mentions
not_supporting
```

Do not label `mentions` as `supports`.

---

## CP6.B Candidate claim deposition

Create a candidate claim/revision only when:

- source identity is resolved;
- source artifact exists;
- exact span is known;
- claim↔span relationship is explicit;
- scope is represented;
- epistemic status remains candidate.

Do not automatically promote to trusted/canonical.

---

## CP6.C RAG deposition

The source artifact / text chunks belong in the Evidence/RAG layer.

The KG should keep:

```text
claim
scope
method/operator relation
EvidenceSpan reference
source/revision link
epistemic status
```

Do not stuff the entire PDF/HTML into the KG.

---

## CP6.D Deduplication / reuse

Prove self-deposition by a second query/replay.

Expected pattern:

```text
First request:
existing KG/RAG insufficient
→ EvidenceGap
→ acquire source
→ candidate deposited

Second equivalent request:
candidate/evidence already found
→ source reused
→ no unnecessary reacquisition
→ same source revision/artifact hash
```

A system that downloads the same source again every time has not demonstrated meaningful self-evolution.

---

## CP6.E Candidate knowledge can assist but must be labeled

If candidate knowledge is used in a current answer/justification:

- its `candidate` status must remain visible;
- it must not be reported as canonical/trusted;
- it must not silently authorize execution;
- it must not bypass Planner/contract/policy gates.

---

## CP6.F Conflict handling

If newly acquired evidence conflicts with existing candidate/canonical knowledge:

- create a conflict record or equivalent existing governance record;
- do not overwrite old knowledge;
- do not auto-select the new source as truth solely because it is newer.

Stop automatic promotion.

---

## CP6 GO criteria

At least one pilot demonstrates:

```text
EvidenceGap
→ SourceWork/Revision/Artifact
→ exact EvidenceSpan
→ Candidate Claim
→ RAG index
→ Candidate KG
→ second-request reuse
```

with:

- no automatic canonical promotion;
- no duplicate acquisition;
- exact source/span binding;
- candidate status preserved;
- no execution authority leakage.

Proceed to CP7.

---

# CP7 — ADMIN REVIEW QUEUE + NIGHT REPORT + FINAL FREEZE

## Objective

Expose candidate knowledge for human governance and leave the repository in a reviewable state.

---

## CP7.A Admin Review Queue

Do not build a large UI if none exists.

At minimum produce a governed review item containing:

```text
review_item_id

Candidate claim
Method/operator/version
Scope

SourceWork identity
SourceRevision
SourceArtifact SHA-256
EvidenceSpan locator
Evidence assessment

Conflict status
Prior usage count if available
Acquisition status

Recommended reviewer actions:
PROMOTE
REJECT
NEEDS_REVISION
MERGE
SUPERSEDE
```

The review queue should make the administrator's job:

> review scientific knowledge

not:

> manually find/download/parse the paper from scratch.

---

## CP7.B Promotion remains manual

Tonight's autonomous run must stop at:

```text
CANDIDATE / REVIEW_PENDING
```

Do not automatically transition to:

```text
TRUSTED / CANONICAL
```

---

## CP7.C Final regression

Run the bounded test ladder relevant to all changed modules.

Then full regression.

Classify all failures.

No unexplained `NEW_FAILURE` may remain.

---

## CP7.D Final Trace audit

Select at least:

1. one Justification/Planner scenario;
2. one EvidenceGap/acquisition scenario;
3. one self-deposition/reuse scenario.

For each produce:

```text
expected path
actual path
first-cause anomalies: none / list
record refs
source refs
candidate status
```

---

## CP7.E Failure log update

Append all true failures encountered during the night.

Do not hide failures that were later repaired.

A repaired failure is still valuable project knowledge.

---

## CP7.F Commit discipline

Do not create one giant overnight commit.

Commit only completed, reviewed checkpoints.

Suggested semantic ownership:

```text
eval:
kg:
retrieval:
evidence:
docs:
```

Before every commit:

```bash
git diff --check
git status --short
```

Inspect changed file list.

Never accidentally commit:

- secrets;
- `.env`;
- unrestricted local paths;
- giant downloaded source corpora;
- temporary night status unless repo policy wants it;
- unrelated routing patch;
- old evaluation audit directories unless intentionally frozen.

---

# 9. GO / NO-GO matrix

| Condition | Action |
|---|---|
| frozen spec changed unexpectedly | STOP |
| v1 formal artifacts changed | STOP |
| v1.1 evaluator defect remains | STOP |
| v1.1 formal run invalid | STOP |
| formal run accidentally repeated | STOP |
| first cause unclear | EDD then STOP if still unclear |
| behavior changed unexpectedly | EDD |
| same failure survives one targeted fix | STOP |
| fix requires 2+ responsibility layers | STOP |
| new schema appears necessary | STOP_FOR_REVIEW |
| new full-suite failure explained as baseline/preexisting | record, continue |
| evidence precision improves but recall drops | NO-GO |
| evidence source real but non-decision-bearing | exclude from projection, keep source |
| source is paywalled/restricted | manual acquisition queue |
| candidate claim extracted successfully | candidate only |
| auto-promotion requested by implementation | BLOCK |
| duplicate reacquisition detected | fix/dedup before GO |

---

# 10. Frozen first-cause taxonomy for justification evaluation

Use precedence exactly:

```text
1.  BEHAVIOR_MUTATED
2.  EXPECTED_ATOM_MISSING
3.  EVIDENCE_UNRESOLVABLE
4.  CLAIM_SOURCE_BINDING_MISMATCH
5.  EVIDENCE_DOES_NOT_SUPPORT_DECISION_ATOM
6.  EXTRA_NON_DECISION_EVIDENCE
7.  SCOPE_MISMATCH
8.  SCOPE_SILENTLY_WIDENED
9.  REPRESENTATION_LINK_MISSING
10. REPRESENTATION_LINK_WRONG
11. EPISTEMIC_STATUS_CONFLATION
12. OWNER_MISATTRIBUTION
```

Do not rename or reorder this taxonomy during tonight's run.

---

# 11. Trace review checklist

For each product-facing checkpoint ask:

## Routing

```text
Was the request routed to the expected mode?
Did a PLAN request accidentally become ASK?
Did a non-execution request enter EXECUTION?
```

## Retrieval

```text
Which retrieval intent?
search_catalog or search_evidence?
Was KG hard-filtering used?
BM25?
dense?
RRF?
governance rerank?
contract gate?
```

## State inspection

```text
Which RepresentationRecords were assessed?
CURRENT / STALE / INVALID?
validated?
cell/gene identity aligned?
```

## Planning

```text
Which target representations?
Which methods/actions considered?
Which existing records reused?
Which steps scheduled?
What blocked or warned?
```

## Scientific applicability

```text
Which decision-bearing proposition?
Which operator revision / port / constraint?
Which representation record?
Which claim?
Which source/evidence?
What epistemic status?
```

## Handoff

```text
handoff_id?
origin_trace_id?
parent_request_id?
original_plan_id?
```

## Execution governance

If execution occurs:

```text
DataAccessGrant?
ApprovalScope?
tool/version?
contract version?
environment?
parameter hash?
ExecutionPolicy?
allowlist?
artifact integrity?
```

---

# 12. EDD examples

## Example A — PLAN unexpectedly becomes ASK

Do not inspect KG first.

EDD:

```text
Expected:
ROUTING → PLAN

Actual:
ROUTING → ASK

First divergent span:
ROUTING

Owner:
Research routing

Allowed repair:
routing only
```

---

## Example B — stale representation reused

EDD:

```text
Expected:
STATE_INSPECTION marks record non-reusable

Actual:
PLANNING reuses stale record

Check in order:
Ledger record status
validated
identity hashes
applicability adapter
Planner consumption

Do not patch KG evidence until owner is identified.
```

---

## Example C — scientific citation attached to runtime stale fact

EDD:

```text
Runtime stale fact owner:
RepresentationLedger

Scientific citation present:
projection/ownership defect

Do not alter the source article.
Do not alter Ledger semantics.
Fix decision-local projection.
```

---

## Example D — source discovered but claim not deposited

EDD path:

```text
source discovery
→ identity resolution
→ artifact acquisition
→ parser
→ EvidenceSpan
→ assessment
→ candidate creation
→ RAG/KG deposition
```

Repair the first failed stage only.

---

# 13. Historical failure lessons that must guide the run

These are prevention rules, not optional background.

## 13.1 Research routing regression

Past failure:

```text
explicit PLAN / Notebook request
→ EVIDENCE_QA / ASK
```

Lesson:

> Use Trace to locate earliest divergence at ROUTING; do not blame Planner/KG downstream.

---

## 13.2 Invalid prerequisite inference

Never infer:

```text
A produces R
B consumes R
therefore
A REQUIRES_BEFORE B
```

`REQUIRES_BEFORE` requires explicit necessity evidence.

---

## 13.3 Representation type equality is insufficient

Never infer reuse from type alone.

Require bounded evidence from:

```text
current/validated state
identity alignment
lineage/provenance
semantic constraints
contracts
```

---

## 13.4 Breadth before product loop

Large candidate graph inventory does not equal trusted product value.

Do not expand breadth tonight.

---

## 13.5 Contribution overclaim

The four contribution scenarios remain:

```text
behavior 0/4
explanation/provenance 4/4
```

Do not rewrite this result.

---

## 13.6 Evaluation fixture nondeterminism

A prior evaluation was confounded by dynamic timestamps.

Lesson:

> Formal inputs must be deterministic and frozen.

---

# 14. Definition of Done for every checkpoint

A checkpoint is not done when "code compiles."

It is done only when:

```text
implementation matches frozen checkpoint target
focused tests pass
Trace/artifacts inspected where applicable
no unexplained behavior mutation
first-cause ownership is clear
regression added for real failures
failure log updated if needed
git diff reviewed
GO criteria explicitly satisfied
```

---

# 15. Expected overnight outputs

Ideal successful night:

```text
1. Clean Justification Fidelity v1.1 formal baseline
2. v1 failed run preserved unchanged
3. Decision-local evidence projection implemented
4. scientific evidence recall remains 5/5
5. decision-evidence precision materially improves
6. Planner behavior remains invariant 4/4
7. EvidenceGap pilot works
8. authoritative source acquired automatically
9. SourceWork → SourceRevision → SourceArtifact pinned
10. exact EvidenceSpan extracted
11. candidate claim deposited
12. source/chunks deposited to RAG
13. Candidate KG updated
14. repeat query reuses acquired knowledge
15. Admin Review Queue receives candidate item
16. no automatic canonical promotion
17. representative Trace audit passes
18. Failure log contains every true failure discovered
19. Night Report states last-good checkpoint and next legal action
```

---

# 16. Valid partial-success outcomes

The night is still scientifically useful if it stops safely.

Examples:

## Partial A

```text
CP0 PASS
CP1 PASS
CP2 formal v1.1 PASS
CP3 NO-GO
```

Useful result:

> clean baseline established; projection implementation blocked with known first cause.

## Partial B

```text
CP0–CP4 PASS
CP5 acquisition blocked by paywall
```

Useful result:

> decision-local evidence fixed; acquisition gap correctly persisted to manual queue.

## Partial C

```text
CP0–CP5 PASS
CP6 candidate deposition NO-GO
```

Useful result:

> source acquisition works; failure isolated to candidate deposition.

A controlled STOP is better than a green but contaminated system.

---

# 17. Night Report template

At the end of the run, always write:

```markdown
# scKG-Agent Night Run Report

## Run identity
- Run ID:
- Start:
- End:
- Baseline commit:
- Final HEAD:
- Last good commit:

## Overall status
PASS / PARTIAL / NO-GO

## Completed checkpoints
- CP0:
- CP1:
- CP2:
- CP3:
- CP4:
- CP5:
- CP6:
- CP7:

## Justification Fidelity v1.1
- formal run consumed:
- spec SHA:
- behavior invariance:
- scientific evidence recall:
- non-scientific evidence abstention:
- evidence resolvability:
- decision-evidence precision:
- ownership fidelity:
- epistemic fidelity:
- scope fidelity:
- representation linkage:
- negative controls:

## Decision-local projection
- before:
- after:
- extra evidence before:
- extra evidence after:
- recall regression:
- behavior mutation:

## Evidence acquisition pilot
- EvidenceGap:
- source discovered:
- canonical source identity:
- SourceRevision:
- artifact type:
- artifact SHA:
- acquisition blocked?:
- reason:

## Self-deposition
- EvidenceSpan:
- assessment:
- CandidateClaim:
- RAG indexed:
- Candidate KG indexed:
- duplicate acquisition avoided:
- second-query reuse:

## Admin review
- review item:
- candidate status:
- conflicts:
- promotion performed:
  MUST BE NO

## Trace audit
### Scenario 1
- expected stages:
- actual stages:
- first divergence:

### Scenario 2
...

## Tests
- focused:
- integration:
- full:
- preexisting failures:
- new failures:

## Failures discovered
- IDs:
- root owners:
- repaired:
- unresolved:

## Files changed
...

## Commits created
...

## Open blockers
...

## First unresolved causal failure
...

## Next legal action
...

## DO NOT CONTINUE WITHOUT REVIEW
YES / NO
```

---

# 18. Final Codex behavior contract

During this run, Codex must follow these rules:

```text
Do not optimize for maximum amount of code written.
Optimize for maximum amount of trustworthy progress.

Do not continue after an unexplained divergence.

Do not convert evaluation failures into green results by changing gold.

Do not let scientific citations prove runtime facts.

Do not let candidate knowledge silently become canonical.

Do not let semantic understanding become execution authorization.

Do not build a second planner.

Do not expand the KG for breadth.

Do not build a new crawler if existing acquisition components can be composed.

Do not hide repaired failures.

Use Trace to find where the system first diverged.
Use EDD to assign first cause.
Fix one owner layer.
Retest immediately.
Deposit the failure lesson.
Only then continue.
```

---

# 19. Final success definition

The strongest possible outcome tonight is not simply:

> "all tests passed."

It is:

> **scKG-Agent can make a state-aware planning decision, attach only the scientific evidence that actually supports that decision, identify when evidence is missing, acquire authoritative evidence on demand, deposit it as candidate knowledge into KG/RAG, reuse that knowledge later, and leave canonical promotion under human governance — while every stage remains auditable through Trace/EDD and every real failure becomes retained development knowledge.**

That is the target.
