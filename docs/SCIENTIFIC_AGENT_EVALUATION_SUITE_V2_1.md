# scKG-Agent Scientific Agent Evaluation Suite v2.1

## Midterm Core Benchmark Contract Freeze

**Project:** scKG-Agent 2.0  
**Contract version:** 2.1  
**Status:** FROZEN EVALUATION CONTRACT; benchmark manifests, gold, runners, cases, datasets and formal results are not created by this checkpoint  
**Supersedes:** Evaluation Suite v2 Draft v1.0 as the normative design for future benchmark construction  
**Scope:** evaluation design only; no production, Planner, KG, Ledger, ToolContract, Trace or policy behavior is changed  

## 1. Purpose and evidence boundary

This specification defines how scKG-Agent will be evaluated as a governed
Scientific Agent. It separates a feasible midterm benchmark from a broader
post-midterm suite and freezes the rules that must exist before cases, gold or
runners are built.

The benchmark must measure whether the system can:

1. understand scientific intent and preserve ambiguity;
2. reason over current data and representation state;
3. construct scientifically valid plans without unnecessary work;
4. determine applicability, missing requirements and incompatibilities;
5. attach decision-local, source-bound and scope-correct evidence;
6. recognize evidence gaps and acquire authoritative sources safely;
7. deposit and reuse candidate knowledge without conflating it with trusted
   knowledge;
8. expose governance boundaries, failures and provenance through auditable
   outputs.

Historical mechanism tests and formal evaluations remain evidence about their
own frozen versions. They are regression anchors, not new v2.1 benchmark
results. In particular:

- the four frozen KG/Planner scenarios showed no observed incremental Planner
  behavior from KG and did show explanation/provenance improvement;
- Decision-local Evidence Projection and the v1.2 justification evaluation
  remain historical frozen results;
- EvidenceGap acquisition, candidate deposition/reuse and the Admin Review
  Queue are bounded pilots;
- governed canonical promotion is not implemented and must be reported as
  NOT_IMPLEMENTED / NOT_RUN.

No current KG, Planner result, evaluator result or historical run is allowed to
become v2.1 scientific gold merely because it already exists.

## 2. Suite split

### 2.1 MIDTERM CORE BENCHMARK

The Midterm Core is the only required benchmark for the midterm report. Its
primary scale is approximately **40–60 distinct parent scientific scenarios**.
Nested atoms, paraphrases, mutations, repeated model calls and workflows do not
increase the independent scientific sample count.

The Midterm Core includes:

- semantic gateway and clarification evaluation;
- state-aware planning;
- scientific applicability and recommendation;
- decision-local evidence and justification fidelity;
- four-study real-data end-to-end evaluation;
- bounded EvidenceGap acquisition;
- bounded S0/S1/S2 candidate-learning utility;
- current governance boundary evaluation;
- fault injection, safety and Trace checks.

The Midterm Core is intended to support bounded, defensible claims. It does not
establish broad scientific qualification, production release readiness,
ordinary trusted execution, or autonomous scientific truth maintenance.

### 2.2 EXTENDED SCIENTIFIC AGENT SUITE

The Extended Suite is deferred until the Midterm Core is frozen and executed.
It may add:

- broader tools, operators, modalities and biological domains;
- more independent studies and larger datasets;
- prospective temporal evaluation;
- multi-turn research collaboration;
- resource-efficiency and cost benchmarking at larger scale;
- independent multi-reviewer scientific adjudication;
- real Governed Promotion transitions after that subsystem is implemented;
- conflict resolution, merge and supersession behavior;
- broader scientific qualification and external replication.

Extended records must follow the same sampling, gold, baseline, holdout and
formal-campaign contracts. They cannot be used retroactively to rewrite the
Midterm Core formal result.

## 3. Evaluation tracks and current capability boundary

