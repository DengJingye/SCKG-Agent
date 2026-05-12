from typing import Any, Dict, List

from core.models import (
    EvidenceBundle,
    WorkflowRecommendation,
    WorkflowStep,
    derived_evidence,
)
from core.settings import get_settings


def build_minimal_workflow_recommendation(
    constraints: Dict[str, Any],
    candidate_tools: List[str] | None = None,
) -> WorkflowRecommendation:
    """Build a deterministic baseline workflow from structured constraints.

    This is a stabilization-stage workflow recommender: it makes the expected
    pipeline shape explicit while the full Workflow graph is still being built.
    """
    task = constraints.get("task", "Unknown")
    modality = constraints.get("modality", "Unknown")
    data_object = constraints.get("data_object", "Unknown")
    output_goal = constraints.get("output_goal", "Unknown")
    candidate_tools = candidate_tools or []
    steps = _steps_for_task(task, modality, data_object, output_goal, candidate_tools)
    warnings = _compatibility_warnings(constraints)
    evidence = derived_evidence(
        evidence_id=f"workflow_template:{task}:{modality}",
        metric_name="workflow_template_match",
        metric_value={"task": task, "modality": modality},
        extraction_method="engine.workflow_recommender.build_minimal_workflow_recommendation",
        source_title="Internal deterministic workflow template",
        confidence=0.55,
        kg_version=get_settings().kg_version,
    )
    return WorkflowRecommendation(
        name=f"{task} workflow for {modality}",
        steps=steps,
        input_signature=[data_object] if data_object != "Unknown" else [],
        output_signature=[output_goal] if output_goal != "Unknown" else [],
        compatibility_warnings=warnings,
        evidence=EvidenceBundle(
            items=[evidence],
            missing_evidence=["workflow_graph_evidence", "step_level_benchmark"],
        ),
    )


