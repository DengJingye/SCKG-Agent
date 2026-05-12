import argparse
import csv
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evidence_schemas import BENCHMARK_FIELDS, PUBLICATION_FIELDS


EVIDENCE_CANDIDATES = PROJECT_ROOT / "data" / "evidence_candidates"
DEFAULT_MANUAL_ANCHORS = EVIDENCE_CANDIDATES / "core50_publication_manual_anchors.tsv"
DEFAULT_PUBLICATION_REVIEW = EVIDENCE_CANDIDATES / "core50_publication_human_review.tsv"
DEFAULT_BENCHMARK_REVIEW = EVIDENCE_CANDIDATES / "core50_benchmark_human_review.tsv"
DEFAULT_NEXT_LEDGER = EVIDENCE_CANDIDATES / "core50_next_batch_human_review.tsv"

REVIEW_TIME = "2026-05-19T00:00:00+08:00"
KG_VERSION = "v0.1"
EMBEDDING_VERSION = "bge-m3-v0.1"
CREATED_AT = "2026-05-19T00:00:00+08:00"


PUBLICATION_ANCHORS = [
    {
        "publication_id": "CAND_PUB_Seurat_v3_2019_Stuart",
        "work_group_id": "PUBWG_Seurat_core_versions",
        "tool_name": "Seurat",
        "tool_alias": "Seurat;Seurat v3",
        "title": "Comprehensive Integration of Single-Cell Data",
        "authors": "Tim Stuart;Andrew Butler;Paul Hoffman;Christoph Hafemeister;Efthymia Papalexi;William M. Mauck III;Yuhan Hao;Marion Stoeckius;Peter Smibert;Rahul Satija",
        "first_author": "Tim Stuart",
        "doi": "10.1016/j.cell.2019.05.031",
        "paper_url": "https://doi.org/10.1016/j.cell.2019.05.031",
        "publication_year": "2019",
        "venue": "Cell",
        "publisher": "Elsevier BV",
        "task": "Data Integration",
        "modality": "scRNA-seq",
        "github_url": "https://github.com/satijalab/seurat",
        "license_reported": "GPL-3.0",
        "confidence": "0.95",
        "canonical_scope": "core_tool",
        "authority_tier": "canonical_primary",
        "notes": "manual Seurat V3 core anchor from human review; wrappers/protocols excluded from canonical authority",
    },
    {
        "publication_id": "CAND_PUB_Seurat_v4_2021_Hao",
        "work_group_id": "PUBWG_Seurat_core_versions",
        "tool_name": "Seurat",
        "tool_alias": "Seurat;Seurat v4",
        "title": "Integrated analysis of multimodal single-cell data",
        "authors": "Yuhan Hao;Stephanie Hao;Erica Andersen-Nissen;William M. Mauck III;Shiwei Zheng;Andrew Butler;Maddie J. Lee;Aaron J. Wilk;Charlotte Darby;Michael Zager;Paul Hoffman;Marion Stoeckius;Efthymia Papalexi;Eric P. Mimitou;Jaison Jain;Aviv Srivastava;Tim Stuart;Lamar B. Fleming;Bertrand Yeung;Angela J. Rogers;Jason M. McElrath;Catherine A. Blish;Rapolas Gottardo;Peter Smibert;Rahul Satija",
        "first_author": "Yuhan Hao",
        "doi": "10.1016/j.cell.2021.04.048",
        "paper_url": "https://doi.org/10.1016/j.cell.2021.04.048",
        "publication_year": "2021",
        "venue": "Cell",
        "publisher": "Elsevier BV",
        "task": "Data Integration;Multimodal Analysis",
        "modality": "scRNA-seq;multiome",
        "github_url": "https://github.com/satijalab/seurat",
        "license_reported": "GPL-3.0",
        "confidence": "0.95",
        "canonical_scope": "major_version",
        "authority_tier": "canonical_secondary",
        "notes": "manual Seurat V4 major-version anchor from human review; multimodal analysis authority",
    },
    {
        "publication_id": "CAND_PUB_SingleR_2019_Aran",
        "work_group_id": "PUBWG_CAND_PUB_SingleR_2019_Aran",
        "tool_name": "SingleR",
        "tool_alias": "SingleR",
        "title": "Reference-based analysis of lung single-cell sequencing reveals a transitional profibrotic macrophage",
        "authors": "Dvir Aran;Agnes P. Looney;Leqian Liu;Esther Wu;Valentina Fong;Austin Hsu;Sneha Chak;Rene P. Naikawadi;Paul J. Wolters;Adam R. Abate;Andrew J. Butte;Mallar Bhattacharya",
        "first_author": "Dvir Aran",
        "doi": "10.1038/s41590-018-0276-y",
        "paper_url": "https://doi.org/10.1038/s41590-018-0276-y",
        "publication_year": "2019",
        "venue": "Nature Immunology",
        "publisher": "Springer Science and Business Media LLC",
        "task": "Cell Type Annotation",
        "modality": "scRNA-seq",
        "github_url": "https://github.com/dviraran/SingleR",
        "license_reported": "GPL-3.0",
        "confidence": "0.90",
        "canonical_scope": "core_tool",
        "authority_tier": "canonical_primary",
        "notes": "manual SingleR canonical anchor; corrected human-supplied DOI 10.1038/s41590-019-0312-6 to official DOI 10.1038/s41590-018-0276-y",
    },
    {
        "publication_id": "CAND_PUB_MAESTRO_2020_Wang",
        "work_group_id": "PUBWG_CAND_PUB_MAESTRO_2020_Wang",
        "tool_name": "MAESTRO",
        "tool_alias": "MAESTRO",
        "title": "Integrative analysis of single-cell transcriptome and regulome using MAESTRO",
        "authors": "Chen Wang;Xiaomeng Sun;Shuying Peng;Ying Yao;Yi Chen;Yingying Liu;X. Shirley Liu",
        "first_author": "Chen Wang",
        "doi": "10.1186/s13059-020-02116-x",
        "paper_url": "https://doi.org/10.1186/s13059-020-02116-x",
        "publication_year": "2020",
        "venue": "Genome Biology",
        "publisher": "Springer Science and Business Media LLC",
        "task": "Multi-omics Workflow;Regulome Analysis",
        "modality": "scRNA-seq;scATAC-seq",
        "github_url": "https://github.com/liulab-dfci/MAESTRO",
        "license_reported": "GPL-3.0",
        "confidence": "0.90",
        "canonical_scope": "core_tool",
        "authority_tier": "canonical_primary",
        "notes": "manual MAESTRO canonical anchor; corrected human-supplied DOI 10.1186/s13059-020-02022-2 to official DOI 10.1186/s13059-020-02116-x; editorial shell quarantined",
    },
    {
        "publication_id": "CAND_PUB_MIMOSCA_7882e7558c0e",
        "work_group_id": "PUBWG_CAND_PUB_MIMOSCA_7882e7558c0e",
        "tool_name": "MIMOSCA",
        "tool_alias": "MIMOSCA",
        "title": "Perturb-Seq: Dissecting Molecular Circuits with Scalable Single-Cell RNA Profiling of Pooled Genetic Screens",
        "authors": "Atray Dixit;Oren Parnas;Biyu Li;Jenny Chen;Charles P. Fulco;Livnat Jerby-Arnon;Nemanja D. Marjanovic;Danielle Dionne;Tyler Burks;Raktima Raychowdhury;Britt Adamson;Thomas M. Norman;Eric S. Lander;Jonathan S. Weissman;Nir Friedman;Aviv Regev",
        "first_author": "Atray Dixit",
        "doi": "10.1016/j.cell.2016.11.038",
        "paper_url": "https://doi.org/10.1016/j.cell.2016.11.038",
        "publication_year": "2016",
        "venue": "Cell",
        "publisher": "Elsevier BV",
        "task": "Perturbation Analysis;Multi-condition Analysis",
        "modality": "scRNA-seq",
        "github_url": "https://github.com/asncd/MIMOSCA",
        "license_reported": "MIT",
        "confidence": "0.80",
        "canonical_scope": "core_tool",
        "authority_tier": "canonical_primary",
        "notes": "manual MIMOSCA anchor from human review; MIMOSCA treated as core computational framework within Perturb-seq; assay/method boundary noted",
    },
]