| ID | Midterm Core question | Midterm status |
| --- | --- | --- |
| G0 | Does semantic routing understand open language while preserving ambiguity and hard governance? | Required gateway evaluation |
| T1 | Does planning reflect current state and valid reuse? | Required |
| T2 | Are scientific applicability and recommendation decisions correct? | Required |
| T3 | Is each decision justified by local, resolvable, scope-correct evidence? | Required |
| T4 | Do real-data paths execute technically and remain scientifically coherent? | Required |
| T5 | Are EvidenceGaps detected and authoritative sources acquired correctly? | Required bounded pilot evaluation |
| T6 | Does candidate knowledge improve a later decision without increasing false certainty? | Required S0/S1/S2 pilot evaluation |
| T7 | Are review packets complete and candidate/trusted boundaries preserved? | Required boundary evaluation only |
| T8 | Does the system fail safely and expose first causal failure through Trace/EDD? | Required |

G0 is a gateway, not a ninth scientific score. Routing errors are reported
separately so downstream tracks do not hide failures caused before planning or
retrieval.

For T7, the Midterm Core may test:

- review packet completeness;
- action choices being represented;
- candidate_pending_review preservation;
- no automatic canonical promotion;
- no execution authority created by a review record.

It must not claim to test actual PROMOTE, REJECT, NEEDS_REVISION, MERGE or
SUPERSEDE state transitions until Governed Promotion exists. Those outcomes are
NOT_IMPLEMENTED / NOT_RUN in v2.1 Midterm Core.

## 4. Sampling-unit contract

### 4.1 Required record fields

Every evaluation record must contain at least:

| Field | Meaning |
| --- | --- |
| case_id | Unique record identity |
| parent_scenario_id | Scientific scenario cluster from which nested records derive |
| study_id | Independent biological study identity, or null when not applicable |
| dataset_id | Frozen dataset/artifact identity, or null |
| source_work_id | Authoritative source-work identity, or null |
| mutation_parent_id | Unmutated record identity for fault injections, or null |
| replicate_id | Deterministic or stochastic replicate identity |
| split | development, validation or frozen_holdout |
| track | G0 or T1–T8 |

The manifest must also freeze case version, task family, difficulty, expected
owner, applicable baseline set and gold artifact reference.

### 4.2 Statistical hierarchy

- **Parent scientific scenario** is the main sampling unit for G0, T1, T2, T3
  and scenario-level T8 analyses.
- **Study** is the primary unit for T4; workflows, starting states and outputs
  are nested within study.
- **Source work or acquisition episode** is the primary unit for T5.
- **Learning episode** is the primary unit for T6; original and hidden related
  queries are paired observations inside the episode.
- **Review item / candidate claim family** is the unit for current T7 boundary
  evaluation.
- Atoms are nested observations, not independent scientific samples.
- Mutations are paired nested robustness observations.
- Paraphrases and repeated model calls are replicates, not new scenarios.

All descendants inherit the parent split. A derived record may not be moved to
another split to balance metrics.

### 4.3 Reporting and uncertainty

Counts must always report both:

- number of parent units;
- number of nested records.

Primary confidence intervals resample the appropriate parent cluster, not
atoms. Cluster or hierarchical bootstrap is used only when the number of
clusters is adequate and the resampling hierarchy is declared. With very small
cluster counts, especially four real-data studies, report exact denominators,
study-level results and descriptive uncertainty rather than decorative
significance tests.

Paired comparisons operate on shared parent units. McNemar, paired bootstrap or
Wilcoxon tests are used only when their assumptions and effective sample size
are satisfied. Multiple component comparisons must declare a correction or be
labelled exploratory.

## 5. Workflow-equivalence contract

### 5.1 Gold representation

A scientific workflow is not defined by one unique expected DAG. Workflow gold
must define:

- required final states;
- required prerequisites;
- forbidden operations;
- optional operations;
- partial-order constraints;
- acceptable method alternatives;
- acceptable terminal states;
- state-dependent reuse/skip conditions;
- required clarification or block conditions where applicable.

Exact DAG equality is a deterministic regression diagnostic only. It is not the
sole scientific correctness criterion.

### 5.2 Evaluation order

A workflow is scientifically acceptable only when:

1. every required terminal state is achieved or a preregistered safe
   block/clarification occurs;
2. required prerequisites are present or validly reused;
3. no forbidden operation occurs;
4. the observed order satisfies the frozen partial-order constraints;
5. each chosen method belongs to an allowed equivalence class for the frozen
   scope;
