# Scientific Agent KG Specification v1.1

**Status:** Proposed normative architecture, pending approval.  
**Purpose:** Targeted revision of Scientific Agent KG Specification v1.  
**Supersedes:** v1 for new schema, extraction and maintenance work.  
**Repository basis:** `feature/method-kg-expansion-v1@27bca7e`.

This revision preserves the v1 architecture: one canonical, evidence-backed knowledge foundation supplies scientific semantics; RepresentationLedger owns current dataset state; ToolContract and runtime services own executable implementation facts; Policy and Approval own authorization; Trace and execution records own observed history. It does not promote candidate claims, modify a graph or index, or authorize execution.

The central model remains:

```text
Scientific intent
+ current RepresentationInstances
+ scoped scientific claims
+ versioned Operator and ToolContract bindings
+ runtime and governance decisions
→ request-specific governed Scientific Action Space
```

---

## 1. Normative principles

1. Scientific knowledge, implementation facts, dataset state and execution authorization MUST remain separate.
2. Every decision-bearing scientific relation MUST have claim-level provenance.
3. Applicability MUST be evaluated under an explicit `ApplicabilityScope`; an unscoped claim cannot silently become universal.
4. Input/output ports and their requirements are canonical operation semantics. Convenience relations such as `CONSUMES`, `PRODUCES`, `CAN_FEED` and `REQUIRES_BEFORE` are projections or derivations.
5. Unknown information MUST NOT be converted into compatibility, incompatibility or a ranking penalty.
6. Candidate knowledge MUST NOT become accepted solely because extraction, hashing or schema validation passed.
7. Review strength MUST be proportional to decision risk. Human review is required for high-impact facts, but not universally for every low-risk administrative record.
8. Knowledge promotion MUST NOT authorize execution.
9. Comparative statements MUST be represented as scoped empirical results, not flattened into universal `better_than` edges.
10. Historical snapshots and decisions MUST remain reproducible and rollback-safe.

Throughout this specification, **MUST / MUST NOT** are requirements, **SHOULD** is the default with documented exceptions, and **MAY** is optional.

---

## 2. Canonical ownership boundaries

There MUST be one canonical publication process and manifest with rebuildable query views, not several competing truth stores.

| Information | Authoritative owner | KG treatment |
|---|---|---|
| Scientific propositions and evidence | Canonical knowledge records | Primary knowledge |
| Software projects, packages, releases and documented operator semantics | Canonical knowledge records | Primary knowledge |
| Scientific representation vocabulary and constraints | Canonical knowledge records | Primary knowledge |
| Current representation instances and lineage | RepresentationLedger | Request-time binding only |
| Reviewed local execution interface | ToolContract/StepContract registry | Versioned reference |
| Installed runtimes and resources | Runtime/environment registry | Request-time assessment |
| Permission to act | Policy/Approval/Authorization | Request-time decision |
| Actual execution and validation | Execution/validation records | Historical reference |
| Request trajectory | Canonical Agent Trace | Correlation reference |
| Search scores, embeddings and graph indexes | Derived indexes | Rebuildable projection |

Canonical records MUST remain versioned JSONL/manifest facts. Typed in-memory graphs, SQLite FTS5 and dense indexes are derived. Neo4j MUST NOT be required. Raw user data, credentials, notebook output and runtime logs MUST NOT enter the scientific KG.

An execution or evaluation record may support a narrowly scoped local observation. It does not establish a universal scientific fact.

---

## 3. Entity model

### 3.1 Scientific entities

| Entity | Meaning |
|---|---|
| `ScientificTask` | Intended scientific outcome |
| `MethodFamily` | Scientific grouping of related methods |
| `Method` | Algorithmic/statistical approach independent of software API |
| `MethodVariant` | Named variation with materially different assumptions or semantics |
| `RepresentationType` | Reusable scientific meaning and structural kind of information |
| `RepresentationConstraint` | Declarative restriction over an admissible representation instance |
| `ApplicabilityScope` | Structured conditions under which a claim or relation is asserted |
| `Requirement` | Mandatory, conditional or optional condition for applicability |
| `ScientificConstraint` | General condition over data, design, parameters or biological context |
| `Limitation` | Scoped restriction or failure condition |
| `ParameterDefinition` | Meaning, ownership, valid domain and units of a parameter |
| `MetricDefinition` | Meaning, direction and interpretation of an evaluation metric |
| `WorkflowTemplate` | Reviewed conditional composition, never a universal fixed path |
| `BiologicalContext` | Species, tissue, assay, cohort or study-design context |

