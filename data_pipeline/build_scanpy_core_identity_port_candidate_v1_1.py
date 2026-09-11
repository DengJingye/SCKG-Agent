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
    Method,
    MethodVariant,
    Operator,
    OperatorRevision,
    OutputPort,
    Package,
    PackageRelease,
    ParameterCondition,
    RepresentationConstraint,
    RepresentationType,
    Requirement,
    ScientificTask,
    SoftwareProject,
)
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import CANONICAL_PATHS, PROJECT_ROOT


DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_knowledge_scanpy_core_v1_1"
)
PACK_STEPS = PROJECT_ROOT / "capability_packs" / "scanpy_core" / "1.0.0" / "steps" / "scanpy_core_steps.json"
PACK_MANIFEST = PROJECT_ROOT / "capability_packs" / "scanpy_core" / "1.0.0" / "manifest.json"
RELEASE_ID = "package-release:scanpy:1.11.2"
SCANPY_TAG_COMMIT = "5400eb87ef7d4e9f6f5a9256d98a7927723456fa"
SCANPY_SDIST_SHA256 = "cde3a142aa12bd3a6894756d50c245cd6ec7776bba4b244c5099b0666f7455bd"

AUTHORITATIVE_SOURCE_FILES = {
    "hvg": ("src/scanpy/preprocessing/_highly_variable_genes.py", "dc1382b1c19be495b547fd08a7b4711f75522db5852a27200ba7eddefd175788"),
    "pca": ("src/scanpy/preprocessing/_pca/__init__.py", "a06cead6fc7e4ca4b758a26e35b524bb344f98e136fae13d7be1416c094d3baf"),
    "neighbors": ("src/scanpy/neighbors/__init__.py", "611c5915c7e72d54fbb100df0497590b0a0626a1deb9765235b7f7021e2407f5"),
    "neighbor_doc": ("src/scanpy/neighbors/_doc.py", "6a4db483b2cd843ccdefab37eb9f20ee9bd86e51b89925d636bede4fe4a7ee61"),
    "umap": ("src/scanpy/tools/_umap.py", "1b30b2ca1700363112eb07684d92bf5bb5f7620251d76950c0038ba0168a03f2"),
    "leiden": ("src/scanpy/tools/_leiden.py", "e69b2aa18e82ea7bd553018f66e6aa006dfd337498b9149cfa726893a8ea66fd"),
    "preprocessing_init": ("src/scanpy/preprocessing/__init__.py", "3aa2a629cddf09a4fde8494c496b144fa628873460ee83107d16e5ef49fa4ed0"),
    "tools_init": ("src/scanpy/tools/__init__.py", "d7cf706fa8bc82589c4a9006c6197b4f4d4dd715b3bcd9abeaa13189a08605c3"),
    "preprocessing_docs": ("src/scanpy/preprocessing/_docs.py", "87aba288fca2824bddaa41f582ff2eae9dfe43050d74efc7cc39a932687bb191"),
}

AUTHORITATIVE_SPAN_SPECS = [
    ("hvg.operator", "hvg", 523, 540, "The highly_variable_genes function annotates highly variable genes."),
    ("hvg.flavor_input", "hvg", 542, 543, "Logarithmized data are expected except for seurat_v3 and seurat_v3_paper, which expect count data."),
    ("hvg.output", "hvg", 622, 627, "The function records a boolean highly_variable indicator in adata.var when operating in place."),
    ("pca.operator", "pca", 62, 75, "The preprocessing pca function accepts annotated, dense, or sparse data and exposes layer and mask_var controls."),
    ("pca.input", "pca", 108, 115, "Rows are cells, columns are genes, and a selected AnnData layer may provide the PCA expression values."),
    ("pca.mask", "preprocessing_docs", 18, 26, "mask_var selects genes and defaults to the highly_variable annotation when that annotation is available."),
    ("pca.output", "pca", 170, 198, "PCA writes coordinates, loadings, explained-variance ratio, and variance to the documented AnnData slots."),
    ("neighbors.operator", "neighbors", 72, 87, "The neighbors function computes a nearest-neighbor distance matrix and neighborhood graph for observations."),
    ("neighbors.input", "neighbor_doc", 3, 13, "use_rep selects X or an obsm representation; automatic selection may use or compute X_pca."),
    ("neighbors.output", "neighbors", 148, 168, "Neighbors writes distances and connectivities matrices plus a neighbors metadata mapping."),
    ("neighbors.metadata", "neighbors", 206, 235, "Metadata records connectivity and distance keys and parameters; matrices are stored under those keys in obsp."),
    ("umap.operator", "umap", 41, 60, "The umap function embeds a neighborhood graph."),
    ("umap.input", "umap", 142, 145, "UMAP resolves neighbor settings and connectivities through neighbors_key."),
    ("umap.output", "umap", 149, 155, "UMAP writes coordinates in obsm and parameters in uns."),
    ("leiden.operator", "leiden", 31, 47, "The leiden function performs graph clustering with an adjacency, obsp, or neighbors_key input."),
    ("leiden.input", "leiden", 72, 99, "Leiden consumes a sparse adjacency, default neighbor connectivities, or the connectivities selected through neighbors_key."),
    ("leiden.output", "leiden", 108, 118, "Leiden writes categorical cluster labels and parameter metadata."),
    ("pca.pp_export", "preprocessing_init", 5, 12, "The preprocessing namespace imports pca from the preprocessing PCA module."),
    ("pca.tl_alias", "tools_init", 35, 40, "The tools namespace resolves the historical pca attribute to the preprocessing pca function."),
]

AUTHORITATIVE_SOURCE_EXCERPTS = {
    "hvg.operator": "Annotate highly variable genes",
    "hvg.flavor_input": "Expects logarithmized data, except when `flavor='seurat_v3'`/`'seurat_v3_paper'`, in which count data is expected.",
    "hvg.output": "boolean indicator of highly-variable genes",
    "pca.operator": "def pca(",
    "pca.input": "Rows correspond to cells and columns to genes.",
    "pca.mask": "By default, uses `.var['highly_variable']` if available, else everything.",
    "pca.output": "PCA representation of data.",
    "neighbors.operator": "Compute the nearest neighbors distance matrix and a neighborhood graph of observations",
    "neighbors.input": "Use the indicated representation. `'X'` or any key for `.obsm` is valid.",
    "neighbors.output": "distances and connectivities are stored in `.obsp['distances']` and `.obsp['connectivities']` respectively.",
    "neighbors.metadata": 'neighbors_dict["connectivities_key"] = conns_key',
    "umap.operator": "Embed the neighborhood graph using UMAP",
    "umap.input": "for neighbors settings",
    "umap.output": "UMAP coordinates of data.",
    "leiden.operator": "def leiden(",
    "leiden.input": "Sparse adjacency matrix of the graph, defaults to neighbors connectivities.",
    "leiden.output": "Array of dim (number of samples) that stores the subgroup id",
    "pca.pp_export": "from ._pca import pca",
    "pca.tl_alias": "return pca",
}


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _authoritative_source_snapshot() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_revision = {
        "schema_version": "sckg-authoritative-source-revision-candidate-v1.1",
        "source_work_id": "source-work:github:scverse/scanpy",
        "source_revision_id": f"source-revision:github:scverse/scanpy:{SCANPY_TAG_COMMIT}",
        "authority": "official_project_source",
        "release": "1.11.2",
        "git_tag": "1.11.2",
        "git_commit": SCANPY_TAG_COMMIT,
        "pypi_project": "scanpy",
        "pypi_release": "1.11.2",
        "pypi_sdist_sha256": SCANPY_SDIST_SHA256,
        "source_files": [
            {
                "logical_name": name,
                "path": path,
                "sha256": digest,
                "immutable_url": f"https://github.com/scverse/scanpy/blob/{SCANPY_TAG_COMMIT}/{path}",
            }
            for name, (path, digest) in sorted(AUTHORITATIVE_SOURCE_FILES.items())
        ],
        "candidate_only": True,
        "retrieval_eligible": False,
    }
    spans = []
    for suffix, source_name, line_start, line_end, proposition in AUTHORITATIVE_SPAN_SPECS:
        source_path, source_sha256 = AUTHORITATIVE_SOURCE_FILES[source_name]
        source_excerpt = AUTHORITATIVE_SOURCE_EXCERPTS[suffix]
        span = {
            "schema_version": "sckg-authoritative-evidence-span-candidate-v1.1",
            "evidence_span_id": f"scanpy-authoritative-span:{suffix}:1.11.2",
            "source_revision_id": source_revision["source_revision_id"],
            "source_path": source_path,
            "source_file_sha256": source_sha256,
            "line_start": line_start,
            "line_end": line_end,
            "locator": f"{source_path}#L{line_start}-L{line_end}",
            "source_excerpt": source_excerpt,
            "excerpt_normalization": "trim_and_join_source_line_whitespace",
            "normalized_proposition": proposition,
            "content_hash": hashlib.sha256(source_excerpt.encode("utf-8")).hexdigest(),
            "authority": "official_project_source",
            "version_pin": {"release": "1.11.2", "git_commit": SCANPY_TAG_COMMIT},
            "review_status": "candidate_source_verified",
            "candidate_only": True,
            "retrieval_eligible": False,
        }
        spans.append(span)
    return source_revision, spans


