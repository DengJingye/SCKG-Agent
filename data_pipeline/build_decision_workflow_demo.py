from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.algorithm_representation_v2 import (
    DEFAULT_REPRESENTATIONS_PATH,
    load_tool_representations,
    norm_name,
    representation_to_dict,
)
from engine.evidence_discovery_index import search_hybrid_evidence
DEFAULT_OUTPUT_JSON = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "decision_workflow_demo_v1.json"
)
DEFAULT_OUTPUT_TSV = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "decision_workflow_demo_v1.tsv"
)
DEFAULT_OUTPUT_MD = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "decision_workflow_demo_v1.md"
)
DEFAULT_ALGORITHM_AUDIT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "algorithm_representation_v2_audit.tsv"
)


STEP_DEFINITIONS = [
    {
        "step_id": "input_qc",
        "name": "Input and QC precheck",
        "task": "QC",
        "purpose": "Validate count matrix, metadata, mitochondrial/ribosomal metrics, and per-sample quality distribution.",
        "candidate_tools": ["Scanpy", "Seurat"],
        "default_candidate": "Scanpy",
        "required_input": ["raw count matrix", "sample metadata"],
        "produced_output": ["validated object", "QC metrics"],
        "decision_policy": "Use the ecosystem that matches downstream execution; do not mix object schemas without validation.",
    },
    {
        "step_id": "doublet_detection",
        "name": "Doublet detection",
        "task": "Doublet Detection",
        "purpose": "Estimate doublet risk before integration so artificial hybrid cells do not distort batch correction.",
        "candidate_tools": ["Scrublet", "DoubletFinder"],
        "default_candidate": "Scrublet",
        "required_input": ["validated object", "raw counts"],
        "produced_output": ["doublet scores", "doublet calls"],
        "decision_policy": "Prefer tools with source text and benchmark evidence discovery; thresholds require sample-aware review.",
    },
    {
        "step_id": "normalization_hvg",
        "name": "Normalization and HVG selection",
        "task": "Normalization",
        "purpose": "Normalize library size effects and choose variable features for integration.",
        "candidate_tools": ["Scanpy", "Seurat", "scvi-tools"],
        "default_candidate": "Scanpy",
        "required_input": ["doublet-filtered object"],
        "produced_output": ["normalized expression matrix", "feature set"],
        "decision_policy": "Keep normalization assumptions consistent with the chosen integration method.",
    },
    {
        "step_id": "batch_integration",
        "name": "Batch-aware integration",
        "task": "Data Integration",
        "purpose": "Align multi-sample PBMC data while preserving biological cell-state structure.",
        "candidate_tools": ["Harmony", "scvi-tools", "Seurat"],
        "default_candidate": "Harmony",
        "required_input": ["feature set", "batch metadata"],
        "produced_output": ["batch-corrected embedding"],
        "decision_policy": "Use graph/task compatibility plus benchmark source context; do not treat integration score as universal across datasets.",
    },
    {
        "step_id": "cell_annotation",
        "name": "Cell type annotation",
        "task": "Cell Type Annotation",
        "purpose": "Assign PBMC cell labels with reference-based and marker-based cross-checks.",
        "candidate_tools": ["CellTypist", "SingleR", "Seurat"],
        "default_candidate": "CellTypist",
        "required_input": ["integrated object", "reference labels or marker set"],
        "produced_output": ["cell type labels", "annotation confidence"],
        "decision_policy": "Use annotation tools as candidates only until benchmark DOI/source mismatch is fixed for the frozen benchmark rows.",
    },
    {
        "step_id": "trajectory_optional",
        "name": "Optional trajectory and fate analysis",
        "task": "Trajectory Inference",
        "purpose": "If biology requires dynamic state transitions, run velocity/fate tools after QC and annotation.",
        "candidate_tools": ["scVelo", "CellRank"],
        "default_candidate": "scVelo",
        "required_input": ["annotated object", "spliced/unspliced layers if velocity is used"],
        "produced_output": ["pseudotime or fate probabilities"],
        "decision_policy": "Treat as optional because PBMC steady-state analysis often does not require trajectory inference.",
    },
    {
        "step_id": "audit_report",
        "name": "Evidence audit and report",
        "task": "Evidence Governance",
        "purpose": "Separate executable workflow advice from formal recommendation claims and list evidence gaps.",
        "candidate_tools": ["scKG-Agent"],
        "default_candidate": "scKG-Agent",
        "required_input": ["workflow plan", "retrieval snippets", "evidence gate diagnostics"],
        "produced_output": ["auditable decision report"],
        "decision_policy": "RAG snippets explain context; only reviewed formal evidence can support strong recommendation wording.",
    },
]


