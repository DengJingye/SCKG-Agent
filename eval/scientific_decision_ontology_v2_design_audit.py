"""Generate the design-only Scientific Decision Ontology v2 audit artifacts."""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = ROOT / "data/evidence_candidates/scientific_kg_v1_inventory/scientific_kg_v1_consolidated_graph.json"
OUTPUT = ROOT / "data/ontology/scientific_decision_ontology_v2"
DESIGN_DOC = ROOT / "docs/ontology/SCIENTIFIC_DECISION_ONTOLOGY_V2_DESIGN.md"
CQ_DOC = ROOT / "docs/ontology/SCIENTIFIC_DECISION_ONTOLOGY_V2_COMPETENCY_QUESTIONS.md"
SCHEMA_VERSION = "sckg-scientific-decision-ontology-v2-design-audit-v1"
ONTOLOGY_VERSION = "2.0.0-design.1"
CHECKPOINT_5A_COMMIT = "c8cef942f214efb2844cd3e5bf1aa0c28a4a50ab"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        candidates = [path] if path.is_file() else list(path.rglob("*")) if path.is_dir() else []
        for candidate in candidates:
            if not candidate.is_file() or "__pycache__" in candidate.parts:
                continue
            relative = str(candidate.relative_to(ROOT)).casefold()
            if "sealed" in relative or "quarantine" in relative or "/c7" in relative:
                continue
            files.append(candidate)
    return sorted(set(files))


def _tree(paths: Iterable[Path]) -> dict[str, Any]:
    files = {str(path.relative_to(ROOT)): _sha(path) for path in _safe_files(paths)}
    digest = hashlib.sha256("".join(f"{name}\0{value}\n" for name, value in files.items()).encode()).hexdigest()
    return {"file_count": len(files), "tree_sha256": digest, "files": files}


def protected_identity() -> dict[str, Any]:
    evidence = ROOT / "data/evidence_candidates"
    index = ROOT / "data/indexes/retrieval_foundation_v1"
    return {
        "production_ontology": _tree([
            ROOT / "core/scientific_knowledge_conformance_models.py",
            evidence / "scientific_knowledge_schema_v1_1",
        ]),
        "scientific_kg": _tree([
            evidence / "scientific_kg_v1_inventory",
            evidence / "scientific_kg_v1_uat_decision_rules",
            evidence / "scientific_kg_v1_core",
            evidence / "scientific_kg_content_expansion_v1",
            evidence / "scientific_knowledge_scanpy_core_v1_1",
        ]),
        "rag": _tree([index]),
        "planner": _tree([ROOT / "engine/capability_planner.py", ROOT / "engine/execution_planner.py"]),
        "studio_extractor": _tree([ROOT / "engine/scientific_knowledge_studio.py"]),
    }


PROPERTY_SPECS = [
    ("id", "PROPERTY", "Stable identifier for an ontology or governed record."),
    ("label", "PROPERTY", "Human-readable label."),
    ("definition", "PROPERTY", "Operational textual definition."),
    ("schema_version", "PROPERTY", "Shape or record schema version."),
    ("ontology_version", "PROPERTY", "Ontology release that governs the concept."),
    ("introduced_in", "PROPERTY", "Ontology version that introduced the concept."),
    ("deprecated_in", "PROPERTY", "Ontology version that deprecated the concept."),
    ("replaced_by", "RELATION", "Replacement concept when a governed concept is deprecated."),
    ("version", "PROPERTY", "Version string of a versioned resource."),
    ("qualified_name", "PROPERTY", "Stable package-qualified executable name."),
    ("api_path", "PROPERTY", "Version-specific API location; never an identity by itself."),
    ("immutable_release_ref", "PROPERTY", "Immutable digest or commit for a release."),
    ("release_date", "PROPERTY", "Declared publication date of a release."),
    ("deprecated", "PROPERTY", "Boolean deprecation marker."),
    ("page_number", "PROPERTY", "One-based source page locator."),
    ("section_path", "PROPERTY", "Hierarchical source section locator."),
    ("exact_text", "PROPERTY", "Exact bounded source text."),
    ("text_hash", "PROPERTY", "Digest of normalized or exact text as declared."),
    ("source_revision_id", "RELATION", "Source revision containing an evidence span."),
    ("review_status", "PROPERTY", "Governance review state, separate from evidential support."),
    ("epistemic_status", "PROPERTY", "Epistemic state of a statement revision."),
    ("evidence_support_status", "PROPERTY", "Operational support state assigned by an assessment."),
    ("knowledge_status", "PROPERTY", "Candidate, reviewed, trusted, superseded, or rejected status."),
    ("content_hash", "PROPERTY", "Digest of canonical record content."),
    ("subject", "RELATION", "Subject of a scientific statement."),
    ("predicate", "PROPERTY", "Registered predicate used by a statement."),
    ("object", "RELATION", "Object entity or typed literal of a statement."),
    ("qualifiers", "QUALIFIER", "Context that narrows a statement without changing its core triple."),
    ("scope_id", "RELATION", "Applicability scope governing a statement or capability."),
    ("version_conditions", "QUALIFIER", "Resource-version conditions under which a statement holds."),
    ("evidence_assessment_ids", "RELATION", "Evidence assessments attached to a statement revision."),
    ("provenance_activity_id", "RELATION", "Activity that generated or changed a record."),
    ("modality", "QUALIFIER", "Assay modality context."),
    ("organism_taxon", "QUALIFIER", "Organism taxon context."),
    ("assay", "QUALIFIER", "Assay technology context."),
    ("observation_unit", "QUALIFIER", "Cell, sample, donor, spot, or other observation unit."),
    ("study_design", "QUALIFIER", "Study-design context."),
    ("dataset_class", "QUALIFIER", "Dataset class or cohort context."),
    ("representation_state", "QUALIFIER", "Transformation and freshness state."),
    ("software_version", "QUALIFIER", "Software release context."),
    ("method_version", "QUALIFIER", "Scientific method revision context."),
    ("flavor", "QUALIFIER", "Named method or operator flavor."),
    ("parameter_condition", "QUALIFIER", "Condition on a parameter value."),
    ("evaluation_metric", "QUALIFIER", "Metric used in an empirical statement."),
    ("evaluation_context", "QUALIFIER", "Benchmark or evaluation protocol context."),
    ("requires_gpu", "PROPERTY", "Resource requirement attached to an executable capability."),
    ("lineage_id", "RUNTIME_STATE", "Runtime data-lineage identity."),
    ("feature_identity", "RUNTIME_STATE", "Ordered or mapped feature identity."),
    ("observation_identity", "RUNTIME_STATE", "Ordered or mapped observation identity."),
    ("freshness_status", "RUNTIME_STATE", "Current runtime freshness or staleness state."),
    ("permission", "PROPERTY", "Role or capability needed to invoke an action."),
    ("approval_required", "PROPERTY", "Whether explicit approval is required."),
    ("reversible", "PROPERTY", "Whether the action has a defined rollback."),
    ("preconditions", "PROPERTY", "Typed preconditions for a governed action."),
    ("side_effects", "PROPERTY", "Declared state mutations caused by an action."),
    ("outputs", "PROPERTY", "Typed action outputs."),
    ("trace_stage", "PROPERTY", "Trace stage that records an action."),
]


QUALIFIER_SPECS = [
    ("modality", "Assay modality in which the statement holds", "ApplicabilityScope"),
    ("organism_taxon", "Organism taxon in which the statement holds", "ApplicabilityScope"),
    ("assay", "Assay technology context", "ApplicabilityScope"),
    ("observation_unit", "Unit represented by observations", "ApplicabilityScope"),
    ("study_design", "Study design needed for validity", "ApplicabilityScope"),
    ("dataset_class", "Dataset or cohort class", "ApplicabilityScope"),
    ("representation_state", "Input transformation and freshness context", "ApplicabilityScope"),
    ("software_version", "Software release condition", "VersionConstraint"),
    ("method_version", "Scientific method revision condition", "VersionConstraint"),
    ("flavor", "Named method/operator flavor", "StatementRevision"),
    ("parameter_condition", "Parameter-dependent condition", "StatementRevision"),
    ("evaluation_metric", "Metric for an empirical result", "EvaluationContext"),
    ("evaluation_context", "Benchmark protocol and dataset context", "EvaluationContext"),
    ("modality_strength", "Mandatory, conditional, optional, or recommended modality", "StatementRevision"),
]


