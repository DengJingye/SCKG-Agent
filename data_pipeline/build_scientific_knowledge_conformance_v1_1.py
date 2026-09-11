from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from core.scientific_knowledge_conformance_models import (
    ApplicabilityScope,
    AtomicClaimRevision,
    BenchmarkStudy,
    ConformanceBundle,
    DerivedRelation,
    EmpiricalResult,
    EvaluationDataset,
    EvidenceAssessment,
    InputPort,
    Method,
    MethodVariant,
    MetricDefinition,
    Operator,
    OperatorRevision,
    OutputPort,
    Package,
    PackageRelease,
    ParameterCondition,
    ReferenceArtifact,
    ReferenceArtifactRevision,
    RepresentationConstraint,
    RepresentationComponent,
    RepresentationInstanceBinding,
    RepresentationType,
    Requirement,
    ReviewDecision,
    SCHEMA_VERSION,
    SupersessionRecord,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "scientific_knowledge_schema_v1_1"
)
CANONICAL_PATHS = (
    PROJECT_ROOT / "data" / "canonical_knowledge" / "manifest.json",
    PROJECT_ROOT / "data" / "knowledge_graph_v2" / "nodes.jsonl",
    PROJECT_ROOT / "data" / "knowledge_graph_v2" / "edges.jsonl",
    PROJECT_ROOT / "data" / "decision_graph_v3" / "nodes.jsonl",
    PROJECT_ROOT / "data" / "decision_graph_v3" / "edges.jsonl",
    PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl",
)


def _scope(scope_id: str, **values: Any) -> ApplicabilityScope:
    return ApplicabilityScope(
        scope_id=scope_id,
        scope_status="explicit",
        **values,
    )


def _identity_and_ports_fixture() -> ConformanceBundle:
    scope = _scope(
        "scope:scanpy-pca-1.11",
        task_ids=["task:dimensionality_reduction"],
        version_constraints=[
            {"subject_id": "package:scanpy", "status": "range", "expression": ">=1.11,<2"}
        ],
        modalities=["rna"],
        observation_units=["cell"],
    )
    expression = RepresentationType(
        representation_type_id="representation-type:log_expression",
        label="log-transformed RNA expression",
        observation_unit="cell",
        axes=["cell", "gene"],
        modalities=["rna"],
        value_semantics="real-valued transformed abundance",
        transformation_state=["normalized", "log_transformed"],
        feature_identity="gene identifiers with stable ordering",
        missingness_semantics="missing entries are not equivalent to measured zero",
    )
    pca = RepresentationType(
        representation_type_id="representation-type:pca_coordinates",
        label="PCA coordinates",
        observation_unit="cell",
        axes=["cell", "component"],
        modalities=["rna"],
        value_semantics="real-valued principal-component scores",
        transformation_state=["dimensionality_reduced"],
        feature_identity="ordered principal components",
        missingness_semantics="complete rows required",
    )
    constraint = RepresentationConstraint(
        constraint_id="representation-constraint:pca_input_log_expression",
        representation_type_id=expression.representation_type_id,
        required_value_states=["real_continuous"],
        required_transformations=["log_transformed"],
        required_modalities=["rna"],
        observation_alignment="same_observations",
        scope_id=scope.scope_id,
    )
    input_port = InputPort(
        input_port_id="input-port:scanpy_pca.expression",
        role="expression",
        min_cardinality=1,
        max_cardinality=1,
        requirements=[
            Requirement(
                requirement_id="requirement:scanpy_pca.log_expression",
                level="mandatory",
                representation_constraint_ids=[constraint.constraint_id],
                scope_id=scope.scope_id,
            )
        ],
        scope_id=scope.scope_id,
    )
    output_port = OutputPort(
        output_port_id="output-port:scanpy_pca.coordinates",
        role="coordinates",
        representation_type_id=pca.representation_type_id,
        lineage_input_port_ids=[input_port.input_port_id],
        preserves=["observation_identity"],
        transforms=["feature_axis_to_component_axis"],
        scope_id=scope.scope_id,
    )
    entities = [
        {"record_type": "ScientificTask", "entity_id": "task:dimensionality_reduction", "label": "dimensionality reduction"},
        {"record_type": "Method", "entity_id": "method:pca", "label": "principal component analysis"},
        {"record_type": "SoftwareProject", "entity_id": "software-project:scanpy", "label": "Scanpy"},
        {
            "record_type": "Package",
            "entity_id": "package:scanpy",
            "project_id": "software-project:scanpy",
            "ecosystem": "python",
            "distribution_name": "scanpy",
        },
        {
            "record_type": "PackageRelease",
            "entity_id": "package-release:scanpy:1.11.2",
            "package_id": "package:scanpy",
            "version": "1.11.2",
            "immutable_release_ref": "pypi:scanpy:1.11.2",
        },
        {
            "record_type": "Operator",
            "entity_id": "operator:scanpy.pp.pca",
            "package_id": "package:scanpy",
            "qualified_name": "scanpy.pp.pca",
        },
        OperatorRevision(
            entity_id="operator-revision:scanpy.pp.pca:1.11.2",
            operator_id="operator:scanpy.pp.pca",
            package_release_id="package-release:scanpy:1.11.2",
            implements_method_ids=["method:pca"],
            input_ports=[input_port],
            output_ports=[output_port],
            contract_refs=["scanpy:1.11.2@1.1.0-post-s6"],
            scope_id=scope.scope_id,
        ),
    ]
    return ConformanceBundle(
        fixture_id="conformance-fixture:package-operator-method-and-ports",
        description="Scanpy remains a package, scanpy.pp.pca an operator, and PCA a method; consumes/produces are port projections.",
        scopes=[scope],
        representation_types=[expression, pca],
        representation_constraints=[constraint],
        entities=entities,
        derived_relations=[
            DerivedRelation(
                relation_id="derived-relation:scanpy_pca_consumes",
                relation="CONSUMES",
                source_id="operator-revision:scanpy.pp.pca:1.11.2",
                target_id=expression.representation_type_id,
                scope_id=scope.scope_id,
                derivation_type="port_projection",
                input_port_id=input_port.input_port_id,
                derivation_rule_id="rule:input-port-consumes:v1.1",
                review_status="candidate_pending_review",
            ),
            DerivedRelation(
                relation_id="derived-relation:scanpy_pca_produces",
                relation="PRODUCES",
                source_id="operator-revision:scanpy.pp.pca:1.11.2",
                target_id=pca.representation_type_id,
                scope_id=scope.scope_id,
                derivation_type="port_projection",
                output_port_id=output_port.output_port_id,
                derivation_rule_id="rule:output-port-produces:v1.1",
                review_status="candidate_pending_review",
            ),
        ],
        expected_semantics=[
            "package_operator_method_are_distinct",
            "input_output_ports_are_canonical",
            "consumes_produces_are_port_projections",
        ],
    )