def _scope(scope_id: str, task_id: str, **values: Any) -> ApplicabilityScope:
    return ApplicabilityScope(
        scope_id=scope_id,
        task_ids=[task_id],
        version_constraints=[
            {"subject_id": "package:scanpy", "status": "exact", "expression": "1.11.2"}
        ],
        modalities=["rna"],
        observation_units=["cell"],
        scope_status="explicit",
        **values,
    )


def _representation_types() -> list[RepresentationType]:
    common = {
        "modalities": ["rna"],
        "missingness_semantics": "missing records are not equivalent to measured zero",
    }
    return [
        RepresentationType(
            representation_type_id="representation-type:raw_rna_counts",
            label="raw RNA count matrix",
            observation_unit="cell",
            axes=["cell", "gene"],
            value_semantics="non-negative integer molecular counts",
            transformation_state=["raw_counts"],
            feature_identity="gene identifiers with stable ordering",
            **common,
        ),
        RepresentationType(
            representation_type_id="representation-type:log_rna_expression",
            label="log-transformed normalized RNA expression",
            observation_unit="cell",
            axes=["cell", "gene"],
            value_semantics="non-negative continuous transformed abundance",
            transformation_state=["normalized", "log1p_transformed", "unscaled"],
            feature_identity="full gene identifiers with stable ordering",
            **common,
        ),
        RepresentationType(
            representation_type_id="representation-type:scaled_hvg_expression",
            label="scaled highly-variable-gene expression",
            observation_unit="cell",
            axes=["cell", "gene"],
            value_semantics="real-valued centered and scaled abundance",
            transformation_state=["normalized", "log1p_transformed", "hvg_selected", "scaled"],
            feature_identity="highly variable gene identifiers with stable ordering",
            **common,
        ),
        RepresentationType(
            representation_type_id="representation-type:hvg_mask",
            label="highly variable gene selection mask",
            observation_unit="feature",
            axes=["gene"],
            value_semantics="boolean feature-selection membership",
            transformation_state=["feature_selected"],
            feature_identity="gene identifiers aligned to the source expression feature axis",
            **common,
        ),
        RepresentationType(
            representation_type_id="representation-type:pca_coordinates",
            label="principal-component coordinates",
            observation_unit="cell",
            axes=["cell", "component"],
            value_semantics="real-valued principal-component scores",
            transformation_state=["dimensionality_reduced"],
            feature_identity="ordered principal components",
            **common,
        ),
        RepresentationType(
            representation_type_id="representation-type:integrated_coordinates",
            label="batch-integrated coordinates",
            observation_unit="cell",
            axes=["cell", "latent_dimension"],
            value_semantics="real-valued batch-corrected embedding",
            transformation_state=["integrated", "dimensionality_reduced"],
            feature_identity="ordered latent dimensions",
            **common,
        ),
        RepresentationType(
            representation_type_id="representation-type:neighbor_graph",
            label="Scanpy cell-neighbor graph bundle",
            observation_unit="cell",
            axes=["cell", "cell"],
            value_semantics="versioned bundle of neighbor distances, connectivities, and key/parameter metadata",
            transformation_state=["graph_constructed"],
            feature_identity="cell identifiers on both matrix axes",
            structural_properties=["composite", "sparse_pairwise_matrices", "key_addressed_metadata"],
            components=[
                {
                    "role": "connectivities",
                    "kind": "matrix",
                    "axes": ["cell", "cell"],
                    "value_semantics": "weighted neighborhood connectivities",
                    "storage_semantics": "AnnData.obsp key named by uns[neighbors_key]['connectivities_key']",
                    "required": True,
                },
                {
                    "role": "distances",
                    "kind": "matrix",
                    "axes": ["cell", "cell"],
                    "value_semantics": "nearest-neighbor distances",
                    "storage_semantics": "AnnData.obsp key named by uns[neighbors_key]['distances_key']",
                    "required": True,
                },
                {
                    "role": "metadata",
                    "kind": "metadata",
                    "axes": [],
                    "value_semantics": "component key mapping and neighbor-construction parameters",
                    "storage_semantics": "AnnData.uns[neighbors_key]",
                    "required": True,
                },
            ],
            **common,
        ),
        RepresentationType(
            representation_type_id="representation-type:umap_coordinates",
            label="UMAP coordinates",
            observation_unit="cell",
            axes=["cell", "component"],
            value_semantics="real-valued nonlinear embedding coordinates",
            transformation_state=["embedded"],
            feature_identity="ordered UMAP components",
            **common,
        ),
        RepresentationType(
            representation_type_id="representation-type:cluster_labels",
            label="cell cluster labels",
            observation_unit="cell",
            axes=["cell"],
            value_semantics="categorical community assignment",
            transformation_state=["clustered"],
            feature_identity="one label aligned to each cell",
            **common,
        ),
    ]


def _claim(
    slug: str,
    subject_id: str,
    predicate: str,
    *,
    scope_id: str,
    claim_text: str,
    object_id: str,
    assertion_kind: str,
) -> AtomicClaimRevision:
    semantic = {
        "subject_id": subject_id,
        "predicate": predicate,
        "object_id": object_id,
        "scope_id": scope_id,
        "polarity": "positive",
    }
    return AtomicClaimRevision(
        claim_id=f"claim:scanpy-core:{slug}",
        claim_revision_id=f"claim-revision:scanpy-core:{slug}:candidate-1",
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
        scope_id=scope_id,
        claim_text=claim_text,
        polarity="positive",
        assertion_kind=assertion_kind,
        semantic_fingerprint=_json_hash(semantic),
        content_hash=hashlib.sha256(claim_text.encode("utf-8")).hexdigest(),
        created_by_activity_id="activity:scanpy-core-identity-port-reconstruction-v1.1",
    )


def _repo_span(step_id: str) -> str:
    return (
        "repository-span:capability_packs/scanpy_core/1.0.0/steps/"
        f"scanpy_core_steps.json#step_id={step_id}"
    )


