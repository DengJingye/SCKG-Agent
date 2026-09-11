from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from core.scientific_knowledge_conformance_models import (
    ApplicabilityScope,
    AtomicClaimRevision,
    ConformanceBundle,
    DerivedRelation,
    EvidenceAssessment,
    InputPort,
    Limitation,
    Method,
    MethodVariant,
    Operator,
    OperatorRevision,
    OutputPort,
    Package,
    PackageRelease,
    ParameterCondition,
    RepresentationComponent,
    RepresentationConstraint,
    RepresentationType,
    Requirement,
    ScientificTask,
    SoftwareProject,
    VersionConstraint,
)
from data_pipeline.build_scanpy_core_identity_port_candidate_v1_1 import (
    _authoritative_source_snapshot as _scanpy_authoritative_source_snapshot,
)
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import CANONICAL_PATHS, PROJECT_ROOT


SCHEMA_VERSION = "sckg-scientific-kg-v1-uat-decision-rules-candidate-v1"
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_kg_v1_uat_decision_rules"
)
FROZEN_CORE_DIR = PROJECT_ROOT / "data" / "evidence_candidates" / "scientific_kg_v1_core"


SOURCE_REVISIONS = {
    "harmony": {
        "source_revision_id": "source-revision:cran:harmony:2.0.5",
        "release_artifact_sha256": "907a3c4808656f6bad5a8e314704f92a0cb159ae298390315d5c73794d9a0c6c",
        "release_uri": "https://cran.r-project.org/src/contrib/harmony_2.0.5.tar.gz",
        "files": {
            "ui": {
                "path": "harmony/R/ui.R",
                "sha256": "edf98fad7061bf78bd48a307558e6f854d02ba8488676297a7230bd27814df87",
            },
            "run_harmony": {
                "path": "harmony/R/RunHarmony.R",
                "sha256": "f3b9423c90c84a0da2a3bd1a0af2c40f0e641c8a4807ed289521a0073011da10",
            },
        },
    },
    "scrublet": {
        "source_revision_id": "source-revision:pypi:scrublet:0.2.3",
        "release_artifact_sha256": "2185f63070290267f82a36e5b4cae8c321f10415d2d0c9f7e5e97b1126bf653a",
        "release_uri": "https://files.pythonhosted.org/packages/source/s/scrublet/scrublet-0.2.3.tar.gz",
        "files": {
            "readme": {
                "path": "scrublet-0.2.3/README.md",
                "sha256": "72f3b14a4966db3c50e77ee76f2386d6b0d9c08d5aa608eedca8f8b76f32e1f2",
            },
            "api": {
                "path": "scrublet-0.2.3/src/scrublet/scrublet.py",
                "sha256": "c2065e0acac00c405da36c2cc3fd9fc9453b907d5f66987a9efdee906181b1dc",
            },
        },
    },
    "singler": {
        "source_revision_id": "source-revision:bioconductor:SingleR:2.14.1",
        "release_artifact_sha256": "bdcd9a96d03f666259472c241460d06713834e0603eb7f8c9ebd31c6128aef56",
        "release_uri": "https://bioconductor.org/packages/release/bioc/src/contrib/SingleR_2.14.1.tar.gz",
        "files": {
            "single_r": {
                "path": "SingleR/R/SingleR.R",
                "sha256": "654d44be0e14a2b3ab1b89a5fe584efb3fd1e20c4f2d83201691fbddfaf51181",
            },
            "classify": {
                "path": "SingleR/R/classifySingleR.R",
                "sha256": "afc4c798893bcfbe9445beee9159b3838de220a44d86c65a38c9ad5bb3d91bc8",
            },
            "train": {
                "path": "SingleR/R/trainSingleR.R",
                "sha256": "e797670c89f4723af7e9ec7a2c2e82b2a02fb725e15675b0c8e62f45fb420da2",
            },
            "vignette": {
                "path": "SingleR/vignettes/SingleR.Rmd",
                "sha256": "256a7c631fb5e3b0247cd54ad990238ffafb201cb215e530a1d9a88773773f2d",
            },
        },
    },
    "sckg_profile": {
        "source_revision_id": "source-revision:sckg:capability-pack:scanpy-core:1.0.0",
        "release_artifact_sha256": "ee941316a6ebaef896f50bf9b4957bd935227c06a3e0971ff0ff2450d02abed2",
        "release_uri": "repository:capability_packs/scanpy_core/1.0.0/steps/scanpy_core_steps.json",
        "files": {
            "steps": {
                "path": "capability_packs/scanpy_core/1.0.0/steps/scanpy_core_steps.json",
                "sha256": "ee941316a6ebaef896f50bf9b4957bd935227c06a3e0971ff0ff2450d02abed2",
            }
        },
    },
}


AUTHORITATIVE_SPANS = [
    {
        "key": "harmony.generic_input",
        "source": "harmony",
        "file": "ui",
        "line_start": 3,
        "line_end": 15,
        "source_excerpt": "Use this generic with a cell embeddings matrix, a metadata table and a categorical covariate to run the Harmony algorithm directly on cell embedding matrix.",
    },
    {
        "key": "harmony.output",
        "source": "harmony",
        "file": "ui",
        "line_start": 51,
        "line_end": 62,
        "source_excerpt": "Whether to return the Harmony object or only the corrected PCA embeddings. By default, matrix with corrected PCA embeddings. If return_object is TRUE, returns the full Harmony object (R6 reference class type).",
    },
    {
        "key": "harmony.pca_default",
        "source": "harmony",
        "file": "run_harmony",
        "line_start": 39,
        "line_end": 51,
        "source_excerpt": "the Seurat object. It needs to have the appropriate slot of cell embeddings precomputed. Name of dimension reduction to use. Default is pca. Harmony dimensions placed into a new slot in the Seurat object according to the reduction.save. For downstream Seurat analyses, use reduction='harmony'.",
    },
    {
        "key": "scrublet.input_output",
        "source": "scrublet",
        "file": "readme",
        "line_start": 9,
        "line_end": 15,
        "source_excerpt": "Given a raw (unnormalized) UMI counts matrix counts_matrix with cells as rows and genes as columns, calculate a doublet score for each cell: doublet_scores, predicted_doublets = scrub.scrub_doublets().",
    },
    {
        "key": "scrublet.sample_scope",
        "source": "scrublet",
        "file": "readme",
        "line_start": 17,
        "line_end": 20,
        "source_excerpt": "When working with data from multiple samples, run Scrublet on each sample separately; inspect the doublet score threshold and adjust it manually if necessary.",
    },
    {
        "key": "scrublet.threshold",
        "source": "scrublet",
        "file": "api",
        "line_start": 130,
        "line_end": 135,
        "source_excerpt": "scrub_doublets automatically sets a threshold for calling doublets, but it is best to check it with plot_histogram and adjust it with call_doublets if necessary.",
    },
    {
        "key": "singler.interface",
        "source": "singler",
        "file": "single_r",
        "line_start": 1,
        "line_end": 14,
        "source_excerpt": "Returns the best annotation for each cell in a test dataset, given a labelled reference dataset in the same feature space. test A numeric matrix of single-cell expression values where rows are genes and columns are cells. ref A numeric matrix of (usually normalized and log-transformed) expression values from a reference dataset.",
    },
    {
        "key": "singler.feature_intersection",
        "source": "singler",
        "file": "single_r",
        "line_start": 35,
        "line_end": 38,
        "source_excerpt": "This function is just a convenient wrapper around trainSingleR and classifySingleR. The function will automatically restrict the analysis to the intersection of the genes in both ref and test. If this intersection is empty (e.g., because the two datasets use different gene annotations), an error will be raised.",
    },
    {
        "key": "singler.raw_query",
        "source": "singler",
        "file": "classify",
        "line_start": 63,
        "line_end": 65,
        "source_excerpt": "In practice, the raw counts (for UMI data) or the transcript counts (for read count data) can also be used without normalization and log-transformation. Any monotonic transformation will have no effect the calculation of the correlation values other than for some minor differences due to numerical precision.",
    },
    {
        "key": "singler.reference_labels",
        "source": "singler",
        "file": "train",
        "line_start": 3,
        "line_end": 12,
        "source_excerpt": "Train the SingleR classifier on one or more reference datasets with known labels. ref A numeric matrix of expression values where rows are genes and columns are reference samples (individual cells or bulk samples). labels A character vector or factor of known labels for all samples in ref.",
    },
    {
        "key": "singler.reference_state",
        "source": "singler",
        "file": "train",
        "line_start": 74,
        "line_end": 99,
        "source_excerpt": "This function uses a training data set to select interesting features and construct nearest neighbor indices in rank space. The automatic marker detection identifies genes that are differentially expressed between pairs of labels in the reference dataset. The expression values are expected to be log-transformed and normalized. Classification with classifySingleR assumes that the test dataset contains all marker genes that were detected from the reference.",
    },
    {
        "key": "singler.reference_applicability",
        "source": "singler",
        "file": "vignette",
        "line_start": 141,
        "line_end": 151,
        "source_excerpt": "Low deltas indicate that the assignment is uncertain, which is especially relevant if the cell's true label does not exist in the reference. The pruneScores() function will remove potentially poor-quality or ambiguous assignments based on the deltas.",
    },
    {
        "key": "sckg.pca_profile",
        "source": "sckg_profile",
        "file": "steps",
        "locator": "JSON item step_id=scanpy_core.pca_scaled",
        "source_excerpt": "{\"consumes\":[{\"representation_id\":\"scaled_hvg\"}],\"requires_matrix_state\":\"scaled_hvg\",\"step_id\":\"scanpy_core.pca_scaled\"}",
        "verification_method": "exact_structured_projection_from_pinned_json_item",
    },
]