### 3.2 Software and implementation entities

| Entity | Meaning |
|---|---|
| `SoftwareProject` | Maintained project identity |
| `Package` | Ecosystem-qualified installable distribution |
| `PackageRelease` | Immutable release or commit |
| `Operator` | Stable package-qualified API/CLI operation |
| `OperatorRevision` | Version-specific signature and behavior |
| `InputPort` | Named input role of an OperatorRevision |
| `OutputPort` | Named output role of an OperatorRevision |
| `ImplementationBinding` | Reference from OperatorRevision to existing contracts/adapters/renderers/validators |
| `ReferenceArtifact` | Atlas, label mapping or pretrained-model identity |
| `ReferenceArtifactRevision` | Specific version and content digest |

### 3.3 Empirical-comparison entities

| Entity | Meaning |
|---|---|
| `BenchmarkStudy` | A defined comparative evaluation protocol or published study |
| `EvaluationDataset` | Versioned dataset or split used in an evaluation |
| `EmpiricalResult` | One scoped observation for one method/implementation, metric and evaluation condition |

### 3.4 Provenance and governance records

The canonical record layer MUST support:

- `SourceWork`, `SourceRevision`, `EvidenceSpan`;
- `AtomicClaimRevision`, `EvidenceAssessment`;
- `EntityResolutionDecision`, `ConflictRecord`;
- `ReviewDecision`, `DerivationRecord`;
- `KnowledgeChangeSet`, `KnowledgeSnapshot`, `EvidenceGap`.

These records remain addressable even when a derived graph view does not expose each as a visible node.

---

## 4. ApplicabilityScope

`ApplicabilityScope` is a first-class immutable structured model. It MUST NOT be replaced by a free-text `scope` label.

It SHOULD support the following fields, using governed references or bounded declarative values:

| Field | Meaning |
|---|---|
| `scope_id` | Content-addressed or revisioned identity |
| `task_ids` | Scientific tasks to which the assertion applies |
| `method_or_operator_versions` | Explicit versions, ranges or named variants |
| `modalities` | RNA, ATAC, protein, spatial or governed combinations |
| `organism_taxa` | Applicable organisms, if constrained |
| `biological_context_ids` | Tissue, disease or experimental context when relevant |
| `observation_unit` | Cell, nucleus, spot, sample, donor, etc. |
| `assay_technology_ids` | Platform/assay constraints when relevant |
| `study_design_constraints` | Batch, replicate, pairing and reference/query requirements |
| `representation_constraints` | References to required typed constraints |
| `parameter_constraints` | Conditions under which the assertion holds |
| `resource_constraints` | Scientific/resource applicability conditions, not current availability |
| `evaluation_context_ids` | Benchmark/evaluation contexts for empirical results |
| `valid_time` | When the assertion was valid in its subject domain |
| `scope_status` | `explicit`, `partially_known`, `unknown`, or `not_applicable` |

Scope semantics are conjunctive unless an explicit bounded `any_of` expression is used. Missing dimensions mean unspecified—not universal.

`ApplicabilityScope` MUST be reusable across claims, requirements, evidence assessments, empirical results and derived relations. A narrower scope MAY refine a broader one; it MUST NOT be widened during projection.

The following are distinct:

- unknown software version;
- a claim documented for all supported versions;
- a claim about one release;
- a claim inherited by an explicitly reviewed release range.

Dataset-specific claims MUST reference an evaluation or study context rather than carrying only a `dataset_specific` string.

---

## 5. Method, Package and Operator identity

The normative chain is:

```text
SoftwareProject
→ DISTRIBUTES Package
→ HAS_RELEASE PackageRelease
→ EXPORTS OperatorRevision
→ REVISION_OF Operator
→ IMPLEMENTS Method / MethodVariant
```

An `ImplementationBinding` links an OperatorRevision to an existing contract revision. It does not copy the contract.

### Scanpy example