SCENARIO = {
    "scenario_id": "pbmc_multibatch_workflow_demo_v1",
    "user_query": (
        "I have multi-sample 10x PBMC scRNA-seq data and want QC, doublet detection, "
        "batch integration, cell type annotation, and optional trajectory analysis."
    ),
    "task": "Workflow Planning",
    "task_family": "workflow",
    "modality": "scRNA-seq",
    "platform": "10x Genomics",
    "species": "Human",
    "data_object": "raw count matrix / AnnData / SeuratObject",
    "scale": "multi-sample PBMC; 50k-200k cells",
    "noise": "medium",
    "hardware": ["CPU baseline", "GPU optional for deep latent models"],
    "output_goal": "integrated, doublet-filtered, annotated PBMC object with an auditable report",
    "strictness": "evidence_limited",
}


def build_decision_workflow_demo(
    *,
    scenario: Dict[str, Any] | None = None,
    search_fn: Callable[..., Dict[str, Any]] = search_hybrid_evidence,
    representation_path: Path = DEFAULT_REPRESENTATIONS_PATH,
    algorithm_audit_path: Path = DEFAULT_ALGORITHM_AUDIT,
) -> Dict[str, Any]:
    scenario = scenario or dict(SCENARIO)
    representations = load_tool_representations(representation_path)
    audit_by_tool = {
        norm_name(row.get("tool_name")): row
        for row in read_tsv(algorithm_audit_path)
        if row.get("tool_name")
    }

    steps: List[Dict[str, Any]] = []
    all_snippets: List[Dict[str, Any]] = []
    tool_names = sorted({tool for step in STEP_DEFINITIONS for tool in step["candidate_tools"]})
    for order, definition in enumerate(STEP_DEFINITIONS, start=1):
        constraints = {
            **scenario,
            "task": definition["task"],
            "output_goal": definition["produced_output"][-1],
            "workflow_step": definition["step_id"],
        }
        rag_context = search_fn(
            constraints=constraints,
            tool_names=definition["candidate_tools"],
            max_snippets=80,
        )
        snippets = select_demo_snippets(rag_context.get("snippets") or [], definition["candidate_tools"], limit=5)
        all_snippets.extend(snippets)
        steps.append(
            {
                "order": order,
                **definition,
                "status": "plan_only_evidence_limited",
                "candidate_cards": [
                    tool_card(tool, representations, audit_by_tool, snippets)
                    for tool in definition["candidate_tools"]
                ],
                "evidence_coverage": step_evidence_coverage(definition["candidate_tools"], snippets),
                "retrieval": {
                    "mode": rag_context.get("mode", ""),
                    "pipeline": rag_context.get("pipeline", []),
                    "snippet_count": len(snippets),
                    "matched_tools": rag_context.get("matched_tools", []),
                    "snippets": compact_snippets(snippets),
                },
                "warnings": step_warnings(definition, snippets, audit_by_tool),
            }
        )

    graph = workflow_graph(steps)
    demo = {
        "demo": "decision_workflow_demo_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "positioning": (
            "Evidence-governed single-cell analysis decision workflow. This is broader than a ranked tool report: "
            "it returns an auditable workflow plan, candidate tools, evidence snippets, code skeletons, and gaps."
        ),
        "scenario": scenario,
        "agent_boundary": {
            "architecture": "centralized recursive agent target; deterministic workflow demo in v1",
            "output_authority": "plan-only unless formal evidence gate allows stronger claims",
            "rag_authority": "retrieval context only",
            "kg_authority": "hard constraints and compatibility context",
            "formal_evidence_authority": "only reviewed TSV/promotion flow can support strong recommendation claims",
        },
        "workflow_steps": steps,
        "tool_cards": [tool_card(tool, representations, audit_by_tool, all_snippets) for tool in tool_names],
        "workflow_graph": graph,
        "code_skeletons": build_code_skeletons(),
        "evaluation_hooks": {
            "workflow_path_quality": "Check that required inputs and produced outputs connect step-to-step.",
            "evidence_coverage": "Count source-bound snippets and formal main-evidence eligibility per step.",
            "blocked_unsupported_claims": "Strong claims remain blocked when evidence is frozen or source-mismatched.",
            "user_value": "User receives executable plan, alternatives, caveats, and source-backed context.",
        },
        "global_evidence_coverage": global_evidence_coverage(steps),
        "next_actions": [
            "Fix source_metadata_mismatch for CellTypist/SingleR annotation benchmark before using it as strong benchmark support.",
            "Repair Seurat v3/v4 publication extraction or use publisher HTML/full text.",
            "Add workflow path eval set for 5-10 single-cell scenarios.",
            "Add module-level representations for Seurat, Scanpy, and scvi-tools.",
        ],
        "guardrail": (
            "This demo does not promote formal TSV evidence, does not write Neo4j, and does not change MCDM ranks."
        ),
    }
    return demo


