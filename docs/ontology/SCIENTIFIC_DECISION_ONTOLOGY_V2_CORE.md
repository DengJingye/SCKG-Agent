# Scientific Decision Ontology v2 Core — 5C

Checkpoint: `5C.1-Targeted-Core-Corrections` (N01–N05 only)  
Version: `2.0.0-core-review.1`  
Mode: DESIGN / SCHEMA REFINEMENT ONLY  
Human review: PENDING — `STOP_FOR_QA_RECHECK`

This freezes a **reviewable design proposal**, not an approved production schema.
The controlling specification is the user's targeted 5C.1 correction request;
5C boundaries remain in effect. Only N01–N05 are changed. The historical `scientific_decision_ontology_v2` directory is
preserved byte-for-byte as `DESIGN_AUDIT / NEEDS_REVISION`, including its historical
PASS labels and uncommitted provenance. Those labels do not authorize this core.

## Bounded domain

Evidence-governed single-cell and multi-omics analysis decisions: scientific
objectives, methods, software implementations, representation semantics, input
requirements, assertions, applicability, sources, evidence and version conditions.

Universal biological truth, comprehensive disease/cell ontologies, general
chemistry, diagnosis, complete benchmarking/action ontologies and the migration
framework are out of scope. Biological identifiers may reference external
vocabularies; none are imported wholesale. Chat remains a first-class product
capability; this backend semantic design does not replace Chat.

## Entity-first organization

Admission followed: bounded scope → independently referenced objects and their
lifecycles → modules → scalar/embedded properties → qualifiers → minimal links →
constraints → CQ validation. CQ coverage does not automatically mint concepts.

There are **25 scientific core objects and one external runtime bridge type**.
The 26 types are organized in four scientific modules and one runtime bridge.
Modules are organizational namespaces, not subclass axioms. No generic interface
expands endpoint permissions. `MethodVariant` specializes `Method` through a typed
link. The source registry documents admission, ownership, lifecycle and ID rules
for each object; see [Modules](SCIENTIFIC_DECISION_ONTOLOGY_V2_MODULES.md).

The 23 authoritative link types and two derived projections each define concrete
domain/range, allowed endpoint pairs, direction, cardinality, evidence policy,
qualifier policy and justification. Authoritative means the source of a structural
binding or semantic assertion, **not trusted evidence or execution permission**.

A scientific assertion concerns the actual entity. For example, the domain of
`applicable_to` is Method/MethodVariant/OperatorRevision. `ScientificStatement`
provides an assertion identity, never a surrogate Method endpoint.

## Properties, values and record references

74 properties describe values owned by specific types. API paths, release dates,
deprecation, text hashes, page/section/offsets are scalar fields, not graph nodes.
Numeric constraints, component descriptions, typed literals and version/parameter
conditions are embedded value shapes. Numeric bounds carry a comparator, datatype
and optional unit; evidence must establish a bound. No biological or numerical
threshold is supplied by this design.

Typed record-reference fields and link types are distinguished from scalar
properties. `StatementRevision.statement_id` serializes its `revision_of` binding;
it does not establish a second identity source. Statement subject/object fields
refer to scientific entities and are further restricted by the chosen predicate.
Opaque external assessor/activity references do not imply an imported Agent or
Activity object type. No core endpoint refers to an undefined interface.

## Authoritative statement

`ScientificStatement` is a stable identifier plus schema/ontology version.
`StatementRevision` is an immutable independently judgeable assertion:

- revision ID and stable statement ID;
- typed subject and registered predicate;
- exactly one entity object or typed literal;
- POSITIVE/NEGATIVE polarity;
- qualifiers, explicit context status, optional shared scope reference;
- assertion kind and epistemic status; schema/ontology versions.

Scientific link predicates are explicitly marked `statement_predicate_allowed`.
Structural evidence links and derived projections cannot be used as scientific
predicates. `is_sparse` remains the bounded scalar assertion surface with its
owner/datatype and qualifier policy. `effect_description` is descriptive/display
metadata only (`assertion_allowed=false`, `decision_gate_allowed=false`). It must
not drive a Planner gate, blocking, applicability, capability authorization,
derived scientific truth or trusted statement projection. A decision-bearing
effect needs a registered StatementRevision plus EvidenceAssessment; if the core
cannot express it, defer it rather than repurpose display text. Necessary evidence
structure is not sufficient authorization. No general Effect ontology is added.

A change to subject, predicate, object, polarity, qualifiers or shared immutable
scope requires a new revision. A new independently judgeable proposition requires
its own statement identity. Repeated text does not create independent support.
`AtomicClaimRevision` is a conceptual compatible view only; no adapter or migration
is implemented. Literal datatypes must be reviewed, never guessed from v1 strings.

Atomicity: split “data are sparse; clustering is recommended; clustering permits
information sharing” into three propositions, preserving each condition. These
are **illustrative text, not scientific records or reviewed assertions**. Automatic
atomicity detection belongs to later extraction work.

NEGATIVE denies the same qualified proposition. Absence of evidence is not a
negative claim; not REQUIRED does not imply incompatible or DISCOURAGED.

