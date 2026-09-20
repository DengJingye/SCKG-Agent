# scKG-Agent V3 Benchmark Taxonomy

Status: Phase 1 candidate taxonomy. It describes raw and candidate metadata, not
DEV/Gold labels and not an Agent Gain result.

The taxonomy has three independent dimensions. They must be stored and reported
separately. A question's origin does not imply its knowledge coverage, and
neither determines the stage at which an evaluated system fails.

## 1. Question origin

Question origin records how a question entered the benchmark engineering
pipeline.

| Value | Definition | Allowed use in Phase 1 |
| --- | --- | --- |
| `real-user` | A question or issue authored in a real support, forum, issue, or explicitly authorized local-history context. | Raw seed only. Preserve URL/external ID, access policy, thread references, and redaction status. Never inherit an answer as Gold. |
| `paper-notebook` | A task reconstructed from a published paper, notebook, benchmark capsule, or supplementary computational artifact. | Candidate scenario source. Preserve release/version and artifact digest. Do not report it as a real-user distribution. |
| `controlled-probe` | A project-owned deterministic, safety, state, boundary, or adversarial probe constructed to cover a specified behavior. | Coverage and regression source. Keep separate from naturally occurring questions in all summaries. |

Mapping to the existing `NaturalQuerySourceKind` is conservative:

| Question origin | Existing/new `source_kind` at raw stage | Downstream rule |
| --- | --- | --- |
| `real-user` | Existing `external_forum`, `official_issue`, or `real_history` | May map to `NaturalQueryCase.source_kind` after review. |
| `paper-notebook` | Raw-only extension `paper_notebook` | Must be transformed and adjudicated before mapping to an `EvaluationCase`; it must not be silently relabeled as `real_history`. |
| `controlled-probe` | Raw-only extension `controlled_probe` | May later map to an explicit component/execution case or, when appropriate, the existing `adversarial` source kind. |

## 2. Knowledge coverage

Knowledge coverage describes where the information needed to answer a candidate
scenario exists. It is measured against frozen corpus snapshots; it is not a
property inferred from the question wording and it is not assigned to raw seeds.

For each candidate scenario, first record a coverage vector:

```text
scientific_kg_v2: present | absent | unknown
legacy_kg:        present | absent | unknown
ordinary_rag:     present | absent | unknown
```

The primary coverage label is derived only when all three values are known:

| Value | Derivation from the frozen coverage vector |
| --- | --- |
| `shared` | Required answer evidence is present in at least two of Scientific KG v2, Legacy KG, and ordinary RAG. The exact vector must still be reported. |
| `v2-only` | Present only in the frozen Scientific KG v2 snapshot. |
| `legacy-only` | Present only in the frozen Legacy KG snapshot. |
| `rag-only` | Present only in the frozen ordinary RAG corpus. |
| `out-of-knowledge` | Absent from all three frozen knowledge sources. |

If any vector entry is `unknown`, the derived label remains unassigned. LLM-only
is not included in this coverage vector because model-parametric knowledge is
not a frozen, inspectable evidence corpus. A model may answer from unverified
knowledge, but that does not change the scenario's coverage label or grant
evidence authority.

Coverage assessment must record snapshot IDs/digests and the supporting source
IDs or a documented negative-search result. A scenario cannot be called
`v2-only` merely because Scientific KG v2 retrieved it successfully in one run.

## 3. Failure stage

Failure stage is an outcome of a run. It is not attached to a raw seed and it
must be based on trace, evaluator, or artifact evidence.