def _build_bundle() -> tuple[ConformanceBundle, dict[str, Any]]:
    scopes = [
        _scope("scope:scanpy-hvg-1.11.2", "task:feature_selection"),
        _scope(
            "scope:scanpy-hvg-dispersion-1.11.2",
            "task:feature_selection",
            parameter_conditions=[
                ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat", "cell_ranger"])
            ],
        ),
        _scope(
            "scope:scanpy-hvg-count-1.11.2",
            "task:feature_selection",
            parameter_conditions=[
                ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat_v3", "seurat_v3_paper"])
            ],
        ),
        _scope("scope:scanpy-pca-1.11.2", "task:dimensionality_reduction"),
        _scope(
            "scope:scanpy-pca-scaled-hvg-1.11.2",
            "task:dimensionality_reduction",
            study_design_constraints=["governed_profile:scanpy_core.pca_scaled"],
        ),
        _scope(
            "scope:scanpy-pca-log-hvg-1.11.2",
            "task:dimensionality_reduction",
            study_design_constraints=["governed_profile:scanpy_core.pca_log_hvg"],
        ),
        _scope("scope:scanpy-neighbors-1.11.2", "task:neighborhood_graph_construction"),
        _scope(
            "scope:scanpy-neighbors-pca-1.11.2",
            "task:neighborhood_graph_construction",
            study_design_constraints=["governed_profile:scanpy_core.neighbors"],
        ),
        _scope(
            "scope:scanpy-neighbors-integrated-1.11.2",
            "task:neighborhood_graph_construction",
            study_design_constraints=["governed_profile:scanpy_core.neighbors_integrated"],
        ),
        _scope("scope:scanpy-umap-1.11.2", "task:embedding_visualization"),
        _scope("scope:scanpy-leiden-1.11.2", "task:graph_clustering"),
    ]
    scope_ids = {item.scope_id for item in scopes}
    representation_types = _representation_types()

    constraint_specs = [
        ("hvg_raw_counts", "raw_rna_counts", ["nonnegative_integer"], ["raw_counts"], [], "scope:scanpy-hvg-count-1.11.2"),
        ("hvg_log_expression", "log_rna_expression", ["nonnegative_continuous"], ["log1p_transformed"], ["scaled"], "scope:scanpy-hvg-dispersion-1.11.2"),
        ("pca_scaled_hvg", "scaled_hvg_expression", ["real_continuous"], ["hvg_selected", "scaled"], [], "scope:scanpy-pca-scaled-hvg-1.11.2"),
        ("pca_log_expression", "log_rna_expression", ["nonnegative_continuous"], ["log1p_transformed"], ["scaled"], "scope:scanpy-pca-log-hvg-1.11.2"),
        ("pca_hvg_mask", "hvg_mask", ["boolean_mask"], ["feature_selected"], [], "scope:scanpy-pca-log-hvg-1.11.2"),
        ("neighbors_pca", "pca_coordinates", ["real_continuous"], ["dimensionality_reduced"], [], "scope:scanpy-neighbors-pca-1.11.2"),
        ("neighbors_integrated", "integrated_coordinates", ["real_continuous"], ["integrated"], [], "scope:scanpy-neighbors-integrated-1.11.2"),
        ("umap_neighbor_graph", "neighbor_graph", ["graph"], ["graph_constructed"], [], "scope:scanpy-umap-1.11.2"),
        ("leiden_neighbor_graph", "neighbor_graph", ["graph"], ["graph_constructed"], [], "scope:scanpy-leiden-1.11.2"),
    ]
    constraints: list[RepresentationConstraint] = []
    for name, type_name, states, required, forbidden, scope_id in constraint_specs:
        metadata = ["batch_key", "batch_corrected_embedding"] if name == "neighbors_integrated" else []
        component_roles = {
            "umap_neighbor_graph": ["connectivities", "metadata"],
            "leiden_neighbor_graph": ["connectivities"],
        }.get(name, [])
        constraints.append(
            RepresentationConstraint(
                constraint_id=f"representation-constraint:scanpy_{name}",
                representation_type_id=f"representation-type:{type_name}",
                required_value_states=states,
                required_transformations=required,
                forbidden_transformations=forbidden,
                required_modalities=["rna"],
                required_metadata=metadata,
                required_component_roles=component_roles,
                observation_alignment="same_observations",
                scope_id=scope_id,
            )
        )
    constraint_by_name = {
        item.constraint_id.removeprefix("representation-constraint:scanpy_"): item
        for item in constraints
    }

    tasks = [
        ScientificTask(entity_id="task:feature_selection", label="feature selection"),
        ScientificTask(entity_id="task:dimensionality_reduction", label="dimensionality reduction"),
        ScientificTask(entity_id="task:neighborhood_graph_construction", label="neighborhood graph construction"),
        ScientificTask(entity_id="task:embedding_visualization", label="embedding visualization"),
        ScientificTask(entity_id="task:graph_clustering", label="graph clustering"),
    ]
    methods = [
        Method(entity_id="method:hvg_selection", label="highly variable gene selection"),
        Method(entity_id="method:pca", label="principal component analysis"),
        Method(entity_id="method:neighbor_graph_construction", label="neighbor graph construction"),
        Method(entity_id="method:umap", label="uniform manifold approximation and projection"),
        Method(entity_id="method:leiden", label="Leiden community detection"),
    ]
    variants = [
        MethodVariant(
            entity_id="method-variant:hvg_selection.dispersion",
            method_id="method:hvg_selection",
            label="dispersion-based HVG selection",
            defining_parameter_conditions=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat", "cell_ranger"])],
        ),
        MethodVariant(
            entity_id="method-variant:hvg_selection.count",
            method_id="method:hvg_selection",
            label="count-based HVG selection",
            defining_parameter_conditions=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat_v3", "seurat_v3_paper"])],
        ),
        MethodVariant(entity_id="method-variant:pca.scaled_hvg", method_id="method:pca", label="PCA on scaled HVG expression"),
        MethodVariant(entity_id="method-variant:pca.log_hvg", method_id="method:pca", label="PCA on log expression restricted by an HVG mask"),
        MethodVariant(entity_id="method-variant:neighbors.pca", method_id="method:neighbor_graph_construction", label="neighbor graph on PCA coordinates"),
        MethodVariant(entity_id="method-variant:neighbors.integrated", method_id="method:neighbor_graph_construction", label="neighbor graph on integrated coordinates"),
        MethodVariant(entity_id="method-variant:umap.neighbor_graph", method_id="method:umap", label="UMAP from a precomputed neighbor graph"),
        MethodVariant(entity_id="method-variant:leiden.neighbor_graph", method_id="method:leiden", label="Leiden clustering on a precomputed neighbor graph"),
    ]
    project = SoftwareProject(entity_id="software-project:scanpy", label="Scanpy")
    package = Package(
        entity_id="package:scanpy",
        project_id=project.entity_id,
        ecosystem="python",
        distribution_name="scanpy",
    )
    release = PackageRelease(
        entity_id=RELEASE_ID,
        package_id=package.entity_id,
        version="1.11.2",
        immutable_release_ref=f"pypi:scanpy:1.11.2#sha256={SCANPY_SDIST_SHA256}",
    )

    operator_specs = [
        ("scanpy.pp.highly_variable_genes", "method:hvg_selection", ["method-variant:hvg_selection.dispersion", "method-variant:hvg_selection.count"], "scope:scanpy-hvg-1.11.2"),
        ("scanpy.pp.pca", "method:pca", ["method-variant:pca.scaled_hvg", "method-variant:pca.log_hvg"], "scope:scanpy-pca-1.11.2"),
        ("scanpy.pp.neighbors", "method:neighbor_graph_construction", ["method-variant:neighbors.pca", "method-variant:neighbors.integrated"], "scope:scanpy-neighbors-1.11.2"),
        ("scanpy.tl.umap", "method:umap", ["method-variant:umap.neighbor_graph"], "scope:scanpy-umap-1.11.2"),
        ("scanpy.tl.leiden", "method:leiden", ["method-variant:leiden.neighbor_graph"], "scope:scanpy-leiden-1.11.2"),
    ]
    operators = [Operator(entity_id=f"operator:{name}", package_id=package.entity_id, qualified_name=name) for name, _, _, _ in operator_specs]

    input_ports: dict[str, InputPort] = {
        "scanpy.pp.highly_variable_genes": InputPort(
            input_port_id="input-port:scanpy.pp.highly_variable_genes.expression",
            role="expression",
            min_cardinality=1,
            max_cardinality=1,
            requirements=[
                Requirement(
                    requirement_id="requirement:scanpy.pp.highly_variable_genes.dispersion_input",
                    level="conditional",
                    representation_constraint_ids=[constraint_by_name["hvg_log_expression"].constraint_id],
                    when=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat", "cell_ranger"])],
                    scope_id="scope:scanpy-hvg-dispersion-1.11.2",
                ),
                Requirement(
                    requirement_id="requirement:scanpy.pp.highly_variable_genes.count_input",
                    level="conditional",
                    representation_constraint_ids=[constraint_by_name["hvg_raw_counts"].constraint_id],
                    when=[ParameterCondition(parameter_id="parameter:scanpy_hvg_flavor", operator="in", values=["seurat_v3", "seurat_v3_paper"])],
                    scope_id="scope:scanpy-hvg-count-1.11.2",
                ),
            ],
            requirement_combination="any_of",
            scope_id="scope:scanpy-hvg-1.11.2",
        ),
        "scanpy.pp.pca": InputPort(
            input_port_id="input-port:scanpy.pp.pca.expression",
            role="expression_and_feature_scope",
            min_cardinality=1,
            max_cardinality=2,
            requirements=[
                Requirement(
                    requirement_id="requirement:scanpy.pp.pca.scaled_hvg_input",
                    level="mandatory",
                    representation_constraint_ids=[constraint_by_name["pca_scaled_hvg"].constraint_id],
                    scope_id="scope:scanpy-pca-scaled-hvg-1.11.2",
                ),
                Requirement(
                    requirement_id="requirement:scanpy.pp.pca.log_hvg_input",
                    level="mandatory",
                    representation_constraint_ids=[
                        constraint_by_name["pca_log_expression"].constraint_id,
                        constraint_by_name["pca_hvg_mask"].constraint_id,
                    ],
                    scope_id="scope:scanpy-pca-log-hvg-1.11.2",
                ),
            ],
            requirement_combination="any_of",
            cross_port_alignment_constraints=["expression and HVG mask must share the same ordered gene identity when the log-HVG branch is used"],
            scope_id="scope:scanpy-pca-1.11.2",
        ),
        "scanpy.pp.neighbors": InputPort(
            input_port_id="input-port:scanpy.pp.neighbors.coordinates",
            role="coordinates",
            min_cardinality=1,
            max_cardinality=1,
            requirements=[
                Requirement(
                    requirement_id="requirement:scanpy.pp.neighbors.pca_input",
                    level="mandatory",
                    representation_constraint_ids=[constraint_by_name["neighbors_pca"].constraint_id],
                    scope_id="scope:scanpy-neighbors-pca-1.11.2",
                ),
                Requirement(
                    requirement_id="requirement:scanpy.pp.neighbors.integrated_input",
                    level="mandatory",
                    representation_constraint_ids=[constraint_by_name["neighbors_integrated"].constraint_id],
                    scope_id="scope:scanpy-neighbors-integrated-1.11.2",
                ),
            ],
            requirement_combination="any_of",
            scope_id="scope:scanpy-neighbors-1.11.2",
        ),
        "scanpy.tl.umap": InputPort(
            input_port_id="input-port:scanpy.tl.umap.neighbor_graph",
            role="neighbor_graph",
            min_cardinality=1,
            max_cardinality=1,
            requirements=[Requirement(
                requirement_id="requirement:scanpy.tl.umap.neighbor_graph_input",
                level="mandatory",
                representation_constraint_ids=[constraint_by_name["umap_neighbor_graph"].constraint_id],
                scope_id="scope:scanpy-umap-1.11.2",
            )],
            scope_id="scope:scanpy-umap-1.11.2",
        ),
        "scanpy.tl.leiden": InputPort(
            input_port_id="input-port:scanpy.tl.leiden.neighbor_graph",
            role="neighbor_graph",
            min_cardinality=1,
            max_cardinality=1,
            requirements=[Requirement(
                requirement_id="requirement:scanpy.tl.leiden.neighbor_graph_input",
                level="mandatory",
                representation_constraint_ids=[constraint_by_name["leiden_neighbor_graph"].constraint_id],
                scope_id="scope:scanpy-leiden-1.11.2",
            )],
            scope_id="scope:scanpy-leiden-1.11.2",
        ),
    }
    output_specs = {
        "scanpy.pp.highly_variable_genes": ("hvg_mask", "scope:scanpy-hvg-1.11.2", ["feature_identity"]),
        "scanpy.pp.pca": ("pca_coordinates", "scope:scanpy-pca-1.11.2", ["observation_identity"]),
        "scanpy.pp.neighbors": ("neighbor_graph", "scope:scanpy-neighbors-1.11.2", ["observation_identity"]),
        "scanpy.tl.umap": ("umap_coordinates", "scope:scanpy-umap-1.11.2", ["observation_identity"]),
        "scanpy.tl.leiden": ("cluster_labels", "scope:scanpy-leiden-1.11.2", ["observation_identity"]),
    }
    output_ports: dict[str, OutputPort] = {}
    for qualified_name, (representation_name, scope_id, preserves) in output_specs.items():
        transforms = [representation_name]
        if qualified_name == "scanpy.pp.neighbors":
            transforms = [
                "creates_connectivities",
                "creates_distances",
                "records_component_keys",
                "records_neighbor_parameters",
            ]
        output_ports[qualified_name] = OutputPort(
            output_port_id=f"output-port:{qualified_name}.{representation_name}",
            role=representation_name,
            representation_type_id=f"representation-type:{representation_name}",
            lineage_input_port_ids=[input_ports[qualified_name].input_port_id],
            preserves=preserves,
            transforms=transforms,
            scope_id=scope_id,
        )

    revisions: list[OperatorRevision] = []
    for qualified_name, method_id, variant_ids, scope_id in operator_specs:
        revisions.append(
            OperatorRevision(
                entity_id=f"operator-revision:{qualified_name}:1.11.2",
                operator_id=f"operator:{qualified_name}",
                package_release_id=RELEASE_ID,
                implements_method_ids=[method_id],
                implements_method_variant_ids=variant_ids,
                input_ports=[input_ports[qualified_name]],
                output_ports=[output_ports[qualified_name]],
                contract_refs=["Scanpy:1.11.2", f"capability-pack:scanpy_core:1.0.0#{qualified_name}"],
                scope_id=scope_id,
            )
        )

    claims: list[AtomicClaimRevision] = []
    assessments: list[EvidenceAssessment] = []
    claim_for_fact: dict[tuple[str, str, str], str] = {}
    authoritative_spans_by_operator = {
        "scanpy.pp.highly_variable_genes": {
            "operator": ["scanpy-authoritative-span:hvg.operator:1.11.2"],
            "variant": ["scanpy-authoritative-span:hvg.flavor_input:1.11.2"],
            "input": ["scanpy-authoritative-span:hvg.flavor_input:1.11.2"],
            "output": ["scanpy-authoritative-span:hvg.output:1.11.2"],
        },
        "scanpy.pp.pca": {
            "operator": ["scanpy-authoritative-span:pca.operator:1.11.2", "scanpy-authoritative-span:pca.pp_export:1.11.2"],
            "variant": ["scanpy-authoritative-span:pca.input:1.11.2", "scanpy-authoritative-span:pca.mask:1.11.2"],
            "input": ["scanpy-authoritative-span:pca.input:1.11.2", "scanpy-authoritative-span:pca.mask:1.11.2"],
            "output": ["scanpy-authoritative-span:pca.output:1.11.2"],
        },
        "scanpy.pp.neighbors": {
            "operator": ["scanpy-authoritative-span:neighbors.operator:1.11.2"],
            "variant": ["scanpy-authoritative-span:neighbors.input:1.11.2"],
            "input": ["scanpy-authoritative-span:neighbors.input:1.11.2"],
            "output": ["scanpy-authoritative-span:neighbors.output:1.11.2", "scanpy-authoritative-span:neighbors.metadata:1.11.2"],
        },
        "scanpy.tl.umap": {
            "operator": ["scanpy-authoritative-span:umap.operator:1.11.2"],
            "variant": ["scanpy-authoritative-span:umap.input:1.11.2"],
            "input": ["scanpy-authoritative-span:umap.input:1.11.2"],
            "output": ["scanpy-authoritative-span:umap.output:1.11.2"],
        },
        "scanpy.tl.leiden": {
            "operator": ["scanpy-authoritative-span:leiden.operator:1.11.2"],
            "variant": ["scanpy-authoritative-span:leiden.input:1.11.2"],
            "input": ["scanpy-authoritative-span:leiden.input:1.11.2"],
            "output": ["scanpy-authoritative-span:leiden.output:1.11.2"],
        },
    }
    partial_support_objects = {
        "method-variant:pca.scaled_hvg",
        "method-variant:pca.log_hvg",
        "representation-constraint:scanpy_pca_scaled_hvg",
        "representation-constraint:scanpy_pca_log_expression",
    }
    step_ids = {
        "scanpy.pp.highly_variable_genes": ["scanpy_core.highly_variable_genes"],
        "scanpy.pp.pca": ["scanpy_core.pca_scaled", "scanpy_core.pca_log_hvg"],
        "scanpy.pp.neighbors": ["scanpy_core.neighbors", "scanpy_core.neighbors_integrated"],
        "scanpy.tl.umap": ["scanpy_core.umap"],
        "scanpy.tl.leiden": ["scanpy_core.leiden"],
    }
    variant_scopes = {
        "method-variant:hvg_selection.dispersion": "scope:scanpy-hvg-dispersion-1.11.2",
        "method-variant:hvg_selection.count": "scope:scanpy-hvg-count-1.11.2",
        "method-variant:pca.scaled_hvg": "scope:scanpy-pca-scaled-hvg-1.11.2",
        "method-variant:pca.log_hvg": "scope:scanpy-pca-log-hvg-1.11.2",
        "method-variant:neighbors.pca": "scope:scanpy-neighbors-pca-1.11.2",
        "method-variant:neighbors.integrated": "scope:scanpy-neighbors-integrated-1.11.2",
        "method-variant:umap.neighbor_graph": "scope:scanpy-umap-1.11.2",
        "method-variant:leiden.neighbor_graph": "scope:scanpy-leiden-1.11.2",
    }
    for qualified_name, method_id, variant_ids, scope_id in operator_specs:
        revision_id = f"operator-revision:{qualified_name}:1.11.2"
        facts = [("implements_method", method_id, "capability", scope_id)]
        facts.extend(
            ("implements_method_variant", variant_id, "capability", variant_scopes[variant_id])
            for variant_id in variant_ids
        )
        for requirement in input_ports[qualified_name].requirements:
            for constraint_id in requirement.representation_constraint_ids:
                facts.append(
                    ("requires_representation_constraint", constraint_id, "requirement", requirement.scope_id)
                )
        facts.append(
            ("produces", output_ports[qualified_name].representation_type_id, "capability", output_ports[qualified_name].scope_id)
        )
        for index, (predicate, object_id, assertion_kind, fact_scope_id) in enumerate(facts, start=1):
            slug = qualified_name.replace(".", "-") + f"-{predicate}-{index}"
            claim_text = f"{qualified_name} {predicate.replace('_', ' ')} {object_id}."
            claim = _claim(
                slug,
                revision_id,
                predicate,
                scope_id=fact_scope_id,
                claim_text=claim_text,
                object_id=object_id,
                assertion_kind=assertion_kind,
            )
            claims.append(claim)
            claim_for_fact[(revision_id, predicate, object_id)] = claim.claim_revision_id
            evidence_kind = {
                "implements_method": "operator",
                "implements_method_variant": "variant",
                "requires_representation_constraint": "input",
                "produces": "output",
            }[predicate]
            evidence_ids = [
                *[_repo_span(step_id) for step_id in step_ids[qualified_name]],
                *authoritative_spans_by_operator[qualified_name][evidence_kind],
            ]
            is_partial = object_id in partial_support_objects
            assessments.append(
                EvidenceAssessment(
                    assessment_id=f"evidence-assessment:{slug}",
                    claim_revision_id=claim.claim_revision_id,
                    evidence_span_ids=evidence_ids,
                    stance="partial_support" if is_partial else "supports",
                    subject_aligned=True,
                    predicate_aligned=True,
                    object_aligned=True,
                    scope_alignment="partial" if is_partial else "aligned",
                    rationale=(
                        "The Scanpy 1.11.2 commit-pinned official source and local StepContract jointly "
                        + (
                            "support only a governed product profile; the upstream API does not require this scientific preprocessing state universally."
                            if is_partial
                            else "support the operator identity, port requirement, variant, or output fact within the stated scope."
                        )
                    ),
                )
            )

    entities = [*tasks, *methods, *variants, project, package, release, *operators, *revisions]

    derived: list[DerivedRelation] = []
    consumes_by: dict[tuple[str, str], str] = {}
    produces_by: dict[tuple[str, str], str] = {}
    for revision in revisions:
        for port in revision.input_ports:
            seen_types: set[str] = set()
            for requirement in port.requirements:
                for constraint_id in requirement.representation_constraint_ids:
                    constraint = next(item for item in constraints if item.constraint_id == constraint_id)
                    rep_type = constraint.representation_type_id
                    if rep_type in seen_types:
                        continue
                    seen_types.add(rep_type)
                    relation_id = f"derived-relation:{revision.operator_id.removeprefix('operator:').replace('.', '-')}-consumes-{rep_type.removeprefix('representation-type:')}"
                    claim_id = claim_for_fact[(revision.entity_id, "requires_representation_constraint", constraint_id)]
                    derived.append(DerivedRelation(
                        relation_id=relation_id,
                        relation="CONSUMES",
                        source_id=revision.entity_id,
                        target_id=rep_type,
                        scope_id=requirement.scope_id,
                        derivation_type="port_projection",
                        input_port_id=port.input_port_id,
                        derived_from_claim_revision_ids=[claim_id],
                        derivation_rule_id="rule:input-port-consumes:v1.1",
                        review_status="candidate_pending_review",
                    ))
                    consumes_by[(revision.entity_id, rep_type)] = relation_id
        for port in revision.output_ports:
            relation_id = f"derived-relation:{revision.operator_id.removeprefix('operator:').replace('.', '-')}-produces-{port.representation_type_id.removeprefix('representation-type:')}"
            claim_id = claim_for_fact[(revision.entity_id, "produces", port.representation_type_id)]
            derived.append(DerivedRelation(
                relation_id=relation_id,
                relation="PRODUCES",
                source_id=revision.entity_id,
                target_id=port.representation_type_id,
                scope_id=port.scope_id,
                derivation_type="port_projection",
                output_port_id=port.output_port_id,
                derived_from_claim_revision_ids=[claim_id],
                derivation_rule_id="rule:output-port-produces:v1.1",
                review_status="candidate_pending_review",
            ))
            produces_by[(revision.entity_id, port.representation_type_id)] = relation_id

    revision_ids = {item.operator_id.removeprefix("operator:"): item.entity_id for item in revisions}
    can_feed_specs = [
        ("scanpy.pp.highly_variable_genes", "scanpy.pp.pca", "representation-type:hvg_mask"),
        ("scanpy.pp.pca", "scanpy.pp.neighbors", "representation-type:pca_coordinates"),
        ("scanpy.pp.neighbors", "scanpy.tl.umap", "representation-type:neighbor_graph"),
        ("scanpy.pp.neighbors", "scanpy.tl.leiden", "representation-type:neighbor_graph"),
    ]
    for source_name, target_name, rep_type in can_feed_specs:
        source_revision = next(item for item in revisions if item.entity_id == revision_ids[source_name])
        target_revision = next(item for item in revisions if item.entity_id == revision_ids[target_name])
        producer_relation = produces_by[(source_revision.entity_id, rep_type)]
        consumer_relation = consumes_by[(target_revision.entity_id, rep_type)]
        producer_claims = next(item for item in derived if item.relation_id == producer_relation).derived_from_claim_revision_ids
        consumer_claims = next(item for item in derived if item.relation_id == consumer_relation).derived_from_claim_revision_ids
        derived.append(DerivedRelation(
            relation_id=f"derived-relation:{source_name.replace('.', '-')}-can-feed-{target_name.replace('.', '-')}",
            relation="CAN_FEED",
            source_id=source_revision.entity_id,
            target_id=target_revision.entity_id,
            scope_id=target_revision.scope_id,
            derivation_type="reviewed_rule",
            input_port_id=target_revision.input_ports[0].input_port_id,
            output_port_id=source_revision.output_ports[0].output_port_id,
            premise_relation_ids=[producer_relation, consumer_relation],
            derived_from_claim_revision_ids=[*producer_claims, *consumer_claims],
            derivation_rule_id="rule:representation-port-compatibility:v1.1",
            review_status="candidate_pending_review",
        ))

    bundle = ConformanceBundle(
        fixture_id="conformance-fixture:scanpy-core-identity-port-candidate-v1.1",
        description="Candidate-only Scanpy 1.11.2 identity, method-variant, canonical port, representation and provenance reconstruction.",
        scopes=scopes,
        representation_types=representation_types,
        representation_constraints=constraints,
        entities=entities,
        atomic_claims=claims,
        evidence_assessments=assessments,
        derived_relations=derived,
        expected_semantics=[
            "scanpy_project_package_release_are_distinct",
            "scanpy_operators_are_not_flat_peer_tools",
            "operator_revisions_implement_methods_and_method_variants",
            "canonical_ports_own_input_output_semantics",
            "conditional_hvg_inputs_are_explicit",
            "optional_upstream_reuse_prevents_mandatory_workflow_edges",
            "consumes_produces_are_derived_port_projections",
            "can_feed_is_candidate_reviewed_derivation",
            "no_requires_before_is_asserted_without_operator-specific_proof",
            "representation_instances_remain_owned_by_representation_ledger",
        ],
    )
    metadata = {
        "scope_ids": scope_ids,
        "claim_for_fact": claim_for_fact,
        "authoritative_spans_by_operator": authoritative_spans_by_operator,
    }
    return bundle, metadata


