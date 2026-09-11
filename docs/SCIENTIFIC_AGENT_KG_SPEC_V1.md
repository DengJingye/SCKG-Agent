# Scientific Agent KG Specification v1

**Status:** Proposed normative architecture, pending approval.  
**Purpose:** The future standard for knowledge extraction, curation, maintenance and scientific decision support in scKG-Agent.  
**Repository inspected:** `feature/method-kg-expansion-v1@27bca7e`.

This specification does **not** promote the existing 48 candidate claims, change execution permissions, or declare the repository release-ready.

The central architectural decision is:

> scKG-Agent needs a versioned, evidence-backed model of scientific operations and their applicability—not a flat catalogue of tools and not a graph of frequently co-occurring names.

---

## 1. Purpose and governing principles

The KG must help the Agent answer:

1. What scientific goal is the user pursuing?
2. Which methods can address that goal?
3. What assumptions, representations and contextual conditions do those methods require?
4. Which concrete software operations implement them?
5. Can existing data representations be reused?
6. What transformations would make an otherwise inapplicable method applicable?
7. Which parameters, limitations and alternatives matter?
8. Which actions are implemented, feasible and authorized here?
9. What evidence justifies each decision?

The Scientific Action Space is therefore **computed for a request**, not stored as a universal list of executable tools.

Conceptually:

```text
Scientific intent
+ current data state
+ scoped scientific knowledge
+ registered implementation contracts
+ runtime and governance decisions
→ request-specific Scientific Action Space
```

Throughout this specification:

- **MUST / MUST NOT** define required behavior.
- **SHOULD** defines the default, with documented exceptions.
- **MAY** defines an optional extension.

### Foundational rules

1. Scientific knowledge, implementation facts, local data state and execution authorization MUST remain distinguishable.
2. Every decision-bearing scientific relation MUST have claim-level provenance.
3. Unknown information MUST NOT be silently converted into either compatibility or incompatibility.
4. Package membership, source authority and retrieval relevance MUST NOT substitute for scientific support.
5. Candidate knowledge MUST NOT become accepted knowledge merely because extraction or schema validation succeeded.
6. Knowledge promotion MUST NOT authorize execution.
7. Scientific applicability MUST be evaluated before preference ranking; a high score cannot compensate for an unmet mandatory requirement.
8. The system MUST preserve historical knowledge and decisions sufficiently to reproduce why an earlier plan was generated.

---

## 2. Repository assessment and architectural continuity

The existing implementation provides useful foundations, but its schemas are insufficient as the long-term extraction standard.

| Existing component | Preserve | Limitation addressed by this specification |
|---|---|---|
| [Method Graph models](/Users/lris/Desktop/scKG_agent/SCKG-Agent-recommendation-v1/core/method_graph_models.py) | Methods, representations, transitions and local JSONL manifests | No explicit Package/Operator/Method distinction; edge semantics largely depend on properties |
| [Capability Pack models](/Users/lris/Desktop/scKG_agent/SCKG-Agent-recommendation-v1/core/capability_pack_models.py) | Representation requirements, productions, implementation bindings and readiness boundaries | Scientific methods, configured operations and executable bindings are partly combined |
| [RepresentationLedger](/Users/lris/Desktop/scKG_agent/SCKG-Agent-recommendation-v1/core/representation_models.py) | Actual representation state, lineage, validity and hashes | Must remain the owner of dataset instances, not be absorbed into KG |
| [CapabilityPlanCompiler](/Users/lris/Desktop/scKG_agent/SCKG-Agent-recommendation-v1/engine/capability_planner.py) | Data-aware reuse and contract-backed planning | Future knowledge must supply richer applicability semantics without creating another planner |
| [ToolContract and execution models](/Users/lris/Desktop/scKG_agent/SCKG-Agent-recommendation-v1/core/execution_models.py) | Parameter contracts, approval, runtime, validation and qualification | These records must be referenced, not recreated as scientific facts |
| [Online ClaimEvidenceBinding](/Users/lris/Desktop/scKG_agent/SCKG-Agent-recommendation-v1/agent/claim_grounding.py) | Atomic answer claims and citation locality | Request-time answer bindings are not persistent canonical scientific claims |
| [Candidate AtomicClaim schema](/Users/lris/Desktop/scKG_agent/SCKG-Agent-recommendation-v1/core/method_kg_claim_models.py) | Explicit claims, evidence references, hashes and candidate isolation | Single evidence span, ambiguous version scope, conditional polarity and insufficient lifecycle semantics |
| [Source corpus builder](/Users/lris/Desktop/scKG_agent/SCKG-Agent-recommendation-v1/engine/source_corpus_v2.py) | Source-bound text, locators, source identities and content hashes | Document-level tool associations and coarse claim labels cannot establish claim-local support |