INTERFACE_SPECS = {
    "VersionedResource": (["id", "version", "schema_version"], ["immutable_release_ref", "release_date"], ["PackageRelease", "OperatorRevision", "SourceRevision", "ReferenceArtifactRevision", "StatementRevision"]),
    "EvidenceBearingStatement": (["id", "subject", "predicate", "object", "scope_id", "evidence_assessment_ids"], ["qualifiers", "version_conditions"], ["StatementRevision", "AtomicClaimRevision"]),
    "ExecutableCapability": (["id", "preconditions", "outputs"], ["requires_gpu", "version_conditions"], ["OperatorRevision"]),
    "ReviewableKnowledge": (["id", "review_status", "knowledge_status"], ["epistemic_status"], ["StatementRevision", "EvidenceAssessment", "IdentityAssertion"]),
    "ProvenanceTrackedArtifact": (["id", "content_hash", "provenance_activity_id"], ["source_revision_id"], ["SourceArtifact", "EvidenceSpan", "StatementRevision", "RepresentationRecord"]),
    "DataRepresentation": (["id", "feature_identity", "observation_identity"], ["representation_state", "lineage_id"], ["RepresentationType", "RepresentationRecord"]),
    "ScientificSource": (["id", "schema_version"], ["version", "content_hash"], ["SourceWork", "SourceRevision", "SourceArtifact"]),
}


SHAPE_SPECS = {
    "OperatorRevisionShape": ("OperatorRevision", ["id", "version", "scope_id"], ["implements_method", "requires_input", "produces"]),
    "ScientificStatementShape": ("StatementRevision", ["id", "subject", "predicate", "object", "scope_id", "schema_version", "ontology_version"], ["supports"]),
    "EvidenceSpanShape": ("EvidenceSpan", ["id", "source_revision_id", "page_number", "exact_text", "text_hash"], []),
    "SourceRevisionShape": ("SourceRevision", ["id", "version", "content_hash"], ["revision_of"]),
    "RepresentationTypeShape": ("RepresentationType", ["id", "label", "feature_identity", "observation_identity"], []),
    "ReviewDecisionShape": ("ReviewDecision", ["id", "review_status", "provenance_activity_id"], []),
    "EvidenceAssessmentShape": ("EvidenceAssessment", ["id", "evidence_support_status", "review_status"], ["supports"]),
    "GovernedActionShape": ("GovernedAction", ["id", "preconditions", "permission", "approval_required", "side_effects", "outputs", "trace_stage", "reversible"], []),
}


GROUPS = {
    "A": ("Identity", [
        "Which OperatorRevision implements a given Method?",
        "Which PackageRelease binds a specific OperatorRevision?",
        "Which aliases identify a renamed software project without merging unrelated projects?",
        "Is a software project a fork, replacement, or compatible continuation of another project?",
        "How is an operator identity preserved when its API path moves between releases?",
        "Which stable identity is shared by records extracted from multiple SourceRevisions?",
        "Which genes or proteins are biologically true causal drivers of a disease?",
    ]),
    "B": ("Method / implementation", [
        "Which project, package, operator, and revision form an implementation chain?",
        "Which MethodVariant does an OperatorRevision implement?",
        "Which parameter conditions select a MethodVariant?",
        "Is an OperatorRevision deprecated, and what replaces it?",
        "Which API path and release expose an executable operator?",
        "Is a statement about a Method or about one implementation revision?",
        "Which implementation revisions are equivalent only under a declared scope?",
    ]),
    "C": ("Representation / transformation", [
        "What RepresentationType does an OperatorRevision consume?",
        "What RepresentationType does an OperatorRevision produce?",
        "Which input lineage is a produced representation derived from?",
        "Which transformations preserve observation and feature identity?",
        "Which transformation invalidates an existing neighbor graph?",
        "When is a representation stale because its upstream lineage changed?",
        "Which parameter conditions change an output representation's validity?",
    ]),
    "D": ("Applicability", [
        "Is raw UMI required, optional, or recommended for an operator revision?",
        "Which metadata fields are mandatory for a method?",
        "Which reference artifact revision is required?",
        "Under which organism, assay, observation unit, and study design is a statement valid?",
        "What is incompatible with or contraindicated for a method?",
        "Was a capability merely evaluated under a scope or validated for that scope?",
        "Which clinical diagnosis should be assigned to an individual patient?",
    ]),
    "E": ("Scientific claims", [
        "What is the atomic subject-predicate-object assertion?",
        "Which qualifiers are required for the assertion to remain true?",
        "Does a sentence contain multiple propositions that require separate statements?",
        "Is a limitation a named reusable object or a statement kind?",
        "Which statement contradicts an existing statement under the same scope?",
        "Which graph edge is a projection rather than the authoritative statement?",
        "Which statement revision supersedes an earlier revision?",
    ]),
    "F": ("Evidence", [
        "Which exact EvidenceSpan directly supports a statement revision?",
        "Which SourceRevision contains an EvidenceSpan?",
        "Is support direct, partial, contextual, contradictory, refuting, absent, or uncertain?",
        "Does evidence align with the statement subject, predicate, object, and scope?",
        "Is an EvidenceSpan boundary contaminated by a heading, example, or next section?",
        "Does a source merely exist, or has its evidence been assessed as supporting?",
        "Which EvidenceGap blocks review or execution eligibility?",
    ]),
    "G": ("Version / provenance / temporal", [
        "Which SourceWork and SourceRevision generated an EvidenceSpan?",
        "Which ExtractionRun generated a candidate statement?",
        "Which agent and activity are responsible for a ReviewDecision?",
        "What entity was used by an extraction or review activity?",
        "Which artifact was derived from another artifact?",
        "Which ontology and schema versions governed a record?",
        "During what interval was a scoped statement valid?",
    ]),
    "H": ("Knowledge evolution", [
        "Did a new SourceRevision leave evidence unchanged?",
        "Did evidence move while remaining semantically unchanged?",
        "Did evidence text change enough to require revalidation?",
        "Did a statement's applicability scope change?",
        "Has evidence become stale, unsupported, or contradictory?",
        "Which claim or evidence revision was superseded?",
        "Which ontology migration is required after a class, predicate, cardinality, or constraint change?",
    ]),
    "I": ("Planning / actions", [
        "May an existing RepresentationRecord be reused?",
        "Must a representation be recomputed after lineage change?",
        "Which action invalidates a representation?",
        "When must execution be blocked?",
        "Which action may create a CandidateStatement or EvidenceGap?",
        "Which action requires human approval and what permission is required?",
        "What side effects, outputs, trace stage, and rollback apply to an action?",
    ]),
    "J": ("Governance", [
        "Is knowledge candidate, reviewed, trusted, superseded, or rejected?",
        "Who may review a high-risk candidate?",
        "Does a ReviewDecision apply to the exact artifact hashes shown to the reviewer?",
        "May a candidate be promoted without supporting evidence and required approval?",
        "Which identity merge or supersession decisions remain reversible?",
        "Are runtime state, scientific knowledge, and governed action represented separately?",
        "Which schema changes require a migration plan before release?",
    ]),
    "K": ("Evaluation", [
        "What fraction of competency questions is answerable by current v1?",
        "What class and predicate documentation coverage has been achieved?",
        "Which predicates lack domain, range, inverse, or evidence requirements?",
        "How many duplicate or ambiguous semantic concepts remain?",
        "Do constraint shapes detect invalid endpoint and cardinality bindings?",
        "Which external vocabulary mappings are exact, close, broader, narrower, or absent?",
        "Does a newer ontology release preserve migration coverage for deprecated concepts?",
    ]),
}


STATUS_BY_GROUP = {
    "A": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_CURRENT_V1", "NOT_IN_SCOPE"],
    "B": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_CURRENT_V1", "ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_V2_DESIGN"],
    "C": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_CURRENT_V1", "ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_V2_DESIGN"],
    "D": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "NOT_IN_SCOPE"],
    "E": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_V2_DESIGN"],
    "F": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_V2_DESIGN"],
    "G": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_V2_DESIGN"],
    "H": ["ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_V2_DESIGN"],
    "I": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_V2_DESIGN"],
    "J": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_V2_DESIGN"],
    "K": ["ANSWERABLE_CURRENT_V1", "ANSWERABLE_CURRENT_V1", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "ANSWERABLE_V2_DESIGN", "PARTIALLY_ANSWERABLE", "ANSWERABLE_V2_DESIGN"],
}