6. representations consumed by later steps satisfy lineage and compatibility
   requirements;
7. no unnecessary recomputation violates a state-dependent skip rule.

Optional steps neither earn credit nor cause failure unless they create a
scientific contradiction, invalid state, unnecessary material cost defined by
gold, or forbidden operation.

### 5.3 Workflow metrics

Report separately:

- required-final-state success;
- prerequisite satisfaction;
- forbidden-operation count;
- partial-order validity;
- method-equivalence validity;
- invalid reuse;
- unnecessary recomputation;
- safe block/clarification correctness;
- exact DAG match as diagnostic only.

## 6. Applicability label contract

### 6.1 Requirement-level states

Each requirement is evaluated independently as exactly one of:

| State | Definition |
| --- | --- |
| SATISFIED | Required object and its governed constraints are demonstrably met |
| VIOLATED | Available state demonstrably contradicts a hard compatibility or safety requirement |
| UNKNOWN | The required fact cannot be determined from available governed information |
| MISSING | A required object, field, reference or resource is absent |
| NOT_APPLICABLE | The requirement does not apply under the frozen method variant and scope |

UNKNOWN is epistemic uncertainty. MISSING is known absence. VIOLATED is known
incompatibility. These labels are not interchangeable.

Each requirement record must also freeze:

- requirement_id;
- owner;
- hard or soft criticality;
- scope;
- resolution mode: provide_resource, ask_user, acquire_evidence, select_other,
  or none;
- evidence requirement;
- version applicability.

### 6.2 Action-level aggregation

Action decisions are exactly:

- ALLOW;
- BLOCK;
- CLARIFY.

Aggregation uses the following precedence:

1. A hard VIOLATED requirement produces BLOCK.
2. A hard MISSING requirement produces:
   - CLARIFY when the missing fact/resource is explicitly user-suppliable and
     no safe scheduling decision can be made without it;
   - BLOCK when execution/planning cannot proceed until an external,
     structural or governed resource is provided.
3. A hard UNKNOWN requirement whose truth could change scientific
   applicability or safety produces CLARIFY.
4. Soft UNKNOWN or soft MISSING requirements do not independently block, but
   must remain visible in the justification.
5. ALLOW requires all applicable hard requirements to be SATISFIED or an
   explicitly frozen non-blocking soft state.
6. NOT_APPLICABLE requirements are excluded from the action denominator.

When more than one result applies, action precedence is BLOCK, then CLARIFY,
then ALLOW. The emitted decision must retain all requirement-level states so
aggregation cannot hide simultaneous missing, unknown or violated conditions.

### 6.3 Applicability metrics

Report:

- requirement-state macro-F1 and per-state precision/recall;
- action ALLOW/BLOCK/CLARIFY accuracy;
- false allow;
- false block;
- unnecessary clarification;
- false certainty;
- missing-requirement localization;
- scope and version fidelity.

Safety metrics must be paired with positive coverage; an all-BLOCK or
all-CLARIFY system cannot pass.

## 7. Independent-gold contract

### 7.1 Prohibited gold sources

The following are prohibited as scientific gold:

- current Scientific KG output;
- current Planner output;
- current evaluator output;
- answer or citation produced by any evaluated baseline;
- a historical frozen run treated as truth for a new case.

They may be diagnostic candidate-discovery aids, never adjudication authority.

### 7.2 Required scientific gold

Scientific gold is a versioned, source-bound adjudication artifact plus human
review. Each adjudicated item must include:

- gold item and parent scenario IDs;
- scientific decision or atomic claim;
- authoritative source work and revision;
- exact evidence span and locator;
- evidence/content integrity hashes;
- scope, modality and version;
- accepted and rejected alternatives with rationale;
- expected owner and epistemic state;
- allowed and forbidden evidence relationships;
- adjudicator identity/role, review status and timestamp;
- conflict or uncertainty record when consensus is unavailable.

Evidence existence does not itself prove a decision. The adjudication must
state how the span supports, partially supports, merely mentions or refutes the
claim.

### 7.3 Review policy

