from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from core.scientific_knowledge_conformance_models import (
    ApplicabilityScope,
    AtomicClaimRevision,
    EvidenceAssessment,
    ReferenceArtifact,
    ReferenceArtifactRevision,
    RepresentationType,
    Requirement,
)
from core.scientific_ontology_v2_compatibility_models import (
    CompatibilityDiagnostics,
    CompatibilityResult,
    EvidenceAssessmentView,
    EvidenceCoreProvenance,
    EvidenceSpanCoreView,
    FROZEN_ONTOLOGY_VERSION,
    ReferenceResourceView,
    RelationCompatibilityView,
    RepresentationTypeView,
    RequirementCompatibilityView,
    ScopeCompatibilityView,
    ScopeQualifierView,
    SourceRecordProvenance,
    StatementRevisionView,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FROZEN_CORE_DIR = REPOSITORY_ROOT / "data" / "ontology" / "scientific_decision_ontology_v2_core"
AUTHORITATIVE_BASE_COMMIT = "46910b46b41fe83cc4b11316028db5bfd77647f9"

_T = TypeVar("_T", bound=BaseModel)

_LEGACY_PREDICATE_MAP = {
    "has_key_parameter": "has_parameter",
}
_LEGACY_RELATION_MAP = {
    "implemented_in_release": "bound_to_release",
    "has_key_parameter": "has_parameter",
    "requires_representation_constraint": "requires_constraint",
    "REVISION_OF_OPERATOR": "revision_of",
    "REVISION_OF_PACKAGE": "revision_of",
    "BOUND_TO_PACKAGE_RELEASE": "bound_to_release",
    "BELONGS_TO_PACKAGE": "belongs_to_package",
    "BELONGS_TO_PROJECT": "belongs_to_project",
    "VARIANT_OF_METHOD": "variant_of",
    "IMPLEMENTS_METHOD": "implements_method",
    "IMPLEMENTS_METHOD_VARIANT": "implements_method_variant",
    "HAS_INPUT_PORT": "has_input_port",
    "HAS_OUTPUT_PORT": "has_output_port",
    "HAS_REQUIREMENT": "has_requirement",
    "REQUIRES_CONSTRAINT": "requires_constraint",
    "CONSTRAINS_TYPE": "constrains_type",
    "OUTPUT_REPRESENTATION_TYPE": "output_type",
}
_DERIVED_RELATIONS = {"CONSUMES", "PRODUCES", "CAN_FEED", "consumes", "produces"}
_DEFERRED_RELATIONS = {"REQUIRES_BEFORE"}
_ID_PREFIX_TYPES = (
    ("operator-revision:", "OperatorRevision"),
    ("method-variant:", "MethodVariant"),
    ("parameter:", "ParameterDefinition"),
    ("requirement:", "Requirement"),
    ("scope:", "ApplicabilityScope"),
    ("representation-type:", "RepresentationType"),
    ("operator:", "Operator"),
    ("method:", "Method"),
    ("task:", "ScientificTask"),
)
_TEXT_FIELDS = ("exact_text", "source_excerpt", "source_local_excerpt", "bounded_excerpt")
_ARTIFACT_HASH_FIELDS = ("source_artifact_hash", "source_file_sha256", "artifact_sha256")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _source_id(record: Mapping[str, Any]) -> str:
    for key in (
        "claim_revision_id",
        "evidence_span_id",
        "assessment_id",
        "requirement_id",
        "relation_id",
        "graph_edge_id",
        "scope_id",
        "entity_id",
        "representation_type_id",
        "edge_id",
    ):
        if record.get(key):
            return str(record[key])
    return "unidentified-record"


def _provenance(
    record: Mapping[str, Any],
    *,
    source_layer_id: str,
    source_graph_node_id: str | None = None,
    source_status: str | None = None,
) -> SourceRecordProvenance:
    return SourceRecordProvenance(
        source_layer_id=source_layer_id,
        source_record_id=_source_id(record),
        source_schema_version=record.get("schema_version"),
        source_graph_node_id=source_graph_node_id,
        source_status=source_status,
    )


def _evidence_core_provenance(
    record: Mapping[str, Any],
    *,
    source_layer_id: str,
    source_graph_node_id: str | None = None,
) -> EvidenceCoreProvenance:
    return EvidenceCoreProvenance(
        source_layer_id=source_layer_id,
        source_record_id=_source_id(record),
        source_schema_version=record.get("schema_version"),
        source_graph_node_id=source_graph_node_id,
    )


def _as_dict(record: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, BaseModel):
        return record.model_dump(mode="json")
    return dict(record)


def _validated(model: type[_T], record: BaseModel | Mapping[str, Any]) -> tuple[_T | None, dict[str, Any]]:
    raw = _as_dict(record)
    try:
        return model.model_validate(raw), raw
    except ValidationError:
        return None, raw


def _id_type(record_id: str | None) -> str | None:
    if not record_id:
        return None
    return next((name for prefix, name in _ID_PREFIX_TYPES if record_id.startswith(prefix)), None)


class ScientificOntologyV2CompatibilityService:
    """Read-only, deterministic views over v1 scientific knowledge records.

    The service consumes the frozen 5C.1 design registries but never mutates or
    promotes source records. A compatibility result is qualification metadata,
    not a canonical v2 object and not a Planner or retrieval authorization.
    """

    def __init__(
        self,
        repository_root: Path | None = None,
        *,
        frozen_core_dir: Path | None = None,
    ) -> None:
        self._root = Path(repository_root or REPOSITORY_ROOT)
        self._frozen_core_dir = Path(
            frozen_core_dir
            or self._root / "data" / "ontology" / "scientific_decision_ontology_v2_core"
        )
        self._statement_model = self._read_frozen("statement_model.json")
        self._evidence_model = self._read_frozen("evidence_model.json")
        self._scope_policy = self._read_frozen("scope_policy.json")
        self._link_registry = self._read_frozen("link_type_registry.json")
        self._property_registry = self._read_frozen("property_registry.json")
        self._mapping = self._read_frozen("v1_v2_mapping_draft.json")
        versions = {
            artifact["ontology_version"]
            for artifact in (
                self._statement_model,
                self._evidence_model,
                self._scope_policy,
                self._link_registry,
                self._property_registry,
                self._mapping,
            )
        }
        if versions != {FROZEN_ONTOLOGY_VERSION}:
            raise ValueError("frozen_ontology_version_mismatch")
        if self._mapping.get("migration_implemented") is not False:
            raise ValueError("compatibility_baseline_must_not_be_a_migration")

        self._links = {row["predicate_id"]: row for row in self._link_registry["links"]}
        self._statement_predicates = {
            predicate
            for predicate, row in self._links.items()
            if row.get("statement_predicate_allowed") is True
        }
        self._assertion_properties = {
            row["property_id"]
            for row in self._property_registry["properties"]
            if row.get("assertion_allowed") is True
        }

    def _read_frozen(self, name: str) -> dict[str, Any]:
        path = self._frozen_core_dir / name
        return json.loads(path.read_text(encoding="utf-8"))

    def map_scope(
        self,
        scope: ApplicabilityScope | Mapping[str, Any],
        *,
        source_layer_id: str = "unspecified_v1_layer",
        source_graph_node_id: str | None = None,
        source_status: str | None = None,
        inline_qualifiers: Mapping[str, Iterable[Any]] | None = None,
    ) -> CompatibilityResult:
        validated, raw = _validated(ApplicabilityScope, scope)
        if validated is None:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_V1_SCOPE",),
            )

        dimensions: dict[str, list[Any]] = {
            "task": list(validated.task_ids),
            "version_constraint": [item.model_dump(mode="json") for item in validated.version_constraints],
            "modality": list(validated.modalities),
            "organism_taxon": list(validated.organism_taxa),
            "biological_context": list(validated.biological_context_ids),
            "observation_unit": list(validated.observation_units),
            "assay": list(validated.assay_technology_ids),
            "study_design": list(validated.study_design_constraints),
            "representation_constraint": list(validated.representation_constraint_ids),
            "parameter_condition": [item.model_dump(mode="json") for item in validated.parameter_conditions],
            "resource_constraint": list(validated.resource_constraints),
            "evaluation_context": list(validated.evaluation_context_ids),
        }
        dimensions = {key: value for key, value in dimensions.items() if value}
        reason_codes = ["V1_SCOPE_FIELDS_NORMALIZED"]
        status = "COMPATIBLE_WITH_ADAPTER"

        if validated.valid_from is not None or validated.valid_to is not None:
            return CompatibilityResult(
                status="DEFERRED",
                reason_codes=("TEMPORAL_SCOPE_LINEAGE_DEFERRED",),
            )
        if validated.scope_status in {"unknown", "not_applicable"} and dimensions:
            return CompatibilityResult(
                status="AMBIGUOUS_MAPPING",
                reason_codes=("SCOPE_STATUS_CONFLICT",),
            )
        if validated.scope_status == "partially_known":
            return CompatibilityResult(
                status="AMBIGUOUS_MAPPING",
                reason_codes=("V1_PARTIAL_SCOPE_LACKS_UNKNOWN_DIMENSIONS",),
            )

        inline = {
            key: tuple(sorted({_canonical_json(item) for item in values}))
            for key, values in (inline_qualifiers or {}).items()
        }
        shared = {
            key: tuple(sorted({_canonical_json(item) for item in values}))
            for key, values in dimensions.items()
        }
        conflicts = sorted(key for key in set(inline) & set(shared) if inline[key] != shared[key])
        if conflicts:
            return CompatibilityResult(
                status="AMBIGUOUS_MAPPING",
                reason_codes=("INLINE_SHARED_SCOPE_CONFLICT", *conflicts),
            )

        shared_qualifiers = tuple(
            ScopeQualifierView(dimension=key, values_json=values)
            for key, values in sorted(shared.items())
        )
        inline_only = {key: values for key, values in inline.items() if key not in shared}
        inline_qualifier_views = tuple(
            ScopeQualifierView(dimension=key, values_json=values)
            for key, values in sorted(inline_only.items())
        )
        qualifiers = shared_qualifiers + inline_qualifier_views
        view = ScopeCompatibilityView(
            scope_id=validated.scope_id,
            source_scope_id=validated.scope_id,
            scope_status=validated.scope_status,
            combination="ALL_OF" if validated.combination == "all_of" else "ANY_OF",
            qualifiers=qualifiers,
            shared_qualifiers=shared_qualifiers,
            inline_qualifiers=inline_qualifier_views,
            composition="SHARED_AND_INLINE" if inline_qualifier_views else "SHARED_ONLY",
            provenance=_provenance(
                raw,
                source_layer_id=source_layer_id,
                source_graph_node_id=source_graph_node_id,
                source_status=source_status,
            ),
        )
        return CompatibilityResult(status=status, reason_codes=tuple(reason_codes), view=view)

    def map_atomic_claim(
        self,
        claim: AtomicClaimRevision | Mapping[str, Any],
        *,
        scope: ApplicabilityScope | Mapping[str, Any] | None,
        evidence_assessments: Iterable[EvidenceAssessment | Mapping[str, Any]] = (),
        source_layer_id: str = "unspecified_v1_layer",
        source_graph_node_id: str | None = None,
        source_status: str | None = None,
        inline_qualifiers: Mapping[str, Iterable[Any]] | None = None,
        literal_datatype: str | None = None,
    ) -> CompatibilityResult:
        validated, raw = _validated(AtomicClaimRevision, claim)
        if validated is None:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_V1_ATOMIC_CLAIM",),
            )
        expected_hash = hashlib.sha256(validated.claim_text.encode("utf-8")).hexdigest()
        if expected_hash != validated.content_hash:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("CLAIM_CONTENT_HASH_MISMATCH",),
            )
        if validated.predicate == "effect_description":
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("EFFECT_DESCRIPTION_DISPLAY_ONLY",),
            )

        predicate = _LEGACY_PREDICATE_MAP.get(validated.predicate, validated.predicate)
        allowed = self._statement_predicates | self._assertion_properties
        if predicate not in allowed:
            reason = (
                "KNOWN_NON_STATEMENT_RELATION"
                if predicate in self._links or validated.predicate in _LEGACY_RELATION_MAP
                else "UNKNOWN_PREDICATE"
            )
            status = "AMBIGUOUS_MAPPING" if reason == "KNOWN_NON_STATEMENT_RELATION" else "NOT_MAPPABLE"
            return CompatibilityResult(status=status, reason_codes=(reason, validated.predicate))

        is_property = predicate in self._assertion_properties
        if is_property and validated.object_id is not None:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("SCALAR_PROPERTY_REQUIRES_LITERAL_OBJECT", predicate),
            )
        if not is_property and validated.object_value is not None:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("ENTITY_PREDICATE_REQUIRES_ENTITY_OBJECT", predicate),
            )
        literal_datatype_unavailable = is_property and literal_datatype is None
        literal_reason = self._validate_property_literal(
            predicate, validated.object_value, literal_datatype
        )
        if literal_reason:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=(literal_reason, predicate),
            )
        endpoint_reason = self._validate_statement_endpoints(
            predicate, validated.subject_id, validated.object_id
        )
        if endpoint_reason:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=(endpoint_reason,),
            )
        if scope is None:
            return CompatibilityResult(
                status="AMBIGUOUS_MAPPING",
                reason_codes=("SCOPE_RECORD_UNAVAILABLE",),
            )
        scope_result = self.map_scope(
            scope,
            source_layer_id=source_layer_id,
            inline_qualifiers=inline_qualifiers,
        )
        if scope_result.status not in {"DIRECT_COMPATIBLE", "COMPATIBLE_WITH_ADAPTER"}:
            return CompatibilityResult(
                status=scope_result.status,
                reason_codes=("CLAIM_SCOPE_NOT_COMPATIBLE", *scope_result.reason_codes),
            )
        scope_view = scope_result.view
        assert isinstance(scope_view, ScopeCompatibilityView)
        if validated.scope_id != scope_view.source_scope_id:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=(
                    "SCOPE_IDENTITY_MISMATCH",
                    validated.scope_id,
                    scope_view.source_scope_id,
                ),
            )
        disallowed_dimensions = self._disallowed_scope_dimensions(predicate, scope_view)
        if disallowed_dimensions:
            return CompatibilityResult(
                status="AMBIGUOUS_MAPPING",
                reason_codes=(
                    "PREDICATE_SCOPE_DIMENSION_NOT_ALLOWED",
                    *disallowed_dimensions,
                ),
            )

        evidence_span_ids: list[str] = []
        for assessment in evidence_assessments:
            assessment_model, _ = _validated(EvidenceAssessment, assessment)
            if assessment_model and assessment_model.claim_revision_id == validated.claim_revision_id:
                evidence_span_ids.extend(assessment_model.evidence_span_ids)
        evidence_span_ids = sorted(set(evidence_span_ids))
        status = (
            "DIRECT_COMPATIBLE"
            if predicate == validated.predicate
            else "COMPATIBLE_WITH_ADAPTER"
        )
        reasons = [
            "V1_ATOMIC_CLAIM_ASSERTION_TO_ASSERTED_EPISTEMIC_STATUS",
            "V1_SCOPE_PRESERVED_AS_SHARED_SCOPE_REF",
        ]
        if status == "COMPATIBLE_WITH_ADAPTER":
            reasons.append("LEGACY_PREDICATE_MAPPED_BY_FROZEN_CROSSWALK")
        if literal_datatype_unavailable:
            status = "AMBIGUOUS_MAPPING"
            reasons.append("LITERAL_DATATYPE_UNAVAILABLE")
        view = StatementRevisionView(
            statement_id=validated.claim_id,
            statement_revision_id=validated.claim_revision_id,
            subject_id=validated.subject_id,
            predicate=predicate,
            source_predicate=validated.predicate,
            object_id=validated.object_id,
            literal_value=validated.object_value,
            literal_datatype=literal_datatype,
            polarity=validated.polarity.upper(),
            qualifiers=scope_view.inline_qualifiers,
            inline_qualifiers=scope_view.inline_qualifiers,
            context_composition=(
                "SHARED_SCOPE_AND_INLINE"
                if scope_view.inline_qualifiers
                else "SHARED_SCOPE_ONLY"
            ),
            scope_ref=scope_view.scope_id,
            scope_status=scope_view.scope_status,
            assertion_kind=validated.assertion_kind,
            semantic_fingerprint=validated.semantic_fingerprint,
            content=validated.claim_text,
            content_hash=validated.content_hash,
            supersedes_revision_ids=tuple(validated.supersedes_revision_ids),
            evidence_span_ids=tuple(evidence_span_ids),
            activity_ref=validated.created_by_activity_id,
            source_governance_status=source_status,
            provenance=_provenance(
                raw,
                source_layer_id=source_layer_id,
                source_graph_node_id=source_graph_node_id,
                source_status=source_status,
            ),
        )
        return CompatibilityResult(status=status, reason_codes=tuple(reasons), view=view)

    def _validate_property_literal(
        self,
        predicate: str,
        literal_value: str | None,
        literal_datatype: str | None,
    ) -> str | None:
        if predicate not in self._assertion_properties:
            return None
        if literal_value is None:
            return "SCALAR_PROPERTY_REQUIRES_LITERAL_OBJECT"
        if literal_datatype is None:
            return None
        property_row = next(
            row
            for row in self._property_registry["properties"]
            if row["property_id"] == predicate
        )
        value_type = property_row["value_type"]
        if value_type == "boolean":
            if literal_datatype != "boolean" or literal_value.casefold() not in {"true", "false"}:
                return "PROPERTY_LITERAL_TYPE_MISMATCH"
        elif literal_datatype != value_type:
            return "PROPERTY_LITERAL_TYPE_MISMATCH"
        return None

    def _disallowed_scope_dimensions(
        self, predicate: str, scope: ScopeCompatibilityView
    ) -> tuple[str, ...]:
        dimensions = {item.dimension for item in scope.qualifiers}
        if predicate in self._assertion_properties:
            row = next(
                item
                for item in self._property_registry["properties"]
                if item["property_id"] == predicate
            )
            allowed = set(row.get("assertion_qualifier_policy", {}).get("allowed", []))
        else:
            allowed = set(self._links[predicate].get("qualifier_policy", {}).get("allowed", []))
        accepted_dimensions = set(allowed)
        if {"software_version", "method_version"} & allowed:
            accepted_dimensions.add("version_constraint")
        return tuple(sorted(dimensions - accepted_dimensions))

    def _validate_statement_endpoints(
        self, predicate: str, subject_id: str, object_id: str | None
    ) -> str | None:
        if predicate in self._assertion_properties:
            owners = next(
                row["owners"]
                for row in self._property_registry["properties"]
                if row["property_id"] == predicate
            )
            return None if _id_type(subject_id) in owners else "INVALID_PROPERTY_SUBJECT_TYPE"
        link = self._links[predicate]
        pair = [_id_type(subject_id), _id_type(object_id)]
        return None if pair in link["allowed_endpoint_pairs"] else "INVALID_STATEMENT_ENDPOINT_PAIR"

    def map_evidence_span(
        self,
        record: Mapping[str, Any],
        *,
        source_layer_id: str = "unspecified_v1_layer",
        source_graph_node_id: str | None = None,
        source_status: str | None = None,
    ) -> CompatibilityResult:
        raw = dict(record)
        span_id = raw.get("evidence_span_id")
        locator = raw.get("locator")
        content_hash = raw.get("content_hash")
        exact_text = next((raw.get(key) for key in _TEXT_FIELDS if raw.get(key)), None)
        if not all(isinstance(value, str) and value for value in (span_id, locator, content_hash, exact_text)):
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_OR_INCOMPLETE_EVIDENCE_SPAN",),
            )
        if hashlib.sha256(exact_text.encode("utf-8")).hexdigest() != content_hash:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("EVIDENCE_TEXT_HASH_MISMATCH",),
            )
        artifact_hash = next((raw.get(key) for key in _ARTIFACT_HASH_FIELDS if raw.get(key)), None)
        if artifact_hash is not None and (
            not isinstance(artifact_hash, str)
            or len(artifact_hash) != 64
            or any(char not in "0123456789abcdef" for char in artifact_hash)
        ):
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_SOURCE_ARTIFACT_HASH",),
            )
        page = raw.get("page")
        line_start = raw.get("line_start")
        line_end = raw.get("line_end")
        start_offset = raw.get("start_offset")
        end_offset = raw.get("end_offset")
        if (page is not None and (not isinstance(page, int) or page < 1)) or (
            (line_start is None) != (line_end is None)
        ) or ((start_offset is None) != (end_offset is None)):
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_EVIDENCE_LOCATOR",),
            )
        try:
            view = EvidenceSpanCoreView(
                evidence_span_id=span_id,
                source_revision_id=raw.get("source_revision_id"),
                source_artifact_id=raw.get("source_artifact_id"),
                source_artifact_hash=artifact_hash,
                exact_text=exact_text,
                content_hash=content_hash,
                locator=locator,
                page=page,
                section=raw.get("section"),
                line_start=line_start,
                line_end=line_end,
                start_offset=start_offset,
                end_offset=end_offset,
                activity_ref=raw.get("activity_ref"),
                provenance=_evidence_core_provenance(
                    raw,
                    source_layer_id=source_layer_id,
                    source_graph_node_id=source_graph_node_id,
                ),
            )
        except ValidationError:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_EVIDENCE_LOCATOR",),
            )
        reasons = ["EVIDENCE_EXTERNAL_FIELDS_EXCLUDED"]
        if view.source_revision_id is None:
            reasons.append("SOURCE_REVISION_ID_UNAVAILABLE")
        if view.source_artifact_id is None:
            reasons.append("SOURCE_ARTIFACT_ID_UNAVAILABLE")
        status = "COMPATIBLE_WITH_ADAPTER"
        if len(reasons) > 1:
            status = "AMBIGUOUS_MAPPING"
        return CompatibilityResult(
            status=status,
            reason_codes=tuple(reasons),
            view=view,
            diagnostics=CompatibilityDiagnostics(legacy_source_status=source_status),
        )

    def map_evidence_assessment(
        self,
        assessment: EvidenceAssessment | Mapping[str, Any],
        *,
        statement_revision_ids: set[str],
        evidence_spans: Mapping[str, CompatibilityResult],
        source_layer_id: str = "unspecified_v1_layer",
        source_status: str | None = None,
    ) -> CompatibilityResult:
        validated, raw = _validated(EvidenceAssessment, assessment)
        if validated is None:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_V1_EVIDENCE_ASSESSMENT",),
            )
        if validated.claim_revision_id not in statement_revision_ids:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("STATEMENT_REVISION_NOT_AVAILABLE",),
            )
        missing = [span_id for span_id in validated.evidence_span_ids if span_id not in evidence_spans]
        invalid = []
        for span_id in validated.evidence_span_ids:
            if span_id not in evidence_spans:
                continue
            span_view = evidence_spans[span_id].view
            if (
                not isinstance(span_view, EvidenceSpanCoreView)
                or span_view.evidence_span_id != span_id
                or span_view.provenance.source_record_id != span_id
            ):
                invalid.append(span_id)
        if missing or invalid:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("EVIDENCE_SPAN_NOT_AVAILABLE", *(missing + invalid)),
            )
        support_type, exact = self._support_type(validated)
        reasons = ["V1_STANCE_MAPPED_WITH_EXPLICIT_ALIGNMENT"]
        status = "COMPATIBLE_WITH_ADAPTER" if exact else "AMBIGUOUS_MAPPING"
        if not exact:
            reasons.append("SUPPORT_SEMANTICS_NOT_EXACT")
        reasons.append("V2_ASSESSMENT_AUDIT_METADATA_UNAVAILABLE")
        status = "AMBIGUOUS_MAPPING"
        view = EvidenceAssessmentView(
            assessment_id=validated.assessment_id,
            statement_revision_id=validated.claim_revision_id,
            evidence_span_ids=tuple(validated.evidence_span_ids),
            source_stance=validated.stance,
            support_type=support_type,
            subject_aligned=validated.subject_aligned,
            predicate_aligned=validated.predicate_aligned,
            object_aligned=validated.object_aligned,
            scope_alignment=validated.scope_alignment,
            rationale=validated.rationale,
            review_decision_ids=tuple(validated.review_decision_ids),
            provenance=_provenance(
                raw,
                source_layer_id=source_layer_id,
                source_status=source_status,
            ),
        )
        return CompatibilityResult(status=status, reason_codes=tuple(reasons), view=view)

    @staticmethod
    def _support_type(assessment: EvidenceAssessment) -> tuple[str, bool]:
        fully_aligned = (
            assessment.subject_aligned
            and assessment.predicate_aligned
            and assessment.object_aligned
            and assessment.scope_alignment == "aligned"
        )
        if assessment.stance == "supports":
            return ("DIRECT_SUPPORT", True) if fully_aligned else ("UNCERTAIN", False)
        if assessment.stance == "refutes":
            return ("REFUTES", True) if fully_aligned else ("UNCERTAIN", False)
        if assessment.stance == "partial_support":
            return "PARTIAL_SUPPORT", True
        if assessment.stance in {"mentions_only", "not_supporting"}:
            return "DOES_NOT_SUPPORT", True
        return "UNCERTAIN", False

    def map_requirement(
        self,
        requirement: Requirement | Mapping[str, Any],
        *,
        known_constraint_ids: set[str] | None = None,
        reference_revisions: Mapping[str, CompatibilityResult] | None = None,
        source_layer_id: str = "unspecified_v1_layer",
    ) -> CompatibilityResult:
        validated, raw = _validated(Requirement, requirement)
        if validated is None:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_V1_REQUIREMENT",),
            )
        if known_constraint_ids is not None:
            missing_constraints = sorted(
                set(validated.representation_constraint_ids) - known_constraint_ids
            )
            if missing_constraints:
                return CompatibilityResult(
                    status="NOT_MAPPABLE",
                    reason_codes=("REPRESENTATION_CONSTRAINT_NOT_AVAILABLE", *missing_constraints),
                )
        references = reference_revisions or {}
        missing_references = [
            item
            for item in validated.reference_artifact_revision_ids
            if item not in references or references[item].view is None
        ]
        if missing_references:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("REFERENCE_REVISION_NOT_AVAILABLE", *missing_references),
            )
        target_count = len(validated.representation_constraint_ids) + len(
            validated.reference_artifact_revision_ids
        )
        if target_count > 1:
            return CompatibilityResult(
                status="AMBIGUOUS_MAPPING",
                reason_codes=("V1_REQUIREMENT_TARGET_COMBINATION_UNSPECIFIED",),
            )
        strength_map = {
            "mandatory": "REQUIRED",
            "recommended": "RECOMMENDED",
            "optional": "OPTIONAL",
        }
        strength = strength_map.get(validated.level)
        if validated.level == "conditional":
            status = "AMBIGUOUS_MAPPING"
            reasons = ("CONDITIONAL_STRENGTH_CANNOT_BE_INFERRED",)
        else:
            status = "COMPATIBLE_WITH_ADAPTER"
            reasons = ("V1_REQUIREMENT_LEVEL_MAPPED_BY_FROZEN_POLICY",)
        view = RequirementCompatibilityView(
            requirement_id=validated.requirement_id,
            strength=strength,
            combination="ALL_OF" if target_count == 1 else None,
            activation_status="specified" if validated.when else "unconditional",
            when_json=tuple(_canonical_json(item.model_dump(mode="json")) for item in validated.when),
            representation_constraint_ids=tuple(validated.representation_constraint_ids),
            reference_artifact_revision_ids=tuple(validated.reference_artifact_revision_ids),
            scope_ref=validated.scope_id,
            provenance=_provenance(raw, source_layer_id=source_layer_id),
        )
        return CompatibilityResult(status=status, reason_codes=reasons, view=view)

    def map_reference_resource(
        self,
        artifact: ReferenceArtifact | Mapping[str, Any],
        *,
        revision: ReferenceArtifactRevision | Mapping[str, Any] | None = None,
        source_layer_id: str = "unspecified_v1_layer",
    ) -> CompatibilityResult:
        artifact_model, artifact_raw = _validated(ReferenceArtifact, artifact)
        if artifact_model is None:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_REFERENCE_ARTIFACT",),
            )
        revision_model = None
        if revision is not None:
            revision_model, _ = _validated(ReferenceArtifactRevision, revision)
            if revision_model is None:
                return CompatibilityResult(
                    status="NOT_MAPPABLE",
                    reason_codes=("INVALID_REFERENCE_ARTIFACT_REVISION",),
                )
            if revision_model.artifact_id != artifact_model.entity_id:
                return CompatibilityResult(
                    status="NOT_MAPPABLE",
                    reason_codes=("CROSS_FAMILY_REFERENCE_REVISION",),
                )
        view = ReferenceResourceView(
            artifact_id=artifact_model.entity_id,
            label=artifact_model.label,
            artifact_kind=artifact_model.artifact_kind,
            artifact_revision_id=revision_model.entity_id if revision_model else None,
            version=revision_model.version if revision_model else None,
            content_digest=revision_model.content_digest if revision_model else None,
            species_taxa=tuple(revision_model.species_taxa) if revision_model else (),
            feature_namespace=revision_model.feature_namespace if revision_model else None,
            label_ontology_id=revision_model.label_ontology_id if revision_model else None,
            scope_ref=revision_model.scope_id if revision_model else None,
            provenance=_provenance(artifact_raw, source_layer_id=source_layer_id),
        )
        return CompatibilityResult(
            status="COMPATIBLE_WITH_ADAPTER",
            reason_codes=("V1_REFERENCE_IDENTITY_PRESERVED",),
            view=view,
        )

    def map_representation_type(
        self,
        representation: RepresentationType | Mapping[str, Any],
        *,
        source_layer_id: str = "unspecified_v1_layer",
    ) -> CompatibilityResult:
        validated, raw = _validated(RepresentationType, representation)
        if validated is None:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("INVALID_V1_REPRESENTATION_TYPE",),
            )
        view = RepresentationTypeView(
            representation_type_id=validated.representation_type_id,
            label=validated.label,
            observation_unit=validated.observation_unit,
            axes=tuple(validated.axes),
            modalities=tuple(validated.modalities),
            value_semantics=validated.value_semantics,
            transformation_state=tuple(validated.transformation_state),
            feature_namespace=validated.feature_identity,
            missingness_semantics=validated.missingness_semantics,
            structural_properties=tuple(validated.structural_properties),
            components_json=tuple(
                _canonical_json(item.model_dump(mode="json")) for item in validated.components
            ),
            provenance=_provenance(raw, source_layer_id=source_layer_id),
        )
        return CompatibilityResult(
            status="COMPATIBLE_WITH_ADAPTER",
            reason_codes=("FEATURE_IDENTITY_MAPPED_TO_ABSTRACT_FEATURE_NAMESPACE",),
            view=view,
        )

    def classify_relation(
        self,
        relation: str | Mapping[str, Any],
        *,
        source_layer_id: str = "unspecified_v1_layer",
        source_status: str | None = None,
    ) -> CompatibilityResult:
        raw = {"relation": relation} if isinstance(relation, str) else dict(relation)
        source_relation = str(raw.get("relation") or raw.get("predicate") or "")
        if not source_relation:
            return CompatibilityResult(
                status="NOT_MAPPABLE",
                reason_codes=("MISSING_RELATION",),
            )
        semantic_subject_id = raw.get("semantic_subject_id") or raw.get("source_id")
        semantic_object_id = raw.get("semantic_object_id") or raw.get("target_id")
        if source_relation in _DERIVED_RELATIONS:
            view = RelationCompatibilityView(
                source_relation=source_relation,
                canonical_predicate=source_relation.casefold(),
                predicate_classification="DERIVED_PROJECTION",
                record_authority="DERIVED_RECORD",
                semantic_subject_id=semantic_subject_id,
                semantic_object_id=semantic_object_id,
                provenance=_provenance(raw, source_layer_id=source_layer_id, source_status=source_status),
            )
            return CompatibilityResult(
                status="COMPATIBLE_WITH_ADAPTER",
                reason_codes=("FROZEN_DERIVED_PROJECTION_POLICY",),
                view=view,
            )
        if source_relation in _DEFERRED_RELATIONS:
            view = RelationCompatibilityView(
                source_relation=source_relation,
                canonical_predicate=None,
                predicate_classification="UNRESOLVED_PREDICATE",
                record_authority="UNRESOLVED",
                semantic_subject_id=semantic_subject_id,
                semantic_object_id=semantic_object_id,
                provenance=_provenance(raw, source_layer_id=source_layer_id, source_status=source_status),
            )
            return CompatibilityResult(
                status="DEFERRED",
                reason_codes=("RELATION_DEFERRED_BY_FROZEN_CORE",),
                view=view,
            )
        is_legacy_alias = source_relation in _LEGACY_RELATION_MAP
        canonical = _LEGACY_RELATION_MAP.get(source_relation, source_relation.casefold())
        link = self._links.get(canonical)
        if link and link.get("classification") == "AUTHORITATIVE":
            endpoints = [
                raw.get("semantic_subject_type") or _id_type(semantic_subject_id),
                raw.get("semantic_object_type") or _id_type(semantic_object_id),
            ]
            if endpoints not in link["allowed_endpoint_pairs"]:
                view = RelationCompatibilityView(
                    source_relation=source_relation,
                    canonical_predicate=canonical,
                    predicate_classification="AUTHORITATIVE_LINK_TYPE",
                    record_authority="UNRESOLVED",
                    semantic_subject_id=semantic_subject_id,
                    semantic_object_id=semantic_object_id,
                    provenance=_provenance(
                        raw, source_layer_id=source_layer_id, source_status=source_status
                    ),
                )
                return CompatibilityResult(
                    status="NOT_MAPPABLE",
                    reason_codes=("INVALID_RELATION_ENDPOINT_PAIR",),
                    view=view,
                )
            record_authority = self._record_authority(source_status)
            view = RelationCompatibilityView(
                source_relation=source_relation,
                canonical_predicate=canonical,
                predicate_classification="AUTHORITATIVE_LINK_TYPE",
                record_authority=record_authority,
                semantic_subject_id=semantic_subject_id,
                semantic_object_id=semantic_object_id,
                provenance=_provenance(raw, source_layer_id=source_layer_id, source_status=source_status),
            )
            return CompatibilityResult(
                status=(
                    "DIRECT_COMPATIBLE"
                    if record_authority == "SUPPORTED_AUTHORITATIVE_RECORD"
                    else "COMPATIBLE_WITH_ADAPTER"
                ),
                reason_codes=(
                    (
                        "LEGACY_RELATION_CLASSIFIED_WITHOUT_AUTHORITY_PROMOTION"
                        if is_legacy_alias
                        else "FROZEN_AUTHORITATIVE_LINK_TYPE"
                    ),
                    "PREDICATE_CLASSIFICATION_DOES_NOT_PROMOTE_RECORD_AUTHORITY",
                ),
                view=view,
            )
        view = RelationCompatibilityView(
            source_relation=source_relation,
            canonical_predicate=None,
            predicate_classification="UNRESOLVED_PREDICATE",
            record_authority="UNRESOLVED",
            semantic_subject_id=semantic_subject_id,
            semantic_object_id=semantic_object_id,
            provenance=_provenance(raw, source_layer_id=source_layer_id, source_status=source_status),
        )
        return CompatibilityResult(
            status="NOT_MAPPABLE",
            reason_codes=("UNRESOLVED_RELATION",),
            view=view,
        )

    @staticmethod
    def _record_authority(source_status: str | None) -> str:
        status = (source_status or "").casefold()
        if "candidate" in status:
            return "CANDIDATE_RECORD"
        if status in {"accepted_authoritative", "reviewed_authoritative"}:
            return "SUPPORTED_AUTHORITATIVE_RECORD"
        return "UNRESOLVED"
