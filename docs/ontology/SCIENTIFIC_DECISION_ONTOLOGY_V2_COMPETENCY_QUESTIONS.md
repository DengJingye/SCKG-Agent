# Scientific Decision Ontology v2 Competency Questions

DESIGN_ONLY=true

Total: **77**

## Identity

| ID | Question | Coverage |
|---|---|---|
| CQ-A01 | Which OperatorRevision implements a given Method? | ANSWERABLE_CURRENT_V1 |
| CQ-A02 | Which PackageRelease binds a specific OperatorRevision? | ANSWERABLE_CURRENT_V1 |
| CQ-A03 | Which aliases identify a renamed software project without merging unrelated projects? | ANSWERABLE_V2_DESIGN |
| CQ-A04 | Is a software project a fork, replacement, or compatible continuation of another project? | ANSWERABLE_V2_DESIGN |
| CQ-A05 | How is an operator identity preserved when its API path moves between releases? | PARTIALLY_ANSWERABLE |
| CQ-A06 | Which stable identity is shared by records extracted from multiple SourceRevisions? | ANSWERABLE_CURRENT_V1 |
| CQ-A07 | Which genes or proteins are biologically true causal drivers of a disease? | NOT_IN_SCOPE |

## Method / implementation

| ID | Question | Coverage |
|---|---|---|
| CQ-B01 | Which project, package, operator, and revision form an implementation chain? | ANSWERABLE_CURRENT_V1 |
| CQ-B02 | Which MethodVariant does an OperatorRevision implement? | ANSWERABLE_CURRENT_V1 |
| CQ-B03 | Which parameter conditions select a MethodVariant? | ANSWERABLE_CURRENT_V1 |
| CQ-B04 | Is an OperatorRevision deprecated, and what replaces it? | ANSWERABLE_V2_DESIGN |
| CQ-B05 | Which API path and release expose an executable operator? | ANSWERABLE_V2_DESIGN |
| CQ-B06 | Is a statement about a Method or about one implementation revision? | PARTIALLY_ANSWERABLE |
| CQ-B07 | Which implementation revisions are equivalent only under a declared scope? | ANSWERABLE_V2_DESIGN |

## Representation / transformation

| ID | Question | Coverage |
|---|---|---|
| CQ-C01 | What RepresentationType does an OperatorRevision consume? | ANSWERABLE_CURRENT_V1 |
| CQ-C02 | What RepresentationType does an OperatorRevision produce? | ANSWERABLE_CURRENT_V1 |
| CQ-C03 | Which input lineage is a produced representation derived from? | ANSWERABLE_CURRENT_V1 |
| CQ-C04 | Which transformations preserve observation and feature identity? | ANSWERABLE_V2_DESIGN |
| CQ-C05 | Which transformation invalidates an existing neighbor graph? | ANSWERABLE_V2_DESIGN |
| CQ-C06 | When is a representation stale because its upstream lineage changed? | PARTIALLY_ANSWERABLE |
| CQ-C07 | Which parameter conditions change an output representation's validity? | ANSWERABLE_V2_DESIGN |

## Applicability

| ID | Question | Coverage |
|---|---|---|
| CQ-D01 | Is raw UMI required, optional, or recommended for an operator revision? | ANSWERABLE_CURRENT_V1 |
| CQ-D02 | Which metadata fields are mandatory for a method? | ANSWERABLE_V2_DESIGN |
| CQ-D03 | Which reference artifact revision is required? | ANSWERABLE_V2_DESIGN |
| CQ-D04 | Under which organism, assay, observation unit, and study design is a statement valid? | ANSWERABLE_V2_DESIGN |
| CQ-D05 | What is incompatible with or contraindicated for a method? | ANSWERABLE_V2_DESIGN |
| CQ-D06 | Was a capability merely evaluated under a scope or validated for that scope? | PARTIALLY_ANSWERABLE |
| CQ-D07 | Which clinical diagnosis should be assigned to an individual patient? | NOT_IN_SCOPE |

## Scientific claims

| ID | Question | Coverage |
|---|---|---|
| CQ-E01 | What is the atomic subject-predicate-object assertion? | ANSWERABLE_CURRENT_V1 |
| CQ-E02 | Which qualifiers are required for the assertion to remain true? | ANSWERABLE_V2_DESIGN |
| CQ-E03 | Does a sentence contain multiple propositions that require separate statements? | ANSWERABLE_V2_DESIGN |
| CQ-E04 | Is a limitation a named reusable object or a statement kind? | ANSWERABLE_V2_DESIGN |
| CQ-E05 | Which statement contradicts an existing statement under the same scope? | ANSWERABLE_V2_DESIGN |
| CQ-E06 | Which graph edge is a projection rather than the authoritative statement? | PARTIALLY_ANSWERABLE |
| CQ-E07 | Which statement revision supersedes an earlier revision? | ANSWERABLE_V2_DESIGN |

## Evidence