Programmatic facts and contract identities may be generated mechanically and
audited. Scientific applicability, limitations, scope, biological sanity and
workflow equivalence require qualified source-grounded review. High-impact,
version-sensitive, incompatibility, execution-blocking or conflict-bearing
gold requires an independent second review.

Disagreement is preserved and either resolved under a frozen adjudication
protocol or marked ambiguous/unknown. It must not be silently collapsed to the
current system output.

## 8. Baseline eligibility and information parity

### 8.1 Baseline definitions

| ID | Definition |
| --- | --- |
| B0 | LLM or RAG answer path without Ledger-aware planning or Scientific KG applicability |
| B1 | Hybrid RAG + ToolContract, without Scientific KG scientific constraints |
| B2 | RepresentationLedger + Capability Pack + CapabilityPlanCompiler + explicit no-op Scientific KG applicability |
| B3 | Full current scKG-Agent with Scientific KG applicability, decision-local evidence, Trace and candidate governance |
| B4 | B3 plus the bounded acquisition/candidate-deposition/reuse pipeline; canonical promotion remains unavailable |

### 8.2 Information-parity rule

A causal baseline comparison must freeze:

- query and conversation context;
- dataset and RepresentationLedger snapshot when the baseline is eligible to
  consume them;
- model/provider and decoding configuration;
- prompt and call budget;
- retrieval corpus and source-access policy;
- tool/operator registry;
- ToolContract and Capability Pack versions;
- planner target/options;
- timeouts, retry policy and failure handling.

Only the named capability under ablation may differ. A baseline lacking
information required to perform the track is marked NOT_ELIGIBLE, not scored as
a failure and not used as a strawman.

### 8.3 Track matrix

| Track | Primary eligible comparison | Shared information | Intentionally varied | Not comparable / N/A |
| --- | --- | --- | --- | --- |
| G0 | deterministic fallback vs semantic router, where both exist | query, history, model availability declaration, governance rules | semantic understanding source | task accuracy across unavailable-provider and available-provider strata is reported separately |
| T1 | B2 vs B3 | Ledger, Capability Pack, Planner, target/options, contracts | Scientific KG applicability | B0/B1 workflow metrics when they cannot consume state are NOT_ELIGIBLE |
| T2 | B2 vs B3; B1 only for recommendation questions it can answer | query, state, method inventory, evidence pool | KG scientific requirements | execution metrics for non-planning baselines |
| T3 | decision-local projection OFF vs ON on the same B3 decisions; B2 vs B3 only for provenance contribution | decisions, evidence pool, source bindings | projection or KG evidence layer | behavior claims from projection-only comparison |
| T4 | B2 vs B3 on the same study/workflow where both compile; product path reported separately | data, state, contracts, runtime | KG applicability | B0/B1 end-to-end execution if no eligible planner |
| T5 | same EvidenceGap and same source/access policy | gap, source candidates, network policy, budget | acquisition strategy under study | no-acquisition mode is an abstention baseline, not a discovery failure |
| T6 | S0 vs S1 vs S2 | cloned pre-state, source evidence, downstream task, query budget | no new evidence vs RAG evidence vs structured candidate | B0–B4 labels do not replace S0/S1/S2 |
| T7 | current B4 review packet/boundary checks | candidate, provenance and risk packet | packet or governance mutation | promotion-transition correctness is NOT_IMPLEMENTED / NOT_RUN |
| T8 | paired original vs one preregistered mutation | parent record, all unrelated state | one failure dimension | global task score for Trace-only ablation |

Cross-track aggregate baseline rankings are prohibited when eligibility or
information differs.

## 9. Holdout policy

### 9.1 Freeze timing

Parent IDs, grouping keys, split assignments, hidden related queries and
dataset/source boundaries must be frozen **before development benchmark
execution**. Formal campaign configuration may be frozen later, after the
development runner is validated, but it may not change holdout membership.

Developers and automated coding agents may use only development gold for
iteration. Validation may select thresholds declared in advance. Frozen
holdout gold is not inspected to patch the product, runner or evaluator.

### 9.2 Holdout families

The Midterm Core must include:

1. **Compositional holdout:** familiar entities/components in unseen
   state-task-scope combinations.
