from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from eval.midterm_core_benchmark_v2_1_models import (
    BaselineEligibility,
    BenchmarkSeedBundle,
    DenominatorMetadata,
    EvaluationRecord,
    EvidenceGold,
    LearningCondition,
    LearningEpisode,
    MethodAlternativeSet,
    ParentScenario,
    PartialOrderConstraint,
    RequirementExpectation,
    RequirementGold,
    WorkflowGold,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "eval_v2"
CONTRACT = ROOT / "docs" / "SCIENTIFIC_AGENT_EVALUATION_SUITE_V2_1.md"
CONTRACT_SHA256 = "c5417679a43ebf89495101504c2532cd85dbfde203968febc0fb825fcf46fb5f"
REVIEW_DECISION = "APPROVE"
REVIEWER_ROLE = "project_owner"
REVIEW_DATE = "2026-09-17"
REVIEWER_REASON = (
    "Scientific question, workflow constraints, evidence scope, version and "
    "ownership boundaries were manually reviewed and accepted."
)
REVIEW_CHECKLIST = ROOT / "docs" / "status" / "MIDTERM_CORE_SEED_V0_REVIEW_CHECKLIST.json"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(_canonical(value) + "\n" for value in values),
        encoding="utf-8",
    )


def _baseline(track: str) -> BaselineEligibility:
    mapping = {
        "G0": (["B0", "B3"], "semantic understanding source"),
        "T1": (["B2", "B3"], "Scientific KG applicability"),
        "T2": (["B1", "B2", "B3"], "Scientific KG scientific requirements"),
        "T3": (["B2", "B3"], "decision-local evidence projection"),
        "T4": (["B2", "B3"], "Scientific KG applicability"),
        "T5": (["B3", "B4"], "authoritative source acquisition"),
        "T6": (["S0", "S1", "S2"], "candidate knowledge structure"),
        "T7": (["B4"], "governance boundary mutation"),
        "T8": (["B3"], "one preregistered fault"),
    }
    baselines, varied = mapping[track]
    return BaselineEligibility(
        eligible_baselines=baselines,
        shared_inputs=[
            "parent query/task",
            "frozen scientific state",
            "tool and contract versions",
            "source-access policy where applicable",
        ],
        intentionally_varied_capability=varied,
        not_applicable_metrics=(
            ["end_to_end_execution"]
            if track in {"G0", "T3", "T5", "T6", "T7", "T8"}
            else []
        ),
    )


def parent_scenarios() -> list[ParentScenario]:
    rows = [
        (
            "neighbor-graph-reuse-leiden",
            "clustering",
            "When may Leiden reuse an existing neighbor graph, and when must reuse be rejected?",
            "study:pbmc3k-anchor",
            "dataset:pbmc3k-processed",
            "scanpy-1.11.2",
            "medium",
            [
                "state-aware planning",
                "representation reuse",
                "safe block",
                "workflow equivalence",
            ],
            True,
        ),
        (
            "harmony-embedding-neighbors",
            "batch_integration",
            "Can neighbors consume a compatible Harmony-corrected embedding without forcing PCA?",
            "study:pbmc3k-anchor",
            "dataset:pbmc3k-harmony-state",
            "harmony-2.0.5",
            "medium",
            ["state-aware planning", "method compatibility", "evidence fidelity"],
            True,
        ),
        (
            "scrublet-transformed-input",
            "doublet_detection",
            "May Scrublet run when only normalized or integrated expression is available?",
            "study:pbmc3k-anchor",
            "dataset:pbmc3k-transformed-only",
            "scrublet-0.2.3",
            "medium",
            ["input requirement", "missing resource", "safe block"],
            True,
        ),
        (
            "soupx-input-semantics",
            "ambient_rna_correction",
            "What do SoupX tod/toc tables represent, and can acquired evidence be deposited without promotion?",
            "study:pbmc3k-anchor",
            "dataset:pbmc3k-raw",
            "soupx-1.6.2",
            "medium",
            ["EvidenceGap acquisition", "candidate deposition", "governance boundary"],
            True,
        ),
        (
            "hvg-flavor-conditional-input",
            "feature_selection",
            "Which expression state is required for the selected Scanpy HVG flavor?",
            "study:pbmc3k-anchor",
            "dataset:pbmc3k-raw",
            "scanpy-1.11.2",
            "hard",
            ["conditional requirement", "clarification", "version scope"],
            False,
        ),
        (
            "singler-reference-compatibility",
            "cell_type_annotation",
            "Is the query/reference pair sufficiently aligned and biologically suitable for SingleR?",
            None,
            "scientific-state:singler-query-reference-pair",
            "singler-2.14.1",
            "hard",
            ["reference requirement", "feature alignment", "biological applicability"],
            False,
        ),
        (
            "celltypist-model-feature-alignment",
            "cell_type_annotation",
            "Does CellTypist have compatible normalized input, a resolved model artifact, and an evaluated feature alignment?",
            None,
            "scientific-state:celltypist-query",
            "celltypist-1.7.1",
            "hard",
            ["input state", "reference model", "feature alignment"],
            False,
        ),
        (
            "scvelo-layer-availability",
            "rna_velocity",
            "Are the required spliced/unspliced measurements available for an RNA-velocity task?",
            None,
            "scientific-state:scvelo-layer-availability",
            "scvelo-0.3.3",
            "hard",
            ["modality requirement", "missing input", "evidence gap"],
            False,
        ),
        (
            "mofa2-sample-alignment",
            "multi_omics_integration",
            "Are multi-omic matrices aligned on the same or explicitly overlapping samples for MOFA2?",
            None,
            "scientific-state:mofa2-sample-alignment",
            "mofa2-docs-ec2ee6d",
            "hard",
            ["multimodal input", "sample alignment", "clarification"],
            False,
        ),
    ]
    return [
        ParentScenario(
            scenario_id=f"scenario:v2.1:{slug}",
            task_family=task,
            scientific_question=question,
            study_id=study,
            dataset_id=dataset,
            source_group=source_group,
            difficulty=difficulty,
            split="development",
            capabilities_under_test=capabilities,
            historical_anchor=historical,
            review_status="reviewed",
        )
        for (
            slug,
            task,
            question,
            study,
            dataset,
            source_group,
            difficulty,
            capabilities,
            historical,
        ) in rows
    ]


