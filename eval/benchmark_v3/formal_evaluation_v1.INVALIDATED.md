# Formal evaluation v1 invalidation notice

Status: `INVALID_FOR_SCIENTIFIC_CONCLUSION`

The immutable artifacts under `formal_evaluation_v1/` are retained as an audit
record, but their lane scores and contrasts must not be used to draw a
Scientific KG gain conclusion.

## Primary invalidation reason

The run completed 432 harness units, but provider execution was not healthy:

- 357 of 774 captured provider calls failed with HTTP 402.
- 192 of 432 run units contained at least one failed provider call.
- affected units by lane were 47/108 `llm_only`, 49/108 `generic_rag`,
  51/108 `legacy_kg`, and 45/108 `scientific_kg`.

`runs_completed=432` therefore means that the product process returned and its
receipt was captured. It does not mean that the intended provider reasoning
completed successfully.

## Secondary invalidation reasons

1. The frozen deterministic evaluator used exact substring groups and has
   demonstrable semantic false negatives.
2. K condition/scope error detection used literal forbidden-phrase matching;
   a zero rate is not evidence of zero scope errors.
3. Evidence reliability measured source/context binding, not whether the cited
   evidence entailed the answer claim.
4. W plan validity and artifact validation were aliases of the overall task
   pass value rather than independent checks.
5. Paired-family success required all six runs in a two-condition, three-repeat
   family to pass instead of scoring each repetition's condition pair.
6. The headline contrast averaged heterogeneous K, O, and W endpoints, despite
   the predeclared rule against a cross-track composite score.
7. Failure attribution classified many provider-error and scope-gate outcomes
   as synthesis failures merely because retrieval returned an ID.

## Preservation and recovery rule

- Do not delete, overwrite, rescore, or selectively rerun v1.
- Do not combine v1 successful units with a later run.
- Reuse the frozen 36 scenarios without outcome-driven substitutions.
- Calibrate a replacement evaluator only on DEV and synthetic fixtures.
- Run a provider-readiness gate before freezing and launching the replacement
  experiment.
- If readiness passes, create a separate `formal_evaluation_v2/` and rerun all
  432 units with the same accepted runtime commit.

This notice changes no v1 run, score, receipt, or frozen artifact.
