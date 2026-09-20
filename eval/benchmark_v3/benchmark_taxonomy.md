# scKG-Agent V3 Benchmark Taxonomy

Status: V3 offline development review. These are candidate/sidecar dimensions,
not Gold labels or an Agent Gain result. The old all-000 conclusion is withdrawn.

The taxonomy has three independent dimensions. They must be stored and reported
separately. A question's origin does not imply its knowledge coverage, and
neither determines the stage at which an evaluated system fails.

## 1. Question origin

Question origin records how a question entered the benchmark engineering
pipeline.

| Value | Definition | Current allowed use |
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

For each candidate scenario, first record a coverage vector and its exact
three-bit signature in the fixed order `V2 / Legacy / RAG`:

```text
scientific_kg_v2: present | absent | unknown
legacy_kg:        present | absent | unknown
ordinary_rag:     present | absent | unknown
```

When all three values are known, encode `present=1` and `absent=0`. The exact
signature is the analysis key; the coarse label is a convenience roll-up only.

| Exact signature (`V2/Legacy/RAG`) | Scientific KG v2 | Legacy KG | ordinary RAG | Coarse coverage label |
| --- | --- | --- | --- | --- |
| `111` | present | present | present | `shared` |
| `110` | present | present | absent | `shared` |
| `101` | present | absent | present | `shared` |
| `011` | absent | present | present | `shared` |
| `100` | present | absent | absent | `v2-only` |
| `010` | absent | present | absent | `legacy-only` |
| `001` | absent | absent | present | `rag-only` |
| `000` | absent | absent | absent | `out-of-knowledge` |

The retained coarse labels are therefore derived as follows:

| Value | Derivation from the frozen coverage vector |
| --- | --- |
| `shared` | Required answer evidence is present in at least two of Scientific KG v2, Legacy KG, and ordinary RAG. The exact vector must still be reported. |
| `v2-only` | Present only in the frozen Scientific KG v2 snapshot. |
| `legacy-only` | Present only in the frozen Legacy KG snapshot. |
| `rag-only` | Present only in the frozen ordinary RAG corpus. |
| `out-of-knowledge` | Absent from all three frozen knowledge sources. |

If any vector entry is `unknown`, both exact signature and derived label remain
unassigned; do not invent a wildcard signature. LLM-only
is not included in this coverage vector because model-parametric knowledge is
not a frozen, inspectable evidence corpus. A model may answer from unverified
knowledge, but that does not change the scenario's coverage label or grant
evidence authority.

Coverage assessment must record the exact signature, snapshot IDs/digests, and the supporting source
IDs or a documented negative-search result. A scenario cannot be called
`v2-only` merely because Scientific KG v2 retrieved it successfully in one run.
Formal analyses must stratify or report by exact signature and must not rely only
on the coarse `shared` roll-up, which intentionally merges `111`, `110`, `101`,
and `011`.

For the Phase 2.2 re-audit, the frozen sources are the exact consumers configured
by 07 integration commit `5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee`:

- V2 is only `approved-scientific-kg-v2-01`
  (`SHA256=06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4`)
  with its 121 approved statements, approved evidence chains, explicit scope,
  and 166 separate non-assertive caution contexts. The held scVelo revision is
  excluded.
- Legacy is the paired legacy backend: frozen retrieval foundation, candidate
  `ScientificKGEvidence` adapter, and the legacy tool/catalog graph used for
  candidate filtering. It must not be widened to the approved snapshot.
- RAG is the paired `generic_rag` BM25 consumer over the frozen 800-chunk
  retrieval foundation (790 non-quarantined), plus1847 catalog records conditional
  on `include_catalog=true`, with graph/scientific-evidence channels disabled.
  Catalog authority is discovery metadata only, not recommendation/execution evidence.

Planner, ToolContracts, execution guards, validation contracts, and the approval
system are shared infrastructure across all four lanes. They cannot establish a
V2, Legacy, or RAG coverage bit and cannot be reported as Scientific KG gain.

In this re-audit, `present` means the frozen consumer source contains enough
records to establish every critical fact/condition declared for the candidate,
not merely a related tool, method name, or partial lexical hit. Each `present`
entry therefore has stable supporting IDs, bound excerpts and scope reasons.
Each `absent` entry requires human-checked negative-search scope, variants,
inventory digest, related IDs and reasons for insufficiency. A program scan is
not a manual conclusion. All critical fact-by-source cells require two reviews
(00 resolves disagreement) before deriving a signature. Unreviewed cells are unknown.

Scientific facts, user context/state and task outputs are three separate fields.
Missing user data/version or computed output does not imply absent knowledge.
Runtime-only tasks, once requirements are reviewed, use `not_applicable` with
null exact signature/coarse label; they must not be encoded as000.
The current20 historical labels are withdrawn to unknown, awaiting decomposition.
See `coverage_review.py` and `scoring_protocol.md` for the review contract.

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

Phase 2.2 adds a fourth, explicitly provisional sampling facet named
`benchmark_track_proposal`. It is not a Gold label:

| Value | Candidate use |
| --- | --- |
| `K` | Scientific Knowledge Utility: method, input, condition, version, scope, or evidence questions. |
| `O` | Open-world Real-user Robustness: bug, API, regression, insufficient-context, or open-world issues. |
| `W` | Workflow / Execution: dataset, notebook, state, planning, execution, or artifact tasks. |

Track counts need not be balanced. Track assignment must not use 07 success or
failure. Candidate admission is evaluated separately using
`standalone_answerable`, `needs_version`, `needs_reproducer`,
`needs_data_state`, and `suitable_for_candidate`. An unsuitable issue remains a
raw seed and is not forced into the active candidate pool merely because it was
collected.

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