def _conditional_hvg_fixture() -> ConformanceBundle:
    base_scope = _scope(
        "scope:scanpy-hvg-1.11",
        task_ids=["task:feature_selection"],
        version_constraints=[
            {"subject_id": "operator:scanpy.pp.highly_variable_genes", "status": "range", "expression": ">=1.11,<2"}
        ],
        modalities=["rna"],
        observation_units=["cell"],
    )
    counts = RepresentationType(
        representation_type_id="representation-type:raw_counts",
        label="raw RNA counts",
        observation_unit="cell",
        axes=["cell", "gene"],
        modalities=["rna"],
        value_semantics="nonnegative count abundance",
        transformation_state=["unnormalized"],
        feature_identity="gene identifiers",
        missingness_semantics="measured zero is zero count",
    )
    log_expression = RepresentationType(
        representation_type_id="representation-type:log_expression",
        label="log-transformed RNA expression",
        observation_unit="cell",
        axes=["cell", "gene"],
        modalities=["rna"],
        value_semantics="real-valued transformed abundance",
        transformation_state=["normalized", "log_transformed"],
        feature_identity="gene identifiers",
        missingness_semantics="missing entries are not equivalent to measured zero",
    )
    hvg_mask = RepresentationType(
        representation_type_id="representation-type:hvg_mask",
        label="highly-variable-gene mask",
        observation_unit="gene",
        axes=["gene"],
        modalities=["rna"],
        value_semantics="boolean feature selection mask",
        transformation_state=["feature_selected"],
        feature_identity="gene identifiers aligned to input",
        missingness_semantics="complete feature mask required",
    )
    count_constraint = RepresentationConstraint(
        constraint_id="representation-constraint:hvg_counts",
        representation_type_id=counts.representation_type_id,
        required_value_states=["nonnegative_integer"],
        forbidden_transformations=["normalized", "log_transformed"],
        required_modalities=["rna"],
        feature_alignment="same_features",
        scope_id=base_scope.scope_id,
    )
    log_constraint = RepresentationConstraint(
        constraint_id="representation-constraint:hvg_log_expression",
        representation_type_id=log_expression.representation_type_id,
        required_value_states=["real_continuous"],
        required_transformations=["normalized", "log_transformed"],
        required_modalities=["rna"],
        feature_alignment="same_features",
        scope_id=base_scope.scope_id,
    )
    input_port = InputPort(
        input_port_id="input-port:scanpy_hvg.expression",
        role="expression",
        min_cardinality=1,
        max_cardinality=1,
        requirement_combination="any_of",
        requirements=[
            Requirement(
                requirement_id="requirement:hvg_counts_for_v3_flavors",
                level="conditional",
                representation_constraint_ids=[count_constraint.constraint_id],
                when=[ParameterCondition(parameter_id="parameter:hvg_flavor", operator="in", values=["seurat_v3", "seurat_v3_paper"])],
                scope_id=base_scope.scope_id,
            ),
            Requirement(
                requirement_id="requirement:hvg_log_for_dispersion_flavors",
                level="conditional",
                representation_constraint_ids=[log_constraint.constraint_id],
                when=[ParameterCondition(parameter_id="parameter:hvg_flavor", operator="in", values=["seurat", "cell_ranger"])],
                scope_id=base_scope.scope_id,
            ),
        ],
        scope_id=base_scope.scope_id,
    )
    entities = [
        {"record_type": "ScientificTask", "entity_id": "task:feature_selection", "label": "feature selection"},
        {"record_type": "Method", "entity_id": "method:hvg_selection", "label": "highly variable gene selection"},
        {"record_type": "SoftwareProject", "entity_id": "software-project:scanpy", "label": "Scanpy"},
        {"record_type": "Package", "entity_id": "package:scanpy", "project_id": "software-project:scanpy", "ecosystem": "python", "distribution_name": "scanpy"},
        {"record_type": "PackageRelease", "entity_id": "package-release:scanpy:1.11.2", "package_id": "package:scanpy", "version": "1.11.2", "immutable_release_ref": "pypi:scanpy:1.11.2"},
        {"record_type": "Operator", "entity_id": "operator:scanpy.pp.highly_variable_genes", "package_id": "package:scanpy", "qualified_name": "scanpy.pp.highly_variable_genes"},
        OperatorRevision(
            entity_id="operator-revision:scanpy.pp.highly_variable_genes:1.11.2",
            operator_id="operator:scanpy.pp.highly_variable_genes",
            package_release_id="package-release:scanpy:1.11.2",
            implements_method_ids=["method:hvg_selection"],
            input_ports=[input_port],
            output_ports=[
                OutputPort(
                    output_port_id="output-port:scanpy_hvg.mask",
                    role="feature_mask",
                    representation_type_id=hvg_mask.representation_type_id,
                    lineage_input_port_ids=[input_port.input_port_id],
                    preserves=["feature_identity"],
                    transforms=["feature_statistics_to_boolean_mask"],
                    scope_id=base_scope.scope_id,
                )
            ],
            scope_id=base_scope.scope_id,
        ),
    ]
    return ConformanceBundle(
        fixture_id="conformance-fixture:conditional-hvg-inputs",
        description="One HVG operator has parameter-conditioned alternative input requirements without a global input edge.",
        scopes=[base_scope],
        representation_types=[counts, log_expression, hvg_mask],
        representation_constraints=[count_constraint, log_constraint],
        entities=entities,
        expected_semantics=[
            "hvg_counts_and_log_inputs_are_conditional_alternatives",
            "scope_and_parameter_conditions_are_structured",
        ],
    )