Two specific findings influence this design:

- The candidate prerequisite builder derives relations from matching producer/consumer representation IDs. That establishes a **candidate connection**, not necessarily a mandatory scientific prerequisite.
- Some candidate quality fields report fixed success values. Structural validation and content hashes do not demonstrate absence of semantic contradictions or entity-resolution errors.

Accordingly, this specification supersedes those **design assumptions**, without changing their implementation in this turn.

---

## 3. One knowledge foundation, separate responsibilities

There MUST be one canonical knowledge publication process and manifest, with multiple derived views—not independent competing KGs.

| Information | Authoritative owner | KG treatment |
|---|---|---|
| Scientific propositions and their evidence | Canonical knowledge records | Primary knowledge |
| Software identity, releases and documented API semantics | Canonical knowledge records | Primary knowledge |
| Reviewed local execution interface | Existing ToolContract/StepContract registry | Versioned reference |
| Current dataset content and representations | DataRegistry/DataProfile/RepresentationLedger | Request-time reference |
| Installed packages, available resources and runtime readiness | Runtime/environment registry | Request-time reference |
| Permission to perform an operation | Policy/Approval/Authorization | Request-time decision |
| What actually executed | Execution records and validation records | Historical reference |
| Request trajectory and decision timing | Canonical Agent Trace | Correlation reference |
| Search rankings and embeddings | Derived retrieval indexes | Rebuildable projection |

### Storage rules

- Canonical records MUST remain versioned JSONL/manifest-based facts.
- Typed in-memory graphs, SQLite FTS5 and dense indexes MUST remain derived artifacts.
- Neo4j MUST NOT be a required component.
- Method, Evidence and Decision views MUST identify the canonical snapshot from which they were produced.
- Contract facts remain owned by the contract registry; the knowledge manifest pins their referenced revisions and digests.
- Raw user matrices, credentials, runtime logs and notebook outputs MUST NOT be copied into the canonical scientific KG.

A graph edge may reference an execution or evaluation record. That does not turn one successful local run into a universally valid scientific claim.

---

## 4. Entity model

### 4.1 Scientific entities

| Entity type | Meaning | Examples |
|---|---|---|
| `ScientificTask` | Desired scientific outcome | Feature selection, integration, annotation, differential expression |
| `MethodFamily` | A scientifically meaningful grouping | Graph community detection, latent-factor modeling |
| `Method` | Algorithmic or statistical approach independent of a particular API | PCA, Leiden, Harmony, scVI |
| `MethodVariant` | A named variation with materially different assumptions or semantics | A distinct HVG selection approach |
| `RepresentationType` | Scientific interpretation and structure of information | Raw counts, PCA coordinates, connectivity graph |
| `Requirement` | Typed applicability condition or input requirement | Counts required; reference labels required |
| `ScientificConstraint` | Explicit condition over data, design or parameters | Required alignment of observation identities |
| `Limitation` | A scoped restriction or failure condition | A stated limitation for a particular dataset regime |
| `ParameterDefinition` | Meaning, type and ownership of a parameter | Number of components, clustering resolution |
| `MetricDefinition` | Meaning and interpretation of an assessment | Precision, recall, batch-mixing metric |
| `WorkflowTemplate` | Reviewed, conditional composition of operations | A scoped preprocessing and clustering recipe |
| `BiologicalContext` | Relevant biological and experimental context | Species, tissue, assay, study design |

`ScientificTask` MUST describe an outcome, not merely repeat an API name. Fine-grained operations need not become new top-level task families.

Biological vocabulary SHOULD reference governed external identifiers where appropriate rather than creating duplicate gene, disease or cell-type ontologies.

### 4.2 Software and implementation entities

| Entity type | Meaning |
|---|---|
| `SoftwareProject` | Maintained project or ecosystem identity |
| `Package` | Installable distribution identity, including ecosystem |
| `PackageRelease` | Immutable identified release or commit |
| `Operator` | Stable, package-qualified operation exposed through an API or CLI |
| `OperatorRevision` | Version-specific signature, behavior, inputs, outputs and effects |
| `ImplementationBinding` | Mapping from an operator revision to existing contracts, adapters, renderers and validators |
| `ReferenceArtifact` | Reference atlas, label mapping or pretrained model identity |
| `ReferenceArtifactRevision` | Specific version with digest, scope and provenance |

A fitted model created during analysis is a **runtime artifact**, not another canonical `Method`.

