# scKG-Agent Night Run Report

## Run identity

- Run ID: night-2026-09-14
- Baseline commit: e0ab62c368b6a544f077c601e5590e785578fae2
- Final HEAD: e0ab62c368b6a544f077c601e5590e785578fae2
- Last good commit: e0ab62c368b6a544f077c601e5590e785578fae2
- Branch: feature/method-kg-expansion-v1

## Overall status

PARTIAL / STOP_FOR_REVIEW

## Completed checkpoints

- CP0: PASS
- CP1: PASS
- CP2: PASS; v1.1 formal run consumed exactly once
- CP2.5: PASS; remaining defect attributed to production over-grounding
- CP3: NO-GO
- CP4: not_run
- CP5: not_run
- CP6: not_run
- CP7: report-only stop closure

## CP0 recovery

- Five tracked Semantic Routing v2 files were identified as one isolated WIP.
- The routing-only patch was preserved in a temporary local patch; SHA-256:
  f1a2292172c87b5dbd60353b89792fa87b618c44cfa548fd3f240ec05eb4e5ab.
- Those five tracked files were restored to HEAD without touching evaluation artifacts.
- Frozen spec SHA remained
  989bdf9b51a5e0529174a5a7b2da0bfe9735a6142fecbac9d985306cf6f61a85.
- Source artifact digests: 13/13 matched before CP3.
- Historical v1 formal markers: one started, one completed, ordinal 1, status FAIL.
- Historical v1 artifacts were not overwritten or rerun.
- Initial evaluator verification: 23 passed.

## Justification Fidelity v1.1

- Formal run consumed: YES, exactly once
- Formal status: FAIL
- Report SHA-256:
  5350f5ad74bb7700763415f27f1659ce0b9f583762263db1bc2e011828c977ff
- Spec SHA:
  989bdf9b51a5e0529174a5a7b2da0bfe9735a6142fecbac9d985306cf6f61a85
- Behavior invariance: 4/4
- Scientific evidence recall: 5/5
- Non-scientific evidence abstention: 7/7
- Evidence resolvability/binding: 17/17
- Decision-evidence precision: 5/17
- Ownership fidelity: 12/12
- Epistemic fidelity: 5/5
- Scope fidelity: 5/5
- Representation linkage: 6/6 concrete records + 1/1 explicit absence
- Negative controls: 8/8
- First failure: EXTRA_NON_DECISION_EVIDENCE
- Extra non-decision evidence: 12

The corrected formal result is scientifically interpretable: the evaluator
defects are closed and the remaining result is real production
over-grounding. No production behavior regression was observed.

## CP1 implementation and validation

- Added a v1.1 evaluation-only verifier and tests.
- Corrected behavior comparison to hold the unmutated behavior digest fixed
  across single-fault justification mutations.
- Kept Harmony producer scope separate from the downstream neighbors consumer
  scope.
- Separated representation linkage into 6/6 concrete records and 1/1 explicit
  absence.
- One report-aggregation defect was found during inspection: global tuple
  deduplication produced 4/13 instead of scenario-local 5/17. It was repaired
  once in the evaluator layer and immediately retested.
- Focused CP1 result after repair: 30 passed.
- git diff --check: PASS.

## CP2.5 read-only attribution

- v1.1 formal run scientifically interpretable: YES
- Twelve extra references still present: YES
- Behavior invariant: YES, 4/4
- Remaining defect owned by production evidence projection: YES
- Extra references individually real and binding-valid but non-decision-bearing:
  YES

## CP3 attempted projection contract

The unaccepted CP3 candidate implemented this intended rule:

    target operator input/requirement claims
        + cross-ecosystem CAN_FEED producer-output claim when needed
        - operator-wide output/limitation/guardrail claims
        - scientific citations on runtime Ledger facts

No ranking weights, Planner behavior, KG content, Ledger, contracts, routing,
policy, or Trace schema were changed.

## First unresolved causal failure

### Observed failure

load_frozen_preregistration() rejects the CP3 worktree with:

frozen_source_artifact_digest_mismatch:engine/scientific_kg_applicability.py

### Expected