def tool_card(
    tool_name: str,
    representations: Dict[str, Any],
    audit_by_tool: Dict[str, Dict[str, str]],
    snippets: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    rep = representations.get(norm_name(tool_name))
    rep_dict = representation_to_dict(rep) if rep else {}
    audit = audit_by_tool.get(norm_name(tool_name), {})
    tool_snippets = [snippet for snippet in snippets if norm_name(snippet.get("tool_name")) == norm_name(tool_name)]
    confidence = rep_dict.get("confidence") or {}
    evidence_text = rep_dict.get("evidence_text_view") or {}
    empirical = rep_dict.get("empirical_view") or {}
    return {
        "tool_name": tool_name,
        "source_chunk_count": int(audit.get("source_chunk_count") or evidence_text.get("chunk_id_count") or 0),
        "dense_vector_chunk_count": int(
            audit.get("dense_vector_chunk_count") or evidence_text.get("dense_vector_chunk_count") or 0
        ),
        "benchmark_chunk_count": int(audit.get("benchmark_chunk_count") or empirical.get("benchmark_chunk_count") or 0),
        "publication_chunk_count": int(
            audit.get("publication_chunk_count") or empirical.get("publication_chunk_count") or 0
        ),
        "quality_flags": split_csv(audit.get("quality_flags")) or list(confidence.get("quality_flags") or []),
        "review_status": audit.get("review_status") or confidence.get("review_status", "missing_representation"),
        "retrieval_snippet_count": len(tool_snippets),
        "candidate_authority": "workflow_candidate_only",
        "can_support_strong_recommendation_now": False,
        "boundary": (
            "Tool card can support planning and evidence discovery. It cannot by itself support a strong recommendation."
        ),
    }


def step_evidence_coverage(candidate_tools: Sequence[str], snippets: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_tool = Counter(snippet.get("tool_name", "") for snippet in snippets if snippet.get("tool_name"))
    source_bound = [
        snippet for snippet in snippets
        if is_source_bound_snippet(snippet)
    ]
    formal = [
        snippet for snippet in snippets
        if snippet.get("source_kind") in {"publication", "benchmark"}
    ]
    matched_tools = sorted(set(by_tool) & set(candidate_tools))
    return {
        "candidate_tool_count": len(candidate_tools),
        "matched_tool_count": len(matched_tools),
        "matched_tools": matched_tools,
        "snippet_count": len(snippets),
        "source_bound_snippet_count": len(source_bound),
        "formal_snippet_count": len(formal),
        "coverage_ratio": round(len(matched_tools) / max(len(candidate_tools), 1), 4),
        "missing_tools": [tool for tool in candidate_tools if tool not in matched_tools],
    }


def step_warnings(
    definition: Dict[str, Any],
    snippets: Sequence[Dict[str, Any]],
    audit_by_tool: Dict[str, Dict[str, str]],
) -> List[str]:
    warnings: List[str] = []
    coverage = step_evidence_coverage(definition["candidate_tools"], snippets)
    if coverage["coverage_ratio"] < 1.0:
        warnings.append("Some candidate tools have no retrieved source snippet for this step.")
    if definition["step_id"] == "cell_annotation":
        warnings.append("CellTypist/SingleR benchmark source currently has a wrong DOI/source mismatch; keep benchmark claims blocked.")
    for tool in definition["candidate_tools"]:
        flags = split_csv(audit_by_tool.get(norm_name(tool), {}).get("quality_flags"))
        if "toolkit_requires_module_split" in flags:
            warnings.append(f"{tool} is a broad toolkit; module-level representation is required before precise migration claims.")
    return warnings


def compact_snippets(snippets: Sequence[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    return [
        {
            "tool_name": snippet.get("tool_name", ""),
            "source_kind": snippet.get("source_kind", ""),
            "title": snippet.get("title", ""),
            "source_span": snippet.get("source_span", ""),
            "relevance_score": snippet.get("relevance_score", 0),
            "claim_span": snippet.get("claim_span", ""),
            "claim_boundary": snippet.get("claim_boundary", ""),
        }
        for snippet in snippets[:limit]
    ]


def select_demo_snippets(
    snippets: Sequence[Dict[str, Any]],
    candidate_tools: Sequence[str],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    """Prefer source-bound discovery chunks so the demo shows the PDF/docs RAG layer."""

    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    candidate_keys = [norm_name(tool) for tool in candidate_tools]
    for tool_key in candidate_keys:
        for prefer_source_bound in (True, False):
            for snippet in snippets:
                if norm_name(snippet.get("tool_name")) != tool_key:
                    continue
                if is_source_bound_snippet(snippet) != prefer_source_bound:
                    continue
                snippet_id = str(snippet.get("chunk_id") or snippet.get("record_id") or repr(snippet))
                if snippet_id in seen:
                    continue
                selected.append(snippet)
                seen.add(snippet_id)
                break
        if len(selected) >= limit:
            return selected[:limit]
    for snippet in snippets:
        snippet_id = str(snippet.get("chunk_id") or snippet.get("record_id") or repr(snippet))
        if snippet_id not in seen:
            selected.append(snippet)
            seen.add(snippet_id)
        if len(selected) >= limit:
            break
    return selected[:limit]


def is_source_bound_snippet(snippet: Dict[str, Any]) -> bool:
    source_kind = str(snippet.get("source_kind", ""))
    return source_kind.startswith("source_") or source_kind == "document"


def workflow_graph(steps: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for step in steps:
        node_id = step["step_id"]
        nodes.append(
            {
                "id": node_id,
                "label": step["name"],
                "task": step["task"],
                "candidate_tools": step["candidate_tools"],
                "status": step["status"],
            }
        )
    for left, right in zip(steps, steps[1:]):
        edges.append(
            {
                "source": left["step_id"],
                "target": right["step_id"],
                "handoff": f"{left['produced_output'][-1]} -> {right['required_input'][0]}",
                "compatibility_status": "needs_runtime_validation",
            }
        )
    return {"nodes": nodes, "edges": edges}


def global_evidence_coverage(steps: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    snippet_count = sum(step["evidence_coverage"]["snippet_count"] for step in steps)
    source_bound = sum(step["evidence_coverage"]["source_bound_snippet_count"] for step in steps)
    matched_steps = sum(1 for step in steps if step["evidence_coverage"]["matched_tool_count"] > 0)
    warnings = sum(len(step.get("warnings") or []) for step in steps)
    return {
        "workflow_steps": len(steps),
        "steps_with_any_tool_match": matched_steps,
        "total_retrieval_snippets": snippet_count,
        "source_bound_retrieval_snippets": source_bound,
        "warning_count": warnings,
        "formal_main_recommendation_evidence_count": 0,
        "status": "evidence_limited_plan_only",
    }


def build_code_skeletons() -> Dict[str, str]:
    return {
        "scanpy_python": "\n".join(
            [
                "import scanpy as sc",
                "",
                "adata = sc.read_h5ad('input_raw_counts.h5ad')",
                "sc.pp.calculate_qc_metrics(adata, inplace=True)",
                "# Review QC thresholds per sample before filtering.",
                "sc.pp.filter_cells(adata, min_genes=200)",
                "sc.pp.filter_genes(adata, min_cells=3)",
                "# Run doublet detection with Scrublet or another validated tool before integration.",
                "sc.pp.normalize_total(adata, target_sum=1e4)",
                "sc.pp.log1p(adata)",
                "sc.pp.highly_variable_genes(adata, batch_key='sample_id')",
                "sc.tl.pca(adata)",
                "# Add Harmony/scVI integration here after checking batch metadata and resources.",
                "sc.pp.neighbors(adata)",
                "sc.tl.leiden(adata)",
                "# Add CellTypist/SingleR-style annotation and marker review.",
                "adata.write_h5ad('pbmc_decision_workflow_output.h5ad')",
            ]
        ),
        "seurat_r": "\n".join(
            [
                "library(Seurat)",
                "",
                "obj <- Read10X(data.dir = 'filtered_feature_bc_matrix/') |> CreateSeuratObject()",
                "obj[['percent.mt']] <- PercentageFeatureSet(obj, pattern = '^MT-')",
                "# Review QC thresholds per sample before subsetting.",
                "obj <- subset(obj, subset = nFeature_RNA > 200)",
                "obj <- NormalizeData(obj)",
                "obj <- FindVariableFeatures(obj)",
                "obj <- ScaleData(obj)",
                "obj <- RunPCA(obj)",
                "# Add integration/Harmony/scVI bridge after validating batch metadata.",
                "obj <- FindNeighbors(obj, dims = 1:30)",
                "obj <- FindClusters(obj)",
                "# Add annotation and marker validation.",
                "saveRDS(obj, 'pbmc_decision_workflow_output.rds')",
            ]
        ),
    }


def write_tsv(path: Path, demo: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "order",
        "step_id",
        "name",
        "task",
        "default_candidate",
        "candidate_tools",
        "snippet_count",
        "matched_tools",
        "coverage_ratio",
        "warnings",
        "status",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for step in demo["workflow_steps"]:
            coverage = step["evidence_coverage"]
            writer.writerow(
                {
                    "order": step["order"],
                    "step_id": step["step_id"],
                    "name": step["name"],
                    "task": step["task"],
                    "default_candidate": step["default_candidate"],
                    "candidate_tools": ", ".join(step["candidate_tools"]),
                    "snippet_count": coverage["snippet_count"],
                    "matched_tools": ", ".join(coverage["matched_tools"]),
                    "coverage_ratio": coverage["coverage_ratio"],
                    "warnings": " | ".join(step.get("warnings") or []),
                    "status": step["status"],
                }
            )


def write_markdown(path: Path, demo: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# scKG Decision Workflow Demo v1",
        "",
        demo["positioning"],
        "",
        "## Scenario",
        "",
        f"- Query: {demo['scenario']['user_query']}",
        f"- Modality: {demo['scenario']['modality']}",
        f"- Output goal: {demo['scenario']['output_goal']}",
        "",
        "## Workflow",
        "",
    ]
    for step in demo["workflow_steps"]:
        coverage = step["evidence_coverage"]
        lines.extend(
            [
                f"### {step['order']}. {step['name']}",
                "",
                f"- Task: {step['task']}",
                f"- Default candidate: {step['default_candidate']}",
                f"- Candidate tools: {', '.join(step['candidate_tools'])}",
                f"- Evidence snippets: {coverage['snippet_count']} ({', '.join(coverage['matched_tools']) or 'none'})",
                f"- Status: {step['status']}",
                f"- Policy: {step['decision_policy']}",
            ]
        )
        if step.get("warnings"):
            lines.append(f"- Warnings: {' | '.join(step['warnings'])}")
        lines.append("")
    lines.extend(
        [
            "## Guardrail",
            "",
            demo["guardrail"],
            "",
            "## Next Actions",
            "",
            *[f"- {item}" for item in demo["next_actions"]],
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def split_csv(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the scKG decision workflow demo artifact.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-tsv", type=Path, default=DEFAULT_OUTPUT_TSV)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    args = parser.parse_args()

    demo = build_decision_workflow_demo()
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(demo, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    write_tsv(args.output_tsv, demo)
    write_markdown(args.output_md, demo)
    print(
        json.dumps(
            {
                "output_json": rel(args.output_json),
                "output_tsv": rel(args.output_tsv),
                "output_md": rel(args.output_md),
                "workflow_steps": len(demo["workflow_steps"]),
                **demo["global_evidence_coverage"],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