2. **Dataset/study holdout:** entire study and all derived states/workflows are
   unseen during development.
3. **Source/acquisition holdout:** complete source works/revisions and their
   derived claims are held out.
4. **Temporal/update holdout:** a source revision, software release or
   superseding evidence later than the frozen development cutoff.

Leave-tool or leave-operator holdout is used only when the evaluated system is
expected to generalize without that entity being present. Otherwise it is a
knowledge-coverage test and must not be mislabeled as reasoning
generalization.

### 9.3 Leakage controls

- Paraphrases, mutations, atoms, workflows, evidence spans and derived records
  inherit the parent split.
- Records sharing study_id, dataset lineage, source_work_id, candidate claim
  family or mutation_parent_id must remain grouped where leakage is plausible.
- Hidden related queries for T6 are inaccessible during candidate construction.
- Holdout identities and hashes are frozen in a separately controlled
  manifest; the development process sees only the minimum routing metadata
  needed to run it.
- Any holdout inspection invalidates that campaign version and must be
  recorded; it cannot be silently resealed.

Approximate scenario allocation may target 60% development, 20% validation and
20% frozen holdout, but group integrity and the four-study panel constraints
take precedence over exact percentages.

## 10. Formal campaign protocol

### 10.1 Meaning of exactly once

Formal exactly once means **one immutable preregistered campaign**, not one
provider call per case. The campaign may include preregistered replicates.
Failed and partial campaigns remain immutable artifacts and are never
overwritten.

### 10.2 Pre-run freeze

Before a formal run, freeze and hash:

- suite and schema versions;
- case and split manifests;
- gold and adjudication artifacts;
- dataset, source and evidence manifests;
- KG/candidate snapshot;
- Capability Pack, StepContract and ToolContract snapshots;
- code commit and runner SHA;
- model/provider and prompt configuration;
- deterministic seed policy;
- replicate count per track/baseline;
- request order;
- timeout and network retry policy;
- provider failure and partial-run handling;
- call and cost budget;
- denominator, missing-result and NOT_APPLICABLE rules;
- metric and statistical-analysis code.

Deterministic tracks normally use replicate_count=1. Stochastic LLM tracks use
the preregistered repeat count; repeats are nested within the parent scenario
and never counted as independent scientific samples.

### 10.3 Run handling

- Write a start marker before any evaluated call and an immutable completion
  marker when the campaign terminates.
- Preserve raw outputs, normalized outputs, logs, failure records and hashes.
- Do not change gold, runner or product after seeing the formal result.
- Provider outage follows the frozen retry policy; exhausted failures remain
  failed/not_run according to the preregistered denominator rule.
- A formal failure triggers read-only attribution. Any repair requires a new
  version and future campaign, never a rerun that overwrites the result.

## 11. S0/S1/S2 self-evolution protocol

### 11.1 Conditions

Each learning episode uses three independently cloned states:

| Condition | Knowledge available |
| --- | --- |
| S0 | Frozen pre-acquisition knowledge snapshot |
| S1 | The same newly acquired evidence is available through RAG, but no structured candidate claim exists |
| S2 | The same evidence plus Candidate AtomicClaim and complete provenance is available |

All conditions use:

- a fresh session;
- the same downstream task and task inputs;
- the same source evidence and source-access policy;
- the same model, prompt/call budget and tool registry;
- no canonical promotion;
- no cross-condition cache or memory leakage.

### 11.2 Episode queries

Each episode contains:

1. the original EvidenceGap query;
2. a hidden related query that was not visible during evidence acquisition,
   span selection or candidate-claim construction.

The hidden query tests transfer beyond cache/key matching. It must be
scientifically related but not a paraphrase whose answer is copied directly
from the claim-construction prompt.

### 11.3 Outcomes

Report S0/S1/S2 separately for:

- scientific decision correctness;
- justification completeness;
- evidence and scope fidelity;
- false certainty;
- correct clarification/block behavior;
- evidence reuse and candidate reuse;
- duplicate external reacquisition;
- candidate/trusted status preservation.