def workflow_gold() -> list[WorkflowGold]:
    data = {
        "neighbor-graph-reuse-leiden-valid": dict(
            parent="neighbor-graph-reuse-leiden",
            final=["cluster_labels"],
            prereq=["current_observation_aligned_neighbor_graph"],
            forbidden=["scanpy_core.pca_scaled", "scanpy_core.neighbors"],
            optional=["scanpy_core.umap"],
            order=[("existing_neighbor_graph", "scanpy_core.leiden")],
            alternatives=[("clustering", ["scanpy_core.leiden"])],
            terminal=["completed", "plan_only"],
        ),
        "neighbor-graph-reuse-leiden-stale": dict(
            parent="neighbor-graph-reuse-leiden",
            final=["no_invalid_cluster_plan"],
            prereq=[],
            forbidden=["reuse_stale_neighbor_graph", "reuse_misaligned_neighbor_graph"],
            optional=["rebuild_compatible_neighbor_graph"],
            order=[],
            alternatives=[],
            terminal=["blocked", "clarification_required"],
        ),
        "harmony-embedding-neighbors": dict(
            parent="harmony-embedding-neighbors",
            final=["neighbor_graph"],
            prereq=["current_observation_aligned_harmony_embedding"],
            forbidden=["force_pca_before_neighbors"],
            optional=["scanpy_core.umap", "scanpy_core.leiden"],
            order=[("harmony_embedding", "scanpy_core.neighbors")],
            alternatives=[("neighbors", ["scanpy_core.neighbors"])],
            terminal=["completed", "plan_only"],
        ),
        "scrublet-transformed-input": dict(
            parent="scrublet-transformed-input",
            final=["no_invalid_scrublet_plan"],
            prereq=["preserved_raw_umi_counts"],
            forbidden=["scrublet_on_normalized_expression", "scrublet_on_integrated_expression"],
            optional=[],
            order=[],
            alternatives=[],
            terminal=["blocked"],
        ),
        "soupx-input-semantics": dict(
            parent="soupx-input-semantics",
            final=["candidate_evidence_packet"],
            prereq=["version_pinned_authoritative_source"],
            forbidden=["automatic_canonical_promotion"],
            optional=["candidate_rag_deposition"],
            order=[("acquire_source", "deposit_candidate")],
            alternatives=[],
            terminal=["candidate_pending_review", "blocked"],
        ),
        "hvg-flavor-seurat": dict(
            parent="hvg-flavor-conditional-input",
            final=["highly_variable_gene_mask"],
            prereq=["selected_flavor_seurat", "logarithmized_expression_available_or_scheduled"],
            forbidden=["count_flavor_on_log_expression", "dispersion_flavor_on_raw_counts"],
            optional=[],
            order=[("logarithmized_expression_available_or_scheduled", "scanpy.pp.highly_variable_genes")],
            alternatives=[
                (
                    "hvg",
                    ["scanpy.pp.highly_variable_genes:seurat"],
                )
            ],
            terminal=["completed", "plan_only"],
        ),
        "hvg-flavor-seurat-v3": dict(
            parent="hvg-flavor-conditional-input",
            final=["highly_variable_gene_mask"],
            prereq=["selected_flavor_seurat_v3", "raw_counts"],
            forbidden=["count_flavor_on_log_expression"],
            optional=[],
            order=[("validate_raw_counts", "scanpy.pp.highly_variable_genes")],
            alternatives=[
                ("hvg", ["scanpy.pp.highly_variable_genes:seurat_v3"])
            ],
            terminal=["completed", "blocked"],
        ),
        "hvg-flavor-default-seurat": dict(
            parent="hvg-flavor-conditional-input",
            final=["highly_variable_gene_mask"],
            prereq=["default_flavor_resolves_to_seurat", "logarithmized_expression_available_or_scheduled"],
            forbidden=["unspecified_flavor_forced_to_clarification", "dispersion_flavor_on_raw_counts"],
            optional=[],
            order=[("resolve_scanpy_default_flavor", "logarithmized_expression_available_or_scheduled"), ("logarithmized_expression_available_or_scheduled", "scanpy.pp.highly_variable_genes")],
            alternatives=[
                ("hvg", ["scanpy.pp.highly_variable_genes:seurat"])
            ],
            terminal=["completed", "plan_only"],
        ),
        "singler-reference-compatibility": dict(
            parent="singler-reference-compatibility",
            final=["candidate_cell_type_labels"],
            prereq=[
                "reference_expression",
                "reference_labels",
                "shared_features",
                "biologically_applicable_reference",
            ],
            forbidden=["annotation_with_unaligned_reference"],
            optional=["pruned_labels"],
            order=[("validate_reference", "SingleR::SingleR")],
            alternatives=[("annotation", ["SingleR::SingleR"])],
            terminal=["completed", "blocked", "clarification_required"],
        ),
        "celltypist-model-feature-alignment": dict(
            parent="celltypist-model-feature-alignment",
            final=["candidate_cell_type_labels"],
            prereq=["log_normalized_expression", "resolved_model_artifact", "feature_alignment_report"],
            forbidden=["annotation_with_incompatible_model"],
            optional=["majority_voting"],
            order=[("validate_model_overlap", "celltypist.annotate")],
            alternatives=[("annotation", ["celltypist.annotate"])],
            terminal=["completed", "blocked", "clarification_required"],
        ),
        "scvelo-layer-availability": dict(
            parent="scvelo-layer-availability",
            final=["velocity_representation"],
            prereq=["spliced_counts", "unspliced_counts"],
            forbidden=["velocity_without_required_measurements"],
            optional=["moments"],
            order=[("validate_velocity_layers", "scvelo.velocity")],
            alternatives=[("rna_velocity", ["scvelo.velocity"])],
            terminal=["completed", "blocked", "clarification_required"],
        ),
        "mofa2-sample-alignment": dict(
            parent="mofa2-sample-alignment",
            final=["multiomics_latent_factors"],
            prereq=["multiple_omics_matrices", "same_or_overlapping_samples_supported", "explicit_sample_identity_alignment"],
            forbidden=["silent_sample_identity_coercion"],
            optional=[],
            order=[("validate_sample_alignment", "MOFA2.train")],
            alternatives=[("multiomics_factor_analysis", ["MOFA2.train", "mofapy2.train"])],
            terminal=["completed", "blocked", "clarification_required"],
        ),
    }
    rows = []
    for gold_slug, item in data.items():
        rows.append(
            WorkflowGold(
                workflow_gold_id=f"workflow-gold:v2.1:{gold_slug}",
                parent_scenario_id=f"scenario:v2.1:{item['parent']}",
                split="development",
                required_final_states=item["final"],
                required_prerequisites=item["prereq"],
                forbidden_operations=item["forbidden"],
                optional_operations=item["optional"],
                partial_order_constraints=[
                    PartialOrderConstraint(before=before, after=after)
                    for before, after in item["order"]
                ],
                acceptable_method_alternatives=[
                    MethodAlternativeSet(goal=goal, methods=methods)
                    for goal, methods in item["alternatives"]
                ],
                acceptable_terminal_states=item["terminal"],
                review_status="reviewed",
            )
        )
    return rows


def _req(
    slug: str,
    parent_slug: str,
    entries: list[tuple[str, str, str, bool, str, str]],
) -> RequirementGold:
    requirements = [
        RequirementExpectation(
            requirement_id=f"requirement-gold:{parent_slug}:{name}",
            expected_state=state,
            rationale=rationale,
            evidence_required=evidence_required,
            criticality=criticality,
            resolution_mode=resolution,
        )
        for name, state, rationale, evidence_required, criticality, resolution in entries
    ]
    from eval.midterm_core_benchmark_v2_1_models import aggregate_requirement_action

    return RequirementGold(
        requirement_gold_id=f"requirement-gold-set:v2.1:{slug}",
        parent_scenario_id=f"scenario:v2.1:{parent_slug}",
        split="development",
        requirements=requirements,
        expected_action=aggregate_requirement_action(requirements),
        review_status="reviewed",
    )