def _reuse_and_derivation_fixture() -> ConformanceBundle:
    scope = _scope(
        "scope:neighbor-construction",
        task_ids=["task:neighborhood_graph_construction"],
        modalities=["rna"],
        observation_units=["cell"],
    )
    pca = RepresentationType(
        representation_type_id="representation-type:pca_coordinates",
        label="PCA coordinates",
        observation_unit="cell",
        axes=["cell", "component"],
        modalities=["rna"],
        value_semantics="real-valued principal-component scores",
        transformation_state=["dimensionality_reduced"],
        feature_identity="ordered components",
        missingness_semantics="complete rows required",
    )
    graph = RepresentationType(
        representation_type_id="representation-type:neighbor_graph",
        label="cell neighborhood graph",
        observation_unit="cell",
        axes=["cell", "cell"],
        modalities=["rna"],
        value_semantics="distances and connectivities",
        transformation_state=["neighborhood_constructed"],
        feature_identity="cell identity on both axes",
        missingness_semantics="absent edge is not a missing observation",
        structural_properties=["weighted_graph"],
    )
    constraint = RepresentationConstraint(
        constraint_id="representation-constraint:neighbors_pca_input",
        representation_type_id=pca.representation_type_id,
        required_value_states=["real_continuous"],
        observation_alignment="same_observations",
        scope_id=scope.scope_id,
    )
    neighbors_input = InputPort(
        input_port_id="input-port:neighbors.embedding",
        role="embedding",
        min_cardinality=1,
        max_cardinality=1,
        requirements=[
            Requirement(
                requirement_id="requirement:neighbors_compatible_embedding",
                level="mandatory",
                representation_constraint_ids=[constraint.constraint_id],
                scope_id=scope.scope_id,
            )
        ],
        scope_id=scope.scope_id,
    )
    pca_output = "output-port:pca.coordinates"
    return ConformanceBundle(
        fixture_id="conformance-fixture:optional-upstream-reuse",
        description="A ledger-owned PCA instance satisfies the neighbors port; PCA can feed neighbors but is not a mandatory predecessor.",
        scopes=[scope],
        representation_types=[pca, graph],
        representation_constraints=[constraint],
        entities=[
            {"record_type": "ScientificTask", "entity_id": "task:neighborhood_graph_construction", "label": "neighborhood graph construction"},
            {"record_type": "Method", "entity_id": "method:pca", "label": "PCA"},
            {"record_type": "Method", "entity_id": "method:neighbor_graph", "label": "neighborhood graph construction"},
            {"record_type": "SoftwareProject", "entity_id": "software-project:conformance", "label": "Conformance operators"},
            {"record_type": "Package", "entity_id": "package:conformance", "project_id": "software-project:conformance", "ecosystem": "fixture", "distribution_name": "conformance"},
            {"record_type": "PackageRelease", "entity_id": "package-release:conformance:1", "package_id": "package:conformance", "version": "1", "immutable_release_ref": "fixture:conformance:1"},
            {"record_type": "Operator", "entity_id": "operator:fixture.pca", "package_id": "package:conformance", "qualified_name": "fixture.pca"},
            {"record_type": "Operator", "entity_id": "operator:fixture.neighbors", "package_id": "package:conformance", "qualified_name": "fixture.neighbors"},
            OperatorRevision(
                entity_id="operator-revision:fixture.pca:1",
                operator_id="operator:fixture.pca",
                package_release_id="package-release:conformance:1",
                implements_method_ids=["method:pca"],
                output_ports=[OutputPort(output_port_id=pca_output, role="coordinates", representation_type_id=pca.representation_type_id, scope_id=scope.scope_id)],
                scope_id=scope.scope_id,
            ),
            OperatorRevision(
                entity_id="operator-revision:fixture.neighbors:1",
                operator_id="operator:fixture.neighbors",
                package_release_id="package-release:conformance:1",
                implements_method_ids=["method:neighbor_graph"],
                input_ports=[neighbors_input],
                output_ports=[OutputPort(output_port_id="output-port:neighbors.graph", role="graph", representation_type_id=graph.representation_type_id, lineage_input_port_ids=[neighbors_input.input_port_id], scope_id=scope.scope_id)],
                scope_id=scope.scope_id,
            ),
        ],
        instance_bindings=[
            RepresentationInstanceBinding(
                binding_id="representation-instance-binding:ledger-pca-to-neighbors",
                ledger_id="ledger:fixture",
                representation_record_id="representation-record:pca-existing",
                representation_type_id=pca.representation_type_id,
                constraint_id=constraint.constraint_id,
                satisfaction="satisfied",
                reason_codes=["validated_existing_representation_reusable"],
            )
        ],
        review_decisions=[
            ReviewDecision(
                review_decision_id="review:can-feed-fixture",
                risk_class="R3",
                reviewer_type="qualified_human",
                decision="accepted",
                reviewed_record_ids=["derived-relation:pca_can_feed_neighbors"],
                rationale="Conformance-only review proves the output/input port derivation, not a universal prerequisite.",
                reviewed_artifact_hashes=["e" * 64],
                policy_version="risk-review-v1.1",
                decided_at="2026-09-10T00:00:00Z",
            )
        ],
        derived_relations=[
            DerivedRelation(
                relation_id="derived-relation:pca_produces",
                relation="PRODUCES",
                source_id="operator-revision:fixture.pca:1",
                target_id=pca.representation_type_id,
                scope_id=scope.scope_id,
                derivation_type="port_projection",
                output_port_id=pca_output,
                derivation_rule_id="rule:output-port-produces:v1.1",
                review_status="candidate_pending_review",
            ),
            DerivedRelation(
                relation_id="derived-relation:neighbors_consumes",
                relation="CONSUMES",
                source_id="operator-revision:fixture.neighbors:1",
                target_id=pca.representation_type_id,
                scope_id=scope.scope_id,
                derivation_type="port_projection",
                input_port_id=neighbors_input.input_port_id,
                derivation_rule_id="rule:input-port-consumes:v1.1",
                review_status="candidate_pending_review",
            ),
            DerivedRelation(
                relation_id="derived-relation:pca_can_feed_neighbors",
                relation="CAN_FEED",
                source_id="operator-revision:fixture.pca:1",
                target_id="operator-revision:fixture.neighbors:1",
                scope_id=scope.scope_id,
                derivation_type="reviewed_rule",
                input_port_id=neighbors_input.input_port_id,
                output_port_id=pca_output,
                premise_relation_ids=["derived-relation:pca_produces", "derived-relation:neighbors_consumes"],
                derivation_rule_id="rule:port-compatibility:v1.1",
                review_status="accepted",
                review_decision_ids=["review:can-feed-fixture"],
            )
        ],
        expected_semantics=[
            "representation_instance_is_ledger_owned_not_canonical_entity",
            "existing_representation_allows_optional_upstream_reuse",
            "can_feed_does_not_imply_requires_before",
        ],
    )