PUBLICATION_REVIEW_ROWS = [
    ("CAND_PUB_Seurat_v3_2019_Stuart", "formalize", "core_tool", "architectural_core", "true", "canonical_primary", "absolute_authority", "Seurat V3 core method anchor; wrapper/protocol candidates remain supporting or quarantine."),
    ("CAND_PUB_Seurat_v4_2021_Hao", "formalize", "major_version", "architectural_core", "true", "canonical_secondary", "absolute_authority", "Seurat V4 major-version multimodal anchor."),
    ("CAND_PUB_SingleR_2019_Aran", "formalize", "core_tool", "architectural_core", "true", "canonical_primary", "absolute_authority", "SingleR official/canonical citation; human-supplied DOI corrected before formalization."),
    ("CAND_PUB_MAESTRO_2020_Wang", "formalize", "core_tool", "architectural_core", "true", "canonical_primary", "absolute_authority", "MAESTRO canonical Genome Biology paper; editorial shell remains quarantine."),
    ("CAND_PUB_MIMOSCA_7882e7558c0e", "formalize", "core_tool", "architectural_core", "true", "canonical_primary", "absolute_authority", "MIMOSCA computational framework anchor within Perturb-seq paper; boundary risk retained in notes."),
]


BENCHMARK_ROWS = [
    {
        "benchmark_id": "HR_BMK_scvi_tools_scIB_integration_2022",
        "decision": "formalize",
        "tool_name": "scvi-tools",
        "benchmark_name": "Benchmarking atlas-level data integration in single-cell genomics",
        "benchmark_type": "comparative_benchmark",
        "task": "Data Integration",
        "modality": "scRNA-seq;scATAC-seq",
        "dataset": "85 batches across 13 atlases",
        "metric": "Batch correction and biological conservation metrics",
        "metric_definition": "scIB integration metrics balancing batch removal and biology conservation",
        "direction": "higher_is_better",
        "rank_scope": "scIB atlas-level integration benchmark",
        "n_tools_compared": "68",
        "result_text": "scVI and scANVI variants are top-tier methods for balancing batch correction and biological conservation in the scIB benchmark.",
        "evaluation_protocol": "scIB benchmarking pipeline evaluating batch correction versus biological conservation across atlas-level datasets",
        "paper_title": "Benchmarking atlas-level data integration in single-cell genomics",
        "paper_doi": "10.1038/s41592-021-01336-8",
        "source_url": "https://doi.org/10.1038/s41592-021-01336-8",
        "confidence": "0.90",
        "notes": "Human-reviewed benchmark fact; qualitative conclusion only; no numeric score invented.",
    },
    {
        "benchmark_id": "HR_BMK_SingleR_annotation_2023",
        "decision": "formalize",
        "tool_name": "SingleR",
        "benchmark_name": "A comprehensive benchmarking of cell type annotation methods for single-cell RNA sequencing",
        "benchmark_type": "comparative_benchmark",
        "task": "Cell Type Annotation",
        "modality": "scRNA-seq",
        "dataset": "Simulated and diverse real-world reference atlases",
        "metric": "Accuracy and F1-score",
        "metric_definition": "Cell type annotation accuracy against curated references",
        "direction": "higher_is_better",
        "rank_scope": "Cell type annotation method benchmark",
        "n_tools_compared": "10+",
        "result_text": "SingleR remains among high-performing supervised annotation methods, including top-tier F1-score and accuracy across multiple benchmark settings.",
        "evaluation_protocol": "Cross-validation and independent testing against curated reference atlases",
        "paper_title": "A comprehensive benchmarking of cell type annotation methods for single-cell RNA sequencing",
        "paper_doi": "10.1093/bib/bbad418",
        "source_url": "https://doi.org/10.1093/bib/bbad418",
        "confidence": "0.90",
        "notes": "Human-reviewed benchmark fact aligned with CellTypist benchmark source; qualitative conclusion only.",
    },
]


