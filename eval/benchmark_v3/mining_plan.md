# scKG-Agent V3 Real-world Question Mining Plan

Status: Phase 1.1 design plus Phase 2 mining-pilot protocol. Only the bounded
pilot described below is authorized; no bulk collection, DEV/Gold creation, or
Agent Gain run is authorized by this plan.

## 1. Objective and boundaries

The pipeline turns provenance-preserving raw material into reviewable candidate
scenarios. It does not turn public answers into scientific truth and it does
not use 07 Research Chat behavior to decide which questions to include.

The current outputs are limited to:

- the benchmark and source survey;
- a source registry and access gate;
- the raw seed JSON Schema;
- the three-axis taxonomy;
- this deterministic downstream design;
- a 40--60 record policy-gated pilot used to test provenance, redaction, dedup,
  clustering, and candidate-transformation plumbing.

Explicitly out of scope:

- bulk scraping or crawling beyond the explicit pilot endpoints and quotas;
- copying long third-party threads without a reviewed policy;
- assigning development/evaluation/hidden splits;
- constructing routing, answer, or safety Gold;
- running LLM, RAG, Legacy KG, Scientific KG v2, or Agent Gain comparisons;
- modifying Viewer, Scientific KG, or Research Chat code.

## 2. Artifact layers

The layers are append-only or derivational. No later layer overwrites its source.

```text
source registry
  -> raw seed JSONL
  -> provenance/policy validation report
  -> duplicate groups
  -> semantic clusters
  -> candidate scenarios
  -> human adjudication (future, owned/reviewed by 00)
  -> frozen EvaluationCase/NaturalQueryCase datasets (future)
```

| Layer | Contains | Must not contain |
| --- | --- | --- |
| Source registry | Source entry point, access path, policy status, permitted storage level, priority. | Retrieved question corpus or Gold. |
| Raw seed | Original/minimally transformed question text, provenance, policy, redaction, thread references, hashes, transformation history. | Split, expected answer, Gold tier, knowledge-coverage claim, system output, pass/fail. |
| Duplicate group | Member seed IDs, matching signals, selected canonical display seed, reviewer decision. | Deleted source records or answer labels. |
| Semantic cluster | Seed IDs, embedding/model/version, distance evidence, provisional theme, reviewer status. | System-specific success/failure or Gold. |
| Candidate scenario | Draft user-facing prompt, source seed IDs, required context, uncertainty notes, question origin, frozen coverage vector when available. | Unreviewed scientific answer Gold or final split. |
| Adjudicated case | Existing `EvaluationCase`/`NaturalQueryCase` fields, applicable metrics and approved Gold. | Raw forum answer copied as authority. |

## 3. Collection gate and pilot

Before any source is collected, its registry row must pass the acceptance gate
in `benchmark_sources.md`. Phase 2 starts with a 40--60 item pilot, uses only
reviewed P0 sources, and records prohibited/pending sources without contacting
their content endpoints. The approved pilot calls the official GitHub REST
Issues endpoint once for each allowlisted repository, stores title-level issue
metadata only, excludes pull requests and bot-authored records, and adds a small
project-owned controlled-probe stratum. It never reads issue comments for
answers. scverse Discourse is excluded because its reviewed Terms of Service
prohibit this automated access; Biostars and Bioconductor Support remain
unreviewed and untouched.

For every retrieved item:

1. resolve the canonical URL and stable external ID;
2. record timestamps, access method, query/endpoint, collector version, ETag
   when available, and a hash of the retrieved source record;
3. enforce the permitted storage granularity;
4. remove or redact disallowed PII before durable storage and append each
   transformation with input/output hashes;
5. store thread context as references unless reviewed policy permits text;
6. compute `content_sha256` from the stored UTF-8 `question_text`;
7. validate against `raw_seed_schema.json`;
8. require `record_type=raw_seed` and `gold_eligible=false`.

Policy ambiguity, sensitive data, removed sources, missing stable IDs, or a hash
mismatch produces a review item; it does not get silently repaired.

## 4. Deduplication

Deduplication groups records; it never deletes provenance.

### 4.1 Deterministic grouping

Apply in order:

1. same platform + collection + external ID;
2. canonical URL after removing documented tracking parameters;
3. identical retrieved-record hash;
4. identical stored question-text hash.

Thread root and replies are related through `thread_context`, not automatically
declared duplicates.

### 4.2 Near-duplicate candidates

Only after PII handling, create a reproducible comparison representation using:

- Unicode normalization and whitespace folding;
- case folding for comparison only;
- code-block/path/number placeholders retained as typed tokens rather than
  erased;
- language-aware token similarity;
- a versioned embedding model for semantic candidate retrieval.

Store the normalization version, embedding model/digest, threshold, neighbors,
and scores. Exact thresholds will be selected from a manually reviewed pilot,
not from downstream Agent performance. Borderline pairs require human review.

Each group retains all seed IDs and records a reason such as
`same_external_id`, `same_content`, `cross_post`, `version_variant`,
`paraphrase_candidate`, or `not_duplicate`.

## 5. Clustering

Clustering is for inventory and balanced candidate sampling, not automatic
labeling.

1. Stratify first by `question_origin`, language, and broad task family so large
   sources cannot dominate all clusters.
2. Cluster the redacted comparison representation with fixed seed, model,
   distance metric, and parameters.
3. Retain outliers; do not force every seed into a named task.
4. Have a reviewer name or merge candidate clusters using source examples.
5. Report source and origin composition per cluster.

Knowledge coverage is assessed later against frozen Scientific KG v2, Legacy
KG, and RAG snapshots. It is not used to form raw semantic clusters.

## 6. Candidate scenario generation

A candidate scenario may combine or clarify raw material, but every change must
remain auditable.

Minimum candidate fields:

```text
candidate_id
source_seed_ids
question_origin
draft_query
thread/context requirements
task-family candidate
ambiguities and missing facts
transformation_history
coverage_vector + snapshot digests (only after coverage audit)
exact_coverage_signature (V2/Legacy/RAG; only after coverage audit)
public_exposure
verbatim_overlap
transformation_distance
memorization_risk
review_status = needs_adjudication
gold_status = none
```

`public_exposure` records whether the source text was publicly available before
evaluation. `verbatim_overlap` is a normalized `[0,1]` overlap with source text,
and `transformation_distance` is a normalized `[0,1]` distance with its method
and version retained in the candidate manifest. `memorization_risk` is
`low|medium|high|unknown` and is adjudicated from public exposure, overlap,
release timing, and task distinctiveness; it is not inferred from downstream
system performance. Public exposure never makes a raw seed or candidate Gold.

Generation rules:

- preserve the user's actual uncertainty and version/state constraints;
- remove personal/project identifiers without making the task easier;
- do not copy a forum reply into the expected answer;
- do not select examples because 07 succeeds or fails on them;
- keep controlled probes and paper/notebook tasks distinguishable from
  real-user questions;
- do not assign an expected tool solely because a tool name appears in the
  source;
- do not derive `v2-only`/`legacy-only`/`rag-only` from one retrieval run;
- do not collapse formal coverage analysis to `shared`; retain the exact
  `V2/Legacy/RAG` signature (`111` through `000`);
- keep one source question as multiple candidates only when the distinct
  contexts are documented and reviewers approve the separation.

## 7. Future adjudication and split gate

This gate is intentionally not executed in the current pilot. Before a candidate becomes
an evaluation case, reviewers must:

1. decide applicable routing, answer, safety, trajectory, and execution metrics;
2. create atomic `ReferenceClaim` records with permitted source spans for any
   answer/citation metric;
3. specify `ExpectedTrajectory` only where tools or ordered steps are in scope;
4. verify answerability, safety action, and out-of-knowledge behavior
   independently;
5. freeze knowledge-corpus and source digests;
6. run cross-source and semantic near-duplicate checks before assigning splits;
7. prevent the same thread, notebook, paper, dataset, or paraphrase group from
   crossing protected split boundaries;
8. record adjudicators and disagreements without exposing hidden labels to the
   evaluated system.

The existing `development`, `evaluation`, and `hidden` values remain the only
split vocabulary. The current pilot creates none of them.

## 8. Mapping to existing evaluation models