| Layer | Identity |
|---|---|
| Package | Scanpy |
| Operators | `scanpy.pp.pca`, `scanpy.pp.neighbors`, `scanpy.tl.umap`, `scanpy.tl.leiden` |
| Methods | PCA, neighborhood graph construction, UMAP, Leiden |
| Local realization | OperatorRevision + StepContract/ToolContract + renderer/adapter |

Scanpy, PCA, neighbors, UMAP and Leiden are not flat peer tools.

Required identity rules:

1. One package MAY export many operators.
2. One method MAY have multiple implementations.
3. One operator MAY implement multiple variants under explicit parameter conditions.
4. One operator MAY compose multiple methods.
5. Wrappers MUST distinguish `DELEGATES_TO` from `IMPLEMENTS`.
6. Package dependency MUST NOT imply scientific prerequisite.
7. Implementations of the same method MUST NOT be assumed numerically equivalent.
8. Parameter-name equality MUST NOT imply parameter equivalence.

“Tool” may remain a user-facing catalogue label, but scientific claims MUST resolve to the correct project, package, method or operator identity.

Typed, scoped aliases are required. scVI versus scvi-tools, Monocle versus Monocle3, UMAP as method versus artifact, and CellTypist as project versus operation/reference model MUST NOT be silently merged.

---

## 6. Representation model

### 6.1 RepresentationType

`RepresentationType` defines reusable scientific semantics independent of a particular dataset.

It SHOULD define:

- observation unit and axes;
- modality or structured multimodal composition;
- value semantics and units;
- transformation state;
- feature-identity vocabulary;
- missingness semantics;
- statistical meaning;
- structural properties such as graph direction or matrix sparsity.

Examples include raw UMI counts, log-normalized RNA expression, PCA coordinates, a connectivity graph, cluster labels and a modality-partitioned latent representation.

### 6.2 RepresentationConstraint

`RepresentationConstraint` is a declarative predicate over a future or runtime representation instance. It is not a representation itself.

It SHOULD support:

- `is_a` RepresentationType;
- acceptable schema/refinement versions;
- value-state and transformation requirements;
- required or forbidden provenance steps;
- observation/feature identity and alignment requirements;
- modality presence and pairing constraints;
- required metadata;
- bounded shape/value/resource constraints;
- `all_of`, `any_of` and conditional alternatives.

Constraints MUST use a bounded expression language and MUST NOT embed arbitrary code.

### 6.3 RepresentationInstance

`RepresentationInstance` is a runtime record owned exclusively by RepresentationLedger. It identifies an actual dataset-derived artifact or slot, including:

- artifact/record ID;
- realized RepresentationType;
- storage locator reference;
- cell/feature hashes;
- producing operation and parameters;
- lineage;
- validation and stale state.

The canonical KG MUST NOT contain user-specific RepresentationInstances. At request time, the planner evaluates ledger instances against knowledge-layer RepresentationConstraints.

Container, locator and scientific state remain separate:

- `AnnData` is a container type;
- `adata.X` is a storage location;
- log-normalized RNA expression is a RepresentationType/refinement;
- one validated matrix in a request is a RepresentationInstance.

Multimodal constraints MUST model modality-specific axes and observation mappings. They MUST NOT assume complete paired measurements.

---

## 7. Ports and requirements are canonical operation semantics

Every decision-eligible `OperatorRevision` MUST expose explicit `InputPort` and `OutputPort` records.

### 7.1 InputPort

An InputPort MUST define:

- stable port ID and role;
- cardinality;
- one or more accepted RepresentationConstraints;
- mandatory/optional/conditional requirement status;
- reference-artifact or metadata requirements;
- cross-port alignment constraints;
- applicability scope.

### 7.2 OutputPort

An OutputPort MUST define:

- stable port ID and role;
- produced RepresentationType/refinements;
- production conditions;
- lineage to input ports;
- observation/feature identity preservation or transformation;
- mutation, invalidation and irreversibility effects;
- applicability scope.

### 7.3 Requirements

Requirements are typed records attached to a method, operator or port. They distinguish:

- `mandatory`;
- `conditional`;
- `optional`;
- `recommended`.

Applicability evaluation returns at least `satisfied`, `unsatisfied`, `unknown` or `conflicting`. Unknown mandatory requirements cause profiling, clarification or blocking, not a ranking penalty.

### 7.4 Derived operation projections