LEDGER_ROWS = [
    ("CellTypist", "graph_tool_node_missing", "create_tool_node", "Create Tool node from scrna_tools.tsv metadata, then rerun formal-only backfill."),
    ("Seurat", "publication_anchor_missing", "promote_anchor_manual", "Injected Seurat V3 and V4 anchors; wrapper/protocol candidates remain non-canonical."),
    ("SingleR", "publication_anchor_missing", "promote_anchor_manual", "Injected canonical SingleR anchor; DOI corrected to official Nature Immunology DOI."),
    ("MAESTRO", "publication_anchor_missing", "promote_anchor_manual", "Injected canonical MAESTRO paper; editorial shell remains quarantine."),
    ("MIMOSCA", "publication_anchor_missing", "promote_anchor_manual", "Injected Perturb-seq/MIMOSCA framework anchor with boundary risk note."),
    ("MOFA", "publication_anchor_missing", "legacy_provenance", "MOFA v1 not promoted; MOFA2 remains recommendation authority."),
    ("velociraptor", "publication_anchor_missing", "wrapper_only", "Bioconductor wrapper for scVelo; retrieval-only, no canonical method promotion."),
    ("scIB", "benchmark_source_missing", "framework_not_tool", "Treat as benchmark protocol/framework, not an evaluated recommendation tool."),
    ("scvi-tools", "benchmark_source_missing", "extract_benchmark_fact", "Added scIB qualitative benchmark fact for scVI/scANVI variants."),
    ("SingleR", "benchmark_source_missing", "extract_benchmark_fact", "Added annotation benchmark fact using DOI 10.1093/bib/bbad418."),
    ("MOFA2", "benchmark_source_missing", "source_verified_formalized", "Source verification resolved; promoted bounded joint dimensionality-reduction benchmark fact as HR_BMK_MOFA2_jDR_cancer_2021."),
    ("scVelo", "benchmark_source_missing", "source_verified_formalized", "Source verification resolved; promoted RNA velocity caveat/negative-control benchmark fact as HR_BMK_scVelo_velocity_unraveled_2022."),
    ("cell2location", "benchmark_source_missing", "source_verified_formalized", "Source verification resolved; promoted spatial deconvolution benchmark fact as HR_BMK_cell2location_spatial_deconvolution_2022."),
    ("CellPLM", "benchmark_source_missing", "defer_benchmark", "Independent third-party foundation-model benchmark not yet established."),
    ("nicheformer", "benchmark_source_missing", "defer_benchmark", "Independent third-party benchmark deferred."),
    ("moscot", "benchmark_source_missing", "defer_benchmark", "New tool; rely on primary paper self-evaluation for now."),
    ("CellRank", "benchmark_source_missing", "defer_benchmark", "External benchmark deferred; current candidate shells not usable."),
    ("SeuratExtend", "benchmark_source_missing", "defer_benchmark", "Ecosystem component; performance authority inherited from underlying Seurat/Scanpy context."),
    ("MAESTRO", "benchmark_source_missing", "defer_benchmark", "Pipeline/workflow, not a single algorithm benchmark target."),
    ("MIMOSCA", "benchmark_source_missing", "defer_benchmark", "Perturbation inference lacks stable unified benchmark in current scope."),
    ("wot", "benchmark_source_missing", "defer_benchmark", "Optimal-transport trajectory applications are highly context-specific; benchmark deferred."),
    ("MOFA", "benchmark_source_missing", "ignore", "Superseded by MOFA2 for recommendation authority."),
    ("velociraptor", "benchmark_source_missing", "ignore", "Wrapper performance should be attributed to scVelo, not velociraptor."),
]