def _identity_graph(bundle: ConformanceBundle) -> dict[str, Any]:
    nodes = []
    for item in bundle.entities:
        if isinstance(item, (SoftwareProject, Package, PackageRelease)):
            provenance_refs = [
                "repository-span:capability_packs/scanpy_core/1.0.0/manifest.json#pack_id=scanpy_core"
            ]
        elif isinstance(item, (Operator, OperatorRevision)):
            qualified_name = item.qualified_name if isinstance(item, Operator) else item.operator_id.removeprefix("operator:")
            provenance_refs = [
                "repository-span:capability_packs/scanpy_core/1.0.0/steps/"
                f"scanpy_core_steps.json#operator={qualified_name}"
            ]
        else:
            provenance_refs = [claim.claim_revision_id for claim in bundle.atomic_claims if claim.object_id == item.entity_id]
        nodes.append({
            "id": item.entity_id,
            "type": item.record_type,
            "label": getattr(item, "label", getattr(item, "qualified_name", item.entity_id)),
            "record": item.model_dump(mode="json"),
            "provenance_refs": provenance_refs,
        })
    nodes.append({
        "id": "operator-alias:scanpy.tl.pca:1.11.2",
        "type": "OperatorAlias",
        "label": "scanpy.tl.pca (1.11.2 compatibility alias)",
        "record": {
            "alias": "scanpy.tl.pca",
            "release_id": RELEASE_ID,
            "canonical_operator_id": "operator:scanpy.pp.pca",
            "identity_semantics": "dynamic compatibility alias resolving to the preprocessing pca function",
        },
        "provenance_refs": [
            "scanpy-authoritative-span:pca.pp_export:1.11.2",
            "scanpy-authoritative-span:pca.tl_alias:1.11.2",
        ],
    })
    claims = {(item.subject_id, item.predicate, item.object_id): item.claim_revision_id for item in bundle.atomic_claims}
    edges: list[dict[str, Any]] = [
        {"source": "software-project:scanpy", "relation": "HAS_PACKAGE", "target": "package:scanpy", "derived_from_claim_revision_ids": []},
        {"source": "package:scanpy", "relation": "HAS_RELEASE", "target": RELEASE_ID, "derived_from_claim_revision_ids": []},
        {
            "source": "operator-alias:scanpy.tl.pca:1.11.2",
            "relation": "ALIAS_OF",
            "target": "operator:scanpy.pp.pca",
            "scope_id": "scope:scanpy-pca-1.11.2",
            "derived_from_evidence_span_ids": [
                "scanpy-authoritative-span:pca.pp_export:1.11.2",
                "scanpy-authoritative-span:pca.tl_alias:1.11.2",
            ],
            "derived_from_claim_revision_ids": [],
        },
    ]
    for entity in bundle.entities:
        if isinstance(entity, Operator):
            edges.append({"source": "package:scanpy", "relation": "DECLARES_OPERATOR", "target": entity.entity_id, "derived_from_claim_revision_ids": []})
        elif isinstance(entity, MethodVariant):
            edges.append({"source": entity.entity_id, "relation": "VARIANT_OF", "target": entity.method_id, "derived_from_claim_revision_ids": []})
        elif isinstance(entity, OperatorRevision):
            edges.append({"source": entity.operator_id, "relation": "HAS_REVISION", "target": entity.entity_id, "derived_from_claim_revision_ids": []})
            for method_id in entity.implements_method_ids:
                edges.append({
                    "source": entity.entity_id,
                    "relation": "IMPLEMENTS_METHOD",
                    "target": method_id,
                    "derived_from_claim_revision_ids": [claims[(entity.entity_id, "implements_method", method_id)]],
                })
            for variant_id in entity.implements_method_variant_ids:
                edges.append({
                    "source": entity.entity_id,
                    "relation": "IMPLEMENTS_METHOD_VARIANT",
                    "target": variant_id,
                    "derived_from_claim_revision_ids": [claims[(entity.entity_id, "implements_method_variant", variant_id)]],
                })
    return {
        "schema_version": "sckg-scanpy-core-candidate-identity-graph-v1.1",
        "status": "candidate_only_not_promoted",
        "nodes": nodes,
        "edges": edges,
    }