`CONSUMES` and `PRODUCES` MUST be derived from accepted port definitions:

```text
OperatorRevision → HAS_INPUT → InputPort → ACCEPTS → RepresentationConstraint
OperatorRevision → HAS_OUTPUT → OutputPort → EMITS → RepresentationType

derived view:
OperatorRevision → CONSUMES → RepresentationType
OperatorRevision → PRODUCES → RepresentationType
```

The derived edge MUST retain its port ID, conditions, scope, source claim revisions and derivation record. It MUST NOT strengthen an optional or conditional port into an unconditional fact.

Consumers MUST use ports/requirements for exact planning. `CONSUMES`/`PRODUCES` MAY be used for discovery and coarse graph traversal.

---

## 8. Relation vocabulary and derivation rules

Every relation MUST have registered endpoint types, direction, qualifier requirements and derivation rules.

| Relation | Normative role |
|---|---|
| `HAS_RELEASE`, `EXPORTS`, `REVISION_OF` | Versioned software identity |
| `IMPLEMENTS`, `VARIANT_OF`, `DELEGATES_TO` | Method/implementation mapping |
| `DEPENDS_ON_PACKAGE` | Software dependency only |
| `SUPPORTS_TASK` | Scoped scientific applicability |
| `HAS_INPUT`, `HAS_OUTPUT`, `ACCEPTS`, `EMITS` | Canonical port semantics |
| `REQUIRES` | Typed requirement link |
| `HAS_PARAMETER`, `HAS_LIMITATION`, `USES_REFERENCE` | Scoped decision semantics |
| `PRESERVES`, `TRANSFORMS`, `INVALIDATES` | Representation effects |
| `CONSUMES`, `PRODUCES` | Derived coarse port projections |
| `CAN_FEED` | Reviewed derivation that one output can satisfy one input under conditions |
| `REQUIRES_BEFORE` | Reviewed derivation proving an ordering requirement within scope |
| `ALTERNATIVE_FOR`, `COMPLEMENTS_FOR` | Scoped method comparison/composition |
| `INCOMPATIBLE_WITH` | Explicit, strongly governed incompatibility |
| `BOUND_BY` | Reference to existing contract revision |
| `SUPPORTED_BY` | View over accepted evidence assessments |
| `SUPERSEDES`, `DEPRECATED_BY` | Lifecycle, not semantic equivalence |

Arbitrary relation strings MUST NOT be promoted.

### 8.1 CAN_FEED

`CAN_FEED` is normally derived by a versioned compatibility rule from:

- an accepted OutputPort definition;
- an accepted InputPort constraint;
- overlapping ApplicabilityScopes;
- compatible observation/feature identity behavior;
- compatible method/operator versions.

It MUST identify the exact output and input ports and all proof premises. It is not a manually maintained workflow shortcut.

Because actual satisfaction depends on a concrete RepresentationInstance, `CAN_FEED` means “potentially compatible under these conditions,” not “already available.”

### 8.2 REQUIRES_BEFORE

`REQUIRES_BEFORE` MAY be derived only when a reviewed requirement proves that an earlier operation or effect is necessary. Matching output/input types alone is insufficient.

The prohibited inference remains:

```text
A produces R
B accepts R
therefore A is mandatory before B
```

If any producer can create R, the requirement is normally on R. If the ledger already contains a valid instance of R, an upstream producer can be skipped.

Manual `CAN_FEED` or `REQUIRES_BEFORE` assertions SHOULD be exceptional. They require the same proof record and review as a derived relation, plus a rationale explaining why derivation is inadequate.

### 8.3 Compatibility

Compatibility MUST identify its dimension: representation semantics, port alignment, features, observations, references, versions or software interface. “Both use AnnData” is never sufficient.

Coarse or missing metadata means unknown. Only explicit evidence of contradiction can establish strong incompatibility.

---

## 9. Atomic claims and provenance

### 9.1 AtomicClaimRevision

An AtomicClaim is one independently assessable proposition. Its immutable revision MUST contain:

- schema version;
- stable claim-lineage ID and immutable revision ID;
- typed subject, registered predicate and typed object;
- `ApplicabilityScope` reference;
- bounded normalized claim text;
- positive or negative polarity;
- assertion kind;
- semantic fingerprint and content hash;
- superseded revisions;
- creating activity.