def read_tsv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader), list(reader.fieldnames or [])


def write_tsv(path: Path, rows: List[Dict[str, str]], fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def ensure_unique(rows: Iterable[Dict[str, str]], id_field: str) -> None:
    seen = set()
    for row in rows:
        value = row.get(id_field, "")
        if not value:
            continue
        if value in seen:
            raise ValueError(f"Duplicate {id_field}: {value}")
        seen.add(value)


def publication_anchor_row(spec: Dict[str, str]) -> Dict[str, str]:
    row = {field: "" for field in PUBLICATION_FIELDS}
    row.update(
        {
            "publication_id": spec["publication_id"],
            "work_group_id": spec["work_group_id"],
            "canonical_flag": "true",
            "record_type": "publication",
            "source_record_id": spec["doi"],
            "tool_name": spec["tool_name"],
            "tool_alias": spec["tool_alias"],
            "title": spec["title"],
            "authors": spec["authors"],
            "first_author": spec["first_author"],
            "doi": spec["doi"],
            "paper_url": spec["paper_url"],
            "publication_year": spec["publication_year"],
            "venue": spec["venue"],
            "publisher": spec["publisher"],
            "paper_type": "method_paper",
            "evidence_role": "primary_method_reference",
            "task": spec["task"],
            "modality": spec["modality"],
            "benchmark_included": "false",
            "open_source_reported": "true",
            "github_url": spec["github_url"],
            "license_reported": spec["license_reported"],
            "source_url": spec["paper_url"],
            "source_type": "manual",
            "extraction_method": "manual_canonical_anchor_seed",
            "claim_span": spec["title"],
            "confidence": spec["confidence"],
            "trust_level": "review_needed",
            "review_status": "pending",
            "kg_version": KG_VERSION,
            "embedding_version": EMBEDDING_VERSION,
            "created_at": CREATED_AT,
            "updated_at": CREATED_AT,
            "last_checked": CREATED_AT,
            "notes": f"candidate_only; manual canonical anchor seed; requires human review before ingest; {spec['notes']}",
        }
    )
    row["group_size"] = "1"
    row["group_reason"] = "manual authoritative seed from human review"
    row["canonical_score"] = "130.0000"
    return row


def publication_review_row(values: Tuple[str, str, str, str, str, str, str, str]) -> Dict[str, str]:
    publication_id, decision, scope, category, eligible, tier, support, notes = values
    return {
        "publication_id": publication_id,
        "reviewed_by": "human_review",
        "review_time": REVIEW_TIME,
        "decision": decision,
        "canonical_scope": scope,
        "evidence_category": category,
        "recommendation_eligible": eligible,
        "authority_tier": tier,
        "audit_support_level": support,
        "notes": notes,
    }


def benchmark_review_row(spec: Dict[str, str]) -> Dict[str, str]:
    row = {field: "" for field in BENCHMARK_FIELDS}
    row.update(
        {
            "benchmark_id": spec["benchmark_id"],
            "canonical_flag": "true",
            "record_type": "benchmark",
            "source_record_id": spec["paper_doi"],
            "benchmark_name": spec["benchmark_name"],
            "benchmark_type": spec["benchmark_type"],
            "task": spec["task"],
            "modality": spec["modality"],
            "dataset": spec["dataset"],
            "tool_name": spec["tool_name"],
            "metric": spec["metric"],
            "metric_definition": spec["metric_definition"],
            "direction": spec["direction"],
            "rank_scope": spec["rank_scope"],
            "n_tools_compared": spec["n_tools_compared"],
            "paper_title": spec["paper_title"],
            "paper_doi": spec["paper_doi"],
            "source_url": spec["source_url"],
            "source_type": "paper",
            "result_text": spec["result_text"],
            "evaluation_protocol": spec["evaluation_protocol"],
            "extraction_method": "human_benchmark_review",
            "confidence": spec["confidence"],
            "trust_level": "trusted_core",
            "review_status": "human_reviewed",
            "reviewed_by": "human_review",
            "review_time": REVIEW_TIME,
            "kg_version": KG_VERSION,
            "notes": spec["notes"],
        }
    )
    row["decision"] = spec["decision"]
    row["recommendation_use_allowed_now"] = "true"
    return row


def ledger_row(values: Tuple[str, str, str, str]) -> Dict[str, str]:
    tool_name, issue_type, decision, notes = values
    return {
        "tool_name": tool_name,
        "issue_type": issue_type,
        "reviewer_decision": decision,
        "reviewer_notes": notes,
        "reviewed_by": "human_review",
        "review_time": REVIEW_TIME,
        "formal_ingest_allowed_now": "true" if decision in {"promote_anchor_manual", "extract_benchmark_fact"} else "false",
        "recommendation_use_allowed_now": "true" if decision in {"promote_anchor_manual", "extract_benchmark_fact"} else "false",
    }


def merge_by_id(
    existing_rows: List[Dict[str, str]],
    new_rows: List[Dict[str, str]],
    id_field: str,
    replace: bool = False,
) -> Tuple[List[Dict[str, str]], int, int]:
    merged = deepcopy(existing_rows)
    index = {row.get(id_field, ""): i for i, row in enumerate(merged) if row.get(id_field)}
    added = 0
    refreshed = 0
    for row in new_rows:
        key = row.get(id_field, "")
        if key in index:
            if replace:
                merged[index[key]] = row
                refreshed += 1
            continue
        merged.append(row)
        added += 1
    return merged, added, refreshed


def merge_ledger_rows(
    existing_rows: List[Dict[str, str]],
    new_rows: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], int, int]:
    merged = deepcopy(existing_rows)
    index = {
        (row.get("tool_name", ""), row.get("issue_type", "")): i
        for i, row in enumerate(merged)
        if row.get("tool_name") and row.get("issue_type")
    }
    added = 0
    refreshed = 0
    for row in new_rows:
        key = (row.get("tool_name", ""), row.get("issue_type", ""))
        if key in index:
            merged[index[key]] = row
            refreshed += 1
            continue
        merged.append(row)
        added += 1
    return merged, added, refreshed


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the human-reviewed next-batch evidence decisions.")
    parser.add_argument("--manual-anchors", type=Path, default=DEFAULT_MANUAL_ANCHORS)
    parser.add_argument("--publication-review", type=Path, default=DEFAULT_PUBLICATION_REVIEW)
    parser.add_argument("--benchmark-review", type=Path, default=DEFAULT_BENCHMARK_REVIEW)
    parser.add_argument("--next-ledger", type=Path, default=DEFAULT_NEXT_LEDGER)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    anchors, anchor_fields = read_tsv(args.manual_anchors)
    pub_review, pub_review_fields = read_tsv(args.publication_review)
    bench_review, bench_review_fields = read_tsv(args.benchmark_review)

    anchor_fields = anchor_fields or [*PUBLICATION_FIELDS, "group_size", "group_reason", "canonical_score"]
    pub_review_fields = pub_review_fields or [
        "publication_id",
        "reviewed_by",
        "review_time",
        "decision",
        "canonical_scope",
        "evidence_category",
        "recommendation_eligible",
        "authority_tier",
        "audit_support_level",
        "notes",
    ]
    bench_review_fields = bench_review_fields or [
        "benchmark_id",
        "reviewed_by",
        "review_time",
        "decision",
        "tool_name",
        "benchmark_name",
        "benchmark_type",
        "task",
        "modality",
        "dataset",
        "metric",
        "metric_definition",
        "direction",
        "score",
        "normalized_score",
        "rank",
        "rank_scope",
        "n_tools_compared",
        "result_text",
        "evaluation_protocol",
        "paper_title",
        "paper_doi",
        "paper_pmid",
        "source_url",
        "source_type",
        "confidence",
        "trust_level",
        "review_status",
        "recommendation_use_allowed_now",
        "notes",
    ]
    ledger_fields = [
        "tool_name",
        "issue_type",
        "reviewer_decision",
        "reviewer_notes",
        "reviewed_by",
        "review_time",
        "formal_ingest_allowed_now",
        "recommendation_use_allowed_now",
    ]

    new_anchor_rows = [publication_anchor_row(spec) for spec in PUBLICATION_ANCHORS]
    new_pub_review_rows = [publication_review_row(spec) for spec in PUBLICATION_REVIEW_ROWS]
    new_bench_review_rows = [benchmark_review_row(spec) for spec in BENCHMARK_ROWS]
    new_ledger_rows = [ledger_row(spec) for spec in LEDGER_ROWS]

    anchors, anchors_added, anchors_refreshed = merge_by_id(anchors, new_anchor_rows, "publication_id", replace=True)
    pub_review, pub_added, pub_refreshed = merge_by_id(pub_review, new_pub_review_rows, "publication_id", replace=True)
    bench_review, bench_added, bench_refreshed = merge_by_id(bench_review, new_bench_review_rows, "benchmark_id", replace=True)

    existing_ledger, _ = read_tsv(args.next_ledger)
    ledger_rows, ledger_added, ledger_refreshed = merge_ledger_rows(existing_ledger, new_ledger_rows)

    ensure_unique(anchors, "publication_id")
    ensure_unique(pub_review, "publication_id")
    ensure_unique(bench_review, "benchmark_id")

    if not args.dry_run:
        write_tsv(args.manual_anchors, anchors, anchor_fields)
        write_tsv(args.publication_review, pub_review, pub_review_fields)
        write_tsv(args.benchmark_review, bench_review, bench_review_fields)
        write_tsv(args.next_ledger, ledger_rows, ledger_fields)

    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "manual_anchors": {
                    "path": str(args.manual_anchors),
                    "added": anchors_added,
                    "refreshed": anchors_refreshed,
                    "rows": len(anchors),
                },
                "publication_review": {
                    "path": str(args.publication_review),
                    "added": pub_added,
                    "refreshed": pub_refreshed,
                    "rows": len(pub_review),
                },
                "benchmark_review": {
                    "path": str(args.benchmark_review),
                    "added": bench_added,
                    "refreshed": bench_refreshed,
                    "rows": len(bench_review),
                },
                "next_ledger": {
                    "path": str(args.next_ledger),
                    "added": ledger_added,
                    "refreshed": ledger_refreshed,
                    "rows": len(ledger_rows),
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
