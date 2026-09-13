# Scientific Decision Justification & Boundary Fidelity Evaluation v1

- Formal result: **FAIL**
- Formal run ordinal: **1**
- Frozen spec SHA-256: `989bdf9b51a5e0529174a5a7b2da0bfe9735a6142fecbac9d985306cf6f61a85`
- First failure: `BEHAVIOR_MUTATED`

## Metrics

- Scientific evidence recall: 5/5
- Non-scientific evidence abstention: 7/7
- Evidence resolvability: 17/17
- Scientific decision evidence precision: 5/17
- Scope fidelity: 4/5
- Representation linkage: 11/6 concrete and 1/1 absence
- Epistemic-state fidelity: 5/5
- Ownership fidelity: 12/12
- Negative-control first-cause detection: 8/8

## Interpretation

All twelve required atoms satisfy their frozen atom-local checks. The formal result is FAIL because resolvable, source-bound citations unrelated to the frozen decision atoms remain attached as citation decoration. These references remain in the preregistered precision denominator and are classified EXTRA_NON_DECISION_EVIDENCE.

Unknown Harmony and Scrublet scope dimensions remained unknown/not_evaluated. Runtime facts retained RepresentationLedger/Profiler ownership.

Completed at `2026-09-13T03:09:51.956747+00:00`.
