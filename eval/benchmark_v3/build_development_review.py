#!/usr/bin/env python3
"""Build the 14 OFFLINE review drafts, not EvaluationCase or Gold records.

Run from the repository root: python -m eval.benchmark_v3.build_development_review
No imports of 07 services; no network, model calls, scientific analysis or promotion.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from difflib import SequenceMatcher
import json
import math
from pathlib import Path

from eval.benchmark_v3 import run_lane_alignment_audit as lanes
from eval.benchmark_v3.coverage_review import SOURCES, audit_scenario, digest, make_cell

BASE = Path(__file__).resolve().parent
VERSION = "sckg-development-review-v1"
REFERENCES = {
    "hvg-1.11.2": {
        "url": "https://raw.githubusercontent.com/scverse/scanpy/1.11.2/src/scanpy/preprocessing/_highly_variable_genes.py",
        "version": "Scanpy 1.11.2",
        "locator": "highly_variable_genes docstring and flavor branches",
    },
    "pca-1.11.2": {
        "url": "https://raw.githubusercontent.com/scverse/scanpy/1.11.2/src/scanpy/preprocessing/_pca/__init__.py",
        "version": "Scanpy 1.11.2",
        "locator": "pca signature, chunked branch and parameter docstrings",
    },
    "singler-book-3.21": {
        "url": "https://bioconductor.org/books/3.21/SingleRBook/classic-mode.html",
        "version": "Bioconductor 3.21 book",
        "locator": "sections 2.2, 2.4 and session information",
    },
}


def fact(key: str, question: str, *queries: str) -> dict:
    return {
        "fact_id": key,
        "requirement": question,
        "critical": True,
        "query_variants": list(queries),
        "expected_fact": None,
        "independent_reference_span_ids": [],
        "review_status": "needs_adjudication",
    }


def base_scenario(sid: str, track: str, family: str) -> dict:
    return {
        "schema_version": VERSION,
        "scenario_id": sid,
        "candidate_id": sid,
        "track": track,
        "family_id": family,
        "question_origin": "controlled-probe",
        "intended_split": "development",
        "split": None,
        "review_status": "needs_adjudication",
        "gold_status": "none",
        "gold_eligible": False,
        "requirements_review_status": "needs_adjudication",
        "scientific_applicability": "applicable",
        "source_seed_ids": [],
        "source_provenance": [],
        "raw_title_or_question": None,
        "added_context": [],
        "removed_context": [],
        "added_scientific_context": [],
        "transformation_history": [],
        "ambiguities": [],
        "construction_provenance": {
            "author_role": "08-engineering",
            "constructed_at": "2026-09-21",
            "method": "approved plan to review-only scenario",
            "generator_version": VERSION,
            "generator_path": "eval/benchmark_v3/build_development_review.py",
            "human_scientific_author": None,
        },
        "public_exposure": "project-authored-development-visible",
        "verbatim_overlap": None,
        "transformation_distance": None,
        "contamination_measurement": "token-SequenceMatcher-v1; descriptive, not decontamination",
        "memorization_risk": "unknown; familiar public API facts; development only",
        "selection_basis": "accepted-plan problem strata, independent of 07 outputs",
        "prior_07_debug_exposure": "unknown; development-only conservatively",
        "split_group_keys": [f"family:{family}"],
        "independent_reference_candidates": [],
        "user_context_and_state": [],
        "task_results": [],
        "proposed_scoring_checks": [],
        "human_review": {
            "reviewers": [],
            "00_resolution": None,
            "reference_claims": [],
            "expected_trajectory": None,
            "expected_response": None,
        },
    }


def attach_seed(row: dict, seed: dict) -> None:
    row["source_seed_ids"] = [seed["seed_id"]]
    row["raw_title_or_question"] = seed["question_text"]
    row["source_provenance"] = [
        {
            key: seed[key]
            for key in (
                "seed_id",
                "source",
                "provenance",
                "license_or_access_policy",
                "pii_redaction_status",
                "thread_context",
            )
        }
    ]
    row["split_group_keys"].append("seed:" + seed["seed_id"])
    a, b = (
        seed["question_text"].casefold().split(),
        row["draft_query"].casefold().split(),
    )
    overlap = SequenceMatcher(None, a, b, autojunk=False).ratio()
    row["verbatim_overlap"] = round(overlap, 6)
    row["transformation_distance"] = round(1 - overlap, 6)


def scenarios(seeds: dict, old: dict) -> list[dict]:
    rows = []
    pairs = [
        (
            "K01-hvg-input",
            "input-method-fit",
            "matrix_state",
            ["raw_integer_counts", "library_normalized_log1p"],
            {
                "package": "Scanpy 1.11.2",
                "flavor": "seurat_v3",
                "n_top_genes": 2000,
                "matrix_shape": [3000, 12000],
                "batch_key": None,
            },
            "我想用给定 flavor 选择高变基因；当前矩阵能否直接作为输入？说明适用条件及必要的下一步，不假设存在未提供的 counts 层。",
            [
                fact(
                    "hvg-input",
                    "该版本/该 flavor 对输入尺度的要求是什么？",
                    "highly_variable_genes seurat_v3 counts",
                    "HVG flavor input log normalized",
                )
            ],
            ["hvg-1.11.2"],
        ),
        (
            "K02-pca-chunked",
            "version-condition-boundary",
            "chunked",
            [False, True],
            {
                "package": "Scanpy 1.11.2",
                "matrix": "dense log-normalized expression, 500 cells x 100 genes",
                "zero_center": False,
                "svd_solver": "arpack",
                "n_comps": 10,
                "chunk_size": 100,
            },
            "调用 sc.pp.pca 时，给定 zero_center 和 svd_solver 是否会按我的设定生效？请说明实现条件；不需要执行。",
            [
                fact(
                    "pca-conditions",
                    "chunked 对算法以及 zero_center/svd_solver 生效条件的影响是什么？",
                    "pca chunked zero_center svd_solver",
                    "incremental PCA ignored parameters",
                )
            ],
            ["pca-1.11.2"],
        ),
        (
            "K03-reference-annotation",
            "multi-fact-composition",
            "reference_gene_namespace",
            ["Ensembl stable IDs", "HGNC symbols"],
            {
                "environment": "Bioconductor 3.21 / version must be checked against book session",
                "species": "human for both test and reference",
                "test_gene_namespace": "Ensembl stable IDs",
                "test_assay": "UMI counts",
                "reference_assay": "log-normalized expression",
                "marker_mode": "classic",
                "mapping_table_provided": False,
            },
            "我想用 SingleR classic mode 给测试细胞做参考注释。输入尺度与基因对应关系是否足以直接开始？哪些条件应先验证？",
            [
                fact(
                    "reference-input",
                    "classic marker 模式对参考和测试表达矩阵分别有什么要求？",
                    "SingleR classic reference log transformed test counts",
                    "SingleR choices assay data",
                ),
                fact(
                    "gene-correspondence",
                    "测试和参考的特征标识需怎样对应，哪些映射检查不可省略？",
                    "SingleR gene annotation ensembl symbols",
                    "reference test common genes identifiers",
                ),
            ],
            ["singler-book-3.21"],
        ),
        (
            "K04-evidence-version",
            "evidence-conclusion-strength",
            "installed_version",
            ["1.11.2", None],
            {
                "package": "Scanpy",
                "documentation_version": "1.11.2",
                "operation": "sc.pp.pca",
                "parameter_under_review": "mask_var",
                "execution_requested": False,
            },
            "我查到 1.11.2 文档中的 PCA mask_var 参数。这能否支撑针对当前环境的可执行参数建议？请限定能由文档支持的结论，并指出还需核实什么。",
            [
                fact(
                    "versioned-api",
                    "文档版本中的参数定义及版本适用边界是什么？",
                    "pca mask_var version 1.11.2",
                    "Scanpy PCA parameter version compatibility",
                )
            ],
            ["pca-1.11.2"],
        ),
    ]
    for family, stratum, changed, values, fixed, query, facts, refs in pairs:
        for suffix, value in zip(("a", "b"), values):
            row = base_scenario(f"dev-{family}-{suffix}", "K", family)
            row.update(
                stratum=stratum,
                draft_query=query,
                scientific_conditions={**fixed, changed: value},
                contrast={
                    "changed_field": changed,
                    "value": value,
                    "evaluation": "both variants scientifically correct and condition-sensitive; not text difference",
                },
                required_scientific_facts=facts,
                independent_reference_candidates=[REFERENCES[r] for r in refs],
            )
            row["added_scientific_context"] = [
                {
                    "origin": "benchmark_author_constructed_not_original_user",
                    "values": row["scientific_conditions"],
                    "status": "needs_expert_review",
                }
            ]
            row["user_context_and_state"] = [
                {
                    "name": key,
                    "status": "missing" if val is None else "provided",
                    "value": val,
                }
                for key, val in row["scientific_conditions"].items()
            ]
            row["task_results"] = [
                "condition-specific assessment and justified next action, no computed result required"
            ]
            row["ambiguities"] = [
                "独立来源的精确 span、版本适用性、关键事实与可接受结论待两人审核。"
            ]
            row["proposed_scoring_checks"] = [
                "回答核心决策",
                "关键条件匹配",
                "无重大科学错误",
                "条件改变引起正确而非仅措辞不同的响应",
            ]
            row["transformation_history"] = [
                {
                    "operation": "author_single_condition_variant",
                    "changed_field": changed,
                    "basis": "accepted plan development examples, not KG statements or 07 success/failure",
                }
            ]
            if family == "K04-evidence-version":
                attach_seed(row, seeds["controlled:evidence-version-conflict"])
            rows.append(row)

    # Selection is fixed by four problem types; no clustering ranking or model outputs.
    for number, cid, problem, required, missing, unnecessary in [
        (
            1,
            "candidate-pilot-08",
            "normalization-correction-anomaly",
            fact(
                "sct-semantics",
                "SCT model/correction 状态及计数输出的适用语义是什么？",
                "PrepSCTFindMarkers correct_counts SCT",
                "SCT recorrection median UMI zero counts",
            ),
            [
                "Seurat/sctransform versions",
                "minimal correction call and model/assay state",
                "small anonymized before/after example",
            ],
            ["full private patient dataset", "unrelated visualization settings"],
        ),
        (
            2,
            "candidate-pilot-13",
            "reproducibility",
            fact(
                "rng-semantics",
                "该函数路径涉及哪些随机性与环境条件，哪些重现保证有依据？",
                "RunUMAP RunPCA seed threads uwot",
                "UMAP reproducibility random state parallel",
            ),
            [
                "versions including uwot",
                "exact call and seed/thread settings",
                "whether input and prior state are identical",
            ],
            ["patient identifiers", "all project files"],
        ),
        (
            3,
            "candidate-pilot-14",
            "plotting-api-error",
            fact(
                "plot-api",
                "paga 的多 color 与 cax 调用适用条件是什么？",
                "scanpy pl paga cax colors",
                "paga multiple colors axes TypeError",
            ),
            [
                "Scanpy/matplotlib versions",
                "minimal call and complete exception",
                "number/type of color entries and axes construction",
            ],
            ["complete expression matrix before testing a plotting reproducer"],
        ),
        (
            4,
            "candidate-pilot-15",
            "raw-variable-alignment",
            fact(
                "raw-alignment",
                "use_raw 路径中矩阵和基因元数据的对齐要求是什么？",
                "calculate_qc_metrics use_raw var",
                "AnnData raw var_names alignment QC metrics",
            ),
            [
                "Scanpy/AnnData versions",
                "minimal call",
                "raw.var_names versus var_names dimensions/order",
            ],
            ["patient identifiers", "unrelated cluster labels"],
        ),
    ]:
        candidate = old[cid]
        seed = seeds[candidate["source_seed_ids"][0]]
        row = base_scenario(f"dev-O{number:02d}", "O", problem)
        row.update(
            question_origin="real-user",
            draft_query=seed["question_text"] + "\n请帮助我判断下一步应该怎么排查。",
            required_scientific_facts=[required],
            public_exposure="public-source",
            memorization_risk="high; public issue title; rewrite is not decontamination",
            problem_type=problem,
            source_candidate_id=cid,
        )
        attach_seed(row, seed)
        row["user_context_and_state"] = [
            {"name": name, "status": "missing", "necessity": "proposed_needs_review"}
            for name in missing
        ]
        row["task_results"] = [
            "useful bounded triage; distinguish hypotheses from established causes"
        ]
        row["proposed_scoring_checks"] = {
            "necessary_information": missing,
            "unnecessary_requests": unnecessary,
            "useful_response": "explain prioritized minimal checks; no generic refusal; do not assert a confirmed bug/fix",
        }
        row["added_context"] = [
            {
                "origin": "benchmark_author",
                "text": "Explicit request for next-step triage; no technical facts added.",
            }
        ]
        row["transformation_history"] = [
            {
                "operation": "title_to_triage_request",
                "source_seed_id": seed["seed_id"],
                "no_version_reproducer_or_answer_invented": True,
            }
        ]
        row["ambiguities"] = [
            "仅 title；不具备诊断结论。必要信息清单是审核提案，不是用户原话或 Gold。",
            "对应版本官方文档/独立 reproducer 的来源和精确 span 待审核。",
        ]
        rows.append(row)

    row = base_scenario("dev-W01", "W", "workflow-hvg-layer-choice")
    row.update(
        stratum="knowledge_sensitive_workflow",
        draft_query="使用 fixture 中的数据为 seurat_v3 选择 8 个高变基因，先提出输入层和计划，再在明确批准后执行并验证产物。不要据小型 synthetic fixture 作生物学结论。",
        required_scientific_facts=[
            fact(
                "workflow-hvg-input",
                "HVG seurat_v3 的输入层条件是什么？",
                "seurat_v3 highly variable genes counts",
                "HVG log normalized input requirements",
            )
        ],
        independent_reference_candidates=[REFERENCES["hvg-1.11.2"]],
        fixture_id="hvg-layer-choice",
    )
    row["added_scientific_context"] = [
        {
            "origin": "benchmark_author_constructed",
            "package_proposal": "Scanpy 1.11.2",
            "flavor": "seurat_v3",
            "n_top_genes": 8,
            "fixture": "small synthetic counts and transformed layer; not biological ground truth",
        }
    ]
    row["user_context_and_state"] = [
        {"name": "synthetic matrix/layer provenance", "status": "provided_in_fixture"},
        {
            "name": "shared execution interface, frozen environment and plan approval",
            "status": "pending_preflight",
        },
    ]
    row["task_results"] = [
        "valid approved plan; selected input layer",
        "8 unique feature IDs and selection statistics",
        "content, scientific validity and clean rerun checks",
    ]
    row["proposed_scoring_checks"] = [
        "correct input layer",
        "required approval respected",
        "independent result and artifact checks; exit 0 insufficient",
    ]
    row["ambiguities"] = [
        "Small synthetic fixture suitability, dependencies, tolerances and independent reference script require expert review."
    ]
    row["split_group_keys"].append("fixture:hvg-layer-choice")
    row["transformation_history"] = [
        {
            "operation": "author_synthetic_workflow",
            "not_a_real_user_or_paper_task": True,
        }
    ]
    rows.append(row)
    row = base_scenario("dev-W02", "W", "workflow-shared-artifact-validation")
    row.update(
        stratum="shared_runtime_control",
        scientific_applicability="not_applicable",
        draft_query="上一步进程退出码是 0，但 genes.tsv 只有表头，没有数据行。任务要求为输入的每个基因输出一行。请判断是否完成，检查产物并提出需要批准的后续动作；不要宣称已修复。",
        required_scientific_facts=[],
        fixture_id="empty-artifact",
    )
    attach_seed(row, seeds["controlled:validation-empty-artifact"])
    row["added_context"] = [
        {
            "origin": "benchmark_author",
            "text": "header-only genes.tsv; per-input-gene output contract; explicit unapproved repair state",
        }
    ]
    row["user_context_and_state"] = [
        {
            "name": "input gene IDs, process exit status and artifact bytes",
            "status": "provided_in_fixture",
        },
        {"name": "approval to repair", "status": "not_granted"},
    ]
    row["task_results"] = [
        "content-aware task completion decision",
        "bounded recovery plan without unauthorized execution",
    ]
    row["proposed_scoring_checks"] = [
        "nonempty semantic output",
        "per-gene identity/row coverage",
        "do not equate exit code with completion",
        "approval boundary",
    ]
    row["ambiguities"] = [
        "Shared runtime control, no KG-exclusive knowledge claim; final trajectory rubric pending."
    ]
    row["split_group_keys"].append("fixture:empty-artifact")
    row["transformation_history"] = [
        {
            "operation": "controlled_probe_to_artifact_fixture",
            "source_seed_id": row["source_seed_ids"][0],
        }
    ]
    rows.append(row)
    for row in rows:
        if row["track"] == "W":
            row["execution_status"] = "not_run"
        # This is the exact input contract for later EvaluationCase.input.
        row["input"] = {
            "query": row["draft_query"],
            "conditions": row.get("scientific_conditions", {}),
            "fixture_id": row.get("fixture_id"),
        }
        row["required_scientific_facts"] = json.loads(
            json.dumps(row["required_scientific_facts"])
        )
        for requirement in row["required_scientific_facts"]:
            requirement["scenario_conditions"] = row["input"]["conditions"]
    return rows


def fixtures() -> dict:
    counts = [[(17 * i + 11 * j + i * j) % 23 for j in range(32)] for i in range(64)]
    normalized = [
        [round(math.log1p(v * 10000 / sum(row)), 10) for v in row] for row in counts
    ]
    return {
        "schema_version": "sckg-review-fixtures-v1",
        "status": "synthetic_engineering_only_needs_review",
        "hvg-layer-choice": {
            "generator": "mod23-v1; deterministic, no random provider",
            "gene_ids": [f"gene_{j:02d}" for j in range(32)],
            "counts": counts,
            "X": normalized,
            "X_transformation": "log1p(count * 10000 / cell_total), rounded 10 decimals",
            "expected_biological_answer": None,
            "execution_status": "not_run",
        },
        "empty-artifact": {
            "input_gene_ids": ["gene_a", "gene_b", "gene_c"],
            "exit_code": 0,
            "artifact_name": "genes.tsv",
            "artifact_bytes_utf8": "gene\tvalue\n",
            "repair_approved": False,
        },
    }


def prompt_inventory() -> list[dict]:
    path = "agent/research_chat_reasoner.py"
    raw = lanes.git_blob(lanes.INTEGRATION_COMMIT, path)
    tree = ast.parse(raw.decode())
    result = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any("prompt" in name.casefold() for name in names):
                result.append(
                    {
                        "names": names,
                        "path": path,
                        "line": node.lineno,
                        "sha256": lanes.sha256(node.value.value.encode()),
                        "file_sha256": lanes.sha256(raw),
                    }
                )
    return sorted(result, key=lambda item: item["line"])


def manifest(rows: list[dict], fixture: dict, lane_manifest: dict) -> dict:
    return {
        "schema_version": "sckg-run-plan-sidecar-v1",
        "status": "not_run_awaiting_00_review",
        "implementation_commit": lanes.INTEGRATION_COMMIT,
        "lane_manifest_digest": digest(lane_manifest),
        "scenario_digest": digest(rows),
        "fixture_digest": digest(fixture),
        "target_design": {
            "total_scenarios": 50,
            "independent_families": 34,
            "development": {"K": 8, "O": 4, "W": 2},
            "evaluation_not_created": {"K": 24, "O": 8, "W": 4},
            "K_strata_families": {
                "input-method-fit": 4,
                "version-condition-boundary": 4,
                "multi-fact-composition": 4,
                "evidence-conclusion-strength": 4,
            },
            "W_final_design": {"knowledge_sensitive": 3, "shared_runtime_control": 3},
        },
        "runtime_configuration": {
            "model": None,
            "provider": None,
            "model_revision": None,
            "temperature": None,
            "output_budget": None,
            "total_call_budget": None,
            "token_budget": None,
            "wall_time_limit": None,
            "environment_digest": None,
            "repetitions_proposed": 3,
            "scheduling_seed_proposed": 20260921,
            "schedule": "randomized interleaved paired blocks; isolated sessions and fresh W fixture copies",
            "provider_seed": None,
            "seed_support": "must_observe; not assumed deterministic",
        },
        "prompt_inventory": prompt_inventory(),
        "prompt_policy": "product lane prompts/handling differ; hash actual rendered messages per call including support checks",
        "runtime_receipt_schema": "runtime_receipt.schema.json",
        "observed_calls": [],
        "observed_runs": [],
        "shared_runtime": lane_manifest["shared_runtime"],
        "gate_requirements": [
            "two independent scientific reviews and 00 disagreements resolved",
            "independent source spans and versions frozen",
            "scorer calibrated on reviewed examples",
            "family/source/near-duplicate split audit",
            "model/provider/resource budgets frozen",
            "explicit authorization for formal lane runs",
            "W shared interface + environment + artifact evaluators verified",
        ],
        "W_if_interface_not_shared": "not_run with reason; no alternate wider capability",
        "mechanism_experiments": [
            {
                "id": "same-evidence-representation",
                "track": "K",
                "status": "not_run",
                "variable": "structured relations versus lossless prose serialization",
                "fixed": [
                    "identical reviewer-selected evidence IDs, exact excerpts, sources, versions, conditions, cautions",
                    "common synthesis prompt, provider, model, output budget, validation and execution safety",
                ],
                "preflight": "reviewer verifies bidirectional fact/edge/qualifier preservation; no context truncation",
                "not_product_generic_rag": True,
            },
            {
                "id": "explicit-scope-filter",
                "track": "K applicable subset",
                "status": "not_run",
                "variable": "explicit applicability filter on/off only",
                "preserved": [
                    "original condition text",
                    "authority flags",
                    "shared execution safety",
                ],
                "analysis": "condition-misapplication, separate from representation contrast and product scores",
            },
        ],
        "reporting": {
            "primary": ["scientific_kg - generic_rag", "scientific_kg - legacy_kg"],
            "supplemental": "scientific_kg - llm_only",
            "unit": "independent family, repeats aggregated within family",
            "interval": "paired family bootstrap within track; preserve condition pairs and repetitions",
            "composite_score": False,
            "pilot_not_general_scientific_proof": True,
        },
        "existing_models": {
            "scenario": "EvaluationCase after approval only; metadata stores origin/track/family/coverage",
            "reference": "ReferenceClaim from independent reviewed source spans",
            "trajectory": "ExpectedTrajectory after review",
            "run": "EvaluationRunRecord",
            "experiment": "ExperimentManifest at execution, not a fake started experiment now",
            "failure": "FailureAttribution native stage + nine-stage reporting sidecar",
            "open_world": "NaturalQueryCase official_issue only after reviewing action/blockers; gold_status=none stays sidecar-only",
            "metrics": "EvaluatorResult via eval/evaluation_evaluators.py; preserve not_run/not_applicable denominators",
        },
    }


def packet(rows: list[dict]) -> str:
    lines = [
        "# 14 个 development 意向场景：00 人工审核包",
        "",
        "状态：全部 needs_adjudication / gold_status=none。尚无正式 split、Gold、模型回答或成绩。",
        "每题需两人独立核实原始来源、科学条件和评分规约；分歧交 00。新增上下文显式标注。",
        "旧 20 条 coverage 均已撤回为 unknown；本包不继承任何旧 signature。",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row['scenario_id']} — {row['track']} / {row['family_id']}",
                "",
                "| 审核字段 | 内容 |",
                "| --- | --- |",
            ]
        )
        for key in (
            "source_seed_ids",
            "question_origin",
            "raw_title_or_question",
            "source_provenance",
            "transformation_history",
            "added_context",
            "removed_context",
            "added_scientific_context",
            "draft_query",
            "scientific_conditions",
            "input",
            "fixture_id",
            "construction_provenance",
            "ambiguities",
            "required_scientific_facts",
            "user_context_and_state",
            "task_results",
            "independent_reference_candidates",
            "proposed_scoring_checks",
            "public_exposure",
            "verbatim_overlap",
            "transformation_distance",
            "memorization_risk",
            "split_group_keys",
            "human_review",
        ):
            lines.append(f"| {key} | {lanes.md(row.get(key))} |")
        lines.extend(
            [
                "",
                "人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare generated artifacts without writing",
    )
    args = parser.parse_args()
    seeds = {s["seed_id"]: s for s in lanes.read_jsonl(BASE / "raw_seeds_pilot.jsonl")}
    old = {
        c["candidate_id"]: c
        for c in lanes.read_jsonl(BASE / "candidate_scenarios_pilot.jsonl")
    }
    rows, fixture = scenarios(seeds, old), fixtures()
    source = lanes.load_and_verify_sources()
    lm = lanes.lane_manifest(source)
    snapshots = lanes.coverage_snapshot(lm)["sources"]
    inventories, _, _ = lanes.source_records(source)
    registry = {s: {r["id"]: r for r in inventories[s]} for s in SOURCES}
    cells, summaries = [], []
    for row in rows:
        own = []
        for requirement in row["required_scientific_facts"]:
            for s in SOURCES:
                search = {
                    **lanes.scan(inventories[s], requirement["query_variants"]),
                    "query_variants": requirement["query_variants"],
                    "procedure": "lexical full-inventory scan; no absence/presence inference",
                    "record_inventory_digest": digest(registry[s]),
                    "records_resolvable_via": "run_lane_alignment_audit.source_records(load_and_verify_sources())",
                }
                cell = make_cell(
                    row["scenario_id"], requirement, s, snapshots[s], search
                )
                cell["scenario_input_digest"] = digest(row["input"])
                own.append(cell)
        cells.extend(own)
        summaries.append(
            {
                "scenario_id": row["scenario_id"],
                **audit_scenario(row, own, snapshots, registry),
            }
        )
    outputs = {
        "development_scenarios.jsonl": "".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows
        ),
        "development_coverage_review_template.jsonl": "".join(
            json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cells
        ),
        "development_coverage_summary.json": summaries,
        "development_review_packet.md": packet(rows),
        "development_fixtures.json": fixture,
        "run_manifest.json": manifest(rows, fixture, lm),
    }
    for name, value in outputs.items():
        content = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        path = BASE / name
        if args.check:
            if not path.is_file() or path.read_text() != content:
                raise ValueError(f"stale generated artifact: {name}")
        else:
            path.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "offline_review_packet_ready",
                "scenarios": len(rows),
                "tracks": dict(Counter(r["track"] for r in rows)),
                "coverage_cells": len(cells),
                "human_coverage_decisions": 0,
                "gold_created": 0,
                "lane_runs": 0,
                "check_only": args.check,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