GROUP_REQUIREMENTS = {
    "A": (["SoftwareProject", "Package", "PackageRelease", "Operator", "OperatorRevision", "IdentityAssertion"], ["implements_method", "revision_of", "alias_of", "fork_of", "supersedes"], ["software_version"], ["OperatorRevisionShape"]),
    "B": (["Method", "MethodVariant", "Operator", "OperatorRevision", "PackageRelease", "ParameterDefinition"], ["implements_method", "implements_method_variant", "revision_of", "deprecated_by", "equivalent_to"], ["software_version", "flavor", "parameter_condition"], ["OperatorRevisionShape"]),
    "C": (["RepresentationType", "RepresentationConstraint", "RepresentationRecord", "OperatorRevision"], ["consumes", "produces", "derives_from", "transforms", "preserves", "invalidates"], ["representation_state", "parameter_condition"], ["RepresentationTypeShape", "OperatorRevisionShape"]),
    "D": (["ApplicabilityScope", "RepresentationConstraint", "ReferenceArtifactRevision", "StatementRevision"], ["requires_input", "requires_metadata", "requires_reference", "applicable_to", "validated_on", "incompatible_with"], ["organism_taxon", "assay", "observation_unit", "study_design", "modality_strength"], ["ScientificStatementShape"]),
    "E": (["ScientificStatement", "StatementRevision", "AtomicClaimRevision", "ApplicabilityScope"], ["supersedes", "contradicts", "has_limitation"], ["flavor", "parameter_condition", "modality"], ["ScientificStatementShape"]),
    "F": (["EvidenceSpan", "EvidenceAssessment", "EvidenceGap", "SourceRevision", "StatementRevision"], ["supports", "contradicts", "refutes"], ["organism_taxon", "assay", "software_version"], ["EvidenceSpanShape", "EvidenceAssessmentShape", "ScientificStatementShape"]),
    "G": (["SourceWork", "SourceRevision", "SourceArtifact", "ExtractionRun", "ReviewActivity", "StatementRevision"], ["was_generated_by", "used", "was_derived_from", "was_associated_with", "revision_of"], ["software_version"], ["SourceRevisionShape", "ScientificStatementShape"]),
    "H": (["EvidenceDriftAssessment", "SourceRevision", "StatementRevision", "OntologyConceptRevision", "OntologyMigrationPlan"], ["revision_of", "supersedes", "superseded_by", "contradicts"], ["software_version", "method_version"], ["EvidenceAssessmentShape", "ScientificStatementShape"]),
    "I": (["GovernedAction", "ActionPolicy", "RepresentationRecord", "EvidenceGap", "StatementRevision"], ["invalidates", "derives_from"], ["representation_state", "parameter_condition"], ["GovernedActionShape", "RepresentationTypeShape"]),
    "J": (["ReviewDecision", "ReviewActivity", "StatementRevision", "IdentityAssertion", "GovernedAction"], ["was_generated_by", "was_associated_with", "supersedes"], ["software_version"], ["ReviewDecisionShape", "GovernedActionShape", "ScientificStatementShape"]),
    "K": (["ScientificStatement", "MetricDefinition", "EvaluationDataset", "BenchmarkStudy", "EmpiricalResult", "OntologyConceptRevision"], ["evaluated_under", "validated_on", "replaced_by"], ["evaluation_metric", "evaluation_context"], ["ScientificStatementShape"]),
}


CLASS_MEANINGS = {
    "ScientificTask": "A bounded analysis objective.",
    "Method": "An implementation-independent scientific method.",
    "MethodVariant": "A method specialization defined by scientifically meaningful conditions.",
    "ParameterDefinition": "A version-aware operator parameter definition.",
    "Limitation": "A reusable named limitation object in v1.",
    "SoftwareProject": "A software project identity independent of packaging and release.",
    "Package": "A distribution artifact identity within an ecosystem.",
    "PackageRelease": "An immutable versioned package release.",
    "Operator": "A stable callable operator identity.",
    "OperatorRevision": "A release-bound executable operator contract.",
    "ReferenceArtifact": "A stable identity for an atlas, model, or mapping resource.",
    "ReferenceArtifactRevision": "A content-addressed reference artifact revision.",
    "RepresentationType": "Scientific semantics of a data representation.",
    "RepresentationConstraint": "Conditions a representation must satisfy.",
    "ApplicabilityScope": "Context in which knowledge or capability is valid.",
    "InputPort": "A typed operator input role.",
    "OutputPort": "A typed operator output role with lineage semantics.",
    "Requirement": "A mandatory, conditional, optional, or recommended input requirement.",
    "AtomicClaimRevision": "The v1 versioned scientific assertion record.",
    "EvidenceAssessment": "An assessment of evidence support for a claim revision.",
    "EvidenceSpan": "A bounded, source-revision-specific evidence excerpt.",
    "EvidenceReference": "A lightweight v1 pointer used when a full span is unavailable.",
    "EvidenceGap": "An explicit missing-evidence record.",
    "ReviewDecision": "A governed decision over exact reviewed artifacts.",
    "DerivedRelation": "A graph projection derived from ports or reviewed rules.",
    "MetricDefinition": "A definition of an evaluation metric.",
    "EvaluationDataset": "A versioned evaluation dataset and split definition.",
    "BenchmarkStudy": "A bounded comparison protocol.",
    "EmpiricalResult": "A scoped metric observation from a benchmark.",
    "SupersessionRecord": "A governed revision replacement assertion.",
    "RepresentationInstanceBinding": "A binding between runtime data and scientific representation constraints.",
    "ReferencedObject": "An unresolved placeholder endpoint in the v1 graph.",
    "SourceWork": "A stable intellectual or documentation work identity.",
    "SourceRevision": "A versioned edition or release of a source work.",
    "SourceArtifact": "A content-addressed acquired source file.",
    "RepresentationRecord": "Runtime state for a concrete dataset representation.",
    "TraceSpan": "Runtime audit event connecting inputs, outputs, decisions, and activities.",
}


NEW_CLASS_SPECS = {
    "ScientificStatement": "Stable identity of an evidence-governed scientific assertion.",
    "StatementRevision": "Versioned qualified subject-predicate-object assertion.",
    "IdentityAssertion": "Reviewable claim that two identifiers have a typed identity relationship.",
    "ExtractionRun": "Provenance activity that generates candidate records from sources.",
    "ReviewActivity": "Provenance activity that generates ReviewDecisions.",
    "EvidenceDriftAssessment": "Assessment of evidence continuity across source revisions.",
    "OntologyConceptRevision": "Versioned class, property, predicate, qualifier, or shape definition.",
    "OntologyMigrationPlan": "Governed plan for schema and data migration between ontology releases.",
    "GovernedAction": "Typed action with permissions, preconditions, side effects, trace, and rollback semantics.",
    "ActionPolicy": "Policy governing approval and execution eligibility for actions.",
}


CURRENT_PREDICATE_DEFINITIONS = {
    "BELONGS_TO_PACKAGE": "Graph projection from Operator to owning Package.",
    "BELONGS_TO_PROJECT": "Graph projection from Package to SoftwareProject.",
    "BOUND_TO_PACKAGE_RELEASE": "Graph projection binding OperatorRevision to PackageRelease.",
    "CAN_FEED": "Reviewed compatibility projection between two OperatorRevisions; never assumed transitive.",
    "CONSTRAINS_TYPE": "Links a RepresentationConstraint to its RepresentationType.",
    "CONSUMES": "Port-derived projection from OperatorRevision to consumed RepresentationType.",
    "HAS_INPUT_PORT": "Links OperatorRevision to InputPort.",
    "HAS_OUTPUT_PORT": "Links OperatorRevision to OutputPort.",
    "HAS_REQUIREMENT": "Links InputPort to Requirement.",
    "IMPLEMENTS_METHOD": "Projection from OperatorRevision to implemented Method.",
    "IMPLEMENTS_METHOD_VARIANT": "Projection from OperatorRevision to MethodVariant.",
    "OUTPUT_REPRESENTATION_TYPE": "Links OutputPort to RepresentationType.",
    "PRODUCES": "Port-derived projection from OperatorRevision to RepresentationType.",
    "REQUIRES_CONSTRAINT": "Links Requirement to RepresentationConstraint.",
    "REVISION_OF_OPERATOR": "Links OperatorRevision to stable Operator identity.",
    "REVISION_OF_PACKAGE": "Links PackageRelease to stable Package identity.",
    "SUBJECT_OF_CLAIM": "Projection from a subject entity to its AtomicClaimRevision.",
    "SUPPORTS": "Current broad projection from evidence pointer/span to AtomicClaimRevision.",
}