A named pretrained model distributed for reuse can be a `ReferenceArtifactRevision`.

### 4.3 Knowledge and governance records

The canonical record model MUST also support:

- `SourceWork`
- `SourceRevision`
- `EvidenceSpan`
- `AtomicClaimRevision`
- `EvidenceAssessment`
- `EntityResolutionDecision`
- `ConflictRecord`
- `ReviewDecision`
- `DerivationRecord`
- `KnowledgeChangeSet`
- `KnowledgeSnapshot`
- `EvidenceGap`

These records need not all appear as visible nodes in every graph view. They remain addressable, auditable records.

---

## 5. Package, Operator and Method are different identities

The normative relationship is:

```text
SoftwareProject
→ distributes Package
→ has PackageRelease
→ exports OperatorRevision
→ revision of Operator
→ implements Method / MethodVariant
```

An `ImplementationBinding` then connects the operator revision to the local executable contract.

### Example: Scanpy

| Layer | Identity |
|---|---|
| Package | Scanpy |
| Operators | `scanpy.pp.pca`, `scanpy.pp.neighbors`, `scanpy.tl.umap`, `scanpy.tl.leiden` |
| Scientific semantics | PCA, neighborhood graph construction, UMAP embedding, Leiden clustering |
| Local realization | Registered operator revision + StepContract/ToolContract + renderer/adapter |

This is **not**:

```text
Scanpy, PCA, neighbors, UMAP, Leiden = five equivalent tools
```

### Required identity rules

1. One package MAY expose many operators.
2. One method MAY have implementations in several packages.
3. One operator MAY implement several method variants under explicit parameter conditions.
4. One operator MAY internally compose multiple methods.
5. Wrappers MUST distinguish `DELEGATES_TO` from `IMPLEMENTS`.
6. Software dependency MUST NOT imply scientific prerequisite.
7. Different implementations of the same method MUST NOT be assumed numerically equivalent.
8. Parameter-name equality MUST NOT imply parameter equivalence.

“Tool” may remain a user-facing catalogue term, but new scientific claims MUST resolve it to the appropriate project, package, method or operator identity.

### Ambiguous names

- **scVI / scvi-tools:** model/method versus software package—not interchangeable aliases.
- **Monocle / Monocle3:** require explicit project, implementation-generation and release resolution.
- **UMAP:** may mean a method, a package implementation, an operator or an embedding artifact.
- **CellTypist:** may refer to the project, an annotation operation or a particular pretrained model.

Aliases MUST be typed and scoped. An ambiguous name returns candidate identities or requires clarification; it MUST NOT silently merge them.

---

## 6. Representation and applicability semantics

A file format or matrix slot is not a scientific representation.

For example:

- `AnnData` describes a container.
- `adata.X` describes a storage location.
- “log-normalized RNA expression” describes a scientific state.

These MUST remain distinct.

### 6.1 RepresentationType

A representation definition MUST express applicable dimensions from:

| Dimension | Required meaning |
|---|---|
| Observation unit | Cell, nucleus, spot, sample, donor or another explicit unit |
| Axes | Observations, genes, peaks, proteins, factors, edges, labels |
| Modality | RNA, chromatin accessibility, protein or a structured combination |
| Value semantics | Counts, transformed expression, probabilities, distances, loadings |
| Transformation state | Normalization, logarithm, scaling, residualization, correction |
| Feature identity | Namespace, genome/annotation version, ordering requirements |
| Alignment | Shared observations/features and required mapping |
| Missingness | Unobserved versus measured zero; permitted missing structure |
| Statistical context | Replicates, batches, groups and relevant covariates |
| Provenance requirements | Required producer, transformation and parameter information |
| Structural refinements | Shape, sparsity, directedness, symmetry, units where relevant |

Multimodal representations MUST express modality-specific axes and observation mappings. They MUST NOT assume that all modalities share identical features or complete measurements.

The RepresentationLedger remains responsible for checking these properties on actual artifacts.

### 6.2 Input and output ports

Operator revisions MUST define named input/output ports.

Each input port specifies:

- role;
- cardinality;
- accepted representation constraints;
- required reference artifacts or metadata;
- conditional applicability;
- alignment requirements.

Each output port specifies:

- produced representation;
- conditional availability;
- lineage;
- preservation or transformation of observation/feature identities;
- mutation and invalidation effects.

`CONSUMES` means information is used. It does **not** mean the source artifact is deleted.

### 6.3 Structured requirements

Requirements MUST support bounded declarative expressions:

- `all_of`
- `any_of`
- typed comparisons;
- presence checks;
- version constraints;
- explicit conditional branches.