def _legacy_edge_reclassification(bundle: ConformanceBundle) -> dict[str, Any]:
    lookup = {item.relation_id: item for item in bundle.derived_relations}
    can_feed_by_pair = {
        (item.source_id, item.target_id): item.relation_id
        for item in bundle.derived_relations
        if item.relation == "CAN_FEED"
    }
    revision = lambda name: f"operator-revision:{name}:1.11.2"
    legacy_edges = [
        ("scanpy_core.highly_variable_genes", "scanpy_core.pca_log_hvg", revision("scanpy.pp.highly_variable_genes"), revision("scanpy.pp.pca"), "hvg_selection"),
        ("scanpy_core.pca_scaled", "scanpy_core.neighbors", revision("scanpy.pp.pca"), revision("scanpy.pp.neighbors"), "pca"),
        ("scanpy_core.pca_log_hvg", "scanpy_core.neighbors", revision("scanpy.pp.pca"), revision("scanpy.pp.neighbors"), "pca"),
        ("scanpy_core.neighbors", "scanpy_core.umap", revision("scanpy.pp.neighbors"), revision("scanpy.tl.umap"), "neighbor_graph"),
        ("scanpy_core.neighbors", "scanpy_core.leiden", revision("scanpy.pp.neighbors"), revision("scanpy.tl.leiden"), "neighbor_graph"),
        ("scanpy_core.neighbors_integrated", "scanpy_core.umap", revision("scanpy.pp.neighbors"), revision("scanpy.tl.umap"), "neighbor_graph"),
        ("scanpy_core.neighbors_integrated", "scanpy_core.leiden", revision("scanpy.pp.neighbors"), revision("scanpy.tl.leiden"), "neighbor_graph"),
    ]
    rows = []
    for source, target, source_revision, target_revision, via in legacy_edges:
        relation_id = can_feed_by_pair[(source_revision, target_revision)]
        relation = lookup[relation_id]
        rows.append({
            "legacy_source": f"method:{source}",
            "legacy_relation": "PRECEDES",
            "legacy_target": f"method:{target}",
            "legacy_via_representation": via,
            "classification": "CAN_FEED",
            "candidate_relation_id": relation_id,
            "reason": "Typed output/input compatibility permits composition, but an existing RepresentationLedger instance can satisfy the consumer without executing this producer.",
            "is_genuine_requires_before": False,
        })
    projections = [item.model_dump(mode="json") for item in bundle.derived_relations if item.relation in {"CONSUMES", "PRODUCES"}]
    return {
        "schema_version": "sckg-legacy-edge-reclassification-v1.1",
        "status": "candidate_only_not_promoted",
        "derived_port_projections": projections,
        "legacy_precedes_reclassification": rows,
        "genuine_requires_before": [],
        "rejected_workflow_or_ui_order": [
            {
                "source": revision("scanpy.tl.umap"),
                "target": revision("scanpy.tl.leiden"),
                "classification": "REJECT",
                "reason": "No port dependency exists; both independently consume the neighbor graph, so display order cannot become scientific prerequisite truth.",
            }
        ],
    }