PROPOSED_PREDICATES = [
    ("implements_method", "OperatorRevision", "Method", None, "KEEP"),
    ("implements_method_variant", "OperatorRevision", "MethodVariant", None, "KEEP"),
    ("belongs_to_package", "Operator", "Package", None, "KEEP"),
    ("belongs_to_project", "Package", "SoftwareProject", None, "KEEP"),
    ("revision_of", "VersionedResource", "VersionedResource", None, "REFINE"),
    ("consumes", "OperatorRevision", "RepresentationType", None, "REFINE"),
    ("produces", "OperatorRevision", "RepresentationType", None, "REFINE"),
    ("derives_from", "ProvenanceTrackedArtifact", "ProvenanceTrackedArtifact", None, "ADD"),
    ("transforms", "OperatorRevision", "RepresentationType", None, "ADD"),
    ("preserves", "OperatorRevision", "DataRepresentation", None, "ADD"),
    ("invalidates", "GovernedAction", "RepresentationRecord", None, "ADD"),
    ("modifies", "OperatorRevision", "RepresentationType", None, "ADD"),
    ("filters", "OperatorRevision", "RepresentationType", None, "ADD"),
    ("normalizes", "OperatorRevision", "RepresentationType", None, "ADD"),
    ("integrates", "OperatorRevision", "RepresentationType", None, "ADD"),
    ("aggregates", "OperatorRevision", "RepresentationType", None, "ADD"),
    ("projects_to", "OperatorRevision", "RepresentationType", None, "ADD"),
    ("requires_input", "ExecutableCapability", "RepresentationConstraint", None, "REFINE"),
    ("requires_metadata", "ExecutableCapability", "PropertyDefinition", None, "ADD"),
    ("requires_reference", "ExecutableCapability", "ReferenceArtifactRevision", None, "ADD"),
    ("requires_assay_property", "ScientificStatement", "ApplicabilityScope", None, "ADD"),
    ("requires_study_design", "ScientificStatement", "ApplicabilityScope", None, "ADD"),
    ("applicable_to", "ScientificStatement", "ApplicabilityScope", None, "ADD"),
    ("validated_on", "ScientificStatement", "EvaluationDataset", None, "ADD"),
    ("evaluated_under", "ScientificStatement", "BenchmarkStudy", None, "ADD"),
    ("incompatible_with", "ScientificStatement", "RepresentationConstraint", None, "ADD"),
    ("contraindicated_for", "ScientificStatement", "ApplicabilityScope", None, "ADD"),
    ("assumes", "ScientificStatement", "ScientificStatement", None, "ADD"),
    ("has_limitation", "ScientificStatement", "ScientificStatement", None, "REFINE"),
    ("has_recommendation", "ScientificStatement", "ScientificStatement", None, "ADD"),
    ("supports", "EvidenceAssessment", "StatementRevision", None, "REFINE"),
    ("contradicts", "EvidenceAssessment", "StatementRevision", None, "ADD"),
    ("refutes", "EvidenceAssessment", "StatementRevision", None, "ADD"),
    ("was_generated_by", "ProvenanceTrackedArtifact", "Activity", "generated", "ADD"),
    ("generated", "Activity", "ProvenanceTrackedArtifact", "was_generated_by", "ADD"),
    ("used", "Activity", "ProvenanceTrackedArtifact", "was_used_by", "ADD"),
    ("was_used_by", "ProvenanceTrackedArtifact", "Activity", "used", "ADD"),
    ("was_derived_from", "ProvenanceTrackedArtifact", "ProvenanceTrackedArtifact", None, "ADD"),
    ("was_associated_with", "Activity", "Agent", None, "ADD"),
    ("supersedes", "VersionedResource", "VersionedResource", "superseded_by", "REFINE"),
    ("superseded_by", "VersionedResource", "VersionedResource", "supersedes", "ADD"),
    ("alias_of", "IdentityAssertion", "VersionedResource", None, "ADD"),
    ("deprecated_by", "VersionedResource", "VersionedResource", None, "ADD"),
    ("fork_of", "SoftwareProject", "SoftwareProject", None, "ADD"),
    ("equivalent_to", "IdentityAssertion", "VersionedResource", None, "ADD"),
    ("replaced_by", "OntologyConceptRevision", "OntologyConceptRevision", None, "ADD"),
]


def build_properties() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "concepts": [
            {
                "property_id": item_id,
                "classification": classification,
                "definition": definition,
                "value_kind": "IRI_OR_RECORD_REF" if classification == "RELATION" else "TYPED_LITERAL_OR_TERM",
                "rationale": "Use the lightest semantic construct that preserves validation and query meaning.",
            }
            for item_id, classification, definition in PROPERTY_SPECS
        ],
    }


def build_classes(graph: dict[str, Any]) -> dict[str, Any]:
    physical: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in graph["nodes"]:
        physical[node["record_type"]].append(node["record"])
    current_names = list(CLASS_MEANINGS)
    dispositions = defaultdict(lambda: "KEEP", {
        "Method": "REFINE", "MethodVariant": "REFINE", "OperatorRevision": "REFINE",
        "RepresentationType": "REFINE", "RepresentationConstraint": "REFINE", "ApplicabilityScope": "REFINE",
        "AtomicClaimRevision": "SPLIT", "EvidenceAssessment": "REFINE", "EvidenceSpan": "REFINE",
        "EvidenceGap": "REFINE", "ReviewDecision": "REFINE", "DerivedRelation": "REFINE",
        "SourceRevision": "REFINE", "PackageRelease": "REFINE", "RepresentationRecord": "REFINE",
        "TraceSpan": "REFINE", "Limitation": "MERGE", "EvidenceReference": "EXTERNALIZE",
        "ReferencedObject": "DEPRECATE",
    })
    current = []
    for name in current_names:
        records = physical.get(name, [])
        observed = sorted({key for row in records for key in row})
        if records:
            status = "CURRENT_V1_PHYSICAL_GRAPH"
            example = next((row.get("entity_id") or row.get("claim_revision_id") or row.get("scope_id") or row.get("evidence_span_id") or row.get("gap_id") for row in records), None)
        elif name in {"SourceWork", "SourceRevision", "SourceArtifact"}:
            status, example = "CURRENT_PILOT_ONLY", f"{name.lower()}:soupx-example"
        elif name in {"RepresentationRecord", "TraceSpan"}:
            status, example = "CURRENT_RUNTIME_MODEL", f"runtime:{name.lower()}:example"
        else:
            status, example = "CURRENT_V1_SCHEMA_NOT_GRAPH_MATERIALIZED", None
        current.append({
            "class_id": name,
            "status": status,
            "meaning": CLASS_MEANINGS[name],
            "owner": "scientific_knowledge" if name not in {"RepresentationRecord", "TraceSpan"} else "runtime",
            "instance_examples": [example] if example else [],
            "physical_instance_count": len(records),
            "observed_properties": observed,
            "required_properties": ["id", "schema_version"],
            "optional_properties": ["label", "ontology_version", "introduced_in", "deprecated_in", "replaced_by"],
            "lifecycle": "versioned_and_governed" if name.endswith("Revision") or name in {"AtomicClaimRevision", "ReviewDecision", "EvidenceAssessment"} else "stable_identity_or_component",
            "versioned": name.endswith("Revision") or name in {"AtomicClaimRevision", "PackageRelease"},
            "reviewable": name in {"AtomicClaimRevision", "EvidenceAssessment", "ReviewDecision", "DerivedRelation", "SourceRevision", "EvidenceGap"},
            "layer": "runtime" if name in {"RepresentationRecord", "TraceSpan"} else "scientific",
            "currently_overloaded": name in {"AtomicClaimRevision", "Limitation", "EvidenceReference", "ReferencedObject", "DerivedRelation"},
            "interface_candidates": [interface_id for interface_id, (_, _, implementers) in INTERFACE_SPECS.items() if name in implementers],
            "v2_disposition": dispositions[name],
        })
    proposed = []
    for row in current:
        if row["v2_disposition"] in {"DEPRECATE", "EXTERNALIZE"}:
            continue
        proposed.append({**row, "status": "PROPOSED_V2", "introduced_in": "v1", "deprecated_in": None, "replaced_by": None})
    for name, meaning in NEW_CLASS_SPECS.items():
        proposed.append({
            "class_id": name,
            "meaning": meaning,
            "owner": "ontology_governance" if name.startswith("Ontology") else "scientific_knowledge",
            "instance_examples": [],
            "physical_instance_count": 0,
            "observed_properties": [],
            "required_properties": ["id", "schema_version", "ontology_version"],
            "optional_properties": ["label", "introduced_in", "deprecated_in", "replaced_by"],
            "lifecycle": "versioned_and_governed",
            "versioned": name not in {"ScientificStatement"},
            "reviewable": True,
            "layer": "governance" if name in {"GovernedAction", "ActionPolicy", "OntologyConceptRevision", "OntologyMigrationPlan"} else "scientific",
            "currently_overloaded": False,
            "interface_candidates": [],
            "v2_disposition": "ADD",
            "status": "PROPOSED_V2",
            "introduced_in": ONTOLOGY_VERSION,
            "deprecated_in": None,
            "replaced_by": None,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "scope_note": "Audited classes include physical v1 graph records, non-materialized v1.1 schemas, pilot provenance identities, and runtime bridge models; their statuses remain explicit.",
        "current_classes": current,
        "proposed_classes": proposed,
    }


def build_interfaces() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "interfaces": [
            {
                "interface_id": name,
                "definition": f"Reusable semantic shape for {name}.",
                "required_properties": required,
                "optional_properties": optional,
                "implementing_classes": classes,
                "design_only": True,
            }
            for name, (required, optional, classes) in INTERFACE_SPECS.items()
        ],
    }