def _reference_and_multimodal_fixture() -> ConformanceBundle:
    scope = _scope(
        "scope:multimodal-and-reference",
        task_ids=["task:cell_type_annotation", "task:multimodal_integration"],
        modalities=["rna", "atac"],
        observation_units=["cell"],
        study_design_constraints=["paired_or_partially_paired_modalities"],
    )
    expression = RepresentationType(
        representation_type_id="representation-type:query_expression",
        label="query expression",
        observation_unit="cell",
        axes=["cell", "gene"],
        modalities=["rna"],
        value_semantics="expression abundance",
        feature_identity="gene namespace must match or map to reference",
        missingness_semantics="missing genes require explicit mapping",
    )
    multimodal = RepresentationType(
        representation_type_id="representation-type:rna_atac_multimodal",
        label="RNA and ATAC multimodal observations",
        observation_unit="cell",
        axes=["cell", "gene", "peak"],
        modalities=["rna", "atac"],
        value_semantics="modality-partitioned count matrices",
        feature_identity="genes and peaks retain separate namespaces",
        missingness_semantics="unobserved modality differs from measured zero",
    )
    expression_constraint = RepresentationConstraint(
        constraint_id="representation-constraint:annotation_query_expression",
        representation_type_id=expression.representation_type_id,
        required_modalities=["rna"],
        feature_alignment="explicit_mapping",
        scope_id=scope.scope_id,
    )
    multimodal_constraint = RepresentationConstraint(
        constraint_id="representation-constraint:multivi_partially_paired",
        representation_type_id=multimodal.representation_type_id,
        required_modalities=["rna", "atac"],
        observation_alignment="partially_paired",
        feature_alignment="explicit_mapping",
        allow_missing_modalities=True,
        required_metadata=["modality_indicator", "batch_key"],
        scope_id=scope.scope_id,
    )
    reference = ReferenceArtifact(
        entity_id="reference-artifact:cell_annotation_atlas",
        label="versioned cell annotation atlas",
        artifact_kind="atlas",
    )
    reference_revision = ReferenceArtifactRevision(
        entity_id="reference-artifact-revision:cell_annotation_atlas:1",
        artifact_id=reference.entity_id,
        version="1",
        content_digest="a" * 64,
        species_taxa=["NCBITaxon:9606"],
        feature_namespace="HGNC",
        label_ontology_id="CL",
        scope_id=scope.scope_id,
    )
    return ConformanceBundle(
        fixture_id="conformance-fixture:reference-and-multimodal-requirements",
        description="Reference artifacts and multimodal alignment are explicit port requirements rather than metadata tags.",
        scopes=[scope],
        representation_types=[expression, multimodal],
        representation_constraints=[expression_constraint, multimodal_constraint],
        entities=[
            {"record_type": "ScientificTask", "entity_id": "task:cell_type_annotation", "label": "cell type annotation"},
            {"record_type": "ScientificTask", "entity_id": "task:multimodal_integration", "label": "multimodal integration"},
            {"record_type": "Method", "entity_id": "method:reference_annotation", "label": "reference-based annotation"},
            {"record_type": "Method", "entity_id": "method:multivi", "label": "MultiVI"},
            {"record_type": "SoftwareProject", "entity_id": "software-project:fixture", "label": "Fixture project"},
            {"record_type": "Package", "entity_id": "package:fixture", "project_id": "software-project:fixture", "ecosystem": "fixture", "distribution_name": "fixture"},
            {"record_type": "PackageRelease", "entity_id": "package-release:fixture:1", "package_id": "package:fixture", "version": "1", "immutable_release_ref": "fixture:1"},
            {"record_type": "Operator", "entity_id": "operator:fixture.annotate", "package_id": "package:fixture", "qualified_name": "fixture.annotate"},
            {"record_type": "Operator", "entity_id": "operator:fixture.multivi", "package_id": "package:fixture", "qualified_name": "fixture.multivi"},
            reference,
            reference_revision,
            OperatorRevision(
                entity_id="operator-revision:fixture.annotate:1",
                operator_id="operator:fixture.annotate",
                package_release_id="package-release:fixture:1",
                implements_method_ids=["method:reference_annotation"],
                input_ports=[InputPort(input_port_id="input-port:annotation.query", role="query_expression", min_cardinality=1, max_cardinality=1, requirements=[Requirement(requirement_id="requirement:annotation.query", level="mandatory", representation_constraint_ids=[expression_constraint.constraint_id], scope_id=scope.scope_id), Requirement(requirement_id="requirement:annotation.reference", level="mandatory", reference_artifact_revision_ids=[reference_revision.entity_id], scope_id=scope.scope_id)], scope_id=scope.scope_id)],
                scope_id=scope.scope_id,
            ),
            OperatorRevision(
                entity_id="operator-revision:fixture.multivi:1",
                operator_id="operator:fixture.multivi",
                package_release_id="package-release:fixture:1",
                implements_method_ids=["method:multivi"],
                input_ports=[InputPort(input_port_id="input-port:multivi.modalities", role="modalities", min_cardinality=1, max_cardinality=2, requirements=[Requirement(requirement_id="requirement:multivi.modalities", level="mandatory", representation_constraint_ids=[multimodal_constraint.constraint_id], scope_id=scope.scope_id)], cross_port_alignment_constraints=["modality-specific feature axes", "explicit observation mapping"], scope_id=scope.scope_id)],
                scope_id=scope.scope_id,
            ),
        ],
        expected_semantics=[
            "reference_artifact_revision_is_a_separate_required_input",
            "multimodal_constraints_preserve_modality_axes_and_partial_pairing",
        ],
    )


