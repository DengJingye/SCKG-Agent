# Phase 2.1 Candidate Quality & Coverage Audit Report

> Historical report: BOTH the Phase2.1 ToolContract coverage and Phase2.2
> hardcoded all-000 coverage are WITHDRAWN. All20 current labels are unknown.
> The following former notice is historical, not a valid scientific conclusion.
>
> Superseded coverage notice: Phase 2.2 re-audited all 20 identity drafts against
> the exact consumers at 07 integration commit
> `5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee`. The Phase 2.1 `100` result used a
> ToolContract from shared runtime infrastructure and is not a Scientific KG v2
> coverage result. Use `coverage_audit_report.md` and
> `evaluation_lane_manifest.md` for the current candidate coverage audit.

Run: `candidate-audit-20260921-v1`
Status: complete bounded audit; no DEV/Gold, Agent Gain, or 05/06/07 changes

## Outcome

- Candidate review packet: 20 candidates (13 real-user,
  4 paper/notebook, 3 controlled probes).
- Existing Phase 2 candidates retained: 6; newly selected real-user candidates: 10.
- Paper/notebook raw seeds: 8 from two policy-reviewed, pinned public releases;
  four enter the candidate packet and none inherits an upstream answer.
- Coverage audits: 20 with exact signatures
  `{"000": 19, "100": 1}`.
- Semantic clustering: 10 clusters over
  56 raw seeds; largest cluster
  10/56
  (17.9%).
- Validation: `passed` with 8 paper seeds,
  20 candidates, and 20
  coverage records checked.

## Selection independence and reviewability

The additional real-user candidates were selected across ten predeclared scientific/problem
strata (resource behavior, normalization, object state, clustering semantics/backend,
reference mapping, reproducibility, visualization API, QC/raw alignment, and batch-aware
feature selection). Selection did not use TF-IDF/semantic cluster membership, a 07 response,
or any system success/failure. All drafts are verbatim identity transforms so reviewers can
see exactly what is missing. Added scientific context is empty for every candidate.

## Scientific review blockers

1. Public issue records are title-only. Reproducer, version, object/data state, and intended
   behavior must be independently collected or authored before promotion.
2. Paper/notebook tasks reference external data/capsules. Their input licenses, exact digests,
   and executable environments require separate review; upstream answers and Gold programs
   remain excluded.
3. Nineteen candidates are `000`: the frozen sources do not jointly supply the issue-specific
   or dataset-dependent facts needed for a complete answer. Partial term matches are retained
   in the negative-search records and were not promoted.
4. The `100` validation probe is supported only at the governed ToolContract pattern level;
   its future Gold wording and applicable tools still require expert adjudication.
5. Clusters remain sampling/review aids. Their semantic coherence and stability have not been
   human-rated, so they cannot define task labels or protected splits.

## Explicit non-actions

No development/evaluation/hidden split, answer Gold, routing Gold, expected trajectory,
Agent Gain run, A/B/C/D comparison, or Research Chat call was created. No Viewer, Scientific
KG, or Research Chat file was modified.