| ID | Question | Coverage |
|---|---|---|
| CQ-F01 | Which exact EvidenceSpan directly supports a statement revision? | ANSWERABLE_CURRENT_V1 |
| CQ-F02 | Which SourceRevision contains an EvidenceSpan? | ANSWERABLE_CURRENT_V1 |
| CQ-F03 | Is support direct, partial, contextual, contradictory, refuting, absent, or uncertain? | ANSWERABLE_V2_DESIGN |
| CQ-F04 | Does evidence align with the statement subject, predicate, object, and scope? | ANSWERABLE_V2_DESIGN |
| CQ-F05 | Is an EvidenceSpan boundary contaminated by a heading, example, or next section? | ANSWERABLE_V2_DESIGN |
| CQ-F06 | Does a source merely exist, or has its evidence been assessed as supporting? | PARTIALLY_ANSWERABLE |
| CQ-F07 | Which EvidenceGap blocks review or execution eligibility? | ANSWERABLE_V2_DESIGN |

## Version / provenance / temporal

| ID | Question | Coverage |
|---|---|---|
| CQ-G01 | Which SourceWork and SourceRevision generated an EvidenceSpan? | ANSWERABLE_CURRENT_V1 |
| CQ-G02 | Which ExtractionRun generated a candidate statement? | ANSWERABLE_V2_DESIGN |
| CQ-G03 | Which agent and activity are responsible for a ReviewDecision? | ANSWERABLE_V2_DESIGN |
| CQ-G04 | What entity was used by an extraction or review activity? | ANSWERABLE_V2_DESIGN |
| CQ-G05 | Which artifact was derived from another artifact? | ANSWERABLE_V2_DESIGN |
| CQ-G06 | Which ontology and schema versions governed a record? | PARTIALLY_ANSWERABLE |
| CQ-G07 | During what interval was a scoped statement valid? | ANSWERABLE_V2_DESIGN |

## Knowledge evolution

| ID | Question | Coverage |
|---|---|---|
| CQ-H01 | Did a new SourceRevision leave evidence unchanged? | ANSWERABLE_V2_DESIGN |
| CQ-H02 | Did evidence move while remaining semantically unchanged? | ANSWERABLE_V2_DESIGN |
| CQ-H03 | Did evidence text change enough to require revalidation? | ANSWERABLE_V2_DESIGN |
| CQ-H04 | Did a statement's applicability scope change? | ANSWERABLE_V2_DESIGN |
| CQ-H05 | Has evidence become stale, unsupported, or contradictory? | ANSWERABLE_V2_DESIGN |
| CQ-H06 | Which claim or evidence revision was superseded? | PARTIALLY_ANSWERABLE |
| CQ-H07 | Which ontology migration is required after a class, predicate, cardinality, or constraint change? | ANSWERABLE_V2_DESIGN |

## Planning / actions

| ID | Question | Coverage |
|---|---|---|
| CQ-I01 | May an existing RepresentationRecord be reused? | ANSWERABLE_CURRENT_V1 |
| CQ-I02 | Must a representation be recomputed after lineage change? | ANSWERABLE_V2_DESIGN |
| CQ-I03 | Which action invalidates a representation? | ANSWERABLE_V2_DESIGN |
| CQ-I04 | When must execution be blocked? | ANSWERABLE_V2_DESIGN |
| CQ-I05 | Which action may create a CandidateStatement or EvidenceGap? | ANSWERABLE_V2_DESIGN |
| CQ-I06 | Which action requires human approval and what permission is required? | PARTIALLY_ANSWERABLE |
| CQ-I07 | What side effects, outputs, trace stage, and rollback apply to an action? | ANSWERABLE_V2_DESIGN |

## Governance

| ID | Question | Coverage |
|---|---|---|
| CQ-J01 | Is knowledge candidate, reviewed, trusted, superseded, or rejected? | ANSWERABLE_CURRENT_V1 |
| CQ-J02 | Who may review a high-risk candidate? | ANSWERABLE_CURRENT_V1 |
| CQ-J03 | Does a ReviewDecision apply to the exact artifact hashes shown to the reviewer? | ANSWERABLE_V2_DESIGN |
| CQ-J04 | May a candidate be promoted without supporting evidence and required approval? | ANSWERABLE_V2_DESIGN |
| CQ-J05 | Which identity merge or supersession decisions remain reversible? | ANSWERABLE_V2_DESIGN |
| CQ-J06 | Are runtime state, scientific knowledge, and governed action represented separately? | PARTIALLY_ANSWERABLE |
| CQ-J07 | Which schema changes require a migration plan before release? | ANSWERABLE_V2_DESIGN |

## Evaluation

| ID | Question | Coverage |
|---|---|---|
| CQ-K01 | What fraction of competency questions is answerable by current v1? | ANSWERABLE_CURRENT_V1 |
| CQ-K02 | What class and predicate documentation coverage has been achieved? | ANSWERABLE_CURRENT_V1 |
| CQ-K03 | Which predicates lack domain, range, inverse, or evidence requirements? | ANSWERABLE_V2_DESIGN |
| CQ-K04 | How many duplicate or ambiguous semantic concepts remain? | ANSWERABLE_V2_DESIGN |
| CQ-K05 | Do constraint shapes detect invalid endpoint and cardinality bindings? | ANSWERABLE_V2_DESIGN |
| CQ-K06 | Which external vocabulary mappings are exact, close, broader, narrower, or absent? | PARTIALLY_ANSWERABLE |
| CQ-K07 | Does a newer ontology release preserve migration coverage for deprecated concepts? | ANSWERABLE_V2_DESIGN |

Every question's required classes, predicates, qualifiers, and constraints are recorded in `competency_question_coverage.json`.