def build_predicates(graph: dict[str, Any]) -> dict[str, Any]:
    by_node = {node["graph_node_id"]: node["record_type"] for node in graph["nodes"]}
    current_counts = Counter(edge["predicate"] for edge in graph["edges"])
    current = []
    for predicate_id, count in sorted(current_counts.items()):
        pairs = sorted({(by_node.get(edge["source_graph_node_id"], "Unknown"), by_node.get(edge["target_graph_node_id"], "Unknown")) for edge in graph["edges"] if edge["predicate"] == predicate_id})
        domain = sorted({x for x, _ in pairs})
        range_ = sorted({y for _, y in pairs})
        definition = CURRENT_PREDICATE_DEFINITIONS.get(predicate_id, f"V1 claim predicate `{predicate_id}` projected from an AtomicClaimRevision to its object.")
        flags = []
        lower = predicate_id.casefold()
        if predicate_id.isupper() and lower in current_counts:
            flags.append("DUPLICATE_PREDICATE")
        if predicate_id in {"SUPPORTS", "requires_representation", "requires_representation_constraint", "key_parameter", "has_limitation"}:
            flags.append("OVERLOADED_PREDICATE")
        if predicate_id in {"SUPPORTS", "requires_representation", "key_parameter"}:
            flags.append("AMBIGUOUS_PREDICATE")
        if len(domain) > 1 or len(range_) > 1:
            flags.append("MISSING_DOMAIN_RANGE")
        if predicate_id.isupper() and predicate_id not in {"CAN_FEED"}:
            flags.append("MISSING_INVERSE")
        if predicate_id == "CAN_FEED":
            flags.append("UNSAFE_TRANSITIVE_ASSUMPTION")
        current.append({
            "predicate_id": predicate_id,
            "human_label": predicate_id.replace("_", " ").title(),
            "definition": definition,
            "domain": domain,
            "range": range_,
            "inverse_predicate": None,
            "cardinality": "0..*",
            "symmetric": False,
            "transitive": False,
            "functional": predicate_id in {"BELONGS_TO_PACKAGE", "BELONGS_TO_PROJECT", "BOUND_TO_PACKAGE_RELEASE", "REVISION_OF_OPERATOR", "REVISION_OF_PACKAGE"},
            "evidence_required": predicate_id not in {"HAS_INPUT_PORT", "HAS_OUTPUT_PORT", "HAS_REQUIREMENT", "CONSTRAINS_TYPE", "OUTPUT_REPRESENTATION_TYPE", "REQUIRES_CONSTRAINT"},
            "allowed_qualifiers": ["software_version", "parameter_condition", "representation_state"],
            "schema_version": "v1-observed",
            "deprecated": False,
            "replacement_predicate": None,
            "observed_count": count,
            "audit_flags": flags,
        })

    cq_for_predicate = {
        "revision_of": ["CQ-A02", "CQ-G01"], "consumes": ["CQ-C01"], "produces": ["CQ-C02"],
        "derives_from": ["CQ-C03", "CQ-I01"], "transforms": ["CQ-C04"], "preserves": ["CQ-C04"],
        "invalidates": ["CQ-C05", "CQ-I03"], "modifies": ["CQ-C07"], "filters": ["CQ-C04"],
        "normalizes": ["CQ-C04"], "integrates": ["CQ-C04"], "aggregates": ["CQ-C04"], "projects_to": ["CQ-C02"],
        "requires_input": ["CQ-D01"], "requires_metadata": ["CQ-D02"], "requires_reference": ["CQ-D03"],
        "requires_assay_property": ["CQ-D04"], "requires_study_design": ["CQ-D04"], "applicable_to": ["CQ-D04"],
        "validated_on": ["CQ-D06", "CQ-K05"], "evaluated_under": ["CQ-D06", "CQ-K06"],
        "incompatible_with": ["CQ-D05"], "contraindicated_for": ["CQ-D05"], "assumes": ["CQ-E02"],
        "has_limitation": ["CQ-E04"], "has_recommendation": ["CQ-D01"], "supports": ["CQ-F01", "CQ-F03"],
        "contradicts": ["CQ-E05", "CQ-F03"], "refutes": ["CQ-F03"], "was_generated_by": ["CQ-G02", "CQ-G03"],
        "generated": ["CQ-G02"], "used": ["CQ-G04"], "was_used_by": ["CQ-G04"], "was_derived_from": ["CQ-G05"],
        "was_associated_with": ["CQ-G03"], "supersedes": ["CQ-E07", "CQ-H06"], "superseded_by": ["CQ-H06"],
        "alias_of": ["CQ-A03"], "deprecated_by": ["CQ-B04"], "fork_of": ["CQ-A04"], "equivalent_to": ["CQ-B07"],
        "replaced_by": ["CQ-H07", "CQ-K07"],
    }
    proposed = []
    for predicate_id, domain, range_, inverse, disposition in PROPOSED_PREDICATES:
        proposed.append({
            "predicate_id": predicate_id,
            "human_label": predicate_id.replace("_", " "),
            "definition": f"Governed v2 relation `{predicate_id}` from {domain} to {range_}.",
            "domain": [domain],
            "range": [range_],
            "inverse_predicate": inverse,
            "cardinality": "0..*",
            "symmetric": predicate_id == "equivalent_to",
            "transitive": False,
            "functional": predicate_id in {"revision_of", "deprecated_by"},
            "evidence_required": predicate_id not in {"was_generated_by", "generated", "used", "was_used_by", "was_derived_from", "was_associated_with"},
            "allowed_qualifiers": ["modality", "organism_taxon", "assay", "observation_unit", "study_design", "representation_state", "software_version", "flavor", "parameter_condition"],
            "schema_version": SCHEMA_VERSION,
            "ontology_version": ONTOLOGY_VERSION,
            "introduced_in": ONTOLOGY_VERSION if disposition == "ADD" else "v1",
            "deprecated_in": None,
            "replaced_by": None,
            "deprecated": False,
            "replacement_predicate": None,
            "disposition": disposition,
            "competency_question_ids": cq_for_predicate.get(predicate_id, ["CQ-E01"]),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "current_predicates": current,
        "proposed_predicates": proposed,
        "projection_policy": "Upper-case structural edges may remain read-only graph projections; authoritative v2 statements use the governed lower-case predicate registry and explicit StatementRevision records.",
    }


def build_qualifiers() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "qualifiers": [
            {
                "qualifier_id": name,
                "definition": definition,
                "owner": owner,
                "value_kind": "controlled_term_or_version_constraint",
                "operational_rule": "Omit only when unknown is explicitly represented by scope status; never silently generalize.",
                "not_a_scope_duplicate": True,
            }
            for name, definition, owner in QUALIFIER_SPECS
        ],
    }


def build_shapes() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "shape_language": "SHACL-like design contract; no production validator migration in this checkpoint",
        "shapes": [
            {
                "shape_id": shape_id,
                "target_class": target,
                "required_properties": required,
                "allowed_types": [target],
                "cardinality": {prop: "1" for prop in required},
                "endpoint_constraints": predicates,
                "version_requirements": ["schema_version", "ontology_version"],
                "evidence_requirements": ["evidence_assessment_ids"] if shape_id == "ScientificStatementShape" else [],
            }
            for shape_id, (target, required, predicates) in SHAPE_SPECS.items()
        ],
    }


def build_competency_questions() -> dict[str, Any]:
    rows = []
    for letter, (group_name, questions) in GROUPS.items():
        classes, predicates, qualifiers, constraints = GROUP_REQUIREMENTS[letter]
        for index, question in enumerate(questions, 1):
            rows.append({
                "competency_question_id": f"CQ-{letter}{index:02d}",
                "group": group_name,
                "question": question,
                "coverage": STATUS_BY_GROUP[letter][index - 1],
                "required_classes": classes,
                "required_predicates": predicates,
                "required_qualifiers": qualifiers,
                "required_constraints": constraints,
                "rationale": "Design requirement; answerability is assessed against frozen v1 and this design artifact, not migrated data.",
            })
    counts = Counter(row["coverage"] for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "question_count": len(rows),
        "coverage_counts": dict(sorted(counts.items())),
        "questions": rows,
    }