Conditions MUST NOT contain arbitrary executable code.

Applicability has at least:

- `satisfied`
- `unsatisfied`
- `unknown`
- `conflicting`

Unknown mandatory requirements require profiling, clarification or blocking—not a ranking penalty.

### 6.4 Parameters

The model MUST distinguish:

1. API-valid value/range;
2. software default;
3. paper-reported setting;
4. tutorial example;
5. scientifically motivated recommendation;
6. user override;
7. locally selected or experimentally tuned value.

A paper that used 30 PCs does not establish a universal default of 30.

Each setting claim requires version, scope and provenance. Existing `ParameterProvenance` remains the runtime record of what was actually selected.

---

## 7. Relation vocabulary and semantics

Every relation MUST have registered endpoint types, direction, scope requirements and projection rules. Arbitrary new relation strings MUST NOT enter canonical data.

| Relation | Meaning and restrictions |
|---|---|
| `HAS_RELEASE` | Package → PackageRelease |
| `EXPORTS` | PackageRelease → OperatorRevision |
| `REVISION_OF` | Versioned record → stable identity |
| `IMPLEMENTS` | OperatorRevision → Method/MethodVariant, optionally conditional |
| `VARIANT_OF` | MethodVariant → Method |
| `DELEGATES_TO` | Wrapper operator → underlying operator |
| `DEPENDS_ON_PACKAGE` | Software dependency with version conditions |
| `SUPPORTS_TASK` | Method/operator can address a scoped scientific task |
| `HAS_INPUT` / `HAS_OUTPUT` | OperatorRevision → named port |
| `CONSUMES` / `PRODUCES` | Scoped projection through a port to representation semantics |
| `REQUIRES` | Subject → mandatory, conditional or optional Requirement |
| `HAS_PARAMETER` | OperatorRevision/MethodVariant → ParameterDefinition |
| `HAS_LIMITATION` | Subject → scoped Limitation |
| `USES_REFERENCE` | OperatorRevision → reference requirement/artifact |
| `PRESERVES` / `TRANSFORMS` / `INVALIDATES` | Explicit representation-property effects |
| `CAN_FEED` | A reviewed conditional output-to-input compatibility relation |
| `REQUIRES_BEFORE` | A justified ordering constraint within a defined scope |
| `ALTERNATIVE_FOR` | Methods are alternatives for a specific task/context—not universally |
| `COMPLEMENTS_FOR` | Methods have complementary roles in a defined composition |
| `INCOMPATIBLE_WITH` | Explicit incompatibility, with conditions and evidence |
| `BOUND_BY` | ImplementationBinding → existing contract revision |
| `SUPPORTED_BY` | A view over accepted evidence assessments |
| `SUPERSEDES` / `DEPRECATED_BY` | Lifecycle relationships, not automatic equivalence |

### 7.1 Prerequisites are not co-occurrence

The following inference is prohibited:

```text
A produces R
B consumes R
therefore A is mandatory before B
```

It may establish a candidate `CAN_FEED` relation only after checking:

- representation refinements;
- port roles;
- identity alignment;
- scope intersection;
- version compatibility;
- relevant constraints.

A mandatory prerequisite needs an explicit requirement or a reviewed derivation proving necessity within a defined scope.

If several producers can satisfy a requirement, the requirement is on the representation—not on one particular producer.

If the ledger already contains a valid representation, the producer may be skipped.

### 7.2 No generic compatibility shortcut

“Both accept AnnData” is insufficient.

Compatibility MUST identify what is compatible: format, representation semantics, features, observations, references, versions or software interfaces.

A “batch integration” label does not prove that an output is valid input to every downstream differential-expression method.

---

## 8. AtomicClaim and evidence model

### 8.1 Atomicity

An AtomicClaim is one independently assessable proposition.

A sentence saying a method accepts counts, produces labels and outperforms alternatives contains at least three claims with potentially different evidence and scopes.

The canonical claim is distinct from:

- source wording;
- extraction metadata;
- an online `ClaimRequest`;
- an answer’s `ClaimEvidenceBinding`.

### 8.2 Required AtomicClaimRevision fields

| Field | Normative meaning |
|---|---|
| `schema_version` | Record schema |
| `claim_id` | Stable claim-lineage identity |
| `claim_revision_id` | Immutable revision identity |
| `subject_id` | Resolved typed entity |
| `predicate` | Registered semantic predicate |
| `object` | Exactly one typed entity reference or structured literal |
| `qualifiers` | Port, conditions, applicability scope and relevant context |
| `claim_text` | Bounded normalized proposition preserving source meaning |
| `polarity` | Positive or negative |
| `assertion_kind` | Definition, capability, requirement, recommendation, empirical observation or limitation |
| `version_scope` | Explicit software/method/reference revisions or ranges |
| `version_scope_status` | Known, unknown or genuinely version-independent |
| `semantic_fingerprint` | Stable digest for proposition comparison and deduplication |
| `content_hash` | Digest of the immutable revision payload |
| `supersedes_revision_ids` | Explicit revision history |
| `created_by_activity_id` | Extraction or curation provenance |