Conditionality belongs in ApplicabilityScope/requirements, not polarity.

Review status is derived from ReviewDecision records. A materialized status MAY be included in a snapshot but is not the audit source.

### 9.2 Evidence model

The required provenance is many-to-many:

```text
SourceWork → SourceRevision → EvidenceSpan
EvidenceSpan → EvidenceAssessment → AtomicClaimRevision
AtomicClaimRevision → SUBJECT / OBJECT → typed entities
```

An `EvidenceAssessment` records:

- one claim revision;
- one span or explicitly justified bounded span group;
- stance: `supports`, `refutes`, `partial_support`, `mentions_only`, `not_supporting`;
- subject/predicate/object alignment;
- scope and version alignment;
- rationale and review provenance.

Adding corroborating evidence MUST NOT change the proposition identity merely because the source differs.

Source revisions MUST pin stable locator, source identity/work group, release/commit where available, acquisition time, source date/revision, original and extracted-text hashes, extraction method, license/access constraints and correction/retraction status.

Evidence spans MUST preserve enough local context to interpret tables, figures, signatures and qualifications. Claims reference evidence; they do not duplicate full source text.

### 9.3 Authority is claim-specific

- Official versioned API documentation can establish API behavior.
- A methods paper can establish described mechanism and scoped empirical observations.
- A benchmark can establish results only under its evaluation design.
- Issue discussions are candidate failure evidence unless separately verified.
- A local contract establishes project implementation/governance facts, not literature-backed science.

Retrieval rank, citation count, DOI presence or official branding alone does not establish support. Duplicate source works must not inflate evidence counts.

### 9.4 Claim-linked projections

Every decision-bearing projected edge MUST retain:

- typed endpoints and qualifiers;
- ApplicabilityScope;
- immutable claim revision IDs;
- evidence-assessment IDs;
- direct or derived status;
- derivation rule/version and premise IDs when derived;
- knowledge snapshot and provenance digest.

Derived relations form an acyclic proof graph. A derived edge cannot serve as its own evidence.

Multi-entity evidence produces claim-local entity associations. It MUST NOT copy all document-level entities to every claim or mutate retrieval membership.

---

## 10. Comparative evidence model

Comparative evidence is not a bare `MethodA BETTER_THAN MethodB` edge.

### 10.1 BenchmarkStudy

A `BenchmarkStudy` MUST define:

- study/protocol identity and revision;
- scientific task and ApplicabilityScope;
- evaluated method/operator revisions;
- dataset/split references;
- metric definitions and directions;
- preprocessing and parameter policy;
- baselines and comparison protocol;
- random seeds/repeats where applicable;
- source/evidence provenance;
- limitations and review state.

### 10.2 EvaluationDataset

An `EvaluationDataset` MUST define, or reference an existing governed manifest for:

- stable dataset/revision identity;
- modality, organism and biological context;
- unit of analysis and study design;
- sample/batch/donor structure;
- reference labels or truth status;
- split definition and leakage controls;
- transformations allowed before evaluation;
- content fingerprint or external version reference;
- access/licensing constraints.

User datasets remain runtime artifacts and are not copied into this entity model.

### 10.3 EmpiricalResult

An `EmpiricalResult` is one observation linking:

- BenchmarkStudy;
- EvaluationDataset/split;
- Method or exact OperatorRevision;
- MetricDefinition;
- value, uncertainty and aggregation unit;
- parameters/environment when materially relevant;
- ApplicabilityScope;
- exact supporting EvidenceSpan or governed evaluation record;
- result status and review provenance.

Pairwise superiority is a derived interpretation only when the comparison protocol, metric direction, uncertainty rule and relevant scope permit it. It MUST preserve both underlying result IDs and MUST NOT be projected as universal method superiority.

Missing measurements, non-comparable preprocessing, different splits or incompatible metric definitions MUST produce `not_comparable`, not a rank.

BenchmarkStudy and EmpiricalResult may support method selection after applicability filtering. They MUST NOT override unmet requirements, ToolContract constraints or policy.

---

## 11. Risk-based governance and review

Human review is not universally required for every record. Governance is based on decision impact, novelty, uncertainty and propagation reach.

### 11.1 Risk classes