def _steps_for_task(
    task: str,
    modality: str,
    data_object: str,
    output_goal: str,
    candidate_tools: List[str],
) -> List[WorkflowStep]:
    templates = {
        "QC": [
            ("input validation", "QC", [data_object], ["validated object"]),
            ("cell and gene quality metrics", "QC", ["validated object"], ["qc metrics"]),
            ("filter low-quality cells", "QC", ["qc metrics"], ["filtered high-quality cells"]),
        ],
        "Doublet Detection": [
            ("input validation", "QC", [data_object], ["validated object"]),
            ("doublet score estimation", "Doublet Detection", ["validated object"], ["doublet risk scores"]),
            ("threshold review with sample context", "Doublet Detection", ["doublet risk scores"], ["doublet calls"]),
            ("post-filter QC check", "QC", ["doublet calls"], [output_goal]),
        ],
        "Ambient RNA Removal": [
            ("droplet and empty-background inspection", "QC", [data_object], ["ambient RNA profile"]),
            ("ambient contamination estimation", "Ambient RNA Removal", ["ambient RNA profile"], ["contamination estimates"]),
            ("expression decontamination", "Ambient RNA Removal", ["contamination estimates"], ["decontaminated expression matrix"]),
            ("marker preservation review", "QC", ["decontaminated expression matrix"], [output_goal]),
        ],
        "Data Integration": [
            ("QC and normalization", "QC", [data_object], ["normalized expression matrix"]),
            ("highly variable feature selection", "Normalization", ["normalized expression matrix"], ["feature set"]),
            ("batch-aware integration", "Data Integration", ["feature set"], ["batch-corrected embedding"]),
            ("clustering-ready validation", "Clustering", ["batch-corrected embedding"], ["validated embedding"]),
        ],
        "Cell Type Annotation": [
            ("QC and normalization", "QC", [data_object], ["normalized expression matrix"]),
            ("cluster or neighborhood construction", "Clustering", ["normalized expression matrix"], ["cell groups"]),
            ("reference-based or marker-based annotation", "Cell Type Annotation", ["cell groups"], ["cell type labels"]),
            ("annotation confidence review", "Cell Type Annotation", ["cell type labels"], [output_goal]),
        ],
        "Spatial Deconvolution": [
            ("spatial count and spot QC", "QC", [data_object], ["validated spatial object"]),
            ("reference cell type harmonization", "Cell Type Annotation", ["validated spatial object"], ["reference cell profiles"]),
            ("spot-level deconvolution", "Spatial Deconvolution", ["reference cell profiles"], ["cell abundance estimates"]),
            ("spatial pattern validation", "Spatial Deconvolution", ["cell abundance estimates"], [output_goal]),
        ],
        "Trajectory Inference": [
            ("QC and normalization", "QC", [data_object], ["normalized expression matrix"]),
            ("feature selection and dimensionality reduction", "Normalization", ["normalized expression matrix"], ["latent embedding"]),
            ("trajectory graph or pseudotime inference", "Trajectory Inference", ["latent embedding"], ["pseudotime"]),
            ("branch and uncertainty review", "Trajectory Inference", ["pseudotime"], [output_goal]),
        ],
        "RNA Velocity": [
            ("spliced/unspliced layer validation", "QC", [data_object], ["velocity-ready expression layers"]),
            ("dynamical model fitting", "RNA Velocity", ["velocity-ready expression layers"], ["velocity estimates"]),
            ("latent time and transition review", "RNA Velocity", ["velocity estimates"], ["dynamic cell-state transitions"]),
            ("uncertainty and assumption audit", "Trajectory Inference", ["dynamic cell-state transitions"], [output_goal]),
        ],
        "Optimal Transport Trajectory": [
            ("timepoint and batch metadata check", "QC", [data_object], ["time-resolved cell states"]),
            ("cost representation construction", "Optimal Transport Trajectory", ["time-resolved cell states"], ["transport cost model"]),
            ("optimal transport map inference", "Optimal Transport Trajectory", ["transport cost model"], ["cell-state transition map"]),
            ("trajectory plausibility review", "Trajectory Inference", ["cell-state transition map"], [output_goal]),
        ],
        "Differential Expression": [
            ("QC and normalization", "QC", [data_object], ["normalized expression matrix"]),
            ("group definition and covariate check", "Differential Expression", ["metadata"], ["contrast design"]),
            ("differential gene testing", "Differential Expression", ["contrast design"], ["differentially expressed genes"]),
            ("effect size and multiple-testing review", "Differential Expression", ["differentially expressed genes"], [output_goal]),
        ],
        "Trajectory Differential Expression": [
            ("trajectory object validation", "Trajectory Inference", [data_object], ["pseudotime or lineage assignments"]),
            ("smoother design and lineage contrast", "Trajectory Differential Expression", ["pseudotime or lineage assignments"], ["trajectory DE design"]),
            ("trajectory-aware gene testing", "Trajectory Differential Expression", ["trajectory DE design"], ["lineage-associated genes"]),
            ("power and FDR review", "Differential Expression", ["lineage-associated genes"], [output_goal]),
        ],
        "Perturbation Differential Expression": [
            ("perturbation metadata validation", "Perturbation Differential Expression", [data_object], ["treatment-control design"]),
            ("condition and covariate review", "Differential Expression", ["treatment-control design"], ["contrast design"]),
            ("perturbation-associated expression modeling", "Perturbation Differential Expression", ["contrast design"], ["perturbation-associated effects"]),
            ("evidence caveat and audit", "Perturbation Differential Expression", ["perturbation-associated effects"], [output_goal]),
        ],
        "Foundation Model Representation": [
            ("input tokenization and modality check", "Foundation Model Representation", [data_object], ["model-ready cell representation"]),
            ("embedding extraction or model selection", "Foundation Model Representation", ["model-ready cell representation"], ["cell embeddings"]),
            ("downstream task evaluation", "Data Integration", ["cell embeddings"], ["evaluated representation"]),
            ("claim and benchmark audit", "Foundation Model Representation", ["evaluated representation"], [output_goal]),
        ],
        "Clustering": [
            ("QC and normalization", "QC", [data_object], ["normalized feature matrix"]),
            ("feature selection", "Normalization", ["normalized feature matrix"], ["feature set"]),
            ("embedding and graph construction", "Clustering", ["feature set"], ["neighbor graph"]),
            ("community detection and marker review", "Clustering", ["neighbor graph"], [output_goal]),
        ],
        "Multiome Integration": [
            ("per-modality QC", "QC", [data_object], ["RNA and protein/ATAC QC outputs"]),
            ("modality-specific normalization", "Normalization", ["RNA and protein/ATAC QC outputs"], ["normalized modality matrices"]),
            ("joint representation learning", "Multiome Integration", ["normalized modality matrices"], ["joint embedding"]),
            ("clustering and annotation on joint space", "Cell Type Annotation", ["joint embedding"], [output_goal]),
        ],
        "Workflow Planning": [
            ("QC", "QC", [data_object], ["filtered object"]),
            ("normalization", "Normalization", ["filtered object"], ["normalized matrix"]),
            ("batch correction or integration if needed", "Data Integration", ["normalized matrix"], ["analysis embedding"]),
            ("downstream analysis", "Workflow Planning", ["analysis embedding"], [output_goal]),
        ],
        "Workflow Compatibility": [
            ("source object inspection", "Workflow Compatibility", [data_object], ["source schema"]),
            ("metadata and assay mapping", "Workflow Compatibility", ["source schema"], ["mapped schema"]),
            ("object conversion", "Workflow Compatibility", ["mapped schema"], ["target object"]),
            ("post-conversion validation", "Workflow Compatibility", ["target object"], [output_goal]),
        ],
    }

    raw_steps = templates.get(
        task,
        [
            ("constraint review", task, [data_object], ["analysis plan"]),
            ("candidate tool validation", task, ["analysis plan"], [output_goal]),
        ],
    )
    return [
        _step(
            name=name,
            order=index,
            task=step_task,
            required_input=required_input,
            produced_output=produced_output,
            candidate_tools=candidate_tools if index == len(raw_steps) else [],
            modality=modality,
        )
        for index, (name, step_task, required_input, produced_output)
        in enumerate(raw_steps, start=1)
    ]