SOURCE_LINE_SPAN_SHA256 = {
    "harmony.generic_input": "7a45e5ea11b2eb4194a87e3b978e1b8b3c29febd0167732b23fc79dc0a76011e",
    "harmony.output": "d7e19dca3c452e6b2b9698dd0c34bff7ef14a584697b117cbd0d1214ec4b3568",
    "harmony.pca_default": "8ad9ba99f15ac19f6cc957457e17645831f1a3afd952f3275420985839408e4c",
    "scrublet.input_output": "90b98e14d1d71c251ccb56963bc2b85fb0cbcdf7657b48ba9c77426e96a6ecca",
    "scrublet.sample_scope": "96c6d95398e9bf55ad7080ae763c20ee87571928c767e5971be4b326c5a0cd56",
    "scrublet.threshold": "c6c158b1c87b72c6b7efd657e67a6a1297c600b92334e2cbbd541b72bb6891eb",
    "singler.interface": "d2030d4eda4ae5aa89972741f6f5f5f38686c8b7aa2f2953ac97148763512bd0",
    "singler.feature_intersection": "1564afea806c68cc668616d972a9cb780832aa5dd9fe7703076bd6d01662efe5",
    "singler.raw_query": "9f4e677a43b7696de7a960a6d8796d9ecf3f4fb20c52f1e85fd49d84051067bd",
    "singler.reference_labels": "bf4883d0db241e86b3977190da29ae144e2e7d6cc29570f41e950f1c39e5b611",
    "singler.reference_state": "2d012ee2cac7f75511b6782e782b8944814b917aa6c3fcf4ff45f6bb455b2d22",
    "singler.reference_applicability": "99d967f8fa221421f5323b7fce83afa20d407029005717ae6a1a8ad1e9d73ee1",
}


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _canonical_hashes() -> dict[str, str]:
    return {str(path.relative_to(PROJECT_ROOT)): _sha_file(path) for path in CANONICAL_PATHS if path.exists()}


def _scope(
    scope_id: str,
    task_id: str,
    version_subject: str,
    version: str,
    *,
    study_design: list[str] | None = None,
    representation_constraint_ids: list[str] | None = None,
    parameter_conditions: list[ParameterCondition] | None = None,
) -> ApplicabilityScope:
    return ApplicabilityScope(
        scope_id=scope_id,
        task_ids=[task_id],
        version_constraints=[VersionConstraint(subject_id=version_subject, status="exact", expression=version)],
        modalities=["rna"],
        observation_units=["cell"],
        study_design_constraints=study_design or [],
        representation_constraint_ids=representation_constraint_ids or [],
        parameter_conditions=parameter_conditions or [],
        scope_status="explicit",
    )


def _rep(
    representation_type_id: str,
    label: str,
    axes: list[str],
    value_semantics: str,
    states: list[str],
    *,
    components: list[RepresentationComponent] | None = None,
) -> RepresentationType:
    return RepresentationType(
        representation_type_id=representation_type_id,
        label=label,
        observation_unit="cell",
        axes=axes,
        modalities=["rna"],
        value_semantics=value_semantics,
        transformation_state=states,
        feature_identity="ordered gene identifiers when a feature axis is present; otherwise inherited lineage",
        missingness_semantics="missing values are not permitted unless the operator explicitly documents them",
        components=components or [],
    )


def _constraint(
    constraint_id: str,
    type_id: str,
    scope_id: str,
    *,
    states: list[str] | None = None,
    transformations: list[str] | None = None,
    forbidden: list[str] | None = None,
    metadata: list[str] | None = None,
    components: list[str] | None = None,
    observation_alignment: str = "same_observations",
    feature_alignment: str = "not_applicable",
) -> RepresentationConstraint:
    return RepresentationConstraint(
        constraint_id=constraint_id,
        representation_type_id=type_id,
        required_value_states=states or [],
        required_transformations=transformations or [],
        forbidden_transformations=forbidden or [],
        required_modalities=["rna"],
        required_metadata=metadata or [],
        required_component_roles=components or [],
        observation_alignment=observation_alignment,
        feature_alignment=feature_alignment,
        scope_id=scope_id,
    )


def _requirement(
    requirement_id: str,
    scope_id: str,
    constraint_ids: list[str],
    *,
    level: str = "mandatory",
    when: list[ParameterCondition] | None = None,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        level=level,
        representation_constraint_ids=constraint_ids,
        when=when or [],
        scope_id=scope_id,
    )


def _input_port(
    input_port_id: str,
    role: str,
    scope_id: str,
    requirements: list[Requirement],
    *,
    combination: str = "all_of",
    min_cardinality: int = 1,
    alignment: list[str] | None = None,
) -> InputPort:
    return InputPort(
        input_port_id=input_port_id,
        role=role,
        min_cardinality=min_cardinality,
        max_cardinality=1,
        requirements=requirements,
        requirement_combination=combination,
        cross_port_alignment_constraints=alignment or [],
        scope_id=scope_id,
    )


def _output_port(
    output_port_id: str,
    role: str,
    type_id: str,
    scope_id: str,
    lineage: list[str],
    *,
    preserves: list[str],
    transforms: list[str],
) -> OutputPort:
    return OutputPort(
        output_port_id=output_port_id,
        role=role,
        representation_type_id=type_id,
        lineage_input_port_ids=lineage,
        preserves=preserves,
        transforms=transforms,
        invalidates=[],
        irreversible=False,
        scope_id=scope_id,
    )


def _source_snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scanpy_source, scanpy_spans = _scanpy_authoritative_source_snapshot()
    sources = [scanpy_source]
    for name, source in SOURCE_REVISIONS.items():
        sources.append(
            {
                "schema_version": "sckg-authoritative-source-revision-candidate-v1.1",
                "source_revision_id": source["source_revision_id"],
                "authority": "official_project_source" if name != "sckg_profile" else "project_governance_profile",
                "release_artifact_sha256": source["release_artifact_sha256"],
                "release_uri": source["release_uri"],
                "source_files": [
                    {"logical_name": key, **value}
                    for key, value in sorted(source["files"].items())
                ],
                "candidate_only": True,
                "retrieval_eligible": False,
            }
        )
    spans = [
        {
            **span,
            "source_bound": True,
            "verification_method": "exact_bounded_span_from_pinned_source",
        }
        for span in scanpy_spans
    ]
    for spec in AUTHORITATIVE_SPANS:
        source = SOURCE_REVISIONS[spec["source"]]
        source_file = source["files"][spec["file"]]
        span_id = f"uat-authoritative-span:{spec['key']}"
        locator = spec.get("locator")
        if locator is None:
            locator = f"{source_file['path']}#L{spec['line_start']}-L{spec['line_end']}"
        spans.append(
            {
                "schema_version": "sckg-authoritative-evidence-span-candidate-v1.1",
                "evidence_span_id": span_id,
                "source_revision_id": source["source_revision_id"],
                "source_path": source_file["path"],
                "source_file_sha256": source_file["sha256"],
                "locator": locator,
                "line_start": spec.get("line_start"),
                "line_end": spec.get("line_end"),
                "source_line_span_sha256": SOURCE_LINE_SPAN_SHA256.get(spec["key"]),
                "source_excerpt": spec["source_excerpt"],
                "content_hash": _sha_text(spec["source_excerpt"]),
                "verification_method": spec.get("verification_method", "exact_bounded_span_from_pinned_source"),
                "source_bound": True,
                "candidate_only": True,
                "retrieval_eligible": False,
                "review_status": "candidate_source_verified",
            }
        )
    return sources, spans


def _condition_matches(condition: ParameterCondition, parameters: dict[str, str]) -> bool:
    value = parameters.get(condition.parameter_id)
    if condition.operator == "present":
        return value is not None
    if condition.operator == "equals":
        return value in condition.values[:1]
    if condition.operator == "in":
        return value in condition.values
    return value not in condition.values


def constraint_matches(constraint: RepresentationConstraint, instance: dict[str, Any]) -> bool:
    if instance.get("representation_type_id") != constraint.representation_type_id:
        return False
    if not set(constraint.required_value_states) <= set(instance.get("value_states", [])):
        return False
    if not set(constraint.required_transformations) <= set(instance.get("transformations", [])):
        return False
    if set(constraint.forbidden_transformations) & set(instance.get("transformations", [])):
        return False
    if not set(constraint.required_modalities) <= set(instance.get("modalities", [])):
        return False
    if not set(constraint.required_metadata) <= set(instance.get("metadata", {})):
        return False
    if not set(constraint.required_component_roles) <= set(instance.get("component_roles", [])):
        return False
    if constraint.observation_alignment != "not_applicable" and instance.get("observation_alignment") != constraint.observation_alignment:
        return False
    if constraint.feature_alignment != "not_applicable" and instance.get("feature_alignment") != constraint.feature_alignment:
        return False
    return True


def port_accepts(
    port: InputPort,
    constraints: dict[str, RepresentationConstraint],
    instances: list[dict[str, Any]],
    parameters: dict[str, str] | None = None,
) -> bool:
    parameters = parameters or {}
    if port.min_cardinality == 0 and not instances:
        return True
    active = [
        requirement
        for requirement in port.requirements
        if requirement.level != "conditional"
        or all(_condition_matches(condition, parameters) for condition in requirement.when)
    ]
    if not active:
        return False
    matches = []
    for requirement in active:
        matched = any(
            constraint_matches(constraints[constraint_id], instance)
            for constraint_id in requirement.representation_constraint_ids
            for instance in instances
        )
        matches.append(True if requirement.level == "optional" and not matched else matched)
    return any(matches) if port.requirement_combination == "any_of" else all(matches)