| Value | Boundary | Typical evidence |
| --- | --- | --- |
| `routing` | Domain, intent, task, action mode, or clarification decision is wrong before the appropriate task path is selected. | Router/intent result, `routing_gold`, gateway or `intent_parse` failure. |
| `state` | Required data, representation, version, conversation, approval, or workspace state is missing, stale, or interpreted incorrectly. | State inspection/profile span, representation ledger, conversation state, approval state. |
| `retrieval` | The system selects the wrong retrieval route, misses the required item/span, or admits an irrelevant/forbidden result. | Recall/MRR/span hit, retrieval trace, source IDs, leakage signal. |
| `scope` | Retrieved or generated content is about the wrong dataset, species, modality, task boundary, numeric population, or claim applicability. | Claim `scope_match`/`numeric_scope_match`, scenario constraints, human/judge scope review. |
| `evidence` | The claim lacks permitted authority, source-span support, citation coverage, or valid provenance despite being in the intended scope. | `ReferenceClaim.source_span_ids`, claim audit, citation evaluator, authority gate. |
| `synthesis` | Correctly routed and available evidence is composed into an incomplete, contradictory, unsupported, or wrong-shape answer. | Open-answer evaluator, claim precision/recall, response-shape result, answer-composition trace. |
| `planning` | Required/forbidden steps, tool/contract selection, parameters, order, authorization request, or stopping plan is wrong before execution. | `ExpectedTrajectory`, ToolContract/planning gate, authorization/approval trace. |
| `execution` | An admitted plan fails during environment binding, tool invocation, runtime, artifact creation, or bounded repair execution. | Execution span, exit status, stdout/stderr, tool-call and artifact manifests. |
| `validation-governance` | Validation, scientific/safety audit, package integrity, privacy, policy enforcement, or final governed decision is wrong or missing. | Validator/audit spans, governance violations, package hashes, release gate. |

### 3.1 Mapping from existing native stages

The coarse V3 value is a reporting overlay. It does not replace
`FailureAttribution.root_stage`, `root_error_type`, `owner_module`, or the native
trace sequence used by `attribute_failure()`.

| Existing stage/signal | V3 failure stage |
| --- | --- |
| `gateway`, `intent_parse`, canonical `ROUTING` | `routing` |
| `data_profile`, canonical `STATE_INSPECTION`, state/representation evaluator | `state` |
| `kg_filter`, `retrieval`, canonical `RETRIEVAL` | `retrieval` |
| `scope_match`, `numeric_scope_match`, explicit applicability evaluator | `scope` |
| evidence gate, source-span/citation/authority evaluator | `evidence` |
| `answer_compose`, report generation, open-answer composition evaluator | `synthesis` |
| `contract`, `plan`, `authorization`, `approval`, canonical `PLANNING`/`POLICY`/`APPROVAL` | `planning` |
| runtime bind, notebook compile/run, `execution`, canonical `EXECUTION` | `execution` |
| `validation`, `repair`, `decision`, `package`, `audit`, governance/release gate | `validation-governance` |

When more than one stage fails, retain all downstream symptoms but assign the
root using the earliest supported failure in the native ordered trace, matching
the behavior in `eval/evaluation_evaluators.py`. If evidence is insufficient,
use the existing native value `unknown`; do not guess a V3 stage.

## 4. Additional candidate-scenario facets

Task family, request type, data modality, language, risk, answerability, and
expected artifact may be recorded as candidate metadata. They are useful for
sampling and stratified reports, but they are not substitutes for the three
dimensions above.

In particular:

- `real-user` does not mean `shared` or answerable;
- `v2-only` does not mean Scientific KG v2 answered correctly;
- `out-of-knowledge` does not automatically mean `BLOCK`; clarification or a
  bounded statement of missing evidence may be correct;
- a failed final answer must not be assigned to `synthesis` when an earlier
  retrieval, scope, or evidence failure is supported by the trace.

## 5. Compatibility with existing Gold and metrics

After independent adjudication, downstream cases continue to use the existing
separation:

```text
routing_gold = domain / intent / task / context inheritance / clarification
answer_gold  = atomic ReferenceClaim records with source spans and scope
safety_gold  = ALLOW / CLARIFY / BLOCK and execution constraints
```

The V3 taxonomy does not add Gold to a raw seed. It supplies provenance and
sampling/diagnostic metadata around the existing `NaturalQueryCase`,
`EvaluationCase`, `ExpectedTrajectory`, `ReferenceClaim`, and
`FailureAttribution` contracts.