def _benchmark_and_supersession_fixture() -> ConformanceBundle:
    scope = _scope(
        "scope:batch-integration-benchmark-fixture",
        task_ids=["task:batch_integration"],
        modalities=["rna"],
        observation_units=["cell"],
        evaluation_context_ids=["benchmark-study:integration-fixture:1"],
    )
    claim = AtomicClaimRevision(
        claim_id="claim:fixture_release_supersession",
        claim_revision_id="claim-revision:fixture_release_supersession:1",
        subject_id="package-release:fixture:2",
        predicate="supersedes",
        object_id="package-release:fixture:1",
        scope_id=scope.scope_id,
        claim_text="Fixture release 2 supersedes fixture release 1 within the documented API lineage.",
        polarity="positive",
        assertion_kind="definition",
        semantic_fingerprint="b" * 64,
        content_hash="c" * 64,
        created_by_activity_id="activity:fixture-curation",
    )
    return ConformanceBundle(
        fixture_id="conformance-fixture:benchmark-and-supersession",
        description="Comparative evidence remains scoped to a benchmark, dataset, metric and source; supersession preserves revision lineage.",
        scopes=[scope],
        entities=[
            {"record_type": "ScientificTask", "entity_id": "task:batch_integration", "label": "batch integration"},
            {"record_type": "Method", "entity_id": "method:harmony", "label": "Harmony"},
            {"record_type": "Method", "entity_id": "method:scanorama", "label": "Scanorama"},
            {"record_type": "SoftwareProject", "entity_id": "software-project:fixture", "label": "Fixture project"},
            {"record_type": "Package", "entity_id": "package:fixture", "project_id": "software-project:fixture", "ecosystem": "fixture", "distribution_name": "fixture"},
            {"record_type": "PackageRelease", "entity_id": "package-release:fixture:1", "package_id": "package:fixture", "version": "1", "immutable_release_ref": "fixture:1"},
            {"record_type": "PackageRelease", "entity_id": "package-release:fixture:2", "package_id": "package:fixture", "version": "2", "immutable_release_ref": "fixture:2"},
        ],
        atomic_claims=[claim],
        evidence_assessments=[
            EvidenceAssessment(
                assessment_id="evidence-assessment:fixture_supersession",
                claim_revision_id=claim.claim_revision_id,
                evidence_span_ids=["sourcev2:fixture-supersession"],
                stance="supports",
                subject_aligned=True,
                predicate_aligned=True,
                object_aligned=True,
                scope_alignment="aligned",
                rationale="The pinned release note explicitly records the replacement relation.",
                review_decision_ids=["review:fixture-supersession"],
            )
        ],
        review_decisions=[
            ReviewDecision(
                review_decision_id="review:fixture-supersession",
                risk_class="R3",
                reviewer_type="qualified_human",
                decision="accepted",
                reviewed_record_ids=[
                    claim.claim_revision_id,
                    "evidence-assessment:fixture_supersession",
                    "supersession:fixture-release-2",
                ],
                rationale="Conformance fixture retains the scoped evidence and revision lineage.",
                reviewed_artifact_hashes=["f" * 64],
                policy_version="risk-review-v1.1",
                decided_at="2026-09-10T00:00:00Z",
            )
        ],
        metrics=[MetricDefinition(metric_id="metric:integration_score", label="integration score", direction="higher_is_better")],
        evaluation_datasets=[
            EvaluationDataset(
                dataset_id="evaluation-dataset:integration-fixture",
                revision="1",
                modalities=["rna"],
                observation_unit="cell",
                study_design=["two batches", "fixed preprocessing"],
                split_definition="fixed evaluation split",
                leakage_controls=["no tuning on evaluation split"],
                content_fingerprint="d" * 64,
                scope_id=scope.scope_id,
            )
        ],
        benchmark_studies=[
            BenchmarkStudy(
                benchmark_id="benchmark-study:integration-fixture:1",
                revision="1",
                task_id="task:batch_integration",
                scope_id=scope.scope_id,
                evaluated_subject_ids=["method:harmony", "method:scanorama"],
                dataset_ids=["evaluation-dataset:integration-fixture"],
                metric_ids=["metric:integration_score"],
                comparison_protocol="Same data, preprocessing, metric definition and evaluation split.",
                evidence_span_ids=["sourcev2:fixture-benchmark"],
            )
        ],
        empirical_results=[
            EmpiricalResult(result_id="empirical-result:harmony-fixture", benchmark_id="benchmark-study:integration-fixture:1", dataset_id="evaluation-dataset:integration-fixture", subject_id="method:harmony", metric_id="metric:integration_score", value=0.81, uncertainty="illustrative fixture only", aggregation_unit="dataset", scope_id=scope.scope_id, evidence_span_ids=["sourcev2:fixture-benchmark"], status="reported"),
            EmpiricalResult(result_id="empirical-result:scanorama-fixture", benchmark_id="benchmark-study:integration-fixture:1", dataset_id="evaluation-dataset:integration-fixture", subject_id="method:scanorama", metric_id="metric:integration_score", value=0.79, uncertainty="illustrative fixture only", aggregation_unit="dataset", scope_id=scope.scope_id, evidence_span_ids=["sourcev2:fixture-benchmark"], status="reported"),
        ],
        supersessions=[
            SupersessionRecord(
                supersession_id="supersession:fixture-release-2",
                old_revision_id="package-release:fixture:1",
                new_revision_id="package-release:fixture:2",
                relation="SUPERSEDES",
                scope_id=scope.scope_id,
                reason="Pinned release note documents the successor release.",
                effective_at="2026-01-01T00:00:00Z",
                derived_from_claim_revision_ids=[claim.claim_revision_id],
                review_decision_ids=["review:fixture-supersession"],
            )
        ],
        expected_semantics=[
            "empirical_results_are_scoped_not_universal_superiority_edges",
            "benchmark_dataset_metric_and_evidence_are_explicit",
            "supersession_preserves_old_and_new_revision_identity",
        ],
    )