def _build_knowledge() -> tuple[ConformanceBundle, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tasks = [
        ScientificTask(entity_id="task:feature_selection", label="highly variable feature selection"),
        ScientificTask(entity_id="task:dimensionality_reduction", label="dimensionality reduction"),
        ScientificTask(entity_id="task:neighbor_graph", label="neighbor graph construction"),
        ScientificTask(entity_id="task:embedding", label="graph embedding"),
        ScientificTask(entity_id="task:clustering", label="graph clustering"),
        ScientificTask(entity_id="task:batch_integration", label="batch integration"),
        ScientificTask(entity_id="task:doublet_detection", label="doublet detection"),
        ScientificTask(entity_id="task:cell_type_annotation", label="reference-based cell-type annotation"),
    ]

    scopes = [
        _scope("scope:uat:scanpy:hvg:1.11.2", "task:feature_selection", "package-release:scanpy:1.11.2", "1.11.2"),
        _scope("scope:uat:scanpy:hvg-dispersion:1.11.2", "task:feature_selection", "package-release:scanpy:1.11.2", "1.11.2", parameter_conditions=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat", "cell_ranger"])]),
        _scope("scope:uat:scanpy:hvg-count:1.11.2", "task:feature_selection", "package-release:scanpy:1.11.2", "1.11.2", parameter_conditions=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat_v3", "seurat_v3_paper"])]),
        _scope("scope:uat:scanpy:pca:1.11.2", "task:dimensionality_reduction", "package-release:scanpy:1.11.2", "1.11.2"),
        _scope("scope:uat:profile:scanpy-pca-scaled-hvg:1.0.0", "task:dimensionality_reduction", "source-revision:sckg:capability-pack:scanpy-core:1.0.0", "1.0.0", study_design=["project_profile_not_upstream_scanpy_fact"], representation_constraint_ids=["representation-constraint:uat:pca-profile-scaled-hvg"]),
        _scope("scope:uat:scanpy:neighbors:1.11.2", "task:neighbor_graph", "package-release:scanpy:1.11.2", "1.11.2"),
        _scope("scope:uat:scanpy:umap:1.11.2", "task:embedding", "package-release:scanpy:1.11.2", "1.11.2"),
        _scope("scope:uat:scanpy:leiden:1.11.2", "task:clustering", "package-release:scanpy:1.11.2", "1.11.2"),
        _scope("scope:uat:harmony:generic:2.0.5", "task:batch_integration", "package-release:harmony:2.0.5", "2.0.5", study_design=["generic_cell_embedding_interface"]),
        _scope("scope:uat:harmony:pca-default:2.0.5", "task:batch_integration", "package-release:harmony:2.0.5", "2.0.5", study_design=["Seurat_interface_defaults_to_pca"]),
        _scope("scope:uat:scrublet:0.2.3", "task:doublet_detection", "package-release:scrublet:0.2.3", "0.2.3", study_design=["one_capture_or_sample_unit_per_run", "droplet_umi_counts"]),
        _scope("scope:uat:singler:2.14.1", "task:cell_type_annotation", "package-release:singler:2.14.1", "2.14.1", study_design=["reference_labels_must_cover_biological_target_space"]),
    ]

    representations = [
        _rep("representation-type:expression_matrix", "expression matrix in X or a named layer", ["cell", "gene"], "numeric expression values with declared transformation state", ["state_declared"]),
        _rep("representation-type:raw_umi_counts", "raw UMI count matrix", ["cell", "gene"], "non-negative integer-like UMI counts", ["raw_counts"]),
        _rep("representation-type:log_expression", "log-transformed expression matrix", ["cell", "gene"], "logarithmized expression values", ["log1p"]),
        _rep("representation-type:hvg_mask", "highly-variable feature mask", ["gene"], "boolean feature-selection mask", ["feature_selected"]),
        _rep("representation-type:pca_coordinates", "PCA cell coordinates", ["cell", "principal_component"], "real-valued principal-component scores", ["dimension_reduced"]),
        _rep("representation-type:cell_embedding", "cell embedding", ["cell", "embedding_dimension"], "real-valued cell coordinates with declared provenance", ["dimension_reduced"]),
        _rep("representation-type:batch_covariates", "cell-aligned batch covariates", ["cell", "covariate"], "categorical integration covariates", ["metadata"]),
        _rep(
            "representation-type:neighbor_graph",
            "Scanpy neighbor graph",
            ["cell", "cell"],
            "neighbor connectivities, distances and construction metadata",
            ["graph_constructed"],
            components=[
                RepresentationComponent(role="connectivities", kind="matrix", axes=["cell", "cell"], value_semantics="weighted neighbor connectivities", storage_semantics="sparse matrix selected by connectivities_key", required=True),
                RepresentationComponent(role="distances", kind="matrix", axes=["cell", "cell"], value_semantics="neighbor distances", storage_semantics="sparse matrix selected by distances_key", required=True),
                RepresentationComponent(role="parameters", kind="metadata", axes=[], value_semantics="neighbors_key, component keys, use_rep and parameters", storage_semantics="bounded metadata mapping", required=True),
            ],
        ),
        _rep("representation-type:adjacency_matrix", "explicit graph adjacency", ["cell", "cell"], "sparse weighted adjacency matrix", ["graph_constructed"]),
        _rep("representation-type:umap_coordinates", "UMAP coordinates", ["cell", "embedding_dimension"], "real-valued UMAP coordinates", ["embedded"]),
        _rep("representation-type:cluster_labels", "cluster labels", ["cell"], "categorical Leiden membership", ["clustered"]),
        _rep("representation-type:doublet_assessment", "doublet scores and predicted calls", ["cell"], "continuous scores plus threshold-derived boolean calls", ["doublet_scored"]),
        _rep("representation-type:gene_by_cell_expression", "SingleR query expression", ["gene", "cell"], "gene-by-cell expression with declared value state", ["state_declared"]),
        _rep("representation-type:reference_expression", "SingleR reference expression", ["gene", "reference_sample"], "reference expression in the query feature namespace", ["reference_annotated"]),
        _rep("representation-type:reference_labels", "SingleR reference labels", ["reference_sample"], "known label per reference sample", ["reference_annotated"]),
        _rep("representation-type:cell_type_labels", "SingleR annotation result", ["cell"], "predicted and pruned labels with scores", ["annotated"]),
    ]

    constraints = [
        _constraint("representation-constraint:uat:hvg-log", "representation-type:log_expression", "scope:uat:scanpy:hvg-dispersion:1.11.2", states=["fresh"], transformations=["log1p"], forbidden=["integrated"], metadata=["ordered_observation_ids", "ordered_feature_ids", "source_slot"], feature_alignment="same_features"),
        _constraint("representation-constraint:uat:hvg-counts", "representation-type:raw_umi_counts", "scope:uat:scanpy:hvg-count:1.11.2", states=["fresh", "integer_like_counts"], forbidden=["normalized", "log1p", "scaled", "integrated"], metadata=["ordered_observation_ids", "ordered_feature_ids", "source_slot"], feature_alignment="same_features"),
        _constraint("representation-constraint:uat:pca-expression", "representation-type:expression_matrix", "scope:uat:scanpy:pca:1.11.2", states=["fresh", "state_declared"], metadata=["ordered_observation_ids", "ordered_feature_ids", "source_slot", "lineage_id"], feature_alignment="same_features"),
        _constraint("representation-constraint:uat:pca-hvg-mask", "representation-type:hvg_mask", "scope:uat:scanpy:pca:1.11.2", states=["fresh", "feature_selected"], metadata=["ordered_feature_ids", "lineage_id"], observation_alignment="not_applicable", feature_alignment="same_features"),
        _constraint("representation-constraint:uat:pca-profile-scaled-hvg", "representation-type:expression_matrix", "scope:uat:profile:scanpy-pca-scaled-hvg:1.0.0", states=["fresh", "state_declared", "hvg_scoped"], transformations=["log1p", "scaled"], metadata=["ordered_observation_ids", "ordered_feature_ids", "source_slot", "lineage_id"], feature_alignment="same_features"),
        _constraint("representation-constraint:uat:neighbors-x", "representation-type:expression_matrix", "scope:uat:scanpy:neighbors:1.11.2", states=["fresh", "state_declared"], metadata=["ordered_observation_ids", "ordered_feature_ids", "source_slot", "lineage_id", "semantic_parameter_signature"], feature_alignment="same_features"),
        _constraint("representation-constraint:uat:neighbors-pca", "representation-type:pca_coordinates", "scope:uat:scanpy:neighbors:1.11.2", states=["fresh", "dimension_reduced"], metadata=["ordered_observation_ids", "lineage_id", "source_slot", "semantic_parameter_signature"]),
        _constraint("representation-constraint:uat:neighbors-embedding", "representation-type:cell_embedding", "scope:uat:scanpy:neighbors:1.11.2", states=["fresh", "dimension_reduced"], metadata=["ordered_observation_ids", "lineage_id", "source_slot", "semantic_parameter_signature"]),
        _constraint("representation-constraint:uat:neighbor-graph-reuse", "representation-type:neighbor_graph", "scope:uat:scanpy:umap:1.11.2", states=["fresh", "graph_constructed"], metadata=["ordered_observation_ids", "lineage_id", "neighbors_key", "connectivities_key", "distances_key", "semantic_parameter_signature"], components=["connectivities", "distances", "parameters"]),
        _constraint("representation-constraint:uat:leiden-neighbor-graph", "representation-type:neighbor_graph", "scope:uat:scanpy:leiden:1.11.2", states=["fresh", "graph_constructed"], metadata=["ordered_observation_ids", "lineage_id", "neighbors_key", "connectivities_key", "semantic_parameter_signature"], components=["connectivities", "parameters"]),
        _constraint("representation-constraint:uat:leiden-adjacency", "representation-type:adjacency_matrix", "scope:uat:scanpy:leiden:1.11.2", states=["fresh", "graph_constructed"], metadata=["ordered_observation_ids", "lineage_id", "semantic_parameter_signature"]),
        _constraint("representation-constraint:uat:harmony-pca", "representation-type:pca_coordinates", "scope:uat:harmony:pca-default:2.0.5", states=["fresh", "dimension_reduced"], metadata=["ordered_observation_ids", "lineage_id", "source_slot", "semantic_parameter_signature"]),
        _constraint("representation-constraint:uat:harmony-generic", "representation-type:cell_embedding", "scope:uat:harmony:generic:2.0.5", states=["fresh", "dimension_reduced"], metadata=["ordered_observation_ids", "lineage_id", "source_slot", "semantic_parameter_signature"]),
        _constraint("representation-constraint:uat:harmony-covariates", "representation-type:batch_covariates", "scope:uat:harmony:generic:2.0.5", states=["fresh", "metadata"], metadata=["ordered_observation_ids", "covariate_names"]),
        _constraint("representation-constraint:uat:scrublet-raw", "representation-type:raw_umi_counts", "scope:uat:scrublet:0.2.3", states=["fresh", "integer_like_counts"], forbidden=["normalized", "log1p", "scaled", "integrated"], metadata=["ordered_observation_ids", "ordered_feature_ids", "capture_unit_id", "source_slot"], feature_alignment="same_features"),
        _constraint("representation-constraint:uat:singler-query-raw", "representation-type:gene_by_cell_expression", "scope:uat:singler:2.14.1", states=["fresh", "raw_counts"], forbidden=["integrated"], metadata=["ordered_observation_ids", "ordered_feature_ids", "feature_namespace"], feature_alignment="intersection"),
        _constraint("representation-constraint:uat:singler-query-log", "representation-type:gene_by_cell_expression", "scope:uat:singler:2.14.1", states=["fresh", "log_expression"], forbidden=["integrated"], metadata=["ordered_observation_ids", "ordered_feature_ids", "feature_namespace"], feature_alignment="intersection"),
        _constraint("representation-constraint:uat:singler-reference-expression", "representation-type:reference_expression", "scope:uat:singler:2.14.1", states=["fresh", "reference_annotated", "log_expression"], metadata=["ordered_reference_ids", "ordered_feature_ids", "feature_namespace", "biological_applicability_confirmed", "organism_taxon"], observation_alignment="not_applicable", feature_alignment="intersection"),
        _constraint("representation-constraint:uat:singler-reference-labels", "representation-type:reference_labels", "scope:uat:singler:2.14.1", states=["fresh", "reference_annotated"], metadata=["ordered_reference_ids", "label_namespace"], observation_alignment="not_applicable"),
    ]
    constraint_by_id = {item.constraint_id: item for item in constraints}

    projects: list[Any] = []
    for key, label, ecosystem, distribution, version in [
        ("scanpy", "Scanpy", "python", "scanpy", "1.11.2"),
        ("harmony", "Harmony", "r", "harmony", "2.0.5"),
        ("scrublet", "Scrublet", "python", "scrublet", "0.2.3"),
        ("singler", "SingleR", "r_bioconductor", "SingleR", "2.14.1"),
    ]:
        projects.extend([
            SoftwareProject(entity_id=f"software-project:{key}", label=label),
            Package(entity_id=f"package:{key}", project_id=f"software-project:{key}", ecosystem=ecosystem, distribution_name=distribution),
            PackageRelease(entity_id=f"package-release:{key}:{version}", package_id=f"package:{key}", version=version, immutable_release_ref=SOURCE_REVISIONS.get(key, {}).get("release_artifact_sha256", "5400eb87ef7d4e9f6f5a9256d98a7927723456fa")),
        ])

    methods = [
        Method(entity_id="method:hvg_selection", label="highly-variable feature selection"),
        Method(entity_id="method:pca", label="principal component analysis"),
        Method(entity_id="method:neighbor_graph_construction", label="nearest-neighbor graph construction"),
        Method(entity_id="method:umap", label="UMAP embedding"),
        Method(entity_id="method:leiden", label="Leiden graph clustering"),
        Method(entity_id="method:harmony_integration", label="Harmony integration"),
        Method(entity_id="method:scrublet", label="Scrublet doublet scoring"),
        Method(entity_id="method:singler_annotation", label="SingleR reference annotation"),
        MethodVariant(entity_id="method-variant:hvg.dispersion", method_id="method:hvg_selection", label="dispersion-based HVG selection", defining_parameter_conditions=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat", "cell_ranger"])]),
        MethodVariant(entity_id="method-variant:hvg.count", method_id="method:hvg_selection", label="count-based HVG selection", defining_parameter_conditions=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat_v3", "seurat_v3_paper"])]),
        MethodVariant(entity_id="method-variant:pca.sckg-scaled-hvg-profile", method_id="method:pca", label="scKG project profile PCA on scaled HVGs"),
        MethodVariant(entity_id="method-variant:harmony.pca-default", method_id="method:harmony_integration", label="Harmony PCA-default object interface"),
        MethodVariant(entity_id="method-variant:harmony.generic-embedding", method_id="method:harmony_integration", label="Harmony generic embedding interface"),
    ]

    operator_specs = [
        ("scanpy", "scanpy.pp.highly_variable_genes", "1.11.2", "method:hvg_selection", "scope:uat:scanpy:hvg:1.11.2"),
        ("scanpy", "scanpy.pp.pca", "1.11.2", "method:pca", "scope:uat:scanpy:pca:1.11.2"),
        ("scanpy", "scanpy.pp.neighbors", "1.11.2", "method:neighbor_graph_construction", "scope:uat:scanpy:neighbors:1.11.2"),
        ("scanpy", "scanpy.tl.umap", "1.11.2", "method:umap", "scope:uat:scanpy:umap:1.11.2"),
        ("scanpy", "scanpy.tl.leiden", "1.11.2", "method:leiden", "scope:uat:scanpy:leiden:1.11.2"),
        ("harmony", "harmony.RunHarmony", "2.0.5", "method:harmony_integration", "scope:uat:harmony:generic:2.0.5"),
        ("scrublet", "scrublet.Scrublet.scrub_doublets", "0.2.3", "method:scrublet", "scope:uat:scrublet:0.2.3"),
        ("singler", "SingleR::SingleR", "2.14.1", "method:singler_annotation", "scope:uat:singler:2.14.1"),
    ]
    operators: list[Operator] = []
    for package, qualified_name, _, _, _ in operator_specs:
        operators.append(Operator(entity_id=f"operator:{qualified_name}", package_id=f"package:{package}", qualified_name=qualified_name))

    hvg_input = _input_port(
        "input-port:uat:scanpy.hvg:expression",
        "expression",
        "scope:uat:scanpy:hvg:1.11.2",
        [
            _requirement("requirement:uat:hvg:dispersion-log", "scope:uat:scanpy:hvg-dispersion:1.11.2", ["representation-constraint:uat:hvg-log"], level="conditional", when=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat", "cell_ranger"])]),
            _requirement("requirement:uat:hvg:count-flavors", "scope:uat:scanpy:hvg-count:1.11.2", ["representation-constraint:uat:hvg-counts"], level="conditional", when=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat_v3", "seurat_v3_paper"])]),
        ],
        combination="any_of",
    )
    pca_expression = _input_port("input-port:uat:scanpy.pca:expression", "expression", "scope:uat:scanpy:pca:1.11.2", [_requirement("requirement:uat:pca:expression", "scope:uat:scanpy:pca:1.11.2", ["representation-constraint:uat:pca-expression"] )], alignment=["expression and optional feature mask must share ordered feature identity"])
    pca_mask = _input_port("input-port:uat:scanpy.pca:feature-mask", "optional_feature_mask", "scope:uat:scanpy:pca:1.11.2", [_requirement("requirement:uat:pca:hvg-mask", "scope:uat:scanpy:pca:1.11.2", ["representation-constraint:uat:pca-hvg-mask"], level="optional")], min_cardinality=0)
    neighbors_input = _input_port("input-port:uat:scanpy.neighbors:representation", "X_or_obsm_representation", "scope:uat:scanpy:neighbors:1.11.2", [_requirement("requirement:uat:neighbors:x", "scope:uat:scanpy:neighbors:1.11.2", ["representation-constraint:uat:neighbors-x"]), _requirement("requirement:uat:neighbors:pca", "scope:uat:scanpy:neighbors:1.11.2", ["representation-constraint:uat:neighbors-pca"]), _requirement("requirement:uat:neighbors:embedding", "scope:uat:scanpy:neighbors:1.11.2", ["representation-constraint:uat:neighbors-embedding"])], combination="any_of")
    umap_graph = _input_port("input-port:uat:scanpy.umap:neighbor-graph", "neighbor_graph_with_settings", "scope:uat:scanpy:umap:1.11.2", [_requirement("requirement:uat:umap:neighbor-graph", "scope:uat:scanpy:umap:1.11.2", ["representation-constraint:uat:neighbor-graph-reuse"])])
    leiden_graph = _input_port("input-port:uat:scanpy.leiden:graph", "neighbor_connectivities_or_adjacency", "scope:uat:scanpy:leiden:1.11.2", [_requirement("requirement:uat:leiden:neighbor-graph", "scope:uat:scanpy:leiden:1.11.2", ["representation-constraint:uat:leiden-neighbor-graph"]), _requirement("requirement:uat:leiden:adjacency", "scope:uat:scanpy:leiden:1.11.2", ["representation-constraint:uat:leiden-adjacency"])], combination="any_of")
    harmony_embedding = _input_port("input-port:uat:harmony:embedding", "cell_embedding", "scope:uat:harmony:generic:2.0.5", [_requirement("requirement:uat:harmony:pca", "scope:uat:harmony:pca-default:2.0.5", ["representation-constraint:uat:harmony-pca"]), _requirement("requirement:uat:harmony:generic", "scope:uat:harmony:generic:2.0.5", ["representation-constraint:uat:harmony-generic"])], combination="any_of", alignment=["embedding rows and covariate rows must identify the same cells in the same order"])
    harmony_covariates = _input_port("input-port:uat:harmony:covariates", "batch_covariates", "scope:uat:harmony:generic:2.0.5", [_requirement("requirement:uat:harmony:covariates", "scope:uat:harmony:generic:2.0.5", ["representation-constraint:uat:harmony-covariates"])], alignment=["covariate rows must align to embedding cells"])
    scrublet_counts = _input_port("input-port:uat:scrublet:counts", "raw_counts_per_capture_unit", "scope:uat:scrublet:0.2.3", [_requirement("requirement:uat:scrublet:raw-counts", "scope:uat:scrublet:0.2.3", ["representation-constraint:uat:scrublet-raw"])])
    singler_query = _input_port("input-port:uat:singler:query", "query_expression", "scope:uat:singler:2.14.1", [_requirement("requirement:uat:singler:query-raw", "scope:uat:singler:2.14.1", ["representation-constraint:uat:singler-query-raw"]), _requirement("requirement:uat:singler:query-log", "scope:uat:singler:2.14.1", ["representation-constraint:uat:singler-query-log"])], combination="any_of", alignment=["query and reference must have a non-empty feature intersection in a compatible feature namespace"])
    singler_ref = _input_port("input-port:uat:singler:reference-expression", "reference_expression", "scope:uat:singler:2.14.1", [_requirement("requirement:uat:singler:reference-expression", "scope:uat:singler:2.14.1", ["representation-constraint:uat:singler-reference-expression"])], alignment=["reference expression columns and label entries must have identical ordered reference ids"])
    singler_labels = _input_port("input-port:uat:singler:reference-labels", "reference_labels", "scope:uat:singler:2.14.1", [_requirement("requirement:uat:singler:reference-labels", "scope:uat:singler:2.14.1", ["representation-constraint:uat:singler-reference-labels"])], alignment=["one known label is required for every reference sample"])

    revisions = [
        OperatorRevision(entity_id="operator-revision:scanpy.pp.highly_variable_genes:1.11.2:uat-corrected", operator_id="operator:scanpy.pp.highly_variable_genes", package_release_id="package-release:scanpy:1.11.2", implements_method_ids=["method:hvg_selection"], implements_method_variant_ids=["method-variant:hvg.dispersion", "method-variant:hvg.count"], input_ports=[hvg_input], output_ports=[_output_port("output-port:uat:scanpy.hvg:mask", "hvg_mask", "representation-type:hvg_mask", "scope:uat:scanpy:hvg:1.11.2", [hvg_input.input_port_id], preserves=["ordered_feature_ids", "lineage_id"], transforms=["feature_selected"])], scope_id="scope:uat:scanpy:hvg:1.11.2"),
        OperatorRevision(entity_id="operator-revision:scanpy.pp.pca:1.11.2:uat-corrected", operator_id="operator:scanpy.pp.pca", package_release_id="package-release:scanpy:1.11.2", implements_method_ids=["method:pca"], implements_method_variant_ids=["method-variant:pca.sckg-scaled-hvg-profile"], input_ports=[pca_expression, pca_mask], output_ports=[_output_port("output-port:uat:scanpy.pca:coordinates", "pca_coordinates", "representation-type:pca_coordinates", "scope:uat:scanpy:pca:1.11.2", [pca_expression.input_port_id], preserves=["ordered_observation_ids", "lineage_id"], transforms=["dimension_reduced", "records_parameter_signature"])], scope_id="scope:uat:scanpy:pca:1.11.2"),
        OperatorRevision(entity_id="operator-revision:scanpy.pp.neighbors:1.11.2:uat-corrected", operator_id="operator:scanpy.pp.neighbors", package_release_id="package-release:scanpy:1.11.2", implements_method_ids=["method:neighbor_graph_construction"], input_ports=[neighbors_input], output_ports=[_output_port("output-port:uat:scanpy.neighbors:graph", "neighbor_graph", "representation-type:neighbor_graph", "scope:uat:scanpy:neighbors:1.11.2", [neighbors_input.input_port_id], preserves=["ordered_observation_ids", "lineage_id"], transforms=["creates_connectivities", "creates_distances", "records_neighbor_parameters", "records_source_representation"])], scope_id="scope:uat:scanpy:neighbors:1.11.2"),
        OperatorRevision(entity_id="operator-revision:scanpy.tl.umap:1.11.2:uat-corrected", operator_id="operator:scanpy.tl.umap", package_release_id="package-release:scanpy:1.11.2", implements_method_ids=["method:umap"], input_ports=[umap_graph], output_ports=[_output_port("output-port:uat:scanpy.umap:coordinates", "umap_coordinates", "representation-type:umap_coordinates", "scope:uat:scanpy:umap:1.11.2", [umap_graph.input_port_id], preserves=["ordered_observation_ids", "lineage_id"], transforms=["embedded", "records_neighbor_graph_dependency"])], scope_id="scope:uat:scanpy:umap:1.11.2"),
        OperatorRevision(entity_id="operator-revision:scanpy.tl.leiden:1.11.2:uat-corrected", operator_id="operator:scanpy.tl.leiden", package_release_id="package-release:scanpy:1.11.2", implements_method_ids=["method:leiden"], input_ports=[leiden_graph], output_ports=[_output_port("output-port:uat:scanpy.leiden:labels", "cluster_labels", "representation-type:cluster_labels", "scope:uat:scanpy:leiden:1.11.2", [leiden_graph.input_port_id], preserves=["ordered_observation_ids", "lineage_id"], transforms=["clustered", "records_resolution"])], scope_id="scope:uat:scanpy:leiden:1.11.2"),
        OperatorRevision(entity_id="operator-revision:harmony.RunHarmony:2.0.5:uat-corrected", operator_id="operator:harmony.RunHarmony", package_release_id="package-release:harmony:2.0.5", implements_method_ids=["method:harmony_integration"], implements_method_variant_ids=["method-variant:harmony.pca-default", "method-variant:harmony.generic-embedding"], input_ports=[harmony_embedding, harmony_covariates], output_ports=[_output_port("output-port:uat:harmony:corrected-embedding", "corrected_cell_embedding", "representation-type:cell_embedding", "scope:uat:harmony:generic:2.0.5", [harmony_embedding.input_port_id, harmony_covariates.input_port_id], preserves=["ordered_observation_ids", "lineage_id"], transforms=["batch_corrected_embedding", "records_harmony_parameters"])], scope_id="scope:uat:harmony:generic:2.0.5"),
        OperatorRevision(entity_id="operator-revision:scrublet.Scrublet.scrub_doublets:0.2.3:uat-corrected", operator_id="operator:scrublet.Scrublet.scrub_doublets", package_release_id="package-release:scrublet:0.2.3", implements_method_ids=["method:scrublet"], input_ports=[scrublet_counts], output_ports=[_output_port("output-port:uat:scrublet:assessment", "doublet_scores_and_calls", "representation-type:doublet_assessment", "scope:uat:scrublet:0.2.3", [scrublet_counts.input_port_id], preserves=["ordered_observation_ids", "capture_unit_id", "lineage_id"], transforms=["doublet_scored", "threshold_applied"])], scope_id="scope:uat:scrublet:0.2.3"),
        OperatorRevision(entity_id="operator-revision:SingleR::SingleR:2.14.1:uat-corrected", operator_id="operator:SingleR::SingleR", package_release_id="package-release:singler:2.14.1", implements_method_ids=["method:singler_annotation"], input_ports=[singler_query, singler_ref, singler_labels], output_ports=[_output_port("output-port:uat:singler:labels", "predicted_and_pruned_labels", "representation-type:cell_type_labels", "scope:uat:singler:2.14.1", [singler_query.input_port_id, singler_ref.input_port_id, singler_labels.input_port_id], preserves=["ordered_observation_ids", "lineage_id"], transforms=["annotated", "records_scores", "records_pruned_labels"])], scope_id="scope:uat:singler:2.14.1"),
    ]

    limitation_entities = [
        Limitation(entity_id="limitation:scrublet:per-capture-scope", label="Scrublet should be run separately per capture/sample unit"),
        Limitation(entity_id="limitation:scrublet:threshold-review", label="Scrublet threshold requires diagnostic review"),
        Limitation(entity_id="limitation:scrublet:no-automatic-deletion", label="doublet scores/calls do not authorize automatic cell deletion"),
        Limitation(entity_id="limitation:singler:reference-applicability", label="reference label space may not cover the query biology"),
    ]
    entities: list[Any] = [*tasks, *projects, *methods, *operators, *revisions, *limitation_entities]

    source_by_span: dict[str, dict[str, Any]] = {}
    sources, spans = _source_snapshot()
    for span in spans:
        source_by_span[span["evidence_span_id"]] = span

    claim_specs = [
        ("hvg-dispersion-log", revisions[0].entity_id, "requires_representation", "representation-constraint:uat:hvg-log", None, "Dispersion-based seurat and cell_ranger HVG flavors require logarithmized expression.", "scope:uat:scanpy:hvg-dispersion:1.11.2", ["scanpy-authoritative-span:hvg.flavor_input:1.11.2"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("hvg-count-flavors", revisions[0].entity_id, "requires_representation", "representation-constraint:uat:hvg-counts", None, "seurat_v3 and seurat_v3_paper HVG flavors require count data.", "scope:uat:scanpy:hvg-count:1.11.2", ["scanpy-authoritative-span:hvg.flavor_input:1.11.2"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("hvg-output", revisions[0].entity_id, "produces", "representation-type:hvg_mask", None, "The operator records a boolean highly-variable feature indicator.", "scope:uat:scanpy:hvg:1.11.2", ["scanpy-authoritative-span:hvg.output:1.11.2"], "R2", "capability", "promotion_ready"),
        ("pca-expression", revisions[1].entity_id, "accepts_representation", "representation-constraint:uat:pca-expression", None, "Scanpy PCA accepts cell-by-gene expression from the selected matrix or layer without a universal HVG requirement.", "scope:uat:scanpy:pca:1.11.2", ["scanpy-authoritative-span:pca.input:1.11.2", "scanpy-authoritative-span:pca.mask:1.11.2"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("pca-mask-optional", revisions[1].entity_id, "accepts_optional_representation", "representation-constraint:uat:pca-hvg-mask", None, "PCA may use a feature mask; if no mask is specified, Scanpy uses highly_variable when available and otherwise all features.", "scope:uat:scanpy:pca:1.11.2", ["scanpy-authoritative-span:pca.mask:1.11.2"], "R3", "requirement", "promotion_ready_after_expert_review"),
        ("pca-project-profile", "method-variant:pca.sckg-scaled-hvg-profile", "project_profile_requires", "representation-constraint:uat:pca-profile-scaled-hvg", None, "The scKG Scanpy Core project profile chooses scaled HVG expression for its controlled PCA step; this is not a universal Scanpy requirement.", "scope:uat:profile:scanpy-pca-scaled-hvg:1.0.0", ["uat-authoritative-span:sckg.pca_profile"], "R3", "recommendation", "scoped_profile_only"),
        ("neighbors-input", revisions[2].entity_id, "accepts_representation", None, "X or any compatible obsm embedding", "Scanpy neighbors accepts X or a named obsm representation; PCA is an automatic/default path rather than a universal prerequisite.", "scope:uat:scanpy:neighbors:1.11.2", ["scanpy-authoritative-span:neighbors.input:1.11.2"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("neighbors-output", revisions[2].entity_id, "produces", "representation-type:neighbor_graph", None, "Scanpy neighbors stores distances, connectivities and metadata that names their keys and construction parameters.", "scope:uat:scanpy:neighbors:1.11.2", ["scanpy-authoritative-span:neighbors.output:1.11.2", "scanpy-authoritative-span:neighbors.metadata:1.11.2"], "R3", "capability", "promotion_ready_after_expert_review"),
        ("umap-input", revisions[3].entity_id, "requires_representation", "representation-constraint:uat:neighbor-graph-reuse", None, "Scanpy UMAP resolves neighbor settings and connectivities through neighbors_key.", "scope:uat:scanpy:umap:1.11.2", ["scanpy-authoritative-span:umap.input:1.11.2"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("leiden-input", revisions[4].entity_id, "accepts_representation", None, "neighbor connectivities or explicit adjacency", "Scanpy Leiden consumes an explicit sparse adjacency or the connectivities selected from a neighbor graph; UMAP is not an input.", "scope:uat:scanpy:leiden:1.11.2", ["scanpy-authoritative-span:leiden.input:1.11.2"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("leiden-output", revisions[4].entity_id, "produces", "representation-type:cluster_labels", None, "Scanpy Leiden records categorical cluster labels and clustering parameters.", "scope:uat:scanpy:leiden:1.11.2", ["scanpy-authoritative-span:leiden.output:1.11.2"], "R2", "capability", "promotion_ready"),
        ("harmony-generic-input", revisions[5].entity_id, "accepts_representation", "representation-constraint:uat:harmony-generic", None, "The generic Harmony interface accepts a cell embedding matrix with aligned metadata and categorical covariates.", "scope:uat:harmony:generic:2.0.5", ["uat-authoritative-span:harmony.generic_input"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("harmony-pca-default", revisions[5].entity_id, "accepts_representation", "representation-constraint:uat:harmony-pca", None, "The Seurat Harmony interface defaults to a precomputed PCA reduction, while the generic interface is not restricted to PCA.", "scope:uat:harmony:pca-default:2.0.5", ["uat-authoritative-span:harmony.pca_default", "uat-authoritative-span:harmony.generic_input"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("harmony-covariates", revisions[5].entity_id, "requires_representation", "representation-constraint:uat:harmony-covariates", None, "Harmony requires cell-aligned metadata and names the categorical covariates to integrate.", "scope:uat:harmony:generic:2.0.5", ["uat-authoritative-span:harmony.generic_input"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("harmony-output", revisions[5].entity_id, "produces", "representation-type:cell_embedding", None, "Harmony returns a corrected embedding matrix, not corrected expression counts.", "scope:uat:harmony:generic:2.0.5", ["uat-authoritative-span:harmony.output"], "R4", "capability", "promotion_ready_after_expert_review"),
        ("scrublet-input", revisions[6].entity_id, "requires_representation", "representation-constraint:uat:scrublet-raw", None, "Scrublet requires a cell-by-gene raw unnormalized UMI count matrix.", "scope:uat:scrublet:0.2.3", ["uat-authoritative-span:scrublet.input_output"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("scrublet-output", revisions[6].entity_id, "produces", "representation-type:doublet_assessment", None, "Scrublet returns continuous doublet scores and threshold-derived predicted doublet calls.", "scope:uat:scrublet:0.2.3", ["uat-authoritative-span:scrublet.input_output"], "R3", "capability", "promotion_ready_after_expert_review"),
        ("scrublet-sample-scope", revisions[6].entity_id, "has_limitation", "limitation:scrublet:per-capture-scope", None, "Multiple samples or capture units should be analyzed separately because merged proportions may violate Scrublet's assumptions.", "scope:uat:scrublet:0.2.3", ["uat-authoritative-span:scrublet.sample_scope"], "R4", "limitation", "promotion_ready_after_expert_review"),
        ("scrublet-threshold", revisions[6].entity_id, "has_limitation", "limitation:scrublet:threshold-review", None, "The automatically selected Scrublet threshold should be diagnosed and adjusted when necessary.", "scope:uat:scrublet:0.2.3", ["uat-authoritative-span:scrublet.threshold", "uat-authoritative-span:scrublet.sample_scope"], "R4", "limitation", "promotion_ready_after_expert_review"),
        ("scrublet-no-delete", revisions[6].entity_id, "project_guardrail", "limitation:scrublet:no-automatic-deletion", None, "Scores and predicted calls are evidence for review; they do not themselves authorize automatic cell deletion.", "scope:uat:scrublet:0.2.3", ["uat-authoritative-span:scrublet.input_output", "uat-authoritative-span:scrublet.threshold"], "R4", "recommendation", "review_required_partial_support"),
        ("singler-query", revisions[7].entity_id, "accepts_representation", None, "raw counts or log expression query matrix", "SingleR accepts a gene-by-cell query matrix, including raw UMI counts or transcript counts without normalization and log transformation.", "scope:uat:singler:2.14.1", ["uat-authoritative-span:singler.interface", "uat-authoritative-span:singler.raw_query"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("singler-reference-expression", revisions[7].entity_id, "requires_representation", "representation-constraint:uat:singler-reference-expression", None, "SingleR requires reference expression, usually normalized and log-transformed for automatic marker detection.", "scope:uat:singler:2.14.1", ["uat-authoritative-span:singler.reference_labels", "uat-authoritative-span:singler.reference_state"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("singler-reference-labels", revisions[7].entity_id, "requires_representation", "representation-constraint:uat:singler-reference-labels", None, "SingleR requires a known label for each reference sample.", "scope:uat:singler:2.14.1", ["uat-authoritative-span:singler.reference_labels"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("singler-features", revisions[7].entity_id, "requires_compatibility", None, "non-empty compatible feature intersection", "SingleR restricts analysis to the reference-query gene intersection and rejects an empty intersection.", "scope:uat:singler:2.14.1", ["uat-authoritative-span:singler.feature_intersection"], "R4", "requirement", "promotion_ready_after_expert_review"),
        ("singler-applicability", revisions[7].entity_id, "has_limitation", "limitation:singler:reference-applicability", None, "Reference applicability must be reviewed because absent target labels can yield uncertain or incorrect assignments.", "scope:uat:singler:2.14.1", ["uat-authoritative-span:singler.reference_applicability"], "R4", "limitation", "promotion_ready_after_expert_review"),
    ]

    claims: list[AtomicClaimRevision] = []
    assessments: list[EvidenceAssessment] = []
    risk_rows: list[dict[str, Any]] = []
    binding_rows: list[dict[str, Any]] = []
    for suffix, subject, predicate, object_id, object_value, text, scope_id, span_ids, risk, assertion_kind, eligibility in claim_specs:
        claim_id = f"claim:uat:{suffix}"
        revision_id = f"claim-revision:uat:{suffix}:v1"
        claim = AtomicClaimRevision(
            claim_id=claim_id,
            claim_revision_id=revision_id,
            subject_id=subject,
            predicate=predicate,
            object_id=object_id,
            object_value=object_value,
            scope_id=scope_id,
            claim_text=text,
            polarity="positive",
            assertion_kind=assertion_kind,
            semantic_fingerprint=_sha_text(f"{subject}|{predicate}|{object_id or object_value}|{scope_id}"),
            content_hash=_sha_text(text),
            created_by_activity_id="activity:scientific-kg-v1-uat-decision-rule-correction",
        )
        stance = "partial_support" if eligibility == "review_required_partial_support" else "supports"
        claims.append(claim)
        assessments.append(EvidenceAssessment(assessment_id=f"evidence-assessment:uat:{suffix}", claim_revision_id=revision_id, evidence_span_ids=span_ids, stance=stance, subject_aligned=True, predicate_aligned=True, object_aligned=stance == "supports", scope_alignment="aligned" if stance == "supports" else "partial", rationale="Bound to exact bounded text from a version-pinned official source; partial support is retained where the project guardrail is a governed inference."))
        risk_rows.append({"record_id": revision_id, "record_type": "AtomicClaimRevision", "risk_class": risk, "review_requirement": "designated_owner_and_independent_review" if risk == "R4" else "qualified_human" if risk == "R3" else "source_grounded_model_review", "promotion_eligibility": eligibility, "review_status": "candidate_pending_review"})
        binding_rows.append({"claim_revision_id": revision_id, "claim_content_hash": claim.content_hash, "evidence_span_ids": span_ids, "evidence_locators": [source_by_span[span_id]["locator"] for span_id in span_ids], "source_file_sha256": [source_by_span[span_id]["source_file_sha256"] for span_id in span_ids], "evidence_excerpt_sha256": [source_by_span[span_id]["content_hash"] for span_id in span_ids], "assessment": stance, "proof_kinds": [source_by_span[span_id]["verification_method"] for span_id in span_ids], "candidate_only": True})

    relations: list[DerivedRelation] = []
    relation_by_port_type: dict[tuple[str, str], str] = {}
    for revision in revisions:
        for port in revision.input_ports:
            consumed_types = sorted({
                constraint_by_id[constraint_id].representation_type_id
                for requirement in port.requirements
                for constraint_id in requirement.representation_constraint_ids
            })
            for representation_type_id in consumed_types:
                relation_id = f"derived-relation:uat:consumes:{_sha_text(port.input_port_id + representation_type_id)[:16]}"
                relation_by_port_type[(port.input_port_id, representation_type_id)] = relation_id
                relations.append(DerivedRelation(relation_id=relation_id, relation="CONSUMES", source_id=revision.entity_id, target_id=representation_type_id, scope_id=port.scope_id, derivation_type="port_projection", input_port_id=port.input_port_id, derived_from_claim_revision_ids=[], derivation_rule_id="rule:v1.1:input-port-projection", review_status="candidate_pending_review"))
        for port in revision.output_ports:
            relation_id = f"derived-relation:uat:produces:{_sha_text(port.output_port_id)[:16]}"
            relation_by_port_type[(port.output_port_id, port.representation_type_id)] = relation_id
            relations.append(DerivedRelation(relation_id=relation_id, relation="PRODUCES", source_id=revision.entity_id, target_id=port.representation_type_id, scope_id=port.scope_id, derivation_type="port_projection", output_port_id=port.output_port_id, derived_from_claim_revision_ids=[], derivation_rule_id="rule:v1.1:output-port-projection", review_status="candidate_pending_review"))

    claim_revision_by_suffix = {suffix: f"claim-revision:uat:{suffix}:v1" for suffix, *_ in claim_specs}
    can_feed_specs = [
        (revisions[1], revisions[2], revisions[1].output_ports[0], neighbors_input, ["pca-expression", "neighbors-input"], "PCA coordinates satisfy the neighbors PCA branch only when observation identity, lineage, semantic parameters and freshness are compatible."),
        (revisions[5], revisions[2], revisions[5].output_ports[0], neighbors_input, ["harmony-output", "neighbors-input"], "Harmony corrected embeddings satisfy the neighbors obsm branch only when observation identity, lineage, semantic parameters and freshness are compatible."),
        (revisions[2], revisions[3], revisions[2].output_ports[0], umap_graph, ["neighbors-output", "umap-input"], "A neighbor graph can feed UMAP only when connectivities, distances, metadata keys, observation identity, parameter signature and freshness satisfy the input constraint."),
        (revisions[2], revisions[4], revisions[2].output_ports[0], leiden_graph, ["neighbors-output", "leiden-input"], "A neighbor graph can feed Leiden when connectivities, metadata keys, observation identity, parameter signature and freshness satisfy the input constraint; UMAP is not required."),
    ]
    proof_rows: list[dict[str, Any]] = []
    for producer, consumer, output_port, input_port, claim_suffixes, proof in can_feed_specs:
        relation_id = f"derived-relation:uat:can-feed:{_sha_text(producer.entity_id + consumer.entity_id)[:16]}"
        relation = DerivedRelation(relation_id=relation_id, relation="CAN_FEED", source_id=producer.entity_id, target_id=consumer.entity_id, scope_id=consumer.scope_id, derivation_type="reviewed_rule", input_port_id=input_port.input_port_id, output_port_id=output_port.output_port_id, premise_relation_ids=[relation_by_port_type[(output_port.output_port_id, output_port.representation_type_id)], relation_by_port_type[(input_port.input_port_id, output_port.representation_type_id)]], derived_from_claim_revision_ids=[claim_revision_by_suffix[item] for item in claim_suffixes], derivation_rule_id="rule:v1.1:claim-scoped-port-compatibility", review_status="candidate_pending_review")
        relations.append(relation)
        proof_rows.append({"relation_id": relation_id, "type_equality_only": False, "proof": proof, "checks": ["source_bound_claim_support", "input_output_semantic_compatibility", "observation_identity", "lineage_compatibility", "semantic_parameter_compatibility", "staleness"], "result": "candidate_proof_complete_review_pending"})

    for relation in relations:
        risk = "R4" if relation.relation == "CAN_FEED" else "R3"
        risk_rows.append({"record_id": relation.relation_id, "record_type": "DerivedRelation", "risk_class": risk, "review_requirement": "designated_owner_and_independent_review" if risk == "R4" else "qualified_human", "promotion_eligibility": "review_required", "review_status": "candidate_pending_review"})

    bundle = ConformanceBundle(
        fixture_id="conformance-fixture:scientific-kg-v1-uat-decision-rules",
        description="Corrected candidate-only decision rules for Scanpy Core, Harmony, Scrublet and SingleR.",
        scopes=scopes,
        representation_types=representations,
        representation_constraints=constraints,
        entities=entities,
        atomic_claims=claims,
        evidence_assessments=assessments,
        derived_relations=relations,
        expected_semantics=[
            "frozen_core_candidate_remains_unchanged",
            "hvg_input_is_flavor_conditional",
            "pca_hvg_and_log_assumptions_are_project_profile_only",
            "neighbors_accepts_compatible_X_or_obsm_representations",
            "reuse_is_representation_specific_and_staleness_aware",
            "leiden_does_not_require_umap",
            "harmony_returns_corrected_embedding_not_counts",
            "scrublet_requires_raw_counts_per_capture_unit_and_requires_threshold_review",
            "singler_accepts_raw_query_counts_and_requires_valid_labelled_reference",
            "can_feed_requires_claim_scoped_compatibility_proof_not_type_equality",
            "all_high_risk_claims_bind_exact_bounded_spans_from_pinned_sources",
        ],
    )
    return bundle, spans, binding_rows, [*risk_rows, *proof_rows]


def _instance(type_id: str, *, states: list[str], transformations: list[str] | None = None, metadata: dict[str, Any] | None = None, components: list[str] | None = None, observation_alignment: str = "same_observations", feature_alignment: str = "not_applicable") -> dict[str, Any]:
    return {"representation_type_id": type_id, "value_states": states, "transformations": transformations or [], "modalities": ["rna"], "metadata": metadata or {}, "component_roles": components or [], "observation_alignment": observation_alignment, "feature_alignment": feature_alignment}


def _decision_uats(bundle: ConformanceBundle) -> list[dict[str, Any]]:
    revisions = {item.operator_id: item for item in bundle.entities if isinstance(item, OperatorRevision)}
    constraints = {item.constraint_id: item for item in bundle.representation_constraints}
    common_embedding_meta = {"ordered_observation_ids": ["c1", "c2"], "lineage_id": "lineage-1", "source_slot": "obsm/X", "semantic_parameter_signature": "compatible"}
    graph_meta = {"ordered_observation_ids": ["c1", "c2"], "lineage_id": "lineage-1", "neighbors_key": "neighbors", "connectivities_key": "connectivities", "distances_key": "distances", "semantic_parameter_signature": "compatible"}
    fresh_graph = _instance("representation-type:neighbor_graph", states=["fresh", "graph_constructed"], metadata=graph_meta, components=["connectivities", "distances", "parameters"])
    stale_graph = _instance("representation-type:neighbor_graph", states=["stale", "graph_constructed"], metadata=graph_meta, components=["connectivities", "distances", "parameters"])
    misaligned_graph = _instance("representation-type:neighbor_graph", states=["fresh", "graph_constructed"], metadata=graph_meta, components=["connectivities", "distances", "parameters"], observation_alignment="explicit_mapping")
    hvg_log = _instance("representation-type:log_expression", states=["fresh"], transformations=["log1p"], metadata={"ordered_observation_ids": [], "ordered_feature_ids": [], "source_slot": "X"}, feature_alignment="same_features")
    hvg_counts = _instance("representation-type:raw_umi_counts", states=["fresh", "integer_like_counts"], metadata={"ordered_observation_ids": [], "ordered_feature_ids": [], "source_slot": "layers/counts"}, feature_alignment="same_features")
    harmony_embedding = _instance("representation-type:cell_embedding", states=["fresh", "dimension_reduced"], transformations=["batch_corrected_embedding"], metadata={**common_embedding_meta, "source_slot": "obsm/X_harmony"})
    scrublet_raw = _instance("representation-type:raw_umi_counts", states=["fresh", "integer_like_counts"], metadata={"ordered_observation_ids": [], "ordered_feature_ids": [], "capture_unit_id": "capture-1", "source_slot": "layers/counts"}, feature_alignment="same_features")
    scrublet_normalized = _instance("representation-type:raw_umi_counts", states=["fresh", "integer_like_counts"], transformations=["normalized"], metadata={"ordered_observation_ids": [], "ordered_feature_ids": [], "capture_unit_id": "capture-1", "source_slot": "X"}, feature_alignment="same_features")
    query_raw = _instance("representation-type:gene_by_cell_expression", states=["fresh", "raw_counts"], metadata={"ordered_observation_ids": ["c1"], "ordered_feature_ids": ["g1", "g2"], "feature_namespace": "ensembl"}, feature_alignment="intersection")
    reference = _instance("representation-type:reference_expression", states=["fresh", "reference_annotated", "log_expression"], metadata={"ordered_reference_ids": ["r1"], "ordered_feature_ids": ["g1", "g3"], "feature_namespace": "ensembl", "biological_applicability_confirmed": True, "organism_taxon": "NCBITaxon:9606"}, observation_alignment="not_applicable", feature_alignment="intersection")
    labels = _instance("representation-type:reference_labels", states=["fresh", "reference_annotated"], metadata={"ordered_reference_ids": ["r1"], "label_namespace": "author_labels"}, observation_alignment="not_applicable")

    hvg_port = revisions["operator:scanpy.pp.highly_variable_genes"].input_ports[0]
    neighbors_port = revisions["operator:scanpy.pp.neighbors"].input_ports[0]
    umap_port = revisions["operator:scanpy.tl.umap"].input_ports[0]
    leiden_port = revisions["operator:scanpy.tl.leiden"].input_ports[0]
    scrublet_port = revisions["operator:scrublet.Scrublet.scrub_doublets"].input_ports[0]
    singler_ports = revisions["operator:SingleR::SingleR"].input_ports

    def single_r_valid(query: dict[str, Any], ref: dict[str, Any], labs: dict[str, Any]) -> bool:
        if not all(port_accepts(port, constraints, [instance]) for port, instance in zip(singler_ports, [query, ref, labs], strict=True)):
            return False
        query_features = set(query["metadata"]["ordered_feature_ids"])
        ref_features = set(ref["metadata"]["ordered_feature_ids"])
        return bool(query_features & ref_features) and ref["metadata"]["ordered_reference_ids"] == labs["metadata"]["ordered_reference_ids"]

    uats = [
        {"uat_id": "reuse-valid-processed-neighbor-graph", "passed": port_accepts(leiden_port, constraints, [fresh_graph]) and port_accepts(umap_port, constraints, [fresh_graph]), "decision": "reuse"},
        {"uat_id": "skip-unnecessary-preprocessing", "passed": port_accepts(leiden_port, constraints, [fresh_graph]) and not any(item.relation == "REQUIRES_BEFORE" for item in bundle.derived_relations), "decision": "skip_pca_neighbors_umap_for_leiden"},
        {"uat_id": "reject-stale-or-misaligned-graph", "passed": not port_accepts(leiden_port, constraints, [stale_graph]) and not port_accepts(leiden_port, constraints, [misaligned_graph]), "decision": "reject"},
        {"uat_id": "hvg-flavor-counts-vs-log", "passed": port_accepts(hvg_port, constraints, [hvg_log], {"parameter:scanpy_hvg_flavor": "seurat"}) and not port_accepts(hvg_port, constraints, [hvg_counts], {"parameter:scanpy_hvg_flavor": "seurat"}) and port_accepts(hvg_port, constraints, [hvg_counts], {"parameter:scanpy_hvg_flavor": "seurat_v3"}) and not port_accepts(hvg_port, constraints, [hvg_log], {"parameter:scanpy_hvg_flavor": "seurat_v3"}), "decision": "branch_by_flavor"},
        {"uat_id": "harmony-embedding-to-neighbors-reuse", "passed": port_accepts(neighbors_port, constraints, [harmony_embedding]), "decision": "reuse_harmony_embedding"},
        {"uat_id": "leiden-without-umap", "passed": port_accepts(leiden_port, constraints, [fresh_graph]) and all("umap" not in requirement.requirement_id for requirement in leiden_port.requirements), "decision": "allow"},
        {"uat_id": "scrublet-input-state", "passed": port_accepts(scrublet_port, constraints, [scrublet_raw]) and not port_accepts(scrublet_port, constraints, [scrublet_normalized]) and not port_accepts(scrublet_port, constraints, [harmony_embedding]), "decision": "raw_counts_only"},
        {"uat_id": "singler-raw-query-valid-reference", "passed": single_r_valid(query_raw, reference, labels), "decision": "allow"},
        {"uat_id": "singler-invalid-or-misaligned-reference", "passed": not single_r_valid(query_raw, {**reference, "metadata": {**reference["metadata"], "ordered_feature_ids": ["g9"]}}, labels) and not single_r_valid(query_raw, reference, {**labels, "metadata": {**labels["metadata"], "ordered_reference_ids": ["r9"]}}), "decision": "reject"},
    ]
    return uats


def build(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    before = _canonical_hashes()
    frozen_before = {path.name: _sha_file(path) for path in FROZEN_CORE_DIR.iterdir() if path.is_file()}
    bundle, spans, binding_rows, risk_and_proof_rows = _build_knowledge()
    sources, _ = _source_snapshot()
    uats = _decision_uats(bundle)
    risks = [row for row in risk_and_proof_rows if "risk_class" in row]
    proofs = [row for row in risk_and_proof_rows if "proof" in row]
    claims = {item.claim_revision_id: item for item in bundle.atomic_claims}
    assessment_by_claim = {item.claim_revision_id: item for item in bundle.evidence_assessments}

    decision_deltas = {
        "schema_version": SCHEMA_VERSION,
        "frozen_baseline": "22489bd12ea0d0259dcf4c30ab74f4c8e209bf17",
        "frozen_core_modified": False,
        "deltas": [
            {"rule": "HVG input", "frozen": "single mandatory log_expression", "corrected": "conditional log for seurat/cell_ranger; counts for seurat_v3/seurat_v3_paper"},
            {"rule": "PCA input", "frozen": "universal log/HVG implication", "corrected": "generic declared expression; HVG optional; scaled-HVG is a project profile"},
            {"rule": "neighbors input", "frozen": "mandatory PCA coordinates", "corrected": "compatible X, PCA or governed obsm embedding"},
            {"rule": "UMAP/Leiden graph", "frozen": "abstract neighbor_graph", "corrected": "component keys, connectivities, graph parameters, lineage, identity and freshness; Leiden also accepts explicit adjacency"},
            {"rule": "Harmony interface", "frozen": "PCA-only input and multimodal integrated coordinates", "corrected": "PCA-default and generic embedding interfaces; corrected RNA cell embedding output only"},
            {"rule": "Scrublet", "frozen": "raw counts plus one broad limitation", "corrected": "raw per-capture counts, threshold review, no automatic deletion authorization"},
            {"rule": "SingleR", "frozen": "log query plus generic reference expression", "corrected": "raw or log query; reference expression, labels, feature intersection and biological applicability"},
            {"rule": "CAN_FEED", "frozen": "automatic exact RepresentationType equality", "corrected": "four explicit claim-scoped compatibility proofs; no global type-equality generation"},
        ],
    }

    promotion = {
        "schema_version": SCHEMA_VERSION,
        "promotion_performed": False,
        "promotion_ready": sorted(row["record_id"] for row in risks if row.get("promotion_eligibility") == "promotion_ready"),
        "review_required": sorted(row["record_id"] for row in risks if "review" in row.get("promotion_eligibility", "") or row["risk_class"] in {"R3", "R4"}),
        "scoped_profile_only": sorted(row["record_id"] for row in risks if row.get("promotion_eligibility") == "scoped_profile_only"),
        "execution_only_blockers": [
            {"id": "execution-blocker:scanpy-toolcontract-snapshot", "reason": "scientific claims can be promoted independently; execution requires a matching immutable ToolContract snapshot"},
            {"id": "execution-blocker:runtime-representation-binding", "reason": "actual observation/feature identity, lineage, parameter compatibility and staleness remain RepresentationLedger/runtime facts"},
            {"id": "execution-blocker:singler-reference-artifact-revision", "reason": "execution requires an immutable selected reference artifact revision and runtime feature/label alignment"},
        ],
        "scientific_blockers": [
            {"id": row["record_id"], "reason": "risk-appropriate review has not been recorded"}
            for row in risks
            if row["risk_class"] in {"R3", "R4"}
        ],
    }

    quality: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "candidate_only_not_promoted",
    }
    span_ids = {row["evidence_span_id"] for row in spans}
    source_ids = {row["source_revision_id"] for row in sources}
    quality["checks"] = {
        "schema_validity": True,
        "frozen_core_unchanged": frozen_before == {path.name: _sha_file(path) for path in FROZEN_CORE_DIR.iterdir() if path.is_file()},
        "evidence_span_resolvability": all(set(item.evidence_span_ids) <= span_ids for item in bundle.evidence_assessments),
        "source_revision_resolvability": all(row["source_revision_id"] in source_ids for row in spans),
        "evidence_excerpt_hash_validity": all(row["content_hash"] == _sha_text(row["source_excerpt"]) for row in spans),
        "pinned_source_line_span_hashes": all(
            row.get("source_line_span_sha256")
            or row["source_revision_id"].startswith("source-revision:github:scverse/scanpy:")
            or row["source_revision_id"].startswith("source-revision:sckg:capability-pack:")
            for row in spans
        ),
        "claim_content_hash_validity": all(item.content_hash == _sha_text(item.claim_text) for item in bundle.atomic_claims),
        "high_risk_exact_binding": all(assessment_by_claim[row["record_id"]].evidence_span_ids for row in risks if row["record_type"] == "AtomicClaimRevision" and row["risk_class"] in {"R3", "R4"}),
        "no_type_equality_only_can_feed": all(not row["type_equality_only"] for row in proofs),
        "no_requires_before": not any(item.relation == "REQUIRES_BEFORE" for item in bundle.derived_relations),
        "decision_uats": all(row["passed"] for row in uats),
        "candidate_only": not bundle.review_decisions and not promotion["promotion_performed"],
    }
    quality["counts"] = {"operator_revisions": sum(isinstance(item, OperatorRevision) for item in bundle.entities), "atomic_claims": len(claims), "evidence_spans": len(spans), "derived_relations": len(bundle.derived_relations), "can_feed_relations": sum(item.relation == "CAN_FEED" for item in bundle.derived_relations), "decision_uats": len(uats)}

    _write_json(output_dir / "conformance_bundle.json", bundle.model_dump(mode="json"))
    _write_json(output_dir / "authoritative_source_manifest.json", {"schema_version": SCHEMA_VERSION, "sources": sources})
    _write_jsonl(output_dir / "authoritative_evidence_spans.jsonl", spans)
    _write_jsonl(output_dir / "atomic_claims.jsonl", [item.model_dump(mode="json") for item in bundle.atomic_claims])
    _write_jsonl(output_dir / "evidence_assessments.jsonl", [item.model_dump(mode="json") for item in bundle.evidence_assessments])
    _write_jsonl(output_dir / "exact_evidence_bindings.jsonl", binding_rows)
    _write_jsonl(output_dir / "risk_registry.jsonl", risks)
    _write_jsonl(output_dir / "derived_relations.jsonl", [item.model_dump(mode="json") for item in bundle.derived_relations])
    _write_json(output_dir / "derived_relation_proofs.json", {"schema_version": SCHEMA_VERSION, "proofs": proofs})
    _write_json(output_dir / "decision_rule_deltas.json", decision_deltas)
    _write_json(output_dir / "decision_uat_results.json", {"schema_version": SCHEMA_VERSION, "passed": all(row["passed"] for row in uats), "results": uats})
    _write_json(output_dir / "promotion_preflight.json", promotion)
    _write_json(output_dir / "semantic_quality_report.json", quality)
    after = _canonical_hashes()
    dependency_impact = {"canonical_before": before, "canonical_after": after, "canonical_kg_modified": before != after, "retrieval_index_rebuilt": False, "runtime_modified": False, "frozen_core_modified": not quality["checks"]["frozen_core_unchanged"]}
    _write_json(output_dir / "dependency_impact.json", dependency_impact)
    artifact_names = sorted(path.name for path in output_dir.iterdir() if path.is_file() and path.name != "manifest.json")
    manifest = {"schema_version": SCHEMA_VERSION, "status": "candidate_only_not_promoted", "base_commit": "22489bd12ea0d0259dcf4c30ab74f4c8e209bf17", "artifacts": {name: _sha_file(output_dir / name) for name in artifact_names}, **dependency_impact}
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build corrected Scientific KG v1 UAT decision-rule candidate slice")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