After freezing the v1.1 formal baseline, the post-formal CP3 implementation
should be evaluated against unchanged atoms, evidence, scope, and behavior
expectations.

### Actual

The preregistration's 13 immutable source digests include the production file
that CP3 is explicitly required to modify. The evaluator therefore rejects
the candidate before evidence precision/recall can be measured.

### Earliest observable divergence

Evaluation artifact integrity loading, before product request execution and
before any canonical Trace span.

### First responsible layer

Evaluation preregistration artifact/version boundary.

### Why this layer owns the failure

Immutable scientific inputs and mutable system-under-test implementation were
coupled into one digest gate. Updating the digest would rewrite the frozen
formal identity; ignoring it would weaken the comparator.

### Minimal recovery action

Create a reviewed evaluation-versioning correction that separates immutable
scientific source/spec/input digests from old/new SUT implementation digests.
Only after that independent evaluator checkpoint is frozen should the CP3
projection candidate be reapplied and evaluated.

### Stop reason

Continuing now would require changes to both the evaluation boundary and
production projection, exceeding the one-owner/two-layer Runbook limit.

## Trace audit

- CP1/CP2 are evaluation-only and did not require product Trace.
- CP3 failed before a product-facing replay; no Trace result can legitimately
  be claimed.
- No PLAN request entered EXECUTION.

## Tests

- CP0 evaluator: 23 passed.
- CP1 corrected evaluator: 30 passed.
- CP3 first focused attempt: 8 passed, 8 failed.
  - One new test asserted an unprefixed blocking reason instead of the actual
    namespaced reason.
  - Seven evaluator tests were blocked by the frozen SUT digest mismatch.
- Full pytest: not_run after the mandatory CP3 stop.
- PBMC3k/Jupyter: not_run.
- Retrieval benchmark: not_run.

## Files changed

Evaluation-only WIP:

- eval/scientific_decision_justification_fidelity_v1.py
- eval/scientific_decision_justification_fidelity_v1_1.py
- tests/test_scientific_decision_justification_fidelity_v1.py
- tests/test_scientific_decision_justification_fidelity_v1_1.py
- v1 and v1.1 formal evaluation artifact directories

Unaccepted CP3 WIP:

- engine/scientific_kg_applicability.py
- tests/test_scientific_kg_decision_local_projection_v1.py

Run documentation/state:

- Night Runbook
- this Night Report
- issue retrospective entry
- untracked development status

Existing unrelated local audit directories remained untouched.

## Commits created

None.

## Open blockers

- Evaluation freezing must separate immutable knowledge inputs from mutable SUT
  code identity.
- CP3 candidate is unaccepted and must not be committed as a completed
  checkpoint.
- Semantic Routing v2 remains a separate preserved WIP; real LLM smoke was not
  run.

## Next legal action

STOP_FOR_REVIEW

Review and approve the evaluation-versioning boundary before any further
implementation. Do not continue CP3, source acquisition, self-deposition, or
promotion.

## DO NOT CONTINUE WITHOUT REVIEW

YES

---

## CP2.6 recovery addendum

- The unaccepted CP3 adapter and test were preserved as one patch with SHA-256
  6cfcc25eb339372620635200b771e0cca20ce4669736bd1a6db1a6728ffbdf4a.
- The CP3 files were restored to the trusted CP2.5 state.
- Evaluation artifacts are now divided into immutable evaluation inputs and an
  explicitly declared System Under Test.
- The only declared SUT path is engine/scientific_kg_applicability.py.
- Its pre-fix SHA is
  cd4df0b5ef25679070b3eca0108aabf9a8af98575f68b32d6c21481bcb7e3eac.
- v1 and v1.1 historical artifact tree digests remain unchanged.
- v1.2 formal evaluation has not run.
- Focused evaluator/versioning tests: 36 passed.
- Existing KG planner integration tests: 5 passed.
- git diff --check: PASS.
- CP2.6 decision: READY_TO_RESUME_CP3.

The previous STOP remains an auditable historical event. The next legal action
is a reviewed reapplication of the preserved CP3 patch; it was not performed
automatically.