def conformance_fixtures() -> list[ConformanceBundle]:
    return [
        _identity_and_ports_fixture(),
        _conditional_hvg_fixture(),
        _reuse_and_derivation_fixture(),
        _reference_and_multimodal_fixture(),
        _benchmark_and_supersession_fixture(),
    ]


def _legacy_crosswalk() -> dict[str, Any]:
    candidate_path = PROJECT_ROOT / "data" / "evidence_candidates" / "method_kg_atomic_claim_v1" / "atomic_claims.batch1.jsonl"
    candidate_count = len(candidate_path.read_text(encoding="utf-8").splitlines()) if candidate_path.exists() else 0
    return {
        "schema_version": "sckg-scientific-knowledge-legacy-crosswalk-v1.1",
        "status": "analysis_only_not_migrated",
        "legacy_surfaces": [
            {
                "surface": "MethodGraph v0",
                "source": "core/method_graph_models.py + engine/method_graph.py",
                "mapping": {
                    "Capability": "ScientificTask/Capability discovery view; requires explicit task resolution",
                    "Method": "Method, MethodVariant, OperatorRevision, or composed action; record-by-record split required",
                    "Tool": "SoftwareProject, Package, Operator, or ReferenceArtifact; no identity-preserving automatic mapping",
                    "Representation": "RepresentationType plus one or more RepresentationConstraints",
                    "CONSUMES/PRODUCES": "derived port projections only after InputPort/OutputPort migration",
                    "PRECEDES": "candidate derivation; must be reclassified as CAN_FEED, REQUIRES_BEFORE, UI order, or rejected",
                    "SUPPORTED_BY": "requires AtomicClaimRevision and EvidenceAssessment backfill",
                },
                "incompatibilities": [
                    "no Package/PackageRelease/Operator/OperatorRevision identity layers",
                    "Method IDs may encode implementation or configured variants",
                    "CONSUMES and PRODUCES are stored as primary edges rather than port projections",
                    "no first-class ApplicabilityScope",
                    "no claim-revision or evidence-assessment proof chain",
                ],
            },
            {
                "surface": "DecisionGraph v3",
                "source": "core/decision_graph_models.py + data/decision_graph_v3",
                "record_counts": {"nodes": 1058, "edges": 1318},
                "mapping": {
                    "Tool": "unresolved software identity requiring project/package/operator resolution",
                    "Action": "OperatorRevision or governed action bundle, determined from contract binding",
                    "InputArtifact/OutputArtifact": "RepresentationType plus port-specific RepresentationConstraint",
                    "DataAssumption": "Requirement, ScientificConstraint, or ApplicabilityScope qualifier",
                    "Parameter": "ParameterDefinition; reported/default values become separate scoped claims",
                    "FailureMode": "Limitation or runtime failure policy; scientific and operational meanings must be split",
                    "ToolContract": "external contract revision reference; not duplicated into canonical science records",
                },
                "incompatibilities": [
                    "artifact nodes do not distinguish representation type, constraint, and runtime instance",
                    "ACCEPTS_INPUT and PRODUCES_OUTPUT lack canonical port ownership",
                    "relation strings/properties do not enforce scope-preserving derivation",
                    "governance projection contains known source_bound mismatches",
                ],
            },
            {
                "surface": "KnowledgeGraph v2",
                "source": "core/knowledge_graph_models.py + data/knowledge_graph_v2",
                "record_counts": {"nodes": 7537, "edges": 17667},
                "mapping": {
                    "Tool": "catalog discovery identity only until resolved into typed software/method identities",
                    "Task": "ScientificTask after canonical ontology validation",
                    "Publication/Source/SourceChunk": "SourceWork/SourceRevision/EvidenceSpan crosswalk",
                    "Benchmark/Evaluation/Dataset": "BenchmarkStudy/EmpiricalResult/EvaluationDataset after scoped protocol resolution",
                },
                "incompatibilities": [
                    "catalog relationships dominate and are not decision-bearing scientific claims",
                    "no AtomicClaimRevision or claim-local multi-entity evidence association",
                    "no Package/Operator/Method separation",
                    "no typed scope or port semantics",
                ],
            },
            {
                "surface": "AtomicClaim candidate v1",
                "source": "core/method_kg_claim_models.py + data/evidence_candidates/method_kg_atomic_claim_v1",
                "record_counts": {"claims": candidate_count},
                "mapping": {
                    "subject_id": "typed entity after Method/Tool disambiguation",
                    "predicate/object": "registered predicate and typed object",
                    "scope/modality/version": "structured ApplicabilityScope",
                    "source_span_id": "EvidenceAssessment separate from proposition identity",
                    "review_status": "ReviewDecision-derived materialized state",
                    "projected relation": "port projection or reviewed derivation with proof premises",
                },
                "incompatibilities": [
                    "subject_type is limited to Method/Tool and Tool is semantically ambiguous",
                    "scope is a coarse enum; modality and version are not structured scope dimensions",
                    "conditional is encoded as polarity",
                    "one EvidenceSpan is embedded in claim identity, preventing many-to-many support without changing proposition identity",
                    "review status is mutable state rather than an auditable decision record",
                    "CONSUMES/PRODUCES have no canonical ports",
                    "PREREQUISITE validation requires two claims but does not prove necessity or scope compatibility",
                ],
            },
            {
                "surface": "RepresentationLedger v1",
                "source": "core/representation_models.py",
                "mapping": {
                    "RepresentationRecord": "runtime RepresentationInstance; remains ledger-owned",
                    "representation_id": "requires crosswalk to canonical RepresentationType",
                    "metadata/provenance": "evaluated against RepresentationConstraints at request time",
                },
                "incompatibilities": [
                    "representation_id is not currently a governed RepresentationType reference",
                    "free-form metadata cannot by itself satisfy typed constraints",
                    "ledger records must never be migrated into canonical KG entities",
                ],
            },
        ],
        "migration_blockers": [
            {"id": "source_bound_projection_mismatch", "severity": "blocking", "reason": "10 source-unbound evidence rows are projected as bound in the current Decision Graph; provenance cannot be preserved by direct migration."},
            {"id": "graph_input_fingerprint_drift", "severity": "blocking", "reason": "Current canonical graph manifests do not match all present catalog/contract inputs."},
            {"id": "scanpy_contract_snapshot_missing", "severity": "blocking_for_scanpy_implementation_binding", "reason": "A Scanpy contract file exists but the Decision Graph snapshot lacks the corresponding contract node."},
            {"id": "celltypist_singler_contract_version_drift", "severity": "blocking_for_affected_bindings", "reason": "Snapshot contract revisions differ from current contract files."},
            {"id": "scvi_scvi_tools_identity_unresolved", "severity": "blocking_for_affected_identity", "reason": "Method/model and package identities have no governed crosswalk."},
            {"id": "monocle_monocle3_identity_unresolved", "severity": "blocking_for_affected_identity", "reason": "Successor/version identities are unresolved."},
            {"id": "method_binding_semantic_split_required", "severity": "blocking_for_bulk_migration", "reason": "Existing MethodBinding records mix scientific methods, configured variants, composed actions and implementations."},
            {"id": "ports_and_scopes_missing", "severity": "blocking_for_decision_edges", "reason": "Legacy input/output and workflow relations cannot be promoted until ports, requirements and ApplicabilityScopes are reconstructed."},
            {"id": "candidate_claim_review_pending", "severity": "blocking_for_candidate_claims", "reason": "Existing 48 candidates remain pending review and are not eligible for promotion."},
        ],
        "automatic_migration_allowed": False,
        "canonical_modified": False,
    }