## Requirements and context

`Requirement.strength`: REQUIRED, RECOMMENDED, OPTIONAL, DISCOURAGED.
Strength is independent of optional `when` (a conjunction of typed parameter
conditions). `activation_status=specified` requires nonempty `when`;
`unconditional` explicitly has no additional activation condition; `unknown`
means the condition was not established. Empty/absent `when` is never implicitly
universal. Specified conditions do not change strength: recommended/discouraged
and optional advice can each be conditional. Conditional OPTIONAL means permitted
use within that activation condition; it does not become required.

Requirements can target RepresentationConstraint through `requires_constraint`
and/or ReferenceArtifactRevision through the restored `requires_reference` link.
At least one target is required across both relations; neither relation alone is
mandatory. ALL_OF means every target must be met; ANY_OF means one target suffices,
including explicitly selected mixed target alternatives. Reference-only targets
do not imply an input matrix. ReferenceArtifact is stable identity, while its
revision is immutable, version-pinned and content-hashed. Same-family `revision_of`
is required. No downloader, cache manager or resource lifecycle system is added.
No relation verb establishes strength. Port cardinality remains separate.

Simple qualifiers are inline. Allocate an immutable `ApplicabilityScope` only for
reuse or independent governance/version identity. `scope_ref` is optional.
Inline and shared values for the same dimension must agree; conflict rejects,
never silently widens context. Predicate-specific allowed dimensions apply also
to referenced scopes. Unknown is not universal or automatically incompatible.
Shared scope explicitly requires ID, scope_status, combination and qualifiers.
Canonical scope statuses remain lowercase: explicit, partially_known, unknown,
not_applicable. UNKNOWN semantics (serialized `unknown`) forbid known qualifiers;
partially_known requires a nonempty disjoint unknown_dimensions list. Shared
ALL_OF/ANY_OF groups retain their operator. Inline-only dimensions are conjoined
outside that group; equal shared/inline members deduplicate without turning an
ANY_OF member into a new AND requirement. Conflicts reject, including in ANY_OF.
Scope payload changes require a new ID. Full temporal lineage remains DEFERRED.

Qualifier names and values are validated: controlled terms/enums, typed parameter
values with exact units, revision-specific parameter ownership, and version
subject families. The design helper uses a bounded explicit version-pin grammar;
unsupported version formats require review instead of coercion. The helper
remains tests-only and does not alter production validation.

## Minimal evidence

EvidenceSpan contains only stable identity, SourceRevision and SourceArtifact
references, exact text and SHA-256, locator and schema version. Page/section,
paired offsets and external acquisition provenance are optional. HTML/code
excerpts need no fabricated PDF page. Exact-text digest and artifact-byte digest
are different; the referenced artifact owns the latter. Offsets use a declared
immutable Unicode text stream with zero-based start/exclusive end.

Support classification, review, trust, candidate status, retrieval eligibility,
authority and normalized propositions are externalized to their proper owners.
See the explicit core/removed field lists in `evidence_model.json`.

EvidenceAssessment reifies one exact span evaluated against one exact statement
revision, with support type, method, assessor/activity reference, timestamp,
status, alignment and optional confidence. Multiple assessments preserve multiple
sources and simultaneous support/conflict. DIRECT_SUPPORT and REFUTES require
aligned subject, predicate, object and scope. A completed assessment is not a
human review or promotion. The seven support values remain distinct.

SourceWork groups editions/mirrors so duplication is not counted as independent
support. Different works are also not automatically independent; dependency
unknown stays unknown. Source existence, excerpt existence, support, review and
trust are five distinct gates. A new edition does not retroactively invalidate
all earlier version-specific evidence.

## Representation and derived views

RepresentationType describes abstract axes, namespace, observation unit and value
semantics. Concrete row/column identities, paths, matrices, realized lineage,
freshness and validation remain in RepresentationLedger. The external
RepresentationRecord bridge references a RepresentationType; its existing runtime
schema gains no required fields in 5C.

`consumes` derives through input port → requirement → constraint → type;
`produces` derives through output port → type. Views retain source record IDs,
hashes, conditions, alternatives and strength. They do not become authoritative
scientific statements. CAN_FEED is deferred and nontransitive: matching type
names do not establish compatibility or a prerequisite. REQUIRES_BEFORE is not
admitted from tutorial order, package dependencies or workflow frequency.

Most transformation verbs are represented by implemented Method/MethodVariant,
typed ports and display descriptions. A decision-bearing assertion that filtering
invalidates a neighbor structure under X needs a typed StatementRevision and
EvidenceAssessment; the display description cannot supply this assertion.
“Run 123 invalidated record abc” remains runtime Ledger/Trace state.

## Freeze boundary

No production ontology/KG/schema, Chat, retrieval, planner, ledger, ToolContract,
Capability Pack, extractor, staging or gold is changed. No ReviewDecision,
trusted record, promotion, PDF rerun, external LLM call, migration or 5D occurs.
Validation and recorded limitations are in the [5C review](SCIENTIFIC_DECISION_ONTOLOGY_V2_5C_REVIEW.md).