| Risk class | Typical records | Minimum assurance |
|---|---|---|
| `R0 administrative` | Deterministic manifest membership, exact hash links | Automated schema/hash checks |
| `R1 low` | Exact alias backed by stable project metadata; non-decision labels | Automated validation plus sampled review |
| `R2 moderate` | Descriptive capability claims, ordinary outputs, nonblocking parameters | Source-bound assessment plus one qualified review or approved deterministic rule |
| `R3 high` | Input requirements, incompatibilities, limitations, version-sensitive behavior, `CAN_FEED`, comparative conclusions | Qualified human review; independent second review when decision-bearing |
| `R4 critical` | Execution-blocking requirements, destructive/irreversible effects, prohibitions, `REQUIRES_BEFORE`, qualification-changing facts | Two-person or designated-owner review, explicit rationale and impact test |

Risk may be elevated by:

- source disagreement or weak authority;
- ambiguous entity/version resolution;
- wide ApplicabilityScope;
- negative or incompatibility claims;
- large downstream dependency closure;
- behavior that can discard data or change biological conclusions.

### 11.2 Review decisions

A ReviewDecision MUST record reviewer/automation identity, role, timestamp, decision, rationale, artifact hashes, risk class and policy version.

Automated promotion is allowed only where the risk policy explicitly permits it and all deterministic checks pass. LLM extraction cannot be its own approving reviewer.

Re-review is required when a relevant source, scope, entity mapping, operator release or governing rule changes.

Unreviewed candidates remain isolated. A low-risk accepted record cannot be used to smuggle a high-risk derived relation into the action space.

---

## 12. Constructing the Scientific Action Space

The Agent computes an action space from pinned inputs:

- resolved scientific intent;
- DataProfile and RepresentationLedger snapshot;
- canonical knowledge snapshot;
- contract/capability-pack revisions;
- runtime assessment;
- policy and approval context.

The decision sequence remains:

| Question | Authority |
|---|---|
| Does a method address the task under this scope? | Reviewed scientific claims |
| Does a ledger instance satisfy the required ports? | Port constraints + RepresentationLedger |
| Can a missing representation be produced? | Port semantics + reviewed `CAN_FEED` derivations |
| Is an implementation available? | Operator/ImplementationBinding |
| Is the implementation registered and validated? | Existing ToolContract/qualification records |
| Is the runtime ready? | Runtime registry |
| Is the action permitted? | Policy/Approval |
| Which eligible option is preferable? | Scoped comparative evidence and preferences |

Applicability, planning readiness, runtime readiness, execution eligibility and authorization are separate dimensions.

A resulting action candidate SHOULD contain method/operator revisions, port bindings, reused or missing representations, requirements, expected outputs, parameter provenance, limitations, comparative rationale, contract reference and bounded reason codes.

A high empirical rank cannot compensate for an unsatisfied mandatory input. A method can be scientifically appropriate and planning-ready while execution remains disabled.

### Answer grounding

Online ClaimEvidenceBinding SHOULD reference canonical claim revisions when available while retaining exact evidence locality.

- Multiple answer claims retain independent bindings.
- Every scientific citation is local to the supported claim.
- Governance/qualification prose remains separate from literature claims.
- Procedural prose does not impersonate scientific evidence.
- Grounded audit remains an independent check.

Online answer bindings do not automatically write or promote canonical knowledge.

---

## 13. Knowledge lifecycle

### 13.1 Governed ingestion

```text
Source registration
→ immutable SourceRevision
→ EvidenceSpan segmentation
→ candidate AtomicClaim extraction
→ entity/version/scope resolution
→ EvidenceAssessment and conflict detection
→ risk classification
→ risk-appropriate review
→ candidate port/relation projection
→ quality and impact validation
→ approved KnowledgeChangeSet
→ immutable KnowledgeSnapshot
→ derived graph/search views
```

Each activity records input/output IDs, rules/models/software versions and digests. LLM-generated material is candidate-only. Source text is untrusted content, never an instruction to the ingestion process.

### 13.2 Entity and version resolution

Resolution distinguishes exact identity, governed alias, rename, successor, method variant and unresolved ambiguity. Merges/splits need reviewable crosswalks; historical IDs continue to resolve.

Installed package versions MUST NOT be assigned retroactively to unversioned READMEs or older papers.