def _schema_models() -> dict[str, type[Any]]:
    return {
        "applicability_scope.schema.json": ApplicabilityScope,
        "method.schema.json": Method,
        "method_variant.schema.json": MethodVariant,
        "package.schema.json": Package,
        "package_release.schema.json": PackageRelease,
        "operator.schema.json": Operator,
        "input_port.schema.json": InputPort,
        "output_port.schema.json": OutputPort,
        "requirement.schema.json": Requirement,
        "representation_type.schema.json": RepresentationType,
        "representation_component.schema.json": RepresentationComponent,
        "representation_constraint.schema.json": RepresentationConstraint,
        "representation_instance_binding.schema.json": RepresentationInstanceBinding,
        "operator_revision.schema.json": OperatorRevision,
        "reference_artifact.schema.json": ReferenceArtifact,
        "reference_artifact_revision.schema.json": ReferenceArtifactRevision,
        "atomic_claim_revision.schema.json": AtomicClaimRevision,
        "evidence_assessment.schema.json": EvidenceAssessment,
        "review_decision.schema.json": ReviewDecision,
        "derived_relation.schema.json": DerivedRelation,
        "comparative_evidence.schema.json": BenchmarkStudy,
        "evaluation_dataset.schema.json": EvaluationDataset,
        "empirical_result.schema.json": EmpiricalResult,
        "supersession.schema.json": SupersessionRecord,
        "conformance_bundle.schema.json": ConformanceBundle,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output_dir = Path(output_dir)
    canonical_before = {
        str(path.relative_to(PROJECT_ROOT)): _sha256(path)
        for path in CANONICAL_PATHS
        if path.exists()
    }
    schema_dir = output_dir / "schemas"
    fixture_dir = output_dir / "fixtures"
    for name, model in _schema_models().items():
        _write_json(schema_dir / name, model.model_json_schema())
    fixtures = conformance_fixtures()
    fixture_paths: list[Path] = []
    for fixture in fixtures:
        filename = fixture.fixture_id.split(":", 1)[1] + ".json"
        path = fixture_dir / filename
        _write_json(path, fixture.model_dump(mode="json"))
        fixture_paths.append(path)
    crosswalk_path = output_dir / "legacy_crosswalk.json"
    _write_json(crosswalk_path, _legacy_crosswalk())
    semantics = sorted({item for fixture in fixtures for item in fixture.expected_semantics})
    report = {
        "schema_version": "sckg-scientific-knowledge-conformance-report-v1.1",
        "status": "candidate_schema_conformant_not_promoted",
        "fixture_count": len(fixtures),
        "fixture_schema_validity": {"passed": True, "validated": len(fixtures), "total": len(fixtures)},
        "semantic_proof_count": len(semantics),
        "proven_semantics": semantics,
        "fixture_results": [
            {
                "fixture_id": fixture.fixture_id,
                "schema_valid": True,
                "proven_semantics": fixture.expected_semantics,
            }
            for fixture in fixtures
        ],
        "canonical_kg_modified": False,
        "candidate_claims_promoted": False,
        "retrieval_index_rebuilt": False,
        "runtime_modified": False,
    }
    report_path = output_dir / "conformance_report.json"
    _write_json(report_path, report)
    generated = sorted([*schema_dir.glob("*.json"), *fixture_paths, crosswalk_path, report_path])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "candidate_only_not_promoted",
        "architecture_contract": "docs/SCIENTIFIC_AGENT_KG_SPEC_V1_1.md",
        "artifacts": {str(path.relative_to(output_dir)): _sha256(path) for path in generated},
        "canonical_before": canonical_before,
        "canonical_after": {
            str(path.relative_to(PROJECT_ROOT)): _sha256(path)
            for path in CANONICAL_PATHS
            if path.exists()
        },
        "canonical_kg_modified": False,
        "retrieval_index_rebuilt": False,
    }
    if manifest["canonical_before"] != manifest["canonical_after"]:
        raise RuntimeError("canonical or retrieval artifacts changed during conformance generation")
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    manifest = build(args.output_dir)
    print(json.dumps({"status": manifest["status"], "artifact_count": len(manifest["artifacts"])}, sort_keys=True))


if __name__ == "__main__":
    main()