def requirement_gold() -> list[RequirementGold]:
    return [
        _req(
            "neighbor-graph-reuse-leiden-valid",
            "neighbor-graph-reuse-leiden",
            [
                ("graph-present", "SATISFIED", "A compatible graph is registered.", False, "hard", "none"),
                ("observation-alignment", "SATISFIED", "Observation identity matches.", False, "hard", "none"),
                ("freshness", "SATISFIED", "The graph is current.", False, "hard", "none"),
            ],
        ),
        _req(
            "neighbor-graph-reuse-leiden-stale",
            "neighbor-graph-reuse-leiden",
            [
                ("graph-present", "SATISFIED", "A graph record exists.", False, "hard", "none"),
                ("observation-alignment", "VIOLATED", "Observation identity is mismatched.", False, "hard", "select_other"),
                ("freshness", "VIOLATED", "The graph is stale.", False, "hard", "select_other"),
            ],
        ),
        _req(
            "harmony-embedding-neighbors",
            "harmony-embedding-neighbors",
            [
                ("embedding-present", "SATISFIED", "Harmony coordinates are registered.", False, "hard", "none"),
                ("observation-alignment", "SATISFIED", "Rows match current observations.", False, "hard", "none"),
                ("embedding-semantics", "SATISFIED", "Compatibility is a composition inference from Harmony producing corrected embeddings and Scanpy neighbors accepting a selected obsm representation; it is not a direct Harmony-to-Scanpy claim.", True, "hard", "none"),
                ("pca-present", "NOT_APPLICABLE", "PCA is not mandatory when a compatible named embedding is supplied.", True, "soft", "none"),
            ],
        ),
        _req(
            "scrublet-transformed-input",
            "scrublet-transformed-input",
            [
                ("raw-umi-counts", "MISSING", "Only transformed expression is available.", True, "hard", "provide_resource"),
                ("normalized-expression", "VIOLATED", "Normalized expression is not the required raw-count input.", True, "hard", "select_other"),
            ],
        ),
        _req(
            "soupx-input-semantics",
            "soupx-input-semantics",
            [
                ("authoritative-source", "SATISFIED", "A pinned official manual artifact exists.", True, "hard", "none"),
                ("candidate-review-status", "SATISFIED", "The deposited claim remains pending human review.", False, "hard", "none"),
                ("canonical-promotion", "NOT_APPLICABLE", "Promotion is outside Seed v0.", False, "soft", "none"),
            ],
        ),
        _req(
            "hvg-flavor-seurat",
            "hvg-flavor-conditional-input",
            [
                ("flavor-seurat", "SATISFIED", "The request explicitly selects the dispersion-based seurat flavor.", True, "hard", "none"),
                ("log-expression", "MISSING", "Logarithmized expression is absent now but can be produced as a scheduled prerequisite before the selected seurat flavor runs.", True, "hard", "schedule_prerequisite"),
            ],
        ),
        _req(
            "hvg-flavor-seurat-v3",
            "hvg-flavor-conditional-input",
            [
                ("flavor-seurat-v3", "SATISFIED", "The request explicitly selects the count-based seurat_v3 flavor.", True, "hard", "none"),
                ("counts", "SATISFIED", "Raw counts required by the selected seurat_v3 flavor are available.", True, "hard", "none"),
            ],
        ),
        _req(
            "hvg-flavor-default-seurat",
            "hvg-flavor-conditional-input",
            [
                ("default-flavor", "SATISFIED", "Scanpy 1.11.2 resolves an omitted flavor to seurat.", True, "hard", "none"),
                ("log-expression", "MISSING", "Logarithmized expression is absent now but can be produced as a scheduled prerequisite before the resolved default seurat flavor runs.", True, "hard", "schedule_prerequisite"),
            ],
        ),
        _req(
            "singler-reference-compatibility",
            "singler-reference-compatibility",
            [
                ("query-expression", "SATISFIED", "Query expression is present.", True, "hard", "none"),
                ("reference-expression", "SATISFIED", "Reference expression is present.", True, "hard", "none"),
                ("reference-labels", "SATISFIED", "Reference labels are present.", True, "hard", "none"),
                ("shared-features", "SATISFIED", "A non-empty feature intersection exists.", True, "hard", "none"),
                ("biological-applicability", "UNKNOWN", "Reference suitability for this tissue/context is not yet adjudicated.", True, "hard", "ask_user"),
            ],
        ),
        _req(
            "celltypist-model-feature-alignment",
            "celltypist-model-feature-alignment",
            [
                ("log-normalized-expression", "SATISFIED", "Expected normalized input is available.", True, "hard", "none"),
                ("model-artifact", "MISSING", "The actual selected model artifact identity, version and hash have not been resolved by the runtime contract.", False, "hard", "provide_resource"),
                ("feature-alignment-report", "MISSING", "Feature alignment with the resolved model has not been evaluated.", False, "hard", "provide_resource"),
            ],
        ),
        _req(
            "scvelo-layer-availability",
            "scvelo-layer-availability",
            [
                ("spliced-counts", "MISSING", "Spliced measurements are absent.", True, "hard", "provide_resource"),
                ("unspliced-counts", "MISSING", "Unspliced measurements are absent.", True, "hard", "provide_resource"),
            ],
        ),
        _req(
            "mofa2-sample-alignment",
            "mofa2-sample-alignment",
            [
                ("multiple-views", "SATISFIED", "Two omics matrices are supplied.", True, "hard", "none"),
                ("sample-alignment", "UNKNOWN", "MOFA2 scientifically permits overlapping sample sets, but the runtime identity mapping across the supplied matrices has not been verified.", False, "hard", "ask_user"),
            ],
        ),
    ]


