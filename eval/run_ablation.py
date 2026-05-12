import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.constraints import normalize_constraints, parse_research_constraints
from core.llm_client import get_llm
from core.models import (
    EvidenceBundle,
    MigrationPath,
    PredictionRecord,
    ScoredTool,
    ToolCandidate,
    derived_evidence,
)
from core.settings import get_settings
from engine.semantic_hallucination_auditor import audit_report
from engine.workflow_recommender import build_minimal_workflow_recommendation
from eval.generate_predictions import (
    _build_fallback_migrations,
    _build_final_report,
    _apply_migration_intent_to_constraints,
    _choose_recommendation_type,
    _combine_evidence,
    _find_tool_candidates,
    _filter_blocked_tool_outputs,
    _generate_with_agent,
    _filter_blocked_migration_paths,
    _mark_needs_clarification,
    _migration_gate,
    _missing_components,
    _recommended_tool_names,
    _score_candidates,
    _visible_outputs,
    load_gold_queries,
    write_predictions,
)
from eval.run_eval import run_constraint_eval


ABLATION_MODES = (
    "pure_llm",
    "evidence_gate",
    "evidence_gate_auditor",
    "full_kg_pipeline",
)


def run_ablation(
    gold_path: Path,
    output_dir: Path,
    modes: Iterable[str],
    limit: Optional[int] = None,
    blind_migration: bool = False,
) -> Dict[str, Any]:
    modes = list(modes)
    records = load_gold_queries(gold_path)
    if limit is not None:
        records = records[:limit]
    output_dir.mkdir(parents=True, exist_ok=True)
    eval_gold_path = gold_path
    if limit is not None:
        eval_gold_path = output_dir / "gold_subset.jsonl"
        with eval_gold_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    settings = get_settings()
    model_name = settings.model_name or settings.extract_model
    summary: Dict[str, Any] = {
        "model_name": model_name,
        "chat_api_base": settings.openai_api_base or settings.chat_api_base,
        "gold_path": str(gold_path),
        "eval_gold_path": str(eval_gold_path),
        "query_count": len(records),
        "modes": {},
    }
    shared_evidence_constraints = _build_shared_evidence_constraints(records, modes)

    for mode in modes:
        if mode not in ABLATION_MODES:
            raise ValueError(f"Unknown ablation mode: {mode}")
        prediction_path = output_dir / f"predictions_{mode}.jsonl"
        print(f"== {mode} ==")
        started = time.perf_counter()
        predictions: List[PredictionRecord] = []
        latencies: List[float] = []
        for index, record in enumerate(records, start=1):
            print(f"[{index}/{len(records)}] {record['id']}")
            q_started = time.perf_counter()
            predictions.append(
                generate_ablation_prediction(
                    record,
                    mode,
                    shared_evidence_constraints.get(record["id"]),
                    blind_migration=blind_migration,
                )
            )
            latencies.append(time.perf_counter() - q_started)
        write_predictions(predictions, prediction_path)
        eval_report = run_constraint_eval(eval_gold_path, prediction_path)
        elapsed = time.perf_counter() - started
        summary["modes"][mode] = {
            "prediction_path": str(prediction_path),
            "elapsed_seconds": round(elapsed, 3),
            "mean_latency_seconds": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "metrics": {
                name: metric.model_dump(mode="json")
                for name, metric in eval_report.metrics.items()
            },
        }

    summary_path = output_dir / "ablation_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary_table(summary, output_dir / "ablation_summary.tsv")
    print(f"wrote ablation summary to {summary_path}")
    return summary


def _build_shared_evidence_constraints(
    records: List[Dict[str, Any]],
    modes: Iterable[str],
) -> Dict[str, Dict[str, Any]]:
    mode_set = set(modes)
    if not {"evidence_gate", "evidence_gate_auditor"}.issubset(mode_set):
        return {}
    shared: Dict[str, Dict[str, Any]] = {}
    print("== shared evidence-gate constraint parsing ==")
    for index, record in enumerate(records, start=1):
        print(f"[{index}/{len(records)}] {record['id']}")
        shared[record["id"]] = _parse_evidence_gate_constraints(record)
    return shared