Software release, source revision, claim revision, schema version and knowledge snapshot remain separate axes.

### 13.3 Contradictions

Potential contradictions require comparable subjects/predicates, overlapping ApplicabilityScopes and mutually incompatible objects/polarity. Different scopes or versions may explain an apparent conflict.

A ConflictRecord retains competing claims, overlap analysis, evidence, affected decisions and resolution state. Resolution may be scope separation, version separation, rejection, supersession or unresolved conflict.

Source counts or recency alone MUST NOT settle a scientific conflict. An unresolved high-impact conflict blocks only its affected action-space dependency closure.

### 13.4 Incremental changes and promotion

The unit of maintenance is a `KnowledgeChangeSet`, not a tool list. It MUST identify parent snapshot, additions/revisions/retirements, reviews, quality results, dependency impact and rollback target.

Promotion publishes a new immutable snapshot and never edits history in place. Updates operate on dependency closures from changed source/entity/operator records through claims, ports, derivations and projections.

Reprocessing is idempotent for identical pinned inputs and rules.

### 13.5 Supersession, deprecation and staleness

The system distinguishes superseded, deprecated, retracted/invalid, stale and rejected records.

Staleness is event-driven: API/source correction, package deprecation, reference revision, entity remapping, risk-policy change or review expiry. It is not arbitrary age decay.

Stale high-impact knowledge cannot silently authorize new actions, although it may remain visible for discovery with warnings.

### 13.6 Rollback and auditability

Rollback selects a previous coherent snapshot and compatible projections; it does not rewrite history or user data.

Snapshots pin schema/predicate registries, entity/claim/source/evidence revisions, review and derivation records, contract dependency digests and graph/index fingerprints.

Runtime queries MUST NOT combine incompatible graph and evidence-index generations.

---

## 14. Representative conformance examples

These examples demonstrate the model; they are not promoted claims.

### 14.1 Conditional Scanpy HVG input

The versioned operator has an input port with conditional alternatives:

```text
if flavor in {seurat_v3, seurat_v3_paper}
  accepts counts constraint
else for documented dispersion variants
  accepts logarithmized-expression constraint
```

The selected branch, exact version and evidence are recorded in ApplicabilityScope. Neither `adata.X` nor a layer name proves scientific state.

### 14.2 Neighbor graph with optional upstream production

The neighbors operator accepts a representation through a named port. PCA may produce a compatible representation, but this yields a conditional `CAN_FEED`, not a universal PCA prerequisite.

If the ledger already holds a validated compatible embedding, the planner can reuse it. UMAP and Leiden independently consume the resulting graph; UMAP is not a scientific prerequisite for Leiden.

### 14.3 Harmony and Scanorama

These methods may support the same broad task while exposing different operator ports and outputs. Compatibility depends on whether an operator emits an embedding or adjusted expression, together with feature and observation alignment.

A benchmark comparison is represented as scoped EmpiricalResults under one BenchmarkStudy—not a universal winner edge.

### 14.4 Cell annotation and doublet handling

An annotation operator has separate expression and reference ports. Reference species, feature namespace, label ontology and revision are explicit constraints.

Doublet scoring and cell exclusion are separate operations. Producing a score does not authorize removal; the latter remains governed by an explicit action and approval path.

### 14.5 scVI/MultiVI

scvi-tools is a Package; scVI and MultiVI are Methods/MethodVariants with distinct operators. Model setup, training and latent extraction are separate OperatorRevisions. A fitted model is a runtime artifact.

MultiVI constraints explicitly represent RNA/ATAC modality availability, paired/unpaired observation mappings and required batch/modality metadata. A generic `multimodal=true` tag is insufficient.

### 14.6 MOFA2

Input ports represent views, groups and sample-feature mappings. Separate AtomicClaims describe missing-value behavior, latent factors, feature weights and group-related limitations.

An empirical result about one dataset cannot become a universal parameter default or superiority relation.

---

## 15. Quality gates

Reports MUST distinguish machine structure, semantic review, coverage, runtime integration and `not_run` checks. An unexecuted check cannot be reported as zero failures.