No existing evaluation model is modified in this work.

### 8.1 Raw seed to `NaturalQueryCase` after review

| Raw/candidate field | Existing field | Rule |
| --- | --- | --- |
| `seed_id`/`candidate_id` | `case_id` | Create a new stable case ID; retain seed IDs in notes/metadata rather than assuming identity. |
| `question_text`/`draft_query` | `query` | Only the reviewed candidate query maps. |
| `source_kind` | `source_kind` | Direct only for existing `external_forum`, `official_issue`, and `real_history`; extensions require explicit adjudication. |
| `source.canonical_url` | `source_url` | Required for external forum/official issue, consistent with the existing validator. |
| `source.source_title` | `source_title` | Preserve as provenance, not hidden answer context. |
| `provenance.collected_at` | `collected_at` | Preserve original collection time. |
| reviewed thread selection | `conversation_context` | Convert only approved context; a whole public thread is not injected silently. |
| none | `split`, `expected_*`, `gold_status`, `gold_tiers` | Must be created independently during future adjudication. |

### 8.2 Candidate to `EvaluationCase` after review

- The reviewed query/context enters `input` and `conversation_state`.
- Provenance, question origin, source seed IDs, knowledge coverage vector, and
  snapshot digests belong in `source`/`metadata` or a versioned dataset manifest.
- `applicable_metrics` controls denominators exactly as in the current model.
- `answer_gold` uses `ReferenceClaim` with non-empty `source_span_ids` and
  explicit scope.
- `expected_trajectory` uses the existing `ExpectedTrajectory` and
  `ExpectedToolCall` structures.
- `risk_level` remains the existing low/medium/high/critical vocabulary.

### 8.3 Run failure mapping

`eval/evaluation_evaluators.py::attribute_failure()` remains authoritative for
selecting the earliest supported native failure and creating
`FailureAttribution`. The V3 failure stage in `benchmark_taxonomy.md` is derived
for grouped reporting while preserving:

- `root_stage`;
- `root_error_type`;
- `downstream_symptoms`;
- supporting evidence;
- `owner_module` and recommended action.

Scope/evidence/synthesis failures that are emitted by answer evaluators should
enter `EvaluationRunRecord.evaluation_failures`; they must not be inferred from
the final answer alone when stronger trace evidence exists.

## 9. Reproducibility manifest

Every mining run records:

```text
run_id and UTC timestamps
git commit and dirty state
source-registry digest
raw-seed schema digest
collector IDs/versions
source policy decisions
queries/endpoints and page bounds
normalizer and redactor versions
dedup thresholds
embedding model/digest
clustering seed and parameters
input/output counts and hashes
review queue paths
```

Collector failures, access denials, deletions, and unknown policy states are
first-class outcomes. Counts must not be backfilled or guessed.

## 10. Phase 1 infrastructure validation

Phase 1 is complete when:

- the four design artifacts parse and agree on the three taxonomy dimensions;
- the JSON Schema passes Draft 2020-12 schema validation;
- a synthetic allowed record validates;
- a synthetic record with `gold_eligible=true` is rejected;
- no raw schema field assigns split, expected answer, or Gold tier;
- the existing model mapping is documented without changing runtime code;
- `git diff --check` passes;
- no question corpus, DEV/Gold set, or Agent Gain output has been created.

## 11. Phase 2 pilot validation

The bounded pilot additionally requires:

- 40--60 raw seeds, with real-user and controlled-probe counts reported
  separately;
- all raw records validated against `raw_seed_schema.json`, plus a negative
  test proving `gold_eligible=true` is rejected;
- source calls, response headers, selection method, hashes, and policy blocks
  frozen in `collection_manifest.json`;
- exact-duplicate groups and near-duplicate candidates reported without deleting
  source records;
- provisional clusters reported with method/version and
  `needs_adjudication` status;
- any candidate draft carrying `public_exposure`, `verbatim_overlap`,
  `transformation_distance`, and `memorization_risk`, while retaining
  `review_status=needs_adjudication` and `gold_status=none`;
- no DEV/Gold creation, coverage assignment, Agent Gain run, or 05/06/07 change.