def _parse_evidence_gate_constraints(record: Dict[str, Any]) -> Dict[str, Any]:
    user_query = record["query"]
    errors: List[str] = []
    raw_payload: Dict[str, Any] = {}
    if _offline_llm_enabled():
        errors.append("constraint_llm_skipped: offline_llm_enabled")
    else:
        try:
            raw_payload = _call_llm_json(_constraint_only_prompt(user_query))
        except Exception as exc:
            errors.append(f"constraint_llm_failed: {exc}")
    constraints = parse_research_constraints(raw_payload, user_query=user_query)
    return {
        "constraints": constraints.model_dump(mode="json"),
        "errors": errors,
    }


def summarize_existing_ablation(
    gold_path: Path,
    output_dir: Path,
    modes: Iterable[str],
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Rebuild ablation metrics from existing prediction files without model/KG calls."""
    output_dir.mkdir(parents=True, exist_ok=True)
    eval_gold_path = _resolve_eval_gold_path(gold_path, output_dir, limit)
    records = load_gold_queries(eval_gold_path)

    settings = get_settings()
    previous_summary = _load_previous_summary(output_dir / "ablation_summary.json")
    summary: Dict[str, Any] = {
        "model_name": settings.model_name or settings.extract_model,
        "chat_api_base": settings.openai_api_base or settings.chat_api_base,
        "gold_path": str(gold_path),
        "eval_gold_path": str(eval_gold_path),
        "query_count": len(records),
        "summary_mode": "from_existing_predictions",
        "modes": {},
    }

    missing_prediction_files: List[str] = []
    for mode in modes:
        if mode not in ABLATION_MODES:
            raise ValueError(f"Unknown ablation mode: {mode}")
        prediction_path = output_dir / f"predictions_{mode}.jsonl"
        if not prediction_path.exists():
            missing_prediction_files.append(str(prediction_path))
            continue

        eval_report = run_constraint_eval(eval_gold_path, prediction_path)
        previous_mode = previous_summary.get("modes", {}).get(mode, {})
        summary["modes"][mode] = {
            "prediction_path": str(prediction_path),
            "elapsed_seconds": previous_mode.get("elapsed_seconds"),
            "mean_latency_seconds": previous_mode.get("mean_latency_seconds"),
            "metrics": {
                name: metric.model_dump(mode="json")
                for name, metric in eval_report.metrics.items()
            },
        }

    if missing_prediction_files:
        summary["missing_prediction_files"] = missing_prediction_files

    summary_path = output_dir / "ablation_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary_table(summary, output_dir / "ablation_summary.tsv")
    print(f"rebuilt ablation summary from existing predictions: {summary_path}")
    if missing_prediction_files:
        print("missing prediction files:")
        for item in missing_prediction_files:
            print(f"- {item}")
    return summary


def _resolve_eval_gold_path(gold_path: Path, output_dir: Path, limit: Optional[int]) -> Path:
    existing_subset = output_dir / "gold_subset.jsonl"
    if existing_subset.exists():
        return existing_subset
    if limit is None:
        return gold_path
    records = load_gold_queries(gold_path)[:limit]
    with existing_subset.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return existing_subset


def _load_previous_summary(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def generate_ablation_prediction(
    record: Dict[str, Any],
    mode: str,
    shared_constraints: Optional[Dict[str, Any]] = None,
    blind_migration: bool = False,
) -> PredictionRecord:
    if mode == "full_kg_pipeline":
        data = _generate_with_agent(record, blind_migration=blind_migration).model_dump(mode="json")
        data["execution_mode"] = "full_kg_pipeline"
        return PredictionRecord.model_validate(data)
    if mode == "pure_llm":
        return _generate_pure_llm(record)
    if mode == "evidence_gate":
        return _generate_evidence_gate(
            record,
            audit=False,
            shared_constraints=shared_constraints,
            blind_migration=blind_migration,
        )
    if mode == "evidence_gate_auditor":
        return _generate_evidence_gate(
            record,
            audit=True,
            shared_constraints=shared_constraints,
            blind_migration=blind_migration,
        )
    raise ValueError(f"Unknown ablation mode: {mode}")


def _generate_pure_llm(record: Dict[str, Any]) -> PredictionRecord:
    query_id = record["id"]
    user_query = record["query"]
    errors: List[str] = []
    raw_payload: Dict[str, Any] = {}
    if _offline_llm_enabled():
        errors.append("pure_llm_skipped: offline_llm_enabled")
    else:
        try:
            raw_payload = _call_llm_json(_pure_llm_prompt(user_query))
        except Exception as exc:
            errors.append(f"pure_llm_failed: {exc}")

    constraints = parse_research_constraints(
        raw_payload.get("parsed_constraints", {}),
        user_query=user_query,
    )
    constraints_dict = constraints.model_dump(mode="json")
    constraints_dict = _apply_migration_intent_to_constraints(constraints_dict, user_query)
    recommendation_type = _normalize_recommendation_type(
        raw_payload.get("recommendation_type")
        or _choose_recommendation_type(constraints_dict, user_query)
    )
    recommended_tools = _as_string_list(raw_payload.get("recommended_tools"))
    final_report = _as_string(raw_payload.get("final_report")) or _fallback_report(
        mode="pure_llm",
        constraints=constraints_dict,
        recommendation_type=recommendation_type,
        recommended_tools=recommended_tools,
    )
    hallucination_audit = audit_report(
        final_report=final_report,
        evidence_bundle=EvidenceBundle(),
        scored_tools=[],
        candidate_tools=[],
        migration_paths=[],
        workflow_recommendation=None,
    )

    return PredictionRecord(
        id=query_id,
        query_id=query_id,
        user_query=user_query,
        parsed_constraints=constraints_dict,
        candidate_tools=[],
        scored_tools=[],
        migration_paths=[],
        recommendation_type=recommendation_type,
        recommendation_kind=recommendation_type,
        evidence_bundle=EvidenceBundle(),
        workflow_recommendation=None,
        final_report=final_report,
        missing_components=["no_structured_evidence_gate", "no_semantic_audit"],
        clarification_needed=constraints.needs_human_clarification,
        execution_status="partial" if errors else "ok",
        execution_mode="pure_llm",
        candidate_tool_count=0,
        scored_tool_count=0,
        migration_path_count=0,
        output_truncated=False,
        recommended_tools=recommended_tools[:20],
        evidence_coverage=0.0,
        workflow_steps=[],
        claim_count=hallucination_audit.claim_count,
        unsupported_claims=hallucination_audit.unsupported_claim_count,
        semantic_hallucination_rate=hallucination_audit.hallucination_rate,
        hallucination_audit=hallucination_audit.model_dump(mode="json"),
        errors=errors,
    )


def _generate_evidence_gate(
    record: Dict[str, Any],
    audit: bool,
    shared_constraints: Optional[Dict[str, Any]] = None,
    blind_migration: bool = False,
) -> PredictionRecord:
    query_id = record["id"]
    user_query = record["query"]
    errors: List[str] = []
    if shared_constraints is None:
        shared_constraints = _parse_evidence_gate_constraints(record)
    errors.extend(shared_constraints.get("errors", []))
    constraints_dict = shared_constraints.get("constraints", {})
    constraints = parse_research_constraints(constraints_dict, user_query=user_query)
    constraints_dict = constraints.model_dump(mode="json")
    constraints_dict = _apply_migration_intent_to_constraints(constraints_dict, user_query)
    recommendation_type = _choose_recommendation_type(
        constraints=constraints_dict,
        user_query=user_query,
    )
    migration_gate = _migration_gate(user_query, constraints_dict, recommendation_type)
    if migration_gate["recommendation_type"]:
        recommendation_type = migration_gate["recommendation_type"]
    if migration_gate["needs_clarification"]:
        constraints_dict = _mark_needs_clarification(
            constraints_dict,
            migration_gate["reasons"],
        )

    tool_candidates: List[ToolCandidate] = []
    scored_tools: List[ScoredTool] = []
    migration_paths: List[MigrationPath] = []
    workflow = None
    try:
        tool_candidates = _find_tool_candidates(constraints_dict, user_query=user_query)
        tool_candidates, scored_tools = _filter_blocked_tool_outputs(
            tool_candidates,
            scored_tools,
            migration_gate["blocked_tools"],
        )
    except Exception as exc:
        errors.append(f"candidate_retrieval_failed: {exc}")

    if recommendation_type in {"ranked_tools", "workflow", "evidence_chain"}:
        try:
            scored_tools = _score_candidates(tool_candidates, constraints_dict)
            tool_candidates, scored_tools = _filter_blocked_tool_outputs(
                tool_candidates,
                scored_tools,
                migration_gate["blocked_tools"],
            )
        except Exception as exc:
            errors.append(f"mcdm_scoring_failed: {exc}")

    if (recommendation_type == "migration" or not tool_candidates) and migration_gate["allow_migration"]:
        migration_paths = _build_fallback_migrations(
            constraints_dict,
            tool_candidates,
            expected_source_tools=None if blind_migration else record.get("expected_source_tools"),
        )
        migration_paths = _filter_blocked_migration_paths(
            migration_paths,
            migration_gate["blocked_tools"],
        )

    ranked_tool_names = [tool.tool_name for tool in scored_tools]
    candidate_tool_names = [candidate.tool_name for candidate in tool_candidates]
    if recommendation_type in {"workflow", "evidence_chain"}:
        workflow = build_minimal_workflow_recommendation(
            constraints_dict,
            candidate_tools=(ranked_tool_names or candidate_tool_names)[:3],
        )

    visible_candidates, visible_scored, visible_migrations = _visible_outputs(
        tool_candidates=tool_candidates,
        scored_tools=scored_tools,
        migration_paths=migration_paths,
    )
    evidence_bundle = _combine_evidence(
        tool_candidates=visible_candidates,
        scored_tools=visible_scored,
        migration_paths=visible_migrations,
        workflow=workflow,
    )
    missing_components = _missing_components(
        constraints_dict=constraints_dict,
        evidence_bundle=evidence_bundle,
        workflow=workflow,
        recommendation_type=recommendation_type,
        candidate_count=len(tool_candidates),
        scored_count=len(scored_tools),
    )
    missing_components.extend(migration_gate["missing_components"])
    missing_components = sorted(set(missing_components))
    final_report = _build_final_report(
        constraints=constraints_dict,
        recommendation_type=recommendation_type,
        scored_tools=visible_scored,
        migration_paths=visible_migrations,
        workflow=workflow,
        missing_components=missing_components,
    )
    hallucination_audit = audit_report(
        final_report=final_report,
        evidence_bundle=evidence_bundle,
        scored_tools=visible_scored,
        candidate_tools=visible_candidates,
        migration_paths=visible_migrations,
        workflow_recommendation=workflow,
    )
    if audit and _has_blocking_issues(hallucination_audit.model_dump(mode="json")):
        final_report = _safe_audit_blocked_report(
            constraints=constraints_dict,
            recommendation_type=recommendation_type,
            scored_tools=visible_scored,
            migration_paths=visible_migrations,
            workflow=workflow,
            missing_components=missing_components,
        )
        hallucination_audit = audit_report(
            final_report=final_report,
            evidence_bundle=evidence_bundle,
            scored_tools=visible_scored,
            candidate_tools=visible_candidates,
            migration_paths=visible_migrations,
            workflow_recommendation=workflow,
        )

    recommended_tools = _recommended_tool_names(
        recommendation_type=recommendation_type,
        ranked_tool_names=ranked_tool_names,
        candidate_tool_names=candidate_tool_names,
        migration_paths=migration_paths,
    )
    status = "ok"
    if errors:
        status = "partial" if (visible_scored or visible_migrations or workflow) else "error"
    elif missing_components:
        status = "partial"

    return PredictionRecord(
        id=query_id,
        query_id=query_id,
        user_query=user_query,
        parsed_constraints=constraints_dict,
        candidate_tools=[item.model_dump(mode="json") for item in visible_candidates],
        scored_tools=[item.model_dump(mode="json") for item in visible_scored],
        migration_paths=[item.model_dump(mode="json") for item in visible_migrations],
        recommendation_type=recommendation_type,
        recommendation_kind=recommendation_type,
        evidence_bundle=evidence_bundle,
        workflow_recommendation=workflow,
        final_report=final_report,
        missing_components=missing_components,
        clarification_needed=bool(
            constraints_dict.get(
                "needs_human_clarification",
                constraints.needs_human_clarification,
            )
        ),
        execution_status=status,
        execution_mode="evidence_gate_auditor" if audit else "evidence_gate",
        candidate_tool_count=len(tool_candidates),
        scored_tool_count=len(scored_tools),
        migration_path_count=len(migration_paths),
        output_truncated=(
            len(visible_candidates) < len(tool_candidates)
            or len(visible_scored) < len(scored_tools)
            or len(visible_migrations) < len(migration_paths)
        ),
        recommended_tools=recommended_tools[:20],
        evidence_coverage=evidence_bundle.coverage,
        workflow_steps=[step.name for step in workflow.steps] if workflow else [],
        claim_count=hallucination_audit.claim_count,
        unsupported_claims=hallucination_audit.unsupported_claim_count,
        semantic_hallucination_rate=hallucination_audit.hallucination_rate,
        hallucination_audit=hallucination_audit.model_dump(mode="json") if audit else {},
        errors=errors,
    )


def _call_llm_json(prompt: str) -> Dict[str, Any]:
    if _offline_llm_enabled():
        raise RuntimeError("LLM calls are disabled in offline mode.")
    llm = get_llm()
    response = llm.invoke(
        [
            {
                "role": "system",
                "content": "You are a strict JSON API. Return only valid JSON, no Markdown.",
            },
            {"role": "user", "content": prompt},
        ]
    )
    return _parse_json_object(str(response.content))


def _parse_json_object(content: str) -> Dict[str, Any]:
    text = content.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON must be an object")
    return payload


def _offline_llm_enabled() -> bool:
    return get_settings().offline_llm


def _pure_llm_prompt(user_query: str) -> str:
    return f"""
用户需求：
{user_query}

请直接基于 DeepSeek 模型自身知识给出单细胞/多组学分析建议。
不要使用外部图谱、证据门禁或审计器。

必须输出 JSON：
{{
  "parsed_constraints": {{
    "task": "...",
    "modality": "...",
    "platform": "...",
    "data_object": "...",
    "scale": "...",
    "noise": "...",
    "hardware": ["..."],
    "species": "...",
    "output_goal": "...",
    "strictness": "..."
  }},
  "recommendation_type": "ranked_tools|workflow|migration|evidence_chain|none",
  "recommended_tools": ["..."],
  "final_report": "简短 Markdown 报告"
}}

约束：
- 没有把握的字段填 Unknown。
- 不要编造具体 benchmark 分数、排名、论文 DOI。
- final_report 可以使用模型常识，但不要声称系统已有证据。
"""


def _constraint_only_prompt(user_query: str) -> str:
    return f"""
请把用户需求抽取成科研约束 JSON，不要给推荐。

用户需求：
{user_query}

必须输出 JSON，字段：
task, modality, platform, data_object, scale, noise, hardware, species, output_goal, strictness

标准词汇：
- task: QC, Normalization, Batch Correction, Data Integration, Clustering, Cell Type Annotation, Trajectory Inference, Differential Expression, Doublet Detection, Ambient RNA Removal, RNA Velocity, Spatial Deconvolution, Trajectory Differential Expression, Foundation Model Representation, Optimal Transport Trajectory, DTU Analysis, Isoform Quantification, Multiome Integration, Workflow Planning, Workflow Compatibility, Unknown
- modality: scRNA-seq, scATAC-seq, Spatial Transcriptomics, Spatial Metabolomics, CITE-seq, scRNA-seq+scATAC-seq, long-read scRNA-seq, Nanopore, Unknown
- scale: small, medium, large, very_large, Unknown
- noise: low, medium, high, Unknown
- strictness: strict, balanced, exploratory, Unknown

细任务映射规则：
- doublet/multiplet -> Doublet Detection
- ambient RNA/decontamination -> Ambient RNA Removal
- RNA velocity -> RNA Velocity
- spot cell abundance/spatial deconvolution -> Spatial Deconvolution
- lineage/pseudotime differential expression -> Trajectory Differential Expression
- foundation model embedding/representation -> Foundation Model Representation
- optimal transport/Waddington-OT -> Optimal Transport Trajectory
"""


def _normalize_recommendation_type(value: Any) -> str:
    allowed = {"ranked_tools", "workflow", "migration", "evidence_chain", "none"}
    text = _as_string(value)
    return text if text in allowed else "none"


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _as_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_as_string(item) for item in value if _as_string(item)]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,;，；\n]+", value) if item.strip()]
    return [_as_string(value)]


def _split_sentences(report: str) -> List[str]:
    return [line.strip() for line in report.splitlines() if line.strip()]


def _fallback_report(
    mode: str,
    constraints: Dict[str, Any],
    recommendation_type: str,
    recommended_tools: List[str],
) -> str:
    lines = [
        f"## {mode} output",
        f"- recommendation_type: {recommendation_type}",
        f"- task: {constraints.get('task', 'Unknown')}",
        f"- modality: {constraints.get('modality', 'Unknown')}",
    ]
    if recommended_tools:
        lines.append("- recommended_tools: " + ", ".join(recommended_tools[:5]))
    return "\n".join(lines)


def _has_blocking_issues(audit_payload: Dict[str, Any]) -> bool:
    return any(
        issue.get("severity") in {"critical", "high"}
        for issue in audit_payload.get("issues", [])
    )


def _safe_audit_blocked_report(
    constraints: Dict[str, Any],
    recommendation_type: str,
    scored_tools: List[ScoredTool],
    migration_paths: List[MigrationPath],
    workflow: Any,
    missing_components: List[str],
) -> str:
    lines = [
        "## Safe Scientific Output",
        "- report_status: blocked_by_semantic_auditor",
        f"- recommendation_type: {recommendation_type}",
        f"- task: {constraints.get('task', 'Unknown')}",
        f"- modality: {constraints.get('modality', 'Unknown')}",
    ]
    if scored_tools:
        lines.append("- ranked_tools: " + ", ".join(tool.tool_name for tool in scored_tools[:5]))
    if migration_paths:
        lines.append("- migration_paths: " + ", ".join(path.tool_name for path in migration_paths[:3]))
        lines.append(
            "- migration_plausibility: "
            + "; ".join(
                f"{path.tool_name} score={path.score:.3f} "
                f"io={path.io_compatibility if path.io_compatibility is not None else 'NA'} "
                f"jaccard={path.graph_jaccard if path.graph_jaccard is not None else 'NA'}"
                for path in migration_paths[:3]
            )
        )
        gaps = [
            f"{path.tool_name}: " + " | ".join(path.compatibility_gaps[:2])
            for path in migration_paths[:3]
            if path.compatibility_gaps
        ]
        if gaps:
            lines.append("- migration_compatibility_gaps: " + " ; ".join(gaps))
        lines.append(
            "- migration_claim_boundary: exploratory hypothesis only; "
            "requires validation before operational use and has no benchmark-backed performance claim."
        )
    if workflow:
        lines.append("- workflow_steps: " + " -> ".join(step.name for step in workflow.steps))
    if missing_components:
        lines.append("- missing_components: " + ", ".join(missing_components))
    caveats = _task_caveats(constraints, missing_components)
    if caveats:
        lines.append("- evidence_caveats: " + " | ".join(caveats))
    lines.append("- safety_note: unsupported high-risk claims were blocked.")
    return "\n".join(lines)


def _task_caveats(
    constraints: Dict[str, Any],
    missing_components: List[str],
) -> List[str]:
    task = constraints.get("task", "Unknown")
    if task != "Perturbation Differential Expression":
        return []
    caveats = [
        "MIMOSCA can be surfaced only as a conservative perturbation-analysis candidate."
    ]
    if "benchmark" in missing_components or "trusted_recommendation_evidence" in missing_components:
        caveats.append(
            "No strong benchmark-backed performance claim is allowed for this perturbation task."
        )
    return caveats


def _write_summary_table(summary: Dict[str, Any], path: Path) -> None:
    metric_names = [
        "constraint_parse_accuracy",
        "recommendation_type_accuracy",
        "top_k_hit",
        "forbidden_tool_violation_rate",
        "evidence_coverage",
        "recommendation_evidence_coverage",
        "main_tool_recommendation_evidence_coverage",
        "main_tool_publication_evidence_coverage",
        "main_tool_benchmark_evidence_coverage",
        "workflow_completeness",
        "semantic_hallucination_issue_rate",
        "critical_hallucination_rate",
        "high_hallucination_rate",
        "unsupported_tool_claim_rate",
        "semantic_audit_pass_rate",
        "blocked_report_rate",
    ]
    fieldnames = ["mode", "mean_latency_seconds", *metric_names, "prediction_path"]
    rows = []
    for mode, payload in summary["modes"].items():
        metrics = payload["metrics"]
        row = {
            "mode": mode,
            "mean_latency_seconds": payload.get("mean_latency_seconds", ""),
            "prediction_path": payload.get("prediction_path", ""),
        }
        for name in metric_names:
            value = metrics.get(name, {}).get("value")
            row[name] = "" if value is None else value
        rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DeepSeek/Qwen ablation over scKG gold queries.")
    parser.add_argument("--gold", type=Path, default=PROJECT_ROOT / "eval" / "gold_queries.jsonl")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "eval" / "ablation_deepseek")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--modes",
        default="pure_llm,evidence_gate,evidence_gate_auditor,full_kg_pipeline",
        help="Comma-separated subset of: " + ",".join(ABLATION_MODES),
    )
    parser.add_argument(
        "--from-existing",
        action="store_true",
        help="Only summarize existing predictions_<mode>.jsonl files; do not call the model or KG.",
    )
    parser.add_argument(
        "--offline-llm",
        action="store_true",
        help="Do not call DeepSeek/OpenAI; use deterministic constraint fallback for LLM-backed steps.",
    )
    parser.add_argument(
        "--blind-migration",
        action="store_true",
        help="Do not pass gold expected_source_tools into migration generation; use gold only for scoring.",
    )
    args = parser.parse_args()
    if args.offline_llm:
        os.environ["SCKG_OFFLINE_LLM"] = "true"
        get_settings.cache_clear()
    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    if args.from_existing:
        summarize_existing_ablation(args.gold, args.output_dir, modes, args.limit)
    else:
        run_ablation(
            args.gold,
            args.output_dir,
            modes,
            args.limit,
            blind_migration=args.blind_migration,
        )


if __name__ == "__main__":
    main()