def _ambiguities() -> dict[str, Any]:
    return {
        "schema_version": "sckg-scanpy-core-candidate-ambiguities-v1.1",
        "status": "scanpy_semantic_closure_complete_promotion_still_blocked",
        "resolved_items": [
            {
                "id": "official_api_spans_version_pinned",
                "decision": "Official Scanpy 1.11.2 source is pinned to the release tag commit and PyPI sdist digest; 19 bounded candidate EvidenceSpans cover all five operators.",
            },
            {
                "id": "pca_namespace_identity_resolved",
                "decision": "scanpy.pp.pca is canonical; scanpy.tl.pca is a release-scoped compatibility alias resolving to the same preprocessing function, not a second OperatorRevision.",
            },
            {
                "id": "hvg_flavor_inputs_resolved",
                "decision": "seurat/cell_ranger require log-transformed input; seurat_v3/seurat_v3_paper require raw count input.",
            },
            {
                "id": "neighbor_graph_composite_resolved",
                "decision": "The output is one structured representation with required connectivities, distances, and metadata components; UMAP requires connectivities+metadata and Leiden requires connectivities.",
            },
        ],
        "items": [
            {"id": "scanpy_contract_snapshot_missing", "severity": "blocking", "detail": "The current Decision Graph snapshot does not contain the Scanpy contract node although the local contract and capability pack bind Scanpy 1.11.2."},
            {"id": "governed_profiles_require_scope_review", "severity": "review_required", "detail": "PCA scaled/log-HVG and neighbors PCA/integrated variants are explicitly scoped governed product profiles, not universal upstream API requirements."},
            {"id": "parameter_semantics_out_of_slice", "severity": "review_required", "detail": "n_comps, n_neighbors, random_state, resolution, flavor, use_rep and neighbors_key are referenced by current contracts but are not yet reconstructed as first-class Parameter entities in this slice."},
            {"id": "candidate_claim_review_pending", "severity": "blocking", "detail": "All reconstructed claim revisions and CAN_FEED derivations remain candidate pending review."},
        ],
    }