S1 isolates the effect of having evidence. S2 isolates the incremental effect
of structured candidate knowledge. Deposition success or cache reuse alone is
not scientific utility.

An episode is unsafe if correctness or scope fidelity falls, false certainty
increases, or candidate knowledge is presented as trusted. Improvement on the
original query without improvement on the hidden related query is reported as
query-local reuse, not generalized learning.

## 12. Real-data panel contract

### 12.1 Panel size and roles

The Midterm Core targets:

- **4 independent studies**;
- **8–12 end-to-end paths** nested within those studies.

The panel must include these roles:

1. PBMC historical anchor for continuity and regression;
2. multi-donor or multi-batch study;
3. non-PBMC tissue or different species/biological context;
4. distribution shift through platform, disease context or materially
   different technical design.

At least two studies must be unseen during system development. Multiple PBMC
states from one study do not satisfy study diversity.

### 12.2 Selection criteria

Before download or execution, freeze:

- biological and technical role;
- source, accession, release and license/usage note;
- raw and processed artifact availability;
- checksum and immutable artifact identity;
- cell/feature scale and expected compute cost;
- metadata and donor/batch labels;
- scientific tasks supported by the study;
- development exposure status;
- download stability and fallback policy;
- biological sanity checks and their limitations.

Study diversity has priority over inflating workflow count.

### 12.3 Three separate correctness layers

Each path reports:

**Technical execution correctness**

- Notebook compilation;
- code-cell execution;
- error outputs;
- artifact completeness;
- environment binding;
- input hash preservation;
- Trace completeness.

**Scientific workflow correctness**

- workflow-equivalence contract;
- input/output representation validity;
- reuse, skip and prerequisite correctness;
- method applicability;
- parameter and scope validity;
- no forbidden operation.

**Biological sanity checks**

- preregistered dataset-appropriate QC and output checks;
- no impossible dimensions or broken sample structure;
- expected qualitative patterns only when independently defensible;
- no post hoc biological story used as gold.

A runnable Notebook may fail scientific workflow correctness. A plausible plot
may not override a failed technical or provenance gate.

## 13. Safety hard gates and positive coverage

### 13.1 Non-compensable hard gates

The Midterm Core cannot pass if any of the following has a count above zero:

- unauthorized canonical promotion;
- execution authority leakage;
- wrong source binding;
- wrong revision binding;
- candidate/trusted conflation;
- runtime fact falsely proven by a scientific citation;
- conflict silently overwritten;
- input artifact mutated;
- formal artifact overwritten.

Additional track-specific hard gates may be frozen before case generation but
cannot weaken these gates.

### 13.2 Positive-coverage safeguards

Always report:

- positive success rate;
- unnecessary abstention rate;
- false block rate;
- clarification precision/recall where applicable;
- answer/decision coverage;
- eligible action completion rate;
- safe-block rate on truly unsafe cases.

A system that blocks or abstains on every case fails positive coverage even if
all safety-event counts are zero. Safety and utility are reported separately;
no composite score may hide either.

## 14. Midterm Core implementation budget

The following is a construction budget, not a claim of independent sample
size:

| Record family | Target |
| --- | ---: |
| Distinct parent scientific scenarios | 40–60 |
| Semantic gateway episodes | 24–32 |
| Planning scenarios | 24–32 |
| Applicability/recommendation scenarios | 24–32 |
| Evidence decisions | 24–36 |
| Nested evidence atoms | 80–120 |
| Independent real-data studies | 4 |
| Real-data E2E paths | 8–12 |
| Acquisition episodes | 12 |
| S0/S1/S2 learning episodes | 12 |
| Governance/boundary cases | 12 |
| Fault injections | 24–36 |

One parent scenario may contribute records to multiple tracks. Totals must not
be added and presented as independent scientific N. The final manifest reports
overlap explicitly.

For implementation, begin with a development seed set only after this contract
is approved. A suitable seed is 8–10 parent scenarios, 20–30 nested evidence
atoms, two studies, three acquisition episodes, three S0/S1/S2 episodes and
6–8 mutations. Seed results are evaluator-development evidence, not the formal
midterm benchmark.

## 15. Metrics and reporting

No single Scientific Agent Score is permitted. Report a capability matrix:

- semantic routing and clarification;
- planning;
- applicability/recommendation;
- evidence/justification;
- real-data technical execution;
- real-data scientific workflow;
- biological sanity;
- acquisition;
- self-evolution utility;
- governance boundary;
- robustness/Trace.

Each metric must declare:

- numerator and denominator;
- parent sampling unit;
- nested record count;
- eligible baselines;
- development/validation/holdout split;
- NOT_APPLICABLE and NOT_RUN handling;
- confidence interval method, if used.

Case-level hard failures remain visible and cannot be erased by aggregate
coverage. All failed, blocked and not_run results are reported separately.

## 16. Required ablations for the Midterm Core

Only causal, information-matched comparisons are required:

1. **T1 B2 vs B3:** Scientific KG applicability contribution under the same
   Ledger, Capability Pack and Planner.
2. **T3 decision-local projection OFF vs ON:** evidence precision/recall under
   identical decisions and evidence availability.
3. **T6 S0 vs S1 vs S2:** no new evidence, RAG evidence, then structured
   candidate knowledge.
4. **G0 semantic provider available vs deterministic fallback:** reported by
   provider stratum with identical governance gates; it is not required that
   final answer shapes be identical.

ToolContract, Ledger, Trace and source-governance ablations are included only
when a component-specific question and fair inputs are preregistered. Removing
a safety component merely to produce a weaker strawman is prohibited.

## 17. Deferred scope

The following are explicitly deferred from the Midterm Core:

- broad Governed Promotion transition evaluation;
- production PROMOTE/REJECT/NEEDS_REVISION/MERGE/SUPERSEDE execution;
- exhaustive review of all candidate KG claims;
- 24–30 real-data workflows or six large dataset families;
- leave-ecosystem-out unless a justified eligible system exists;
- broad multi-omics and cross-species scientific qualification;
- large-scale human-subject usability studies;
- enterprise IAM, sandbox or ordinary trusted-user execution;
- a universal composite score;
- statistical significance claims unsupported by the number of parent units.

Deferred means NOT_IMPLEMENTED or NOT_RUN, not PASS.

## 18. Construction sequence after contract approval

1. Freeze this v2.1 contract.
2. Define versioned manifests, gold and schemas.
3. Construct and validate the small development seed set.
4. Select and freeze the four-study real-data panel.
5. Freeze all parent split assignments and holdout identities before running
   the development benchmark.
6. Develop and debug runners/evaluators on development records only.
7. Freeze case/gold/runner/data/source/model/contract/KG manifests and the
   formal campaign.
8. Execute the formal campaign once.
9. Preserve immutable results and perform read-only attribution.

No case generation, gold generation, holdout execution or formal benchmark is
authorized by this document-only checkpoint.

## 19. Contract consistency audit

| Check | Result | Evidence |
| --- | --- | --- |
| Matches current implemented boundary | PASS | Acquisition, candidate deposition/reuse and review queue are represented as bounded pilots |
| Unimplemented Governed Promotion not claimed | PASS | T7 transition outcomes are NOT_IMPLEMENTED / NOT_RUN |
| Historical frozen results not relabeled as v2.1 formal results | PASS | Section 1 preserves them only as regression anchors |
| Scientific gold independent of SUT | PASS | Section 7 prohibits KG, Planner and evaluator outputs as gold |
| Baseline information parity | PASS | Section 8 defines eligibility and shared information per track |
| Parent and nested units separated | PASS | Section 4 forbids atom/mutation/replicate pseudoreplication |
| Workflow accepts scientific equivalence | PASS | Section 5 uses constraints, alternatives and partial order |
| Holdout precedes development benchmark | PASS | Section 9 freezes membership before development execution |
| Self-evolution tests utility, not storage alone | PASS | Section 11 isolates S0/S1/S2 and hidden related-query transfer |
| Safety cannot be gamed by universal abstention | PASS | Section 13 pairs hard gates with positive coverage |

## 20. Freeze decision

All twelve required contracts are defined without changing the System Under
Test or generating benchmark content.

**EVAL_V2_1_CONTRACT_FREEZE = PASS**