def _step(
    name: str,
    order: int,
    task: str,
    required_input: List[str],
    produced_output: List[str],
    candidate_tools: List[str],
    modality: str,
) -> WorkflowStep:
    evidence = derived_evidence(
        evidence_id=f"workflow_step:{order}:{task}:{modality}",
        metric_name="workflow_step_template",
        metric_value={"step": name, "task": task, "modality": modality},
        extraction_method="engine.workflow_recommender._step",
        source_title="Internal workflow step template",
        confidence=0.5,
        kg_version=get_settings().kg_version,
    )
    return WorkflowStep(
        name=name,
        order=order,
        task=task,
        required_input=[item for item in required_input if item and item != "Unknown"],
        produced_output=[item for item in produced_output if item and item != "Unknown"],
        candidate_tools=candidate_tools,
        evidence=EvidenceBundle(
            items=[evidence],
            missing_evidence=["validated_step_compatibility"],
        ),
    )


def _compatibility_warnings(constraints: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    modality = constraints.get("modality", "Unknown")
    data_object = constraints.get("data_object", "Unknown")
    species = constraints.get("species", "Unknown")
    hardware = constraints.get("hardware", ["Unknown"])
    noise = constraints.get("noise", "Unknown")

    if modality in {"scATAC-seq", "Spatial Transcriptomics", "Spatial Metabolomics"}:
        warnings.append(f"{modality} should not be treated as a plain scRNA-seq matrix without modality-specific checks.")
    if "to" in data_object or "AnnData/h5ad to SeuratObject" in data_object:
        warnings.append("Cross-ecosystem object conversion needs assay, metadata, and dimensional reduction validation.")
    if species == "Human+Mouse":
        warnings.append("Cross-species workflows require ortholog mapping and conserved feature checks.")
    if noise == "high":
        warnings.append("High-noise data should pass QC and sensitivity checks before downstream interpretation.")
    if "GPU" in hardware:
        warnings.append("GPU-compatible methods still need CPU fallback or resource documentation for reproducibility.")
    return warnings