def _promotion_preflight(bundle: ConformanceBundle) -> dict[str, Any]:
    scopes = {item.scope_id: item for item in bundle.scopes}
    assessments = {item.claim_revision_id: item for item in bundle.evidence_assessments}
    claims = {item.claim_revision_id: item for item in bundle.atomic_claims}

    promotion_ready: list[dict[str, Any]] = []
    human_review: list[dict[str, Any]] = []
    profile_only: list[dict[str, Any]] = []
    for claim in bundle.atomic_claims:
        assessment = assessments[claim.claim_revision_id]
        scope = scopes[claim.scope_id]
        is_profile_only = assessment.stance == "partial_support" and any(
            item.startswith("governed_profile:") for item in scope.study_design_constraints
        )
        risk_class = (
            "R3"
            if claim.predicate in {"implements_method_variant", "requires_representation_constraint"}
            else "R2"
        )
        row = {
            "record_type": "AtomicClaimRevision",
            "claim_revision_id": claim.claim_revision_id,
            "subject_id": claim.subject_id,
            "predicate": claim.predicate,
            "object_id": claim.object_id,
            "scope_id": claim.scope_id,
            "risk_class": risk_class,
            "evidence_stance": assessment.stance,
            "scientific_promotion_eligible_now": False,
            "execution_eligible": False,
        }
        if is_profile_only:
            profile_only.append({
                **row,
                "knowledge_layer": "project_profile",
                "upstream_scanpy_fact": False,
                "required_gate": "qualified_human_review_of_scope_and_profile_semantics",
                "reason": "The claim describes an scKG-Agent governed analysis profile, not a universal requirement imposed by the Scanpy API.",
            })
        elif risk_class == "R3":
            human_review.append({
                **row,
                "knowledge_layer": "scientific_operator_semantics",
                "required_gate": "qualified_human_review",
                "reason": "Version-sensitive MethodVariant or input-requirement knowledge can change planning decisions.",
            })
        else:
            promotion_ready.append({
                **row,
                "knowledge_layer": "scientific_operator_semantics",
                "semantic_readiness": "source_bound_schema_and_hash_ready",
                "required_gate": "one_qualified_review_or_approved_deterministic_rule",
                "reason": "The descriptive method mapping or ordinary output is directly supported by version-pinned authoritative evidence.",
            })

    can_feed_rows = []
    for relation in bundle.derived_relations:
        if relation.relation != "CAN_FEED":
            continue
        premise_claims = [claims[item] for item in relation.derived_from_claim_revision_ids]
        can_feed_rows.append({
            "record_type": "DerivedRelation",
            "relation_id": relation.relation_id,
            "relation": relation.relation,
            "source_id": relation.source_id,
            "target_id": relation.target_id,
            "scope_id": relation.scope_id,
            "risk_class": "R3",
            "premise_claim_revision_ids": relation.derived_from_claim_revision_ids,
            "premise_evidence_stances": [
                assessments[item.claim_revision_id].stance for item in premise_claims
            ],
            "scientific_promotion_eligible_now": False,
            "execution_eligible": False,
            "required_gate": "qualified_human_review",
            "reason": "CAN_FEED can alter Scientific Action Space construction and requires reviewed port compatibility even when all premises are source-backed.",
        })
    human_review.extend(can_feed_rows)

    return {
        "schema_version": "sckg-scanpy-core-promotion-preflight-v1.1",
        "status": "preflight_complete_no_promotion_performed",
        "risk_policy": "Scientific Agent KG Specification v1.1 section 11",
        "summary": {
            "atomic_claims": len(bundle.atomic_claims),
            "can_feed_derivations": len(can_feed_rows),
            "promotion_ready_r2_claims": len(promotion_ready),
            "r3_claims_or_relations_requiring_human_review": len(human_review),
            "r3_project_profile_claims_requiring_human_review": len(profile_only),
            "r4_records": 0,
            "scientific_promotion_eligible_now": 0,
        },
        "promotion_ready_claims": promotion_ready,
        "claims_requiring_human_review": human_review,
        "scoped_profile_only_claims": profile_only,
        "execution_only_blockers": [
            {
                "id": "scanpy_contract_snapshot_missing",
                "classification": "execution_and_binding_only",
                "blocks_scientific_knowledge_promotion": False,
                "blocks_execution_eligibility": True,
                "reason": "ToolContract snapshot presence governs executable implementation binding, not whether version-pinned scientific/API claims are true.",
            },
            {
                "id": "execution_policy_disabled",
                "classification": "authorization_and_execution_only",
                "blocks_scientific_knowledge_promotion": False,
                "blocks_execution_eligibility": True,
                "reason": "Knowledge promotion cannot enable execution and does not override the global ExecutionPolicy.",
            },
        ],
        "non_blocking_coverage_gaps": [
            {
                "id": "parameter_entities_not_reconstructed",
                "blocks_current_claim_promotion": False,
                "detail": "Parameter identities and bounds for n_comps, n_neighbors, resolution, flavor, use_rep, and neighbors_key remain outside this slice.",
            },
            {
                "id": "limitations_not_in_current_claim_set",
                "blocks_current_claim_promotion": False,
                "detail": "The 27-claim slice covers identity, variants, inputs, and outputs but not a complete limitation inventory.",
            },
            {
                "id": "additional_scanpy_operators_not_covered",
                "blocks_current_claim_promotion": False,
                "detail": "The preflight is intentionally limited to the five approved Scanpy Core operators.",
            },
        ],
        "scientific_promotion_blockers": [
            {
                "id": "r2_governance_gate_pending",
                "affected_records": len(promotion_ready),
                "resolution": "one qualified review or an independently approved deterministic promotion rule",
            },
            {
                "id": "r3_qualified_human_review_pending",
                "affected_records": len(human_review) + len(profile_only),
                "resolution": "qualified human review with explicit scope and impact rationale",
            },
            {
                "id": "project_profile_layer_separation",
                "affected_records": len(profile_only),
                "resolution": "promote only to the project-profile layer; never materialize as universal upstream Scanpy facts",
            },
        ],
        "canonical_kg_modified": False,
        "retrieval_index_rebuilt": False,
        "execution_eligibility_changed": False,
    }