def evidence_gold() -> list[EvidenceGold]:
    rows: list[dict[str, Any]] = [
        # Graph reuse decision: scientific interface plus two runtime-owned atoms.
        dict(slug="neighbor-graph-reuse-leiden", atom="leiden-input", decision="neighbor-graph-reuse", claim="Leiden may consume a neighbor graph or an explicit adjacency matrix.", owner="ScientificKG", scope="Scanpy 1.11.2 Leiden", version="1.11.2", required=True, works=["source-work:github:scverse/scanpy"], spans=["scanpy-authoritative-span:leiden.input:1.11.2"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="neighbor-graph-reuse-leiden", atom="graph-current", decision="neighbor-graph-reuse", claim="The registered graph is current.", owner="RepresentationLedger", scope="current dataset instance", version="runtime", required=False, works=[], spans=[], forbidden=["scanpy-authoritative-span:leiden.input:1.11.2"], gaps=[], epistemic="runtime_observed"),
        dict(slug="neighbor-graph-reuse-leiden", atom="graph-stale", decision="neighbor-graph-reuse", claim="The registered graph is stale.", owner="RepresentationLedger", scope="current dataset instance", version="runtime", required=False, works=[], spans=[], forbidden=["scanpy-authoritative-span:leiden.input:1.11.2"], gaps=[], epistemic="runtime_observed"),
        dict(slug="neighbor-graph-reuse-leiden", atom="graph-misaligned", decision="neighbor-graph-reuse", claim="Graph observation identity differs from the current dataset.", owner="RepresentationLedger", scope="current dataset instance", version="runtime", required=False, works=[], spans=[], forbidden=["scanpy-authoritative-span:leiden.input:1.11.2"], gaps=[], epistemic="runtime_observed"),
        # Harmony decision.
        dict(slug="harmony-embedding-neighbors", atom="harmony-input", decision="harmony-neighbors", claim="Harmony accepts matrix-like cell embeddings with batch covariates.", owner="ScientificKG", scope="Harmony 2.0.5", version="2.0.5", required=True, works=["source-work:harmony"], spans=["uat-authoritative-span:harmony.generic_input"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="harmony-embedding-neighbors", atom="harmony-output", decision="harmony-neighbors", claim="Harmony returns corrected cell embeddings.", owner="ScientificKG", scope="Harmony 2.0.5", version="2.0.5", required=True, works=["source-work:harmony"], spans=["uat-authoritative-span:harmony.output"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="harmony-embedding-neighbors", atom="neighbors-input", decision="harmony-neighbors", claim="Scanpy neighbors can use a selected representation from obsm.", owner="ScientificKG", scope="Scanpy 1.11.2 neighbors", version="1.11.2", required=True, works=["source-work:github:scverse/scanpy"], spans=["scanpy-authoritative-span:neighbors.input:1.11.2"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        # Scrublet decision.
        dict(slug="scrublet-transformed-input", atom="raw-input", decision="scrublet-input", claim="Scrublet requires a raw unnormalized UMI count matrix.", owner="ScientificKG", scope="Scrublet 0.2.3", version="0.2.3", required=True, works=["source-work:scrublet"], spans=["uat-authoritative-span:scrublet.input_output"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        # HVG decision.
        dict(slug="hvg-flavor-conditional-input", atom="dispersion-input", decision="hvg-input", claim="Dispersion-based HVG flavors expect logarithmized data.", owner="ScientificKG", scope="Scanpy 1.11.2 HVG flavor condition", version="1.11.2", required=True, works=["source-work:github:scverse/scanpy"], spans=["scanpy-authoritative-span:hvg.flavor_input:1.11.2"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="hvg-flavor-conditional-input", atom="count-input", decision="hvg-input", claim="Seurat v3 HVG flavors expect count data.", owner="ScientificKG", scope="Scanpy 1.11.2 HVG flavor condition", version="1.11.2", required=True, works=["source-work:github:scverse/scanpy"], spans=["scanpy-authoritative-span:hvg.flavor_input:1.11.2"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="hvg-flavor-conditional-input", atom="default-flavor", decision="hvg-input", claim="Scanpy 1.11.2 highly_variable_genes resolves an omitted flavor argument to seurat.", owner="ScientificKG", scope="Scanpy 1.11.2 API default", version="1.11.2", required=True, works=["source-work:github:scverse/scanpy"], spans=["gold-span:scanpy:hvg-default-flavor:1.11.2"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="hvg-flavor-conditional-input", atom="hvg-output", decision="hvg-input", claim="HVG selection records a highly-variable feature mask and statistics.", owner="ScientificKG", scope="Scanpy 1.11.2", version="1.11.2", required=True, works=["source-work:github:scverse/scanpy"], spans=["scanpy-authoritative-span:hvg.output:1.11.2"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        # SingleR decision.
        dict(slug="singler-reference-compatibility", atom="query-input", decision="singler-reference", claim="SingleR accepts query expression including raw-count query input.", owner="ScientificKG", scope="SingleR 2.14.1", version="2.14.1", required=True, works=["source-work:bioconductor:SingleR"], spans=["uat-authoritative-span:singler.interface", "uat-authoritative-span:singler.raw_query"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="singler-reference-compatibility", atom="reference-expression", decision="singler-reference", claim="SingleR requires reference expression profiles.", owner="ScientificKG", scope="SingleR 2.14.1", version="2.14.1", required=True, works=["source-work:bioconductor:SingleR"], spans=["uat-authoritative-span:singler.reference_state"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="singler-reference-compatibility", atom="reference-labels", decision="singler-reference", claim="Reference labels are required to train/use the SingleR reference.", owner="ScientificKG", scope="SingleR 2.14.1", version="2.14.1", required=True, works=["source-work:bioconductor:SingleR"], spans=["uat-authoritative-span:singler.reference_labels"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="singler-reference-compatibility", atom="shared-features", decision="singler-reference", claim="Query and reference must have a usable feature intersection.", owner="ScientificKG", scope="SingleR 2.14.1", version="2.14.1", required=True, works=["source-work:bioconductor:SingleR"], spans=["uat-authoritative-span:singler.feature_intersection"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="singler-reference-compatibility", atom="reference-choice", decision="singler-reference", claim="Reference choice materially affects annotation; the reference should cover expected labels and a similar technology or protocol is preferred.", owner="ScientificKG", scope="SingleRBook 3.22 classic-mode reference choice", version="3.22", required=True, works=["source-work:bioconductor:SingleRBook"], spans=["gold-span:singler:reference-choice:3.22"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        # CellTypist decision.
        dict(slug="celltypist-model-feature-alignment", atom="normalized-input", decision="celltypist-model", claim="CellTypist 1.7.1 expects normalized logarithmized expression for AnnData input.", owner="ScientificKG", scope="CellTypist 1.7.1 annotate input", version="1.7.1", required=True, works=["source-work:celltypist:official-readme"], spans=["gold-span:celltypist:normalized-input:1.7.1"], forbidden=["sourcev2:6d070f599929bf055fb8"], gaps=[], epistemic="source_bound_draft"),
        dict(slug="celltypist-model-feature-alignment", atom="feature-overlap-guidance", decision="celltypist-model", claim="Providing all genes maximizes overlap with features in the CellTypist model.", owner="ScientificKG", scope="CellTypist 1.7.1 feature-overlap guidance", version="1.7.1", required=True, works=["source-work:celltypist:official-readme"], spans=["gold-span:celltypist:normalized-input:1.7.1"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="celltypist-model-feature-alignment", atom="default-model", decision="celltypist-model", claim="When annotate is called without a model argument, CellTypist 1.7.1 defaults to Immune_All_Low.pkl.", owner="ToolContract", scope="CellTypist 1.7.1 annotate API default", version="1.7.1", required=True, works=["source-work:celltypist:annotate"], spans=["gold-span:celltypist:default-model:1.7.1"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="celltypist-model-feature-alignment", atom="resolved-model-artifact", decision="celltypist-model", claim="The actual selected model artifact identity, version and content hash are unresolved for this runtime scenario.", owner="ToolContract", scope="selected runtime model artifact", version="runtime", required=False, works=[], spans=[], forbidden=[], gaps=[], epistemic="runtime_observed"),
        dict(slug="celltypist-model-feature-alignment", atom="model-feature-alignment", decision="celltypist-model", claim="Feature alignment against the resolved model artifact has not yet been computed for this runtime scenario.", owner="ToolContract", scope="selected runtime model artifact and query feature set", version="runtime", required=False, works=[], spans=[], forbidden=[], gaps=[], epistemic="runtime_observed"),
        # scVelo decision: the selected canonical workflow's input requirement is source-bound.
        dict(slug="scvelo-layer-availability", atom="layer-requirement", decision="scvelo-input", claim="The selected canonical scVelo velocity workflow requires identified spliced and unspliced count matrices in AnnData layers.", owner="ScientificKG", scope="scVelo 0.3.3 canonical velocity workflow", version="0.3.3", required=True, works=["source-work:scvelo:official-docs"], spans=["gold-span:scvelo:spliced-unspliced-input:0.3.3"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        # MOFA2 decision.
        dict(slug="mofa2-sample-alignment", atom="overlapping-samples-supported", decision="mofa2-input", claim="MOFA2 accepts multiple omics matrices measured on the same or overlapping sets of samples.", owner="ScientificKG", scope="MOFA2 official documentation at ec2ee6d", version="ec2ee6d", required=True, works=["source-work:mofa2:official-docs"], spans=["gold-span:mofa2:input-output:ec2ee6d"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
        dict(slug="mofa2-sample-alignment", atom="sample-identity-alignment", decision="mofa2-input", claim="The explicit sample-identity mapping across the supplied runtime matrices has not yet been verified.", owner="RepresentationLedger", scope="current multi-omics dataset instances", version="runtime", required=False, works=[], spans=[], forbidden=[], gaps=[], epistemic="runtime_observed"),
        dict(slug="mofa2-sample-alignment", atom="latent-output", decision="mofa2-input", claim="MOFA2 infers a small number of interpretable latent factors.", owner="ScientificKG", scope="MOFA2 official documentation at ec2ee6d", version="ec2ee6d", required=True, works=["source-work:mofa2:official-docs"], spans=["gold-span:mofa2:input-output:ec2ee6d"], forbidden=[], gaps=[], epistemic="source_bound_draft"),
    ]
    return [
        EvidenceGold(
            evidence_gold_id=f"evidence-gold:v2.1:{item['slug']}:{item['atom']}",
            parent_scenario_id=f"scenario:v2.1:{item['slug']}",
            split="development",
            decision_id=f"decision:v2.1:{item['decision']}",
            claim=item["claim"],
            owner=item["owner"],
            scope=item["scope"],
            version=item["version"],
            evidence_required=item["required"],
            source_work_ids=item["works"],
            allowed_evidence_spans=item["spans"],
            forbidden_evidence_spans=item["forbidden"],
            evidence_gap_ids=item["gaps"],
            expected_epistemic_state=item["epistemic"],
            review_status="reviewed",
        )
        for item in rows
    ]


def scientific_source_provenance() -> list[dict[str, Any]]:
    """Independent, source-bound draft evidence introduced by adjudication.

    These records are evaluation-gold provenance candidates, not Scientific KG
    promotion records. Their review state remains draft until a real reviewer
    records a decision.
    """

    rows = [
        {
            "source_work_id": "source-work:github:scverse/scanpy",
            "source_revision_id": "source-revision:scanpy:1.11.2:5400eb87",
            "evidence_span_id": "gold-span:scanpy:hvg-default-flavor:1.11.2",
            "source_document": "scanpy/preprocessing/_highly_variable_genes.py",
            "source_type": "official_release_source",
            "authority": "Scanpy project",
            "version": "1.11.2",
            "immutable_uri": "https://github.com/scverse/scanpy/blob/5400eb87ef7d4e9f6f5a9256d98a7927723456fa/src/scanpy/preprocessing/_highly_variable_genes.py#L523-L543",
            "source_file_sha256": "dc1382b1c19be495b547fd08a7b4711f75522db5852a27200ba7eddefd175788",
            "locator": "src/scanpy/preprocessing/_highly_variable_genes.py#L523-L543",
            "exact_text": "flavor: Literal[\"seurat\", \"cell_ranger\", \"seurat_v3\", \"seurat_v3_paper\"] = \"seurat\"\nExpects logarithmized data, except when `flavor='seurat_v3'`/`'seurat_v3_paper'`, in which count data is expected.",
        },
        {
            "source_work_id": "source-work:bioconductor:SingleRBook",
            "source_revision_id": "source-revision:SingleRBook:3.22",
            "evidence_span_id": "gold-span:singler:reference-choice:3.22",
            "source_document": "SingleRBook / Classic mode / Choice of reference",
            "source_type": "official_versioned_book",
            "authority": "Bioconductor",
            "version": "3.22",
            "immutable_uri": "https://bioconductor.org/books/3.22/SingleRBook/classic-mode.html",
            "source_file_sha256": "234a0d0e6b4766437f3a500e351a8afaafecae8e391c89bbf576a7863aac1169",
            "locator": "Chapter 2, section 2.5 Choice of reference",
            "exact_text": "Unsurprisingly, the choice of reference has a major impact on the annotation results. We need to pick a reference that contains a superset of the labels that we expect to be present in our test dataset. We would also prefer a reference that is generated from a similar technology or protocol as our test dataset.",
        },
        {
            "source_work_id": "source-work:celltypist:official-readme",
            "source_revision_id": "source-revision:celltypist:1.7.1:fe357564",
            "evidence_span_id": "gold-span:celltypist:normalized-input:1.7.1",
            "source_document": "CellTypist README.md",
            "source_type": "official_release_documentation",
            "authority": "CellTypist project",
            "version": "1.7.1",
            "immutable_uri": "https://github.com/Teichlab/celltypist/blob/fe357564a6625d3b1732a022fd39f18e55696e80/README.md#L166-L170",
            "source_file_sha256": "d1a086776c56a93ce09f1a82a42cd121a6acd0df256194d6a78db200cb951632",
            "locator": "README.md#L166-L170",
            "exact_text": "CellTypist requires a logarithmised and normalised expression matrix stored in the `AnnData` (log1p normalised expression to 10,000 counts per cell). Within the `AnnData`, please provide all genes to ensure maximal overlap with genes in the model.",
        },
        {
            "source_work_id": "source-work:celltypist:annotate",
            "source_revision_id": "source-revision:celltypist:1.7.1:fe357564",
            "evidence_span_id": "gold-span:celltypist:default-model:1.7.1",
            "source_document": "celltypist/annotate.py",
            "source_type": "official_release_api_source",
            "authority": "CellTypist project",
            "version": "1.7.1",
            "immutable_uri": "https://github.com/Teichlab/celltypist/blob/fe357564a6625d3b1732a022fd39f18e55696e80/celltypist/annotate.py#L7-L31",
            "source_file_sha256": "29937a222a493ddcc66e5f083d72e602ff1ea5202adde07c8ac068fa9cfba171",
            "locator": "celltypist/annotate.py#L7-L31",
            "exact_text": "model: Optional[Union[str, Model]] = None\nModel used to predict the input cells. Default to using the `'Immune_All_Low.pkl'` model.",
        },
        {
            "source_work_id": "source-work:scvelo:official-docs",
            "source_revision_id": "source-revision:scvelo:0.3.3:22b6e7e6",
            "evidence_span_id": "gold-span:scvelo:spliced-unspliced-input:0.3.3",
            "source_document": "scVelo Getting Started",
            "source_type": "official_release_documentation",
            "authority": "scVelo project",
            "version": "0.3.3",
            "immutable_uri": "https://github.com/theislab/scvelo/blob/22b6e7e6cdb3c321c5a1be4ab2f29486ba01ab4f/docs/source/getting_started.rst#L8-L31",
            "source_file_sha256": "93d2438590e985d84b11a35fb46b58e636010be7b925b564b5c4b0df40b79562",
            "locator": "docs/source/getting_started.rst#L7-L9,L26-L28",
            "exact_text": "First of all, the input data for scVelo are two count matrices of pre-mature (unspliced) and mature (spliced) abundances. Additional data layers where spliced and unspliced counts are stored (`adata.layers`).",
        },
        {
            "source_work_id": "source-work:mofa2:official-docs",
            "source_revision_id": "source-revision:mofa2:gh-pages:ec2ee6d",
            "evidence_span_id": "gold-span:mofa2:input-output:ec2ee6d",
            "source_document": "MOFA2 index.md",
            "source_type": "official_versioned_documentation",
            "authority": "bioFAM",
            "version": "ec2ee6d",
            "immutable_uri": "https://github.com/bioFAM/MOFA2/blob/ec2ee6d9f81573d784795284d18e88675c0911cb/index.md#L8",
            "source_file_sha256": "d851c29a12769f4ed6b51c3e45d74bc7597e59f294d784af86530f96c4f9dcdf",
            "locator": "index.md#L8",
            "exact_text": "Given several data matrices with measurements of multiple -omics data types on the same or on overlapping sets of samples, MOFA infers an interpretable low-dimensional representation in terms of a few latent factors.",
        },
    ]
    for row in rows:
        row["content_hash"] = hashlib.sha256(
            row["exact_text"].encode("utf-8")
        ).hexdigest()
        row["review_status"] = "reviewed"
        row["candidate_only"] = True
        row["review_decision"] = REVIEW_DECISION
        row["reviewer_role"] = REVIEWER_ROLE
        row["review_date"] = REVIEW_DATE
        row["reviewer_reason"] = REVIEWER_REASON
    return rows


def learning_episodes() -> list[LearningEpisode]:
    data = [
        (
            "soupx-input-semantics",
            "soupx-input-semantics",
            "source-work:soupx:official-manual",
            "What do SoupX tod and toc input tables contain?",
            "A dataset contains A) an unfiltered droplet-by-gene matrix and B) a filtered cell-by-gene matrix. For SoupChannel construction, which artifact should populate tod, which should populate toc, and what is missing if only B is available?",
            "source-artifact:sha256:dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19",
            "claim-revision:cp6:7005e7aaf1f910d6:1",
        ),
        (
            "singler-reference-suitability",
            "singler-reference-compatibility",
            "source-work:bioconductor:SingleRBook",
            "What inputs does SingleR need for reference-based annotation?",
            "Should a reference from an unrelated tissue be accepted without clarification?",
            "gold-span:singler:reference-choice:3.22",
            "candidate-claim:v2.1:singler-reference-suitability",
        ),
        (
            "scvelo-layer-requirement",
            "scvelo-layer-availability",
            "source-work:scvelo:official-readme",
            "Which measurements are required for this scVelo velocity workflow?",
            "Can the same workflow run when only total expression is present?",
            "source-artifact:scvelo:0.3.3:22b6e7e6",
            "candidate-claim:v2.1:scvelo-layer-requirement",
        ),
    ]
    episodes = []
    for slug, scenario, source, original, hidden, artifact, claim in data:
        episodes.append(
            LearningEpisode(
                episode_id=f"learning-episode:v2.1:{slug}",
                parent_scenario_id=f"scenario:v2.1:{scenario}",
                split="development",
                source_work_id=source,
                original_query=original,
                hidden_related_query=hidden,
                claim_construction_visible_queries=[original],
                conditions=[
                    LearningCondition(
                        condition="S0",
                        knowledge_snapshot_id=f"snapshot:v2.1:{slug}:s0",
                        added_evidence=False,
                        structured_candidate=False,
                    ),
                    LearningCondition(
                        condition="S1",
                        knowledge_snapshot_id=f"snapshot:v2.1:{slug}:s1",
                        added_evidence=True,
                        structured_candidate=False,
                        evidence_artifact_id=artifact,
                    ),
                    LearningCondition(
                        condition="S2",
                        knowledge_snapshot_id=f"snapshot:v2.1:{slug}:s2",
                        added_evidence=True,
                        structured_candidate=True,
                        evidence_artifact_id=artifact,
                        candidate_claim_id=claim,
                    ),
                ],
                review_status="reviewed",
            )
        )
    return episodes


def study_candidates() -> list[dict[str, Any]]:
    return [
        {
            "study_id": "study:pbmc3k-anchor",
            "role": "PBMC historical anchor",
            "development_exposure": "historical_anchor",
            "organism": "Homo sapiens",
            "tissue_context": "peripheral blood mononuclear cells",
            "dataset_ids": ["dataset:pbmc3k-raw", "dataset:pbmc3k-processed"],
            "artifact_status": "existing_local_versioned_inputs",
            "checksum_status": "existing_frozen_hashes",
            "license_review_status": "draft",
            "workflow_paths": [
                "path:pbmc3k:raw-to-scanpy-core",
                "path:pbmc3k:processed-reuse",
            ],
            "technical_checks": ["notebook execution", "input hash unchanged", "Trace topology"],
            "scientific_checks": ["workflow equivalence", "representation lineage", "reuse/skip"],
            "biological_sanity_checks": ["QC distributions", "cluster/marker outputs as non-gold diagnostics"],
        },
        {
            "study_id": "study:pancreas-reference-annotation-candidate",
            "role": "non-PBMC reference-annotation candidate",
            "development_exposure": "new_development_candidate",
            "organism": "Homo sapiens",
            "tissue_context": "pancreatic cell atlas / cross-study annotation candidate",
            "dataset_ids": ["dataset:pancreas-query-reference-pair"],
            "artifact_status": "candidate_not_acquired",
            "checksum_status": "pending_selection",
            "license_review_status": "pending_selection",
            "workflow_paths": [
                "path:pancreas:reference-annotation",
            ],
            "technical_checks": ["download/checksum", "notebook execution", "input immutability"],
            "scientific_checks": ["reference suitability", "feature alignment"],
            "biological_sanity_checks": ["label coverage", "known broad lineage separation without post hoc exact-label gold"],
        },
        {
            "study_id": "study:pancreas-batch-integration-candidate",
            "role": "non-PBMC batch-integration candidate",
            "development_exposure": "new_development_candidate",
            "organism": "Homo sapiens",
            "tissue_context": "pancreatic multi-donor/batch integration candidate",
            "dataset_ids": ["dataset:pancreas-batch-candidate"],
            "artifact_status": "candidate_not_acquired",
            "checksum_status": "pending_selection",
            "license_review_status": "pending_selection",
            "workflow_paths": ["path:pancreas:batch-aware-state-assessment"],
            "technical_checks": ["download/checksum", "notebook execution", "input immutability"],
            "scientific_checks": ["batch covariate validity", "batch-aware workflow equivalence"],
            "biological_sanity_checks": ["broad lineage preservation without post hoc exact-label gold"],
        },
    ]


def acquisition_episodes() -> list[dict[str, Any]]:
    return [
        {
            "episode_id": "acquisition:v2.1:soupx-input-semantics",
            "parent_scenario_id": "scenario:v2.1:soupx-input-semantics",
            "split": "development",
            "source_work_id": "source-work:soupx:official-manual",
            "status": "historical_anchor_reuse",
            "source_policy": "official version-pinned manual first",
        },
        {
            "episode_id": "acquisition:v2.1:singler-reference-suitability",
            "parent_scenario_id": "scenario:v2.1:singler-reference-compatibility",
            "split": "development",
            "source_work_id": "source-work:bioconductor:SingleRBook",
            "status": "draft_source_pinned",
            "source_policy": "version-pinned Bioconductor SingleRBook 3.22 source",
        },
        {
            "episode_id": "acquisition:v2.1:scvelo-layer-requirement",
            "parent_scenario_id": "scenario:v2.1:scvelo-layer-availability",
            "split": "development",
            "source_work_id": "source-work:scvelo:official-readme",
            "status": "draft_evidence_gap",
            "source_policy": "version-pinned official API/source before papers",
        },
    ]


def governance_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "governance:v2.1:complete-pending-candidate",
            "parent_scenario_id": "scenario:v2.1:soupx-input-semantics",
            "split": "development",
            "expected": "candidate_pending_review",
            "transition": "NOT_RUN",
            "canonical_promotion": False,
        },
        {
            "case_id": "governance:v2.1:missing-provenance",
            "parent_scenario_id": "scenario:v2.1:singler-reference-compatibility",
            "split": "development",
            "expected": "review_packet_blocked",
            "transition": "NOT_RUN",
            "canonical_promotion": False,
        },
        {
            "case_id": "governance:v2.1:candidate-trusted-conflation",
            "parent_scenario_id": "scenario:v2.1:scvelo-layer-availability",
            "split": "development",
            "expected": "boundary_violation_detected",
            "transition": "NOT_RUN",
            "canonical_promotion": False,
        },
        {
            "case_id": "governance:v2.1:decision-without-change-set",
            "parent_scenario_id": "scenario:v2.1:mofa2-sample-alignment",
            "split": "development",
            "expected": "promotion_guard_blocked",
            "transition": "NOT_IMPLEMENTED",
            "canonical_promotion": False,
        },
    ]


def fault_injections() -> list[dict[str, Any]]:
    data = [
        ("wrong-source-binding", "neighbor-graph-reuse-leiden", "T3", "record:v2.1:t3:neighbor-graph-reuse", "CLAIM_SOURCE_BINDING_MISMATCH"),
        ("wrong-revision-binding", "harmony-embedding-neighbors", "T3", "record:v2.1:t3:harmony-neighbors", "EVIDENCE_UNRESOLVABLE"),
        ("candidate-as-trusted", "scvelo-layer-availability", "T7", "record:v2.1:t3:scvelo-input", "EPISTEMIC_STATUS_CONFLATION"),
        ("missing-representation-link", "neighbor-graph-reuse-leiden", "T3", "record:v2.1:t3:neighbor-graph-reuse", "REPRESENTATION_LINK_MISSING"),
        ("silent-scope-widening", "scrublet-transformed-input", "T3", "record:v2.1:t3:scrublet-input", "SCOPE_SILENTLY_WIDENED"),
        ("invalid-graph-reuse", "neighbor-graph-reuse-leiden", "T8", "record:v2.1:t1:neighbor-graph-stale", "BEHAVIOR_MUTATED"),
        ("hidden-query-leak", "singler-reference-compatibility", "T6", "record:v2.1:t6:singler-reference-suitability", "HIDDEN_QUERY_LEAK"),
        ("split-crossing-derived-record", "mofa2-sample-alignment", "T8", "record:v2.1:t1:mofa2-sample-alignment", "SPLIT_INHERITANCE_VIOLATION"),
    ]
    return [
        {
            "mutation_id": f"mutation:v2.1:{slug}",
            "parent_scenario_id": f"scenario:v2.1:{scenario}",
            "mutation_parent_id": mutation_parent_id,
            "split": "development",
            "track": track,
            "expected_first_failure": expected,
            "single_variable_mutation": True,
        }
        for slug, scenario, track, mutation_parent_id, expected in data
    ]


def evaluation_records(
    scenarios: list[ParentScenario],
    evidence: list[EvidenceGold],
    learning: list[LearningEpisode],
) -> list[EvaluationRecord]:
    by_slug = {item.scenario_id.rsplit(":", 1)[-1]: item for item in scenarios}
    records: list[EvaluationRecord] = []

    def add(
        track: str,
        kind: str,
        slug: str,
        suffix: str,
        gold_ref: str,
        *,
        source_work_id: str | None = None,
        mutation_parent_id: str | None = None,
        study_id: str | None = None,
        dataset_id: str | None = None,
        denominator_included: bool = True,
        denominator_id: str | None = None,
        exclusion_reason: str | None = None,
    ) -> None:
        parent = by_slug[slug]
        records.append(
            EvaluationRecord(
                record_id=f"record:v2.1:{track.lower()}:{suffix}",
                parent_scenario_id=parent.scenario_id,
                study_id=parent.study_id if study_id is None else study_id,
                dataset_id=parent.dataset_id if dataset_id is None else dataset_id,
                source_work_id=source_work_id,
                mutation_parent_id=mutation_parent_id,
                replicate_id="r1",
                track=track,
                split=parent.split,
                record_kind=kind,
                gold_ref=gold_ref,
                baseline_eligibility=_baseline(track),
                denominator=DenominatorMetadata(
                    included=denominator_included,
                    denominator_id=(
                        denominator_id
                        or f"denominator:{track}:development-parent"
                    ),
                    exclusion_reason=exclusion_reason,
                ),
            )
        )

    semantic = [
        "neighbor-graph-reuse-leiden",
        "harmony-embedding-neighbors",
        "scrublet-transformed-input",
        "singler-reference-compatibility",
        "celltypist-model-feature-alignment",
        "scvelo-layer-availability",
        "mofa2-sample-alignment",
    ]
    planning = [
        ("neighbor-graph-reuse-leiden", "neighbor-graph-valid", "workflow-gold:v2.1:neighbor-graph-reuse-leiden-valid"),
        ("neighbor-graph-reuse-leiden", "neighbor-graph-stale", "workflow-gold:v2.1:neighbor-graph-reuse-leiden-stale"),
        ("harmony-embedding-neighbors", "harmony-embedding-neighbors", "workflow-gold:v2.1:harmony-embedding-neighbors"),
        ("scrublet-transformed-input", "scrublet-transformed-input", "workflow-gold:v2.1:scrublet-transformed-input"),
        ("hvg-flavor-conditional-input", "hvg-flavor-seurat", "workflow-gold:v2.1:hvg-flavor-seurat"),
        ("hvg-flavor-conditional-input", "hvg-flavor-seurat-v3", "workflow-gold:v2.1:hvg-flavor-seurat-v3"),
        ("hvg-flavor-conditional-input", "hvg-flavor-default-seurat", "workflow-gold:v2.1:hvg-flavor-default-seurat"),
        ("scvelo-layer-availability", "scvelo-layer-availability", "workflow-gold:v2.1:scvelo-layer-availability"),
        ("mofa2-sample-alignment", "mofa2-sample-alignment", "workflow-gold:v2.1:mofa2-sample-alignment"),
    ]
    applicability = [
        ("neighbor-graph-reuse-leiden", "neighbor-graph-valid", "requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-valid"),
        ("neighbor-graph-reuse-leiden", "neighbor-graph-stale", "requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-stale"),
        ("harmony-embedding-neighbors", "harmony-embedding-neighbors", "requirement-gold-set:v2.1:harmony-embedding-neighbors"),
        ("scrublet-transformed-input", "scrublet-transformed-input", "requirement-gold-set:v2.1:scrublet-transformed-input"),
        ("hvg-flavor-conditional-input", "hvg-flavor-seurat", "requirement-gold-set:v2.1:hvg-flavor-seurat"),
        ("hvg-flavor-conditional-input", "hvg-flavor-seurat-v3", "requirement-gold-set:v2.1:hvg-flavor-seurat-v3"),
        ("hvg-flavor-conditional-input", "hvg-flavor-default-seurat", "requirement-gold-set:v2.1:hvg-flavor-default-seurat"),
        ("singler-reference-compatibility", "singler-reference-compatibility", "requirement-gold-set:v2.1:singler-reference-compatibility"),
        ("celltypist-model-feature-alignment", "celltypist-model-feature-alignment", "requirement-gold-set:v2.1:celltypist-model-feature-alignment"),
    ]
    for slug in semantic:
        add("G0", "semantic_gateway", slug, slug, f"semantic-gold:v2.1:{slug}")
    for slug, suffix, gold_ref in planning:
        add("T1", "planning", slug, suffix, gold_ref)
    for slug, suffix, gold_ref in applicability:
        add("T2", "applicability", slug, suffix, gold_ref)

    decision_to_parent: dict[str, str] = {}
    for atom in evidence:
        decision_to_parent.setdefault(atom.decision_id, atom.parent_scenario_id)
    for decision_id, parent_id in decision_to_parent.items():
        slug = parent_id.rsplit(":", 1)[-1]
        add("T3", "evidence_decision", slug, decision_id.rsplit(":", 1)[-1], decision_id)

    add("T4", "real_data_path", "neighbor-graph-reuse-leiden", "pbmc3k-processed-reuse", "path:pbmc3k:processed-reuse")
    add("T4", "real_data_path", "hvg-flavor-conditional-input", "pbmc3k-raw-core", "path:pbmc3k:raw-to-scanpy-core")
    add(
        "T4",
        "real_data_path",
        "singler-reference-compatibility",
        "pancreas-reference-annotation",
        "path:pancreas:reference-annotation",
        study_id="study:pancreas-reference-annotation-candidate",
        dataset_id="dataset:pancreas-query-reference-pair",
        denominator_included=False,
        denominator_id="denominator:T4:development-candidate-not-frozen",
        exclusion_reason="CANDIDATE_REAL_DATA_NOT_FROZEN",
    )
    add(
        "T4",
        "real_data_path",
        "harmony-embedding-neighbors",
        "pancreas-batch-aware",
        "path:pancreas:batch-aware-state-assessment",
        study_id="study:pancreas-batch-integration-candidate",
        dataset_id="dataset:pancreas-batch-candidate",
        denominator_included=False,
        denominator_id="denominator:T4:development-candidate-not-frozen",
        exclusion_reason="CANDIDATE_REAL_DATA_NOT_FROZEN",
    )

    for item in acquisition_episodes():
        slug = item["parent_scenario_id"].rsplit(":", 1)[-1]
        add("T5", "acquisition", slug, item["episode_id"].rsplit(":", 1)[-1], item["episode_id"], source_work_id=item["source_work_id"])
    for item in learning:
        slug = item.parent_scenario_id.rsplit(":", 1)[-1]
        add("T6", "learning_episode", slug, item.episode_id.rsplit(":", 1)[-1], item.episode_id, source_work_id=item.source_work_id)
    for item in governance_cases():
        slug = item["parent_scenario_id"].rsplit(":", 1)[-1]
        add("T7", "governance_boundary", slug, item["case_id"].rsplit(":", 1)[-1], item["case_id"])
    for item in fault_injections():
        slug = item["parent_scenario_id"].rsplit(":", 1)[-1]
        add(
            "T8",
            "fault_injection",
            slug,
            item["mutation_id"].rsplit(":", 1)[-1],
            item["mutation_id"],
            mutation_parent_id=item["mutation_parent_id"],
        )
    return records


def build() -> dict[str, Any]:
    if _sha(CONTRACT) != CONTRACT_SHA256:
        raise ValueError("evaluation_v2_1_contract_digest_mismatch")

    scenarios = parent_scenarios()
    workflows = workflow_gold()
    requirements = requirement_gold()
    evidence = evidence_gold()
    source_provenance = scientific_source_provenance()
    learning = learning_episodes()
    records = evaluation_records(scenarios, evidence, learning)
    BenchmarkSeedBundle(
        parent_scenarios=scenarios,
        evaluation_records=records,
        workflow_gold=workflows,
        requirement_gold=requirements,
        evidence_gold=evidence,
        learning_episodes=learning,
    )

    schema_dir = OUTPUT / "schemas"
    schema_models = {
        "parent_scenario": ParentScenario,
        "evaluation_record": EvaluationRecord,
        "workflow_gold": WorkflowGold,
        "requirement_gold": RequirementGold,
        "evidence_gold": EvidenceGold,
        "learning_episode": LearningEpisode,
    }
    for name, model in schema_models.items():
        _write_json(schema_dir / f"{name}.schema.json", model.model_json_schema())

    gold_dir = OUTPUT / "gold" / "midterm_core_seed_v0"
    _write_jsonl(gold_dir / "parent_scenarios.jsonl", [x.model_dump(mode="json") for x in scenarios])
    _write_jsonl(gold_dir / "workflow_gold.jsonl", [x.model_dump(mode="json") for x in workflows])
    _write_jsonl(gold_dir / "requirement_gold.jsonl", [x.model_dump(mode="json") for x in requirements])
    _write_jsonl(gold_dir / "evidence_gold.jsonl", [x.model_dump(mode="json") for x in evidence])
    _write_jsonl(gold_dir / "scientific_source_provenance.jsonl", source_provenance)
    _write_jsonl(gold_dir / "learning_episodes.jsonl", [x.model_dump(mode="json") for x in learning])
    _write_jsonl(gold_dir / "evaluation_records.jsonl", [x.model_dump(mode="json") for x in records])

    manifest_dir = OUTPUT / "manifests"
    _write_json(manifest_dir / "real_data_studies_seed_v0.json", {"studies": study_candidates()})
    _write_json(manifest_dir / "acquisition_episodes_seed_v0.json", {"episodes": acquisition_episodes()})
    _write_json(manifest_dir / "governance_boundary_cases_seed_v0.json", {"cases": governance_cases()})
    _write_json(manifest_dir / "fault_injections_seed_v0.json", {"mutations": fault_injections()})
    _write_json(
        gold_dir / "gold_provenance.json",
        {
            "schema_version": "sckg-gold-provenance-v2.1",
            "status": "project_owner_reviewed",
            "origin": "independent_source_adjudication_draft",
            "generated_from_current_kg": False,
            "generated_from_current_planner": False,
            "generated_from_current_evaluator": False,
            "human_review_complete": True,
            "review_decision": REVIEW_DECISION,
            "reviewer_role": REVIEWER_ROLE,
            "review_date": REVIEW_DATE,
            "reviewer_reason": REVIEWER_REASON,
            "independent_external_expert_review": False,
            "review_requirement": "satisfied by project-owner manual benchmark adjudication",
        },
    )

    files = [
        path
        for path in OUTPUT.rglob("*")
        if path.is_file()
        and path.name
        not in {"midterm_core_seed_v0.json", "midterm_core_seed_v0.freeze.json"}
    ]
    track_counts: dict[str, int] = {}
    for record in records:
        track_counts[record.track] = track_counts.get(record.track, 0) + 1
    manifest = {
        "schema_version": "sckg-midterm-core-seed-manifest-v0",
        "status": "frozen_seed_v0",
        "formal_benchmark": False,
        "formal_holdout_constructed": False,
        "contract": {
            "path": "docs/SCIENTIFIC_AGENT_EVALUATION_SUITE_V2_1.md",
            "sha256": CONTRACT_SHA256,
        },
        "counts": {
            "parent_scenarios": len(scenarios),
            "historical_anchors": sum(x.historical_anchor for x in scenarios),
            "new_development_scenarios": sum(not x.historical_anchor for x in scenarios),
            "workflow_gold": len(workflows),
            "requirement_gold": len(requirements),
            "evidence_atoms": len(evidence),
            "evidence_decisions": len({x.decision_id for x in evidence}),
            "real_data_studies": len(study_candidates()),
            "real_data_paths": track_counts["T4"],
            "acquisition_episodes": len(acquisition_episodes()),
            "learning_episodes": len(learning),
            "governance_boundary_cases": len(governance_cases()),
            "fault_injections": len(fault_injections()),
            "evaluation_records": len(records),
            "records_by_track": track_counts,
        },
        "sampling_statement": (
            "Only parent scenarios/studies/source works/learning episodes are eligible "
            "primary units; atoms, mutations and replicates remain nested."
        ),
        "split_policy": {
            "current_seed_split": "development",
            "descendants_inherit_parent_split": True,
            "formal_holdout": "not_constructed",
        },
        "gold_boundary": {
            "review_status": "reviewed",
            "independent_of_sut": True,
            "human_review_required": False,
            "human_review_complete": True,
            "review_decision": REVIEW_DECISION,
            "reviewer_role": REVIEWER_ROLE,
            "review_date": REVIEW_DATE,
            "independent_external_expert_review": False,
        },
        "artifact_sha256": {
            path.relative_to(ROOT).as_posix(): _sha(path) for path in sorted(files)
        },
    }
    seed_manifest_path = manifest_dir / "midterm_core_seed_v0.json"
    _write_json(seed_manifest_path, manifest)

    checklist = json.loads(REVIEW_CHECKLIST.read_text(encoding="utf-8"))
    if checklist.get("human_review_complete") is not True:
        raise ValueError("seed_v0_review_checklist_incomplete")
    if checklist.get("review_decision") != REVIEW_DECISION:
        raise ValueError("seed_v0_review_decision_mismatch")
    parent_reviews = checklist.get("parent_scenarios", [])
    if len(parent_reviews) != len(scenarios) or any(
        row.get("review_decision") != REVIEW_DECISION for row in parent_reviews
    ):
        raise ValueError("seed_v0_parent_adjudication_incomplete")

    required_artifacts = {
        "evaluation_contract": CONTRACT,
        "seed_manifest": seed_manifest_path,
        "parent_scenarios": gold_dir / "parent_scenarios.jsonl",
        "workflow_gold": gold_dir / "workflow_gold.jsonl",
        "requirement_gold": gold_dir / "requirement_gold.jsonl",
        "evidence_gold": gold_dir / "evidence_gold.jsonl",
        "scientific_source_provenance": gold_dir / "scientific_source_provenance.jsonl",
        "learning_episodes": gold_dir / "learning_episodes.jsonl",
        "review_checklist": REVIEW_CHECKLIST,
    }
    freeze_manifest = {
        "schema_version": "sckg-midterm-core-seed-freeze-v0",
        "status": "frozen",
        "immutable": True,
        "benchmark_run": False,
        "formal_holdout_constructed": False,
        "human_review_complete": True,
        "review_decision": REVIEW_DECISION,
        "reviewer_role": REVIEWER_ROLE,
        "review_date": REVIEW_DATE,
        "reviewer_reason": REVIEWER_REASON,
        "independent_external_expert_review": False,
        "artifact_sha256": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha(path),
            }
            for name, path in required_artifacts.items()
        },
        "schema_sha256": {
            path.stem.removesuffix(".schema"): {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha(path),
            }
            for path in sorted(schema_dir.glob("*.schema.json"))
        },
    }
    _write_json(manifest_dir / "midterm_core_seed_v0.freeze.json", freeze_manifest)
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True))