| Gate | Normative measurement |
|---|---|
| Schema validity | 100% of proposed published records |
| Endpoint resolution | 100% of referenced typed endpoints |
| Source/evidence integrity | Exact revision, locator and hash resolve for every accepted assessment |
| Claim integrity | 100% immutable revision hash validity |
| Scope completeness | No decision-bearing claim with unacknowledged unknown critical scope |
| Port conformance | Every decision-eligible operator has valid canonical ports |
| Projection fidelity | Derived edges preserve port, requirement, condition and scope semantics |
| Provenance completeness | Every decision-bearing relation reaches accepted claims/evidence or reviewed premises |
| Entity consistency | All identities and applicable versions resolve |
| Duplicate/alias control | No unresolved duplicate or alias ambiguity on promoted decision paths |
| Contradiction handling | No unresolved high-impact conflict in active dependency closure |
| Comparative validity | Every comparison resolves study, dataset, metric, scope and result provenance |
| Risk-review compliance | Review level meets or exceeds record risk class |
| Snapshot coherence | Source, graph, index and contract fingerprints agree |
| Reproducibility | Same inputs/rules regenerate the publication |
| Rollback readiness | Prior coherent snapshot remains addressable |

Empty denominators are `not_applicable`, never automatic success.

Coverage is reported independently:

```text
Entity × task × predicate × ApplicabilityScope
→ supported / gap / unresolved / not_applicable
```

A sparse supported graph is preferable to a completed but fabricated matrix.

---

## 16. Extraction and maintenance deliverables

Every construction batch MUST produce:

1. construction scope and risk policy;
2. pinned source manifest;
3. entity/version/alias resolution table;
4. candidate ApplicabilityScopes and RepresentationConstraints;
5. candidate AtomicClaimRevisions;
6. EvidenceAssessments;
7. candidate Operator ports and claim-linked projections;
8. candidate derivations and proof dependencies;
9. evidence-gap and conflict reports;
10. risk-based review queue;
11. measured quality report with denominators and `not_run` states;
12. dependency-impact report;
13. promotion and rollback manifest after approval.

Manual review tables are generated only for records whose risk policy requires human judgment. Automated low-risk records remain fully auditable through validation and provenance.

---

## 17. Repository adoption

The current 48 candidate claims remain candidate material. This revision neither accepts nor rejects them.

Before promotion they require crosswalks for:

- Method versus Operator versus Package subjects;
- structured ApplicabilityScope;
- RepresentationType versus RepresentationConstraint;
- input/output-port ownership;
- direct versus derived projections;
- `CAN_FEED` versus `REQUIRES_BEFORE`;
- claim-local evidence and true entity resolution;
- risk-appropriate review.

The existing source-bound projection mismatch, fingerprint drift, missing/stale contract projections and ambiguous identities remain explicit blockers for affected dependency closures.

Adoption SHOULD reuse canonical manifests, source/evidence storage, Capability Packs, ToolContracts, RepresentationLedger, online ClaimEvidenceBinding, Trace and evaluation infrastructure. It MUST NOT introduce a parallel planner, runtime registry, authorization system or truth store.

### Recommended next checkpoint

**Scientific Knowledge Schema Conformance + Legacy Crosswalk**

This checkpoint should formalize v1.1 into candidate schemas and non-promoted conformance fixtures. It should prove:

- structured scope intersection;
- Package/Operator/Method separation;
- port-derived consumes/produces;
- conditional HVG inputs;
- ledger-bound reuse;
- reviewed `CAN_FEED` and `REQUIRES_BEFORE` derivations;
- multi-source support and scoped conflicts;
- multimodal alignment;
- benchmark/result representation;
- risk-based review;
- reproducible supersession and rollback.

Tool expansion, canonical promotion and index rebuilding should occur only after that contract is approved.

---

## Final architectural position

> **Evidence-backed AtomicClaims, structured ApplicabilityScopes and canonical Operator ports describe scientific applicability. Reviewed derivations expose possible transformations. The Agent binds those constraints to runtime RepresentationInstances and existing executable contracts to compute a governed, request-specific Scientific Action Space.**

This preserves the accepted boundaries:

- knowledge is not current data state;
- RepresentationType is not a runtime RepresentationInstance;
- source citation is not automatically claim support;
- port compatibility is not automatically a mandatory workflow prerequisite;
- comparative evidence is scoped observation, not universal superiority;
- scientific applicability is not execution authorization.