**Conditionality belongs in qualifiers, not polarity.**

“Unknown version” and “all versions” MUST be distinct.

Dataset-specific claims MUST identify the applicable study/design context; a bare `dataset_specific` label is insufficient.

Review status MUST be derived from review records. It may be materialized in a snapshot but MUST NOT be its only audit evidence.

### 8.3 Evidence support is many-to-many

Required conceptual structure:

```text
SourceWork → SourceRevision → EvidenceSpan
EvidenceSpan → EvidenceAssessment → AtomicClaimRevision
AtomicClaimRevision → SUBJECT / OBJECT → typed entities
```

An EvidenceAssessment MUST record:

- claim revision;
- span reference or explicitly justified span group;
- stance: `supports`, `refutes`, `partial_support`, `mentions_only`, `not_supporting`;
- claim-local subject/predicate/object alignment;
- scope and version alignment;
- support rationale;
- review provenance.

Multiple evidence units may independently support one claim. A bounded group may jointly support a claim, but the logical combination and rationale MUST be explicit.

Adding corroborating evidence MUST NOT create a different scientific proposition merely because the new source has a different ID.

### 8.4 Source and span integrity

A `SourceRevision` MUST preserve:

- source identity and work grouping;
- source type and publisher/maintainer;
- DOI, repository commit, release or other stable locator where available;
- acquisition time;
- source revision/date;
- original-content digest;
- extraction method/version and extracted-text digest;
- licensing/access restrictions;
- retraction, correction or replacement status.

An EvidenceSpan MUST resolve into a specific source revision using exact offsets or a precise structured locator.

It MUST preserve the relevant context: table headers, figure captions, API signatures or surrounding qualifications when required for interpretation.

Claims and graph projections MUST reference the evidence store. They MUST NOT duplicate full source text.

### 8.5 Authority is claim-specific

- Versioned official API documentation is appropriate for API behavior.
- A methods paper supports scientific mechanism and explicitly scoped empirical claims.
- A benchmark supports observations under its evaluated conditions.
- An issue discussion can provide a candidate failure report, but not automatically a universal limitation.
- A project contract establishes a local restriction or implementation boundary—not a literature-backed scientific conclusion.

DOI presence, citation count, official branding and retrieval rank MUST NOT independently establish support.

Preprint/journal versions and copied documentation MUST be grouped to avoid inflating independent evidence counts.

---

## 9. Claim-linked graph projection

Every decision-bearing scientific edge MUST contain:

- typed endpoints;
- relation and applicable qualifiers;
- `derived_from_claim_ids`, resolving to immutable claim revisions;
- support-assessment references;
- derivation type;
- derivation rule/version, if inferred;
- canonical snapshot ID;
- provenance digest.

Two derivation classes are allowed:

1. **Direct projection:** a reviewed claim maps to a registered relation.
2. **Reviewed derivation:** a versioned rule combines accepted premises under validated conditions.

Derived edges MUST preserve a proof dependency graph. A materialized edge cannot be its own evidence or participate in circular justification.

Administrative edges such as revision membership require registry/change provenance. They need not fabricate a scientific claim.

### Multi-entity evidence

A benchmark paragraph mentioning Harmony and Scanorama MAY support separate claims about each.

The extraction must resolve each claim’s subject from the local proposition. It MUST NOT copy all document-level tool names to every claim.

Claim-level entity association MUST NOT implicitly mutate retrieval chunk membership or ranking.

---

## 10. Constructing the Scientific Action Space

The Agent’s action-space computation MUST use pinned inputs:

- resolved scientific intent;
- data/profile/ledger snapshot;
- knowledge snapshot;
- contract and capability-pack revisions;
- runtime assessment;
- current policy/approval context.

It proceeds through distinct questions:

| Question | Authority |
|---|---|
| Does this method address the task? | Reviewed scientific claims |
| Does it apply to these data and representations? | Requirements + ledger |
| Is there a concrete implementation? | Operator/implementation mapping |
| Is that implementation registered and validated? | Existing contracts and qualification records |
| Is the environment ready? | Runtime registry |
| Is this operation authorized now? | Policy/Approval |
| Which eligible option is preferable? | Scoped preferences and comparative evidence |