def build_statement_model() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "decision": "AtomicClaimRevision becomes a backward-compatible implementation surface for StatementRevision during a future migration; ScientificStatement supplies stable assertion identity.",
        "authoritative_model": {
            "identity_class": "ScientificStatement",
            "revision_class": "StatementRevision",
            "required_fields": ["id", "subject", "predicate", "object", "scope_id", "evidence_assessment_ids", "epistemic_status", "review_status", "schema_version", "ontology_version", "provenance_activity_id"],
            "optional_fields": ["qualifiers", "version_conditions", "knowledge_status", "supersedes"],
            "object_rule": "Exactly one entity object or typed literal value.",
            "atomization_rule": "One independently reviewable proposition per StatementRevision; conjunctions require separate revisions unless the predicate itself defines a compound relation.",
        },
        "graph_projection": {
            "allowed": True,
            "example": "OperatorRevision -> requires_input -> RepresentationConstraint",
            "authoritative": False,
            "must_reference_statement_revision": True,
            "must_preserve_scope_and_qualifiers": True,
        },
        "layer_separation": {
            "scientific_knowledge": "Scrublet requires raw UMI under a declared scope.",
            "runtime_state": "This dataset has no raw UMI.",
            "governed_action": "Block this Scrublet execution with a traceable reason.",
        },
    }


def build_evidence_model() -> dict[str, Any]:
    support = {
        "DIRECT_SUPPORT": "Exact evidence entails the statement's subject, predicate, object, and compatible scope.",
        "PARTIAL_SUPPORT": "Evidence supports a proper subset of the statement or a narrower scope.",
        "CONTEXTUAL_SUPPORT": "Evidence supplies relevant context but does not entail the assertion alone.",
        "CONTRADICTS": "Evidence presents an incompatible assertion without establishing formal refutation.",
        "REFUTES": "Evidence directly establishes the negation or invalidity of the assertion under the same scope.",
        "DOES_NOT_SUPPORT": "Evidence is topically related but supplies no support for the assertion.",
        "UNCERTAIN": "Support cannot be determined without additional evidence or review.",
    }
    drift = {
        "CURRENT": "Evidence content and binding remain valid for the active statement revision.",
        "EVIDENCE_CHANGED": "Bound text or its semantic content changed in a newer SourceRevision.",
        "STALE_EVIDENCE": "The evidence binding points to a non-current or invalidated source revision.",
        "REVALIDATION_REQUIRED": "Change may affect support, scope, or statement identity and requires review.",
        "SUPERSEDED": "A governed newer evidence or statement revision replaces this record.",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "support_states": [{"state": key, "operational_definition": value} for key, value in support.items()],
        "distinct_gates": ["source_exists", "evidence_exists", "evidence_supports", "statement_reviewed", "statement_trusted"],
        "evidence_drift_states": [{"state": key, "operational_definition": value} for key, value in drift.items()],
        "drift_inputs": ["prior_source_revision", "new_source_revision", "prior_evidence_span", "candidate_evidence_span", "statement_revision", "scope"],
        "drift_outcomes": ["unchanged", "moved_semantically_unchanged", "text_changed", "scope_changed", "unsupported", "contradicted", "requires_review"],
    }


def build_provenance_model() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "entity_types": ["SourceWork", "SourceRevision", "SourceArtifact", "EvidenceSpan", "StatementRevision", "ReviewDecision"],
        "activity_types": ["ExtractionRun", "ReviewActivity", "GovernedAction"],
        "agent_types": ["HumanReviewer", "SoftwareAgent", "DesignatedOwner"],
        "relations": ["was_generated_by", "used", "was_derived_from", "was_associated_with", "revision_of", "supersedes", "superseded_by"],
        "required_chains": [
            ["SourceWork", "revision_of<-SourceRevision", "contains->EvidenceSpan"],
            ["ExtractionRun", "generated->StatementRevision", "used->EvidenceSpan"],
            ["ReviewActivity", "generated->ReviewDecision", "used->StatementRevision"],
        ],
        "alignment": "Use PROV-O Entity/Activity/Agent and qualified influence patterns where role or time is required; retain scKG domain classes.",
    }