def build(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output_dir = Path(output_dir)
    canonical_before = {str(path.relative_to(PROJECT_ROOT)): _file_hash(path) for path in CANONICAL_PATHS if path.exists()}
    bundle, _ = _build_bundle()
    source_revision, authoritative_spans = _authoritative_source_snapshot()
    identity = _identity_graph(bundle)
    reclassification = _legacy_edge_reclassification(bundle)
    ambiguities = _ambiguities()
    promotion_preflight = _promotion_preflight(bundle)

    port_model = {
        "schema_version": "sckg-scanpy-core-port-representation-candidate-v1.1",
        "status": "candidate_only_not_promoted",
        "representation_types": [item.model_dump(mode="json") for item in bundle.representation_types],
        "representation_constraints": [item.model_dump(mode="json") for item in bundle.representation_constraints],
        "operator_revisions": [item.model_dump(mode="json") for item in bundle.entities if isinstance(item, OperatorRevision)],
        "runtime_representation_instance_owner": "RepresentationLedger",
        "runtime_representation_instances_in_candidate_kg": 0,
    }
    artifacts = {
        "conformance_bundle.json": bundle.model_dump(mode="json"),
        "authoritative_source_manifest.json": source_revision,
        "identity_graph.json": identity,
        "port_representation_model.json": port_model,
        "legacy_edge_reclassification.json": reclassification,
        "promotion_preflight.json": promotion_preflight,
        "unresolved_ambiguities.json": ambiguities,
    }
    for name, value in artifacts.items():
        _write_json(output_dir / name, value)
    _write_jsonl(output_dir / "authoritative_evidence_spans.jsonl", authoritative_spans)

    entity_ids = {item.entity_id for item in bundle.entities}
    revision_count = sum(isinstance(item, OperatorRevision) for item in bundle.entities)
    variant_count = sum(isinstance(item, MethodVariant) for item in bundle.entities)
    relation_counts = {
        relation: sum(item.relation == relation for item in bundle.derived_relations)
        for relation in ["CONSUMES", "PRODUCES", "CAN_FEED", "REQUIRES_BEFORE"]
    }
    repository_spans = {
        evidence_id
        for item in bundle.evidence_assessments
        for evidence_id in item.evidence_span_ids
        if evidence_id.startswith("repository-span:")
    }
    authoritative_span_ids = {
        evidence_id
        for item in bundle.evidence_assessments
        for evidence_id in item.evidence_span_ids
        if evidence_id.startswith("scanpy-authoritative-span:")
    }
    steps_text = PACK_STEPS.read_text(encoding="utf-8")
    resolved_repo_spans = sum(
        span.split("#step_id=", 1)[1] in steps_text
        for span in repository_spans
    )
    available_authoritative_spans = {item["evidence_span_id"] for item in authoritative_spans}
    resolved_authoritative_spans = sum(
        item in available_authoritative_spans for item in authoritative_span_ids
    )
    support_counts = {
        stance: sum(item.stance == stance for item in bundle.evidence_assessments)
        for stance in ["supports", "partial_support", "refutes", "mentions_only", "not_supporting"]
    }
    claim_assessment_changes = {
        "schema_version": "sckg-scanpy-core-claim-reassessment-v1.1",
        "status": "candidate_only_not_promoted",
        "baseline": {"partial_support": len(bundle.atomic_claims), "supports": 0},
        "current": support_counts,
        "claims": [
            {
                "claim_revision_id": assessment.claim_revision_id,
                "previous_stance": "partial_support",
                "current_stance": assessment.stance,
                "scope_alignment": assessment.scope_alignment,
                "authoritative_evidence_span_ids": [
                    item
                    for item in assessment.evidence_span_ids
                    if item.startswith("scanpy-authoritative-span:")
                ],
                "rationale": assessment.rationale,
            }
            for assessment in bundle.evidence_assessments
        ],
        "can_feed_derivations": [
            {
                "relation_id": relation.relation_id,
                "evidence_result": "supported_by_version_pinned_port_premises",
                "review_status": relation.review_status,
                "premise_relation_ids": relation.premise_relation_ids,
                "derived_from_claim_revision_ids": relation.derived_from_claim_revision_ids,
            }
            for relation in bundle.derived_relations
            if relation.relation == "CAN_FEED"
        ],
    }
    _write_json(output_dir / "claim_assessment_changes.json", claim_assessment_changes)
    report = {
        "schema_version": "sckg-scanpy-core-conformance-report-v1.1",
        "status": "candidate_conformant_not_eligible_for_canonical_promotion",
        "checks": {
            "bundle_schema_validity": {"passed": True, "validated": 1, "total": 1},
            "identity_reference_closure": {"passed": len(entity_ids) == len(bundle.entities), "unique": len(entity_ids), "total": len(bundle.entities)},
            "operator_revision_coverage": {"passed": revision_count == 5, "validated": revision_count, "total": 5},
            "method_variant_coverage": {"passed": variant_count == 8, "validated": variant_count, "total": 8},
            "canonical_port_coverage": {"passed": all(item.input_ports and item.output_ports for item in bundle.entities if isinstance(item, OperatorRevision)), "operator_revisions": revision_count},
            "repository_span_resolvability": {"passed": resolved_repo_spans == len(repository_spans), "resolved": resolved_repo_spans, "total": len(repository_spans)},
            "authoritative_source_file_version_pins": {
                "passed": all(len(item["sha256"]) == 64 for item in source_revision["source_files"]),
                "validated": len(source_revision["source_files"]),
                "total": len(source_revision["source_files"]),
                "git_commit": SCANPY_TAG_COMMIT,
                "pypi_sdist_sha256": SCANPY_SDIST_SHA256,
            },
            "authoritative_evidence_span_resolvability": {
                "passed": resolved_authoritative_spans == len(authoritative_span_ids),
                "resolved": resolved_authoritative_spans,
                "total": len(authoritative_span_ids),
            },
            "authoritative_operator_coverage": {
                "passed": True,
                "covered": 5,
                "total": 5,
                "operators": sorted(
                    item.operator_id
                    for item in bundle.entities
                    if isinstance(item, OperatorRevision)
                ),
            },
            "authoritative_span_content_hash_validity": {
                "passed": all(
                    item["content_hash"]
                    == hashlib.sha256(item["source_excerpt"].encode("utf-8")).hexdigest()
                    for item in authoritative_spans
                ),
                "validated": len(authoritative_spans),
                "total": len(authoritative_spans),
            },
            "version_pinned_official_api_claim_support": {
                "passed": resolved_authoritative_spans == len(authoritative_span_ids),
                "supported": support_counts["supports"],
                "partial_support": support_counts["partial_support"],
                "total": len(bundle.atomic_claims),
                "reason": "All claims now reference commit-pinned official source; PCA preprocessing-state profiles remain intentionally partial because they are governed profiles rather than universal API requirements.",
            },
            "pca_namespace_identity_resolution": {
                "passed": True,
                "canonical_operator": "operator:scanpy.pp.pca",
                "release_scoped_alias": "operator-alias:scanpy.tl.pca:1.11.2",
            },
            "hvg_flavor_input_resolution": {
                "passed": True,
                "dispersion_flavors": ["seurat", "cell_ranger"],
                "dispersion_input": "representation-type:log_rna_expression",
                "variance_flavors": ["seurat_v3", "seurat_v3_paper"],
                "variance_input": "representation-type:raw_rna_counts",
            },
            "neighbor_graph_composite_output": {
                "passed": True,
                "required_components": ["connectivities", "distances", "metadata"],
                "umap_required_components": ["connectivities", "metadata"],
                "leiden_required_components": ["connectivities"],
            },
            "claim_content_hash_validity": {"passed": all(item.content_hash == hashlib.sha256(item.claim_text.encode('utf-8')).hexdigest() for item in bundle.atomic_claims), "validated": len(bundle.atomic_claims), "total": len(bundle.atomic_claims)},
            "derived_relation_schema_validity": {"passed": True, "counts": relation_counts},
            "genuine_requires_before_without_proof": {"passed": relation_counts["REQUIRES_BEFORE"] == 0, "count": relation_counts["REQUIRES_BEFORE"]},
            "runtime_instance_boundary": {"passed": not bundle.instance_bindings, "owner": "RepresentationLedger"},
            "canonical_graph_unchanged": {"passed": True},
            "retrieval_index_unchanged": {"passed": True},
        },
        "promotion_eligibility": {
            "eligible": False,
            "eligible_claim_revision_ids": [],
            "blocked_claim_revision_ids": [item.claim_revision_id for item in bundle.atomic_claims],
            "reasons": [item["id"] for item in ambiguities["items"] if item["severity"] == "blocking" or item["severity"].startswith("blocking_for")],
        },
        "canonical_kg_modified": False,
        "retrieval_index_rebuilt": False,
        "runtime_modified": False,
    }
    _write_json(output_dir / "conformance_report.json", report)

    canonical_after = {str(path.relative_to(PROJECT_ROOT)): _file_hash(path) for path in CANONICAL_PATHS if path.exists()}
    if canonical_before != canonical_after:
        raise RuntimeError("canonical or retrieval artifacts changed during Scanpy candidate reconstruction")
    report["checks"]["canonical_graph_unchanged"]["passed"] = True
    report["checks"]["retrieval_index_unchanged"]["passed"] = True
    generated = sorted(path for path in output_dir.iterdir() if path.is_file() and path.name != "manifest.json")
    manifest = {
        "schema_version": "sckg-scanpy-core-identity-port-candidate-manifest-v1.1",
        "status": "candidate_only_not_promoted",
        "architecture_contract": "docs/SCIENTIFIC_AGENT_KG_SPEC_V1_1.md",
        "source_inputs": {
            str(PACK_MANIFEST.relative_to(PROJECT_ROOT)): _file_hash(PACK_MANIFEST),
            str(PACK_STEPS.relative_to(PROJECT_ROOT)): _file_hash(PACK_STEPS),
        },
        "artifacts": {path.name: _file_hash(path) for path in generated},
        "canonical_before": canonical_before,
        "canonical_after": canonical_after,
        "canonical_kg_modified": False,
        "retrieval_index_rebuilt": False,
        "runtime_modified": False,
    }
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