The resulting action candidate SHOULD expose:

- method and operator revision;
- task;
- input bindings or missing requirements;
- expected outputs;
- selected parameter provenance;
- limitations and alternatives;
- scientific applicability;
- planning feasibility;
- execution eligibility;
- explanatory claim/evidence references.

These are independent dimensions—not one `ready=true` flag.

A method can be scientifically appropriate, planning-ready and execution-disabled simultaneously.

### Answer grounding

Online answer bindings SHOULD reference canonical claim revisions when available, while retaining their exact evidence/provenance path.

- One answer may contain multiple claims.
- Every scientific citation must remain local to its supported claim.
- Project qualification statements remain separately labeled.
- Procedural prose must not impersonate literature evidence.
- Grounded audit remains an independent final check.

The KG does not replace online grounding, and online grounding does not automatically write canonical claims.

---

## 11. Knowledge lifecycle

### 11.1 Ingestion and extraction

The governed pipeline is:

```text
Source registration
→ immutable source revision
→ evidence segmentation
→ candidate claim extraction
→ entity/version resolution
→ support and contradiction assessment
→ human review
→ candidate projection
→ quality validation
→ approved change set
→ canonical snapshot
→ derived indexes/views
```

Each activity MUST record inputs, outputs, software/rule versions and content digests.

LLMs MAY propose extraction, entity candidates and normalization. Their outputs remain candidates.

Source text MUST be treated as untrusted content, not instructions for the Agent or ingestion process.

### 11.2 Entity and version resolution

Resolution MUST distinguish:

- exact identifier match;
- governed alias;
- renamed identity;
- software successor;
- method variant;
- unresolved ambiguity.

Entity merges and splits require reviewable crosswalks. Old IDs MUST continue to resolve historically.

A currently installed package version MUST NOT be assigned to a claim from an unversioned README or an older paper without supporting evidence.

Software version, source revision, claim revision, schema version and knowledge snapshot are separate version axes.

### 11.3 Contradiction handling

Potential contradictions are detected among claims with:

- equivalent subjects;
- comparable predicates;
- overlapping scopes and versions;
- mutually incompatible objects or polarity.

Different conditions or versions are not automatically contradictions.

Each ConflictRecord MUST retain:

- competing claims;
- overlap assessment;
- evidence on both sides;
- affected decisions;
- resolution or unresolved status.

Allowed outcomes include:

- scope separation;
- version separation;
- rejection of unsupported interpretation;
- supersession;
- unresolved conflict.

The system MUST NOT resolve scientific conflict by source count or arbitrary recency alone.

An unresolved critical conflict excludes the affected decision path from action eligibility. Unaffected knowledge remains usable.

### 11.4 Review and promotion

Review decisions MUST record reviewer identity, time, rationale and reviewed artifact hashes.

Execution-critical requirements, prohibitions, version mappings and derived prerequisites SHOULD receive independent review beyond the original extractor.

Promotion requires an explicit KnowledgeChangeSet containing:

- parent snapshot;
- additions/revisions/retirements;
- resolved dependencies;
- reviews;
- quality results;
- expected projection changes;
- rollback target.

Promotion publishes a new immutable snapshot. It MUST NOT edit historical claims in place.

### 11.5 Incremental additions and updates

Updates MUST operate on dependency sets:

```text
Changed source/API/entity mapping
→ affected spans and claims
→ affected semantic edges
→ affected method dossiers/templates
→ affected derived projections
```

An unchanged claim may retain support from an older pinned source revision. A new source revision does not silently replace its supporting bytes.

Reprocessing MUST be idempotent: identical inputs and extraction rules cannot create unresolved duplicate claims.

### 11.6 Supersession, deprecation and staleness

These states differ:

- **Superseded:** replaced by a newer accepted record.
- **Deprecated:** retained historically but discouraged for new use.
- **Retracted/invalid:** support withdrawn or record found incorrect.
- **Stale:** review freshness or dependency alignment is uncertain.
- **Rejected:** candidate not accepted.

Staleness MUST be triggered by meaningful events: API changes, source corrections, package deprecation, reference updates or review expiry.

A dated mathematical definition does not become false merely because time passed. A rolling API claim may need prompt revalidation.

Stale execution-critical knowledge MUST not silently authorize a new action. Discovery may retain it with a visible warning.

### 11.7 Rollback and auditability

Rollback publishes a manifest selecting the previous coherent snapshot and compatible projections. It MUST NOT rewrite history.

A snapshot MUST pin:

- schema and predicate-registry versions;
- entity and claim revisions;
- evidence/source revisions;
- review and derivation records;
- contract dependency digests;
- graph/index build fingerprints.

Queries MUST NOT silently combine a new graph with an old incompatible evidence index.

Knowledge rollback does not roll back user data or erase execution history.

---

## 12. Representative examples

These are model demonstrations, not newly accepted KG entries. Actual ingestion must pin source revisions and exact spans.

### 12.1 Scanpy HVG: parameter-conditioned inputs

The Scanpy HVG API documents logarithmized input for its usual dispersion-based routes, but count input for `seurat_v3`/`seurat_v3_paper`. Thus a global “HVG requires log-normalized expression” edge is inadequate. [Official HVG documentation](https://scanpy.readthedocs.io/en/latest/api/scanpy.pp.highly_variable_genes.html).

The model expresses:

| Claim subject | Condition | Requirement |
|---|---|---|
| Versioned HVG operator | Relevant dispersion-based flavor | Logarithmized expression |
| Same operator | `seurat_v3`-family flavor | Count representation |

The Agent selects the branch, binds a validated ledger representation and checks the local contract.

Neither `adata.X` nor a layer named `counts` proves that the required scientific state is present.

### 12.2 PCA → neighbors → UMAP / Leiden

A reviewed workflow may express:

```text
compatible expression → PCA coordinates → neighbor graph
                                           ├→ UMAP embedding
                                           └→ Leiden labels
```

It MUST NOT infer UMAP as a prerequisite for Leiden.

Nor is PCA universally required by every neighborhood construction call: Scanpy documents representation selection, including `.X` and `.obsm` inputs. This belongs to versioned operator semantics and conditional requirements. [Official neighbors documentation](https://scanpy.readthedocs.io/en/stable/api/generated/scanpy.pp.neighbors.html).

If a valid neighbor graph already exists, the ledger can satisfy downstream requirements without rebuilding upstream steps.

### 12.3 Integration: shared task, different outputs

A Harmony implementation and a Scanorama implementation may address integration while exposing different input/output operations.

The KG must identify:

- the precise method;
- the precise integration operator;
- whether its output is an embedding or expression representation;
- required covariates and feature alignment;
- downstream compatibility.

“Supports integration” cannot establish that a returned matrix is raw counts, that all outputs are interchangeable, or that any downstream statistical test is appropriate.

### 12.4 Annotation and doublet detection

For an annotation operator, expression requirements and reference requirements are separate ports.

A reference artifact needs its own species, feature vocabulary, label ontology, version and provenance. An unknown reference match cannot be repaired by citing another paper about the same package.

Similarly, a doublet-score operation and a cell-exclusion operation are distinct actions. Producing scores does not authorize deleting cells.

The scientific claim, local qualification and user approval each retain their own provenance.

### 12.5 scVI and MultiVI

`scvi-tools` is a package; scVI and MultiVI are distinct scientific model identities, with distinct operator bindings.

The official MultiVI tutorial covers joint analysis of paired RNA/ATAC measurements and single-modality observations. The KG therefore needs explicit modality presence and observation correspondence—not a single `multimodal=true` tag. [Official MultiVI tutorial](https://docs.scvi-tools.org/en/latest/tutorials/notebooks/multimodal/MultiVI_tutorial.html).

It must also distinguish:

- method;
- model-construction operator;
- training operation;
- fitted model artifact;
- latent-representation output;
- downstream analysis operator.

Training history belongs to runtime provenance, not the timeless method definition.

### 12.6 MOFA2: views, groups and missingness

MOFA documentation distinguishes views, groups, latent factors and feature weights; it also documents missing-value handling and warns that multi-group analysis is not simply a test of between-group mean differences. [Official MOFA FAQ](https://biofam.github.io/MOFA2/faq.html).

The model must represent separate claims about:

- accepted view structure;
- missing observations;
- latent-factor outputs;
- feature-weight outputs;
- group-related assumptions and limitations.

“Supports multi-omics” alone cannot establish suitability for a user’s differential-analysis question.

MOFA/MOFA2 software succession also demonstrates why project identity, package release and scientific method must remain separate.

---

## 13. Quality gates and measurement

Quality reports MUST distinguish:

- machine-checked structure;
- reviewed semantic support;
- coverage;
- runtime integration;
- not-run checks.

No unexecuted semantic check may be reported as zero failures.

| Gate | Required measurement |
|---|---|
| Schema validity | Valid records / records proposed for publication = 100% |
| Endpoint resolvability | Resolvable typed endpoints / referenced endpoints = 100% |
| Evidence integrity | Exact source revision, locator and hash resolve for every accepted support |
| Claim integrity | Immutable revision hashes validate = 100% |
| Provenance completeness | Every decision-bearing edge reaches reviewed premises and evidence |
| Evidence-backed edge rate | Edges with accepted direct support or valid reviewed derivation / decision-bearing edges |
| Entity consistency | Every referenced identity and applicable version resolves unambiguously |
| Alias ambiguity | No unresolved ambiguity on promoted decision paths |
| Duplicate resolution | No unresolved duplicate identity or proposition in the promoted set |
| Orphan validation | No accidental disconnected required dependency; catalogue-only records reported separately |
| Contradiction handling | No unresolved blocking contradiction in the active decision dependency closure |
| Projection fidelity | No strengthening, lost conditions or false `source_bound` promotion |
| Snapshot coherence | All declared source, graph, index and contract fingerprints agree |
| Review completeness | Every promoted decision-bearing record has an authorized review |
| Reproducibility | Same pinned inputs and rules reproduce the publication |
| Rollback readiness | Previous coherent snapshot remains addressable |

Empty denominators MUST be `not_applicable`, not invented 100% success.

Coverage must be reported separately as:

```text
Entity × task × predicate × scope/version
→ supported / gap / unresolved / not_applicable
```

A sparse, well-supported graph is preferable to a fully populated but fabricated matrix.

Promotion safety and product release readiness remain separate gates. Knowledge validation does not excuse failing application regression; missing runtime artifacts do not themselves establish that a scientific proposition is false.

---

## 14. Extraction and maintenance standard

Every future construction batch MUST provide:

1. **Construction scope:** target decisions, entities, predicates and version bounds.
2. **Source manifest:** authoritative provenance and pinned source revisions.
3. **Entity-resolution table:** identities, aliases and unresolved cases.
4. **Candidate claims:** normalized propositions with complete qualifications.
5. **Evidence assessments:** exact supporting/refuting spans and rationale.
6. **Candidate projections:** typed edges and derivation dependencies.
7. **Evidence-gap report:** explicit absences rather than fabricated completion.
8. **Conflict report:** overlap analysis and affected decision paths.
9. **Human review packet:** source-local wording and blank decisions until review.
10. **Machine quality report:** measured results, denominators and `not_run` states.
11. **Change impact report:** affected existing knowledge and application dependencies.
12. **Promotion/rollback manifest:** only after approval.

The unit of maintenance is an **auditable knowledge change set**, not “another list of tools.”

---

## 15. Adoption in the existing repository

The existing 48 claims remain candidate material. They MUST NOT be automatically rejected or accepted by this specification.

Before future promotion, they need mapping against:

- Method versus Operator versus Package subjects;
- explicit version and scope semantics;
- claim-local evidence support;
- direct versus derived relations;
- `CAN_FEED` versus mandatory prerequisite;
- real entity endpoint resolution;
- independently assessed semantic quality.

The recorded baseline issues—source-bound projection mismatch, fingerprint drift, missing/stale contract projections and ambiguous identities—must remain explicit migration blockers for affected dependencies. They must not be silently repaired during claim extraction.

The migration SHOULD reuse:

- canonical manifests and source/evidence storage;
- capability and contract registries;
- RepresentationLedger;
- current execution/validation/approval records;
- online ClaimEvidenceBinding;
- existing evaluation infrastructure.

It MUST NOT introduce a parallel planner, runtime registry, authorization system or independent knowledge truth source.

### Recommended next checkpoint

**Scientific Knowledge Schema Conformance + Legacy Crosswalk**

Its sole purpose would be to formalize this specification into versioned schemas and conformance examples, and map existing records without promotion.

It should prove that the model can express:

- Scanpy package/operator/method separation;
- conditional HVG requirements;
- optional producers and representation reuse;
- multi-source atomic support;
- scoped contradiction;
- multimodal alignment;
- source/API supersession;
- reproducible rollback.

Tool expansion and canonical promotion should follow only after this contract is approved.

---

## Final architectural position

The long-term model is:

> **Evidence-backed, scoped AtomicClaims describe scientific methods and versioned software operations. Their reviewed projections describe possible scientific transformations. The Agent combines those transformations with the actual RepresentationLedger and existing executable contracts to construct a governed, request-specific Scientific Action Space.**

This preserves four essential distinctions:

- **Knowledge is not current data state.**
- **Scientific applicability is not execution authorization.**
- **A source citation is not automatically claim support.**
- **A possible workflow connection is not automatically a prerequisite.**

Repository inspection and external documentation verification were read-only. No code, candidate claims, canonical graph, indexes or review decisions were changed; no tests, experiments, promotion or commit were performed.