def build_actions() -> dict[str, Any]:
    names = [
        "RunOperator", "ReuseRepresentation", "RecomputeRepresentation", "InvalidateRepresentation", "BlockAction",
        "CreateCandidateStatement", "CreateEvidenceGap", "ReviewCandidate", "RejectCandidate", "MergeIdentity",
        "SupersedeStatement", "PromoteStatement", "RevalidateEvidence",
    ]
    high_risk = {"MergeIdentity", "SupersedeStatement", "PromoteStatement", "RejectCandidate"}
    mutation = {"RunOperator", "RecomputeRepresentation", "InvalidateRepresentation", "CreateCandidateStatement", "CreateEvidenceGap", "RejectCandidate", "MergeIdentity", "SupersedeStatement", "PromoteStatement", "RevalidateEvidence"}
    actions = []
    for name in names:
        actions.append({
            "action_id": name,
            "input_object_types": ["RepresentationRecord"] if "Representation" in name or name == "RunOperator" else ["StatementRevision"],
            "preconditions": ["typed_inputs_resolve", "policy_allows_action", "required_evidence_or_runtime_state_present"],
            "permissions": ["designated_owner"] if name in high_risk else ["scientific_agent_or_reviewer"],
            "approval_required": name in high_risk or name == "ReviewCandidate",
            "side_effects": ["state_change"] if name in mutation else [],
            "outputs": ["TraceSpan", "ActionOutcome"],
            "trace_stage": "DECISION" if name in high_risk or name in {"BlockAction", "ReuseRepresentation"} else "EXECUTION",
            "rollback_or_reversibility": "compensating_action_required" if name in mutation else "reversible_or_no_mutation",
            "implemented": False,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "actions": actions,
        "separation_rule": "GovernedAction consumes Scientific Knowledge plus Runtime State; it is never itself a scientific fact.",
    }


def build_external_alignment() -> dict[str, Any]:
    valid = ["EXACT_MATCH", "CLOSE_MATCH", "BROADER_THAN", "NARROWER_THAN", "NO_MAPPING"]
    models = [
        {
            "external_model": "EDAM",
            "source_url": "https://edamontology.org/",
            "relevant_concepts": ["Operation", "Data", "Format", "Topic"],
            "mappings": [
                {"local_concept": "ScientificTask", "external_concept": "EDAM:operation", "mapping_type": "CLOSE_MATCH"},
                {"local_concept": "RepresentationType", "external_concept": "EDAM:data", "mapping_type": "NARROWER_THAN"},
                {"local_concept": "SourceArtifact.format", "external_concept": "EDAM:format", "mapping_type": "CLOSE_MATCH"},
            ],
            "decision": "Reuse identifiers for established operations/data/formats; retain local representation-state and governance semantics.",
        },
        {
            "external_model": "PROV-O",
            "source_url": "https://www.w3.org/TR/prov-o/",
            "relevant_concepts": ["Entity", "Activity", "Agent", "used", "wasGeneratedBy", "wasDerivedFrom", "wasAssociatedWith"],
            "mappings": [
                {"local_concept": "ExtractionRun", "external_concept": "prov:Activity", "mapping_type": "NARROWER_THAN"},
                {"local_concept": "SourceArtifact", "external_concept": "prov:Entity", "mapping_type": "NARROWER_THAN"},
                {"local_concept": "was_generated_by", "external_concept": "prov:wasGeneratedBy", "mapping_type": "EXACT_MATCH"},
                {"local_concept": "used", "external_concept": "prov:used", "mapping_type": "EXACT_MATCH"},
            ],
            "decision": "Adopt PROV-O relation semantics and qualified influence where role/time is needed.",
        },
        {
            "external_model": "Biolink Model",
            "source_url": "https://biolink.github.io/biolink-model/understanding-the-model/",
            "relevant_concepts": ["Association", "subject", "predicate", "object", "qualifier", "sources"],
            "mappings": [
                {"local_concept": "StatementRevision", "external_concept": "biolink:Association", "mapping_type": "CLOSE_MATCH"},
                {"local_concept": "qualifiers", "external_concept": "biolink:qualifier", "mapping_type": "CLOSE_MATCH"},
            ],
            "decision": "Reuse the S-P-O-Q pattern while retaining scKG revision, scope, evidence assessment, and governance requirements.",
        },
        {
            "external_model": "OBO Relation Ontology",
            "source_url": "https://obofoundry.org/principles/fp-007-relations.html",
            "relevant_concepts": ["relation reuse", "domain", "range", "inverse", "property characteristics"],
            "mappings": [
                {"local_concept": "derives_from", "external_concept": "RO candidate mapping required", "mapping_type": "NO_MAPPING"},
                {"local_concept": "transforms", "external_concept": "RO search required before minting", "mapping_type": "NO_MAPPING"},
            ],
            "decision": "Search and reuse RO/OBO relations before minting; local relations need explicit domain/range and mapping review.",
        },
        {
            "external_model": "RO-Crate 1.3",
            "source_url": "https://www.researchobject.org/ro-crate/specification/1.3/index.html",
            "relevant_concepts": ["Root Data Entity", "Data Entity", "Contextual Entity", "provenance", "profiles", "workflows"],
            "mappings": [
                {"local_concept": "SourceArtifact", "external_concept": "RO-Crate Data Entity", "mapping_type": "NARROWER_THAN"},
                {"local_concept": "ProvenanceTrackedArtifact", "external_concept": "RO-Crate provenance of entities", "mapping_type": "CLOSE_MATCH"},
            ],
            "decision": "Use an RO-Crate profile for exchange packaging later; do not make RO-Crate the internal scientific statement model.",
        },
    ]
    return {"schema_version": SCHEMA_VERSION, "ontology_version": ONTOLOGY_VERSION, "valid_mapping_types": valid, "external_models": models, "wholesale_import": False}


def build_gap_analysis(classes: dict[str, Any], predicates: dict[str, Any]) -> dict[str, Any]:
    class_cq = {
        "AtomicClaimRevision": ["CQ-E01", "CQ-E03"], "Limitation": ["CQ-E04"], "EvidenceReference": ["CQ-F01"],
        "ReferencedObject": ["CQ-A06"], "RepresentationType": ["CQ-C04"], "RepresentationConstraint": ["CQ-C07"],
        "ApplicabilityScope": ["CQ-D04"], "EvidenceAssessment": ["CQ-F03"], "EvidenceSpan": ["CQ-F05"],
        "EvidenceGap": ["CQ-F07"], "ReviewDecision": ["CQ-J03"], "DerivedRelation": ["CQ-E06"],
        "SourceRevision": ["CQ-G01"], "PackageRelease": ["CQ-A02"], "RepresentationRecord": ["CQ-I01"], "TraceSpan": ["CQ-I07"],
        "Method": ["CQ-B06"], "MethodVariant": ["CQ-B03"], "OperatorRevision": ["CQ-B01"],
    }
    entries = []
    for row in classes["current_classes"]:
        action = row["v2_disposition"]
        entries.append({
            "concept_kind": "CLASS",
            "concept_id": row["class_id"],
            "action": action,
            "rationale": f"{action} based on observed v1 ownership, lifecycle, and competency requirements.",
            "competency_question_ids": class_cq.get(row["class_id"], ["CQ-K02"]),
            "replacement_or_target": "StatementRevision" if row["class_id"] == "AtomicClaimRevision" else ("ScientificStatement" if row["class_id"] == "Limitation" else None),
        })
    for row in classes["proposed_classes"]:
        if row["v2_disposition"] == "ADD":
            group = "CQ-H07" if row["class_id"].startswith("Ontology") else "CQ-G02" if row["class_id"].endswith("Run") or row["class_id"].endswith("Activity") else "CQ-E01"
            entries.append({"concept_kind": "CLASS", "concept_id": row["class_id"], "action": "ADD", "rationale": "Required by a competency question and absent as a governed v1 class.", "competency_question_ids": [group], "replacement_or_target": None})
    for row in predicates["current_predicates"]:
        action = "REFINE" if row["audit_flags"] else "KEEP"
        if row["predicate_id"] in {"IMPLEMENTS_METHOD", "PRODUCES", "SUPPORTS"}:
            action = "MERGE"
        entries.append({
            "concept_kind": "PREDICATE",
            "concept_id": row["predicate_id"],
            "action": action,
            "rationale": "Reconcile projection vocabulary with authoritative predicate semantics and explicit domain/range.",
            "competency_question_ids": ["CQ-K03"],
            "replacement_or_target": row["predicate_id"].casefold() if action == "MERGE" else None,
        })
    for row in predicates["proposed_predicates"]:
        if row["disposition"] == "ADD":
            entries.append({"concept_kind": "PREDICATE", "concept_id": row["predicate_id"], "action": "ADD", "rationale": "The relation is required by mapped competency questions; implementation remains deferred.", "competency_question_ids": row["competency_question_ids"], "replacement_or_target": None})
    counts = Counter(row["action"] for row in entries)
    return {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "allowed_actions": ["KEEP", "REFINE", "SPLIT", "MERGE", "ADD", "DEPRECATE", "EXTERNALIZE"],
        "counts": dict(sorted(counts.items())),
        "entries": entries,
    }


def build_quality_metrics() -> list[dict[str, Any]]:
    names = [
        "Competency Question Coverage", "Class Documentation Coverage", "Predicate Documentation Coverage",
        "Domain/Range Coverage", "Inverse Definition Coverage", "Constraint Shape Coverage",
        "Evidence Requirement Coverage", "External Vocabulary Reuse", "Duplicate Semantic Concept Count",
        "Ambiguous Predicate Count", "Logical/Constraint Violation Count", "Deprecated Concept Migration Coverage",
    ]
    return [{"metric_id": name.lower().replace("/", "_").replace(" ", "_"), "label": name, "aggregation": "count_and_rate" if not name.endswith("Count") else "count", "global_score": False} for name in names]


def render_cq_doc(coverage: dict[str, Any]) -> str:
    lines = ["# Scientific Decision Ontology v2 Competency Questions", "", "DESIGN_ONLY=true", "", f"Total: **{coverage['question_count']}**", ""]
    current_group = None
    for row in coverage["questions"]:
        if row["group"] != current_group:
            if current_group is not None:
                lines.append("")
            current_group = row["group"]
            lines.extend([f"## {current_group}", "", "| ID | Question | Coverage |", "|---|---|---|"])
        lines.append(f"| {row['competency_question_id']} | {row['question']} | {row['coverage']} |")
    lines.extend(["", "Every question's required classes, predicates, qualifiers, and constraints are recorded in `competency_question_coverage.json`.", ""])
    return "\n".join(lines)


def render_design_doc(manifest: dict[str, Any], gap: dict[str, Any], predicates: dict[str, Any]) -> str:
    flags = Counter(flag for row in predicates["current_predicates"] for flag in row["audit_flags"])
    return f"""# Scientific Decision Ontology v2 Research & Design Audit

STATUS={manifest['status']}
DESIGN_ONLY=true
PRODUCTION_MIGRATION=false

## Decision

The frozen v1 ontology is useful but is not yet precise and governed enough for unrestricted long-term extraction, evidence evolution, and action authorization. Its strongest foundations are release-bound operators, representation constraints, applicability scopes, evidence-bound claim revisions, and fail-closed review semantics. V2 should preserve these foundations while making the authoritative statement, provenance, evidence drift, identity drift, and action layers explicit.

This design does not replace the production schema. It introduces no Scientific KG content and performs no migration.

## Bounded scope

Scientific Decision Ontology v2 covers evidence-governed single-cell and multi-omics analysis decisions: methods, software implementations, data representations, applicability, evidence, version/provenance, governance, actions, and evaluation context.

It excludes gene/protein/pathway biological truth, comprehensive disease and cell ontologies, general chemistry, and clinical diagnosis. External ontologies should supply those identities.

## Competency-question result

- Total: {manifest['competency_questions']}
- Answerable by current v1: {manifest['coverage']['ANSWERABLE_CURRENT_V1']}
- Answerable by v2 design: {manifest['coverage']['ANSWERABLE_V2_DESIGN']}
- Partially answerable: {manifest['coverage']['PARTIALLY_ANSWERABLE']}
- Out of scope: {manifest['coverage']['NOT_IN_SCOPE']}

## Current audit

- Physical v1 graph classes: {manifest['physical_current_classes']}
- Audited current classes including schema, pilot, and runtime surfaces: {manifest['current_classes']}
- Current graph predicates: {manifest['current_predicates']}
- Candidate v2 classes: {manifest['proposed_classes']}
- Candidate v2 predicates: {manifest['proposed_predicates']}

Observed predicate risks: {dict(sorted(flags.items()))}. Upper-case structural edges remain projections only; lower-case governed predicates and StatementRevision records carry authoritative semantics.

## Core v2 decisions

1. `ScientificStatement` is stable identity; `StatementRevision` is the authoritative versioned S-P-O-Q assertion.
2. `AtomicClaimRevision` is a future compatibility surface for StatementRevision, not a second assertion model.
3. Evidence existence, support, review, and trust remain separate gates.
4. Provenance aligns with PROV-O Entity/Activity/Agent relations while retaining scKG domain classes.
5. Runtime state, scientific knowledge, and governed action remain separate layers.
6. Graph projections are derived views and must reference the statement revisions that justify them.
7. Ontology and evidence drift require explicit revalidation states; no source monitor is implemented here.

## V1 to v2 dispositions

{json.dumps(gap['counts'], ensure_ascii=False, sort_keys=True)}

Every ADD or REFINE entry cites competency-question IDs in `v1_v2_gap_analysis.json`.

## External alignment

- EDAM: reuse established operation, data, and format identifiers where the mapping is strong.
- PROV-O: adopt provenance relation semantics and qualified influence when role or time matters.
- Biolink: reuse the S-P-O-Q association pattern, while retaining scKG evidence assessment and governance.
- OBO/RO: search and reuse existing relations before minting local predicates.
- RO-Crate: plan a future exchange profile; do not use it as the internal statement model.

## Quality metrics

Ontology-Eval uses 12 separate metrics; it deliberately has no single global score. Competency Question Coverage is the primary completeness measure.

## Validation

- Focused design consistency: {manifest['focused_tests']}
- Bounded v1 KG and Studio regression: {manifest['bounded_regression_tests']}

## Integrity and stop

Production ontology, Scientific KG, RAG, Planner, and Studio extractor hashes are frozen in the manifest and validated by focused tests. No quarantined C7 payload was accessed. Human review of competency questions, class hierarchy, predicates, statement model, action model, and shapes is required before any migration plan can become executable.

## Exit

```text
CHECKPOINT=Scientific-Decision-Ontology-v2-Design-Audit
STATUS={manifest['status']}

COMPETENCY_QUESTIONS={manifest['competency_questions']}
ANSWERABLE_CURRENT_V1={manifest['coverage']['ANSWERABLE_CURRENT_V1']}
ANSWERABLE_V2_DESIGN={manifest['coverage']['ANSWERABLE_V2_DESIGN']}
PARTIALLY_ANSWERABLE={manifest['coverage']['PARTIALLY_ANSWERABLE']}
NOT_IN_SCOPE={manifest['coverage']['NOT_IN_SCOPE']}

CURRENT_CLASSES={manifest['current_classes']}
PROPOSED_CLASSES={manifest['proposed_classes']}
CURRENT_PREDICATES={manifest['current_predicates']}
PROPOSED_PREDICATES={manifest['proposed_predicates']}

KEEP={manifest['gap_counts'].get('KEEP', 0)}
REFINE={manifest['gap_counts'].get('REFINE', 0)}
SPLIT={manifest['gap_counts'].get('SPLIT', 0)}
MERGE={manifest['gap_counts'].get('MERGE', 0)}
ADD={manifest['gap_counts'].get('ADD', 0)}
DEPRECATE={manifest['gap_counts'].get('DEPRECATE', 0)}
EXTERNALIZE={manifest['gap_counts'].get('EXTERNALIZE', 0)}

INTERFACES={manifest['interfaces']}
CONSTRAINT_SHAPES={manifest['constraint_shapes']}
EXTERNAL_ALIGNMENTS={manifest['external_alignments']}

PRIMARY_V1_GAPS={json.dumps(manifest['primary_v1_gaps'], ensure_ascii=False)}

FOCUSED_TESTS={manifest['focused_tests']}
ARTIFACT_INTEGRITY={'PASS' if not manifest['protected_changed_groups'] else 'FAIL'}

PRODUCTION_ONTOLOGY_CHANGED={str(manifest['production_ontology_changed']).lower()}
SCIENTIFIC_KG_CHANGED={str(manifest['scientific_kg_changed']).lower()}
RAG_CHANGED={str(manifest['rag_changed']).lower()}
PLANNER_CHANGED={str(manifest['planner_changed']).lower()}
STUDIO_EXTRACTOR_CHANGED={str(manifest['studio_extractor_changed']).lower()}

CHECKPOINT_5A_COMMIT={manifest['checkpoint_5a_commit']}
LOCAL_HEAD={manifest['local_head']}
REMOTE_HEAD={manifest['remote_head']}
PUSH_STATUS={manifest['push_status']}

NEXT_RECOMMENDED_CHECKPOINT={manifest['next_recommended_checkpoint']}
STOPPED=true
```
"""


def generate(*, focused_tests: str = "PENDING", bounded_regression_tests: str = "PENDING") -> dict[str, Any]:
    graph = _json(GRAPH_PATH)
    before = protected_identity()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    DESIGN_DOC.parent.mkdir(parents=True, exist_ok=True)

    properties = build_properties()
    classes = build_classes(graph)
    interfaces = build_interfaces()
    predicates = build_predicates(graph)
    qualifiers = build_qualifiers()
    shapes = build_shapes()
    coverage = build_competency_questions()
    statement = build_statement_model()
    evidence = build_evidence_model()
    provenance = build_provenance_model()
    actions = build_actions()
    external = build_external_alignment()
    gap = build_gap_analysis(classes, predicates)

    artifacts = {
        "class_registry.json": classes,
        "interface_registry.json": interfaces,
        "property_registry.json": properties,
        "predicate_registry.json": predicates,
        "qualifier_registry.json": qualifiers,
        "statement_model.json": statement,
        "evidence_model.json": evidence,
        "provenance_model.json": provenance,
        "action_model.json": actions,
        "constraint_shapes.json": shapes,
        "external_alignment.json": external,
        "v1_v2_gap_analysis.json": gap,
        "competency_question_coverage.json": coverage,
    }
    for name, value in artifacts.items():
        _write(OUTPUT / name, value)

    after = protected_identity()
    changed = [name for name in before if before[name]["tree_sha256"] != after[name]["tree_sha256"]]
    current_types = Counter(node["record_type"] for node in graph["nodes"])
    current_predicates = Counter(edge["predicate"] for edge in graph["edges"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "checkpoint": "Scientific-Decision-Ontology-v2-Design-Audit",
        "status": "PASS" if not changed and 60 <= coverage["question_count"] <= 100 else "PARTIAL",
        "design_only": True,
        "production_migration": False,
        "checkpoint_5a_commit": CHECKPOINT_5A_COMMIT,
        "local_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "remote_head": subprocess.check_output(["git", "rev-parse", "origin/feature/method-kg-expansion-v1"], cwd=ROOT, text=True).strip(),
        "push_status": "VERIFIED" if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == subprocess.check_output(["git", "rev-parse", "origin/feature/method-kg-expansion-v1"], cwd=ROOT, text=True).strip() else "MISMATCH",
        "competency_questions": coverage["question_count"],
        "coverage": coverage["coverage_counts"],
        "physical_current_classes": len(current_types),
        "current_classes": len(classes["current_classes"]),
        "proposed_classes": len(classes["proposed_classes"]),
        "current_predicates": len(current_predicates),
        "proposed_predicates": len(predicates["proposed_predicates"]),
        "gap_counts": gap["counts"],
        "interfaces": len(interfaces["interfaces"]),
        "constraint_shapes": len(shapes["shapes"]),
        "external_alignments": len(external["external_models"]),
        "focused_tests": focused_tests,
        "bounded_regression_tests": bounded_regression_tests,
        "pdf_rerun": False,
        "external_llm_called": False,
        "quality_metrics": build_quality_metrics(),
        "primary_v1_gaps": [
            "Authoritative statement identity/revision and graph projections are not cleanly separated.",
            "Predicate registry contains duplicate projection/claim forms and incomplete domain/range semantics.",
            "Evidence support, provenance activities, evidence drift, and ontology drift are not governed end to end.",
            "Runtime state, scientific knowledge, and governed action exist across separate models without a shared interface contract.",
            "Pilot SourceWork/SourceRevision/SourceArtifact and review flows are not production ontology classes.",
        ],
        "protected_artifacts": after,
        "protected_changed_groups": changed,
        "production_ontology_changed": "production_ontology" in changed,
        "scientific_kg_changed": "scientific_kg" in changed,
        "rag_changed": "rag" in changed,
        "planner_changed": "planner" in changed,
        "studio_extractor_changed": "studio_extractor" in changed,
        "quarantined_c7_payload_accessed": False,
        "next_recommended_checkpoint": "Ontology v2 Human Review / EvidenceSpan + AtomicClaim Quality Gate after ontology freeze",
        "stopped": True,
    }
    _write(OUTPUT / "manifest.json", manifest)
    CQ_DOC.write_text(render_cq_doc(coverage), encoding="utf-8")
    DESIGN_DOC.write_text(render_design_doc(manifest, gap, predicates), encoding="utf-8")

    manifest["artifacts"] = {
        path.name: _sha(path)
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "manifest.json"
    }
    manifest["documents"] = {
        str(DESIGN_DOC.relative_to(ROOT)): _sha(DESIGN_DOC),
        str(CQ_DOC.relative_to(ROOT)): _sha(CQ_DOC),
    }
    _write(OUTPUT / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--focused-tests", default="PENDING")
    parser.add_argument("--bounded-regression-tests", default="PENDING")
    args = parser.parse_args()
    print(json.dumps(generate(focused_tests=args.focused_tests, bounded_regression_tests=args.bounded_regression_tests), ensure_ascii=False, indent=2))
