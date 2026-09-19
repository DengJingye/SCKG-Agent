#!/usr/bin/env python3
"""Build the single auditable midterm metrics source requested by the sprint playbook."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/evaluation/midterm_metrics_snapshot_v2"
V1_PATH = ROOT / "data/evaluation/midterm_project_snapshot_v1/metrics.json"
INPUT_PATH = ROOT / "data/evaluation/midterm_input_binding_v2/20260919-current-01/summary.json"
REPLAY_PATH = ROOT / (
    "data/evaluation/current_version_pbmc3k_replay_v2/20260919-current-01/summary.corrected.json"
)
AGENT_PATH = ROOT / "data/evaluation/agent_tool_selection_v1/live-20260919-36-configured/summary.json"
DASHBOARD_PATH = ROOT.parent / "ui-review-evidence-rag-20260919/verified-statistics.json"
TEST_LOG = ROOT / ".sckg_exec/reports/midterm-sprint-20260919/p0-focused-tests.log"


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def metric(classification: str, values: Any, interpretation: str, source: str) -> dict[str, Any]:
    return {
        "classification": classification,
        "values": values,
        "interpretation": interpretation,
        "source": source,
    }


def ratio(value: Any) -> str:
    if isinstance(value, dict) and {"numerator", "denominator"} <= set(value):
        return f"{value['numerator']}/{value['denominator']}"
    return str(value)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=False)
    v1 = read(V1_PATH)
    binding = read(INPUT_PATH)
    replay = read(REPLAY_PATH)
    agent = read(AGENT_PATH)
    dashboard = read(DASHBOARD_PATH)
    head = git("rev-parse", "HEAD")
    status = git("status", "--short")

    metrics = {
        "schema_version": "sckg-midterm-metrics-snapshot-v2",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "measurement_head": head,
        "worktree_dirty": bool(status),
        "classification_policy": {
            "CURRENT_MEASURED": "Measured on current artifacts or current product replay in this sprint.",
            "FROZEN_HISTORICAL": "Immutable earlier formal result; not a current-SUT score.",
            "DEVELOPMENT_RESULT": "Development evidence without independent sealed validation.",
            "NOT_RUN": "No qualifying run exists.",
        },
        "kg": metric(
            "CURRENT_MEASURED",
            v1["scientific_kg_inventory"]["values"],
            "Artifact inventory carried from the same-day read-only v1 census; counts are inventory, not validation or promotion.",
            str(V1_PATH.relative_to(ROOT)),
        ),
        "rag_index": metric(
            "CURRENT_MEASURED",
            {
                "inventory": v1["rag_index_inventory"]["values"],
                "dashboard_verified_statistics": dashboard,
            },
            "Default and strengthened snapshots stay separate. The old 99.6% label is historical regression only; source association and vector counts use the displayed snapshot provenance.",
            str(DASHBOARD_PATH),
        ),
        "retrieval": metric(
            "DEVELOPMENT_RESULT",
            v1["retrieval_benchmark"]["values"],
            "Fixed 45-question scientific and 12-question catalog development benchmark. Complete BM25, Dense, Hybrid, Scientific KG plus Hybrid, and optional governance profiles already exist; no new tuning or rerun occurred.",
            str(V1_PATH.relative_to(ROOT)),
        ),
        "planner": metric(
            "DEVELOPMENT_RESULT",
            v1["planner_readiness"]["values"],
            "Eight bounded development cases; not independent validation.",
            str(V1_PATH.relative_to(ROOT)),
        ),
        "evidence_fidelity": metric(
            "FROZEN_HISTORICAL",
            v1["evidence_fidelity"]["values"],
            v1["evidence_fidelity"]["interpretation"],
            str(V1_PATH.relative_to(ROOT)),
        ),
        "soupx": metric(
            "DEVELOPMENT_RESULT",
            v1["candidate_self_evolution"]["values"],
            "Bounded candidate acquisition, deposition, review-surface and reuse pilot; no qualified ReviewDecision or canonical promotion.",
            str(V1_PATH.relative_to(ROOT)),
        ),
        "celltypist": metric(
            "DEVELOPMENT_RESULT",
            v1["celltypist_runtime_qualification"]["values"],
            v1["celltypist_runtime_qualification"]["interpretation"],
            str(V1_PATH.relative_to(ROOT)),
        ),
        "real_data_input_binding": metric(
            "CURRENT_MEASURED",
            binding,
            "Offline service integration on real PBMC3k inputs; browser upload behavior is covered separately by the product replay and screenshot evidence.",
            str(INPUT_PATH.relative_to(ROOT)),
        ),
        "real_data_e2e": metric(
            "CURRENT_MEASURED",
            replay,
            "Current browser product replay and manual Jupyter Run All. Numeric/reuse notebooks executed; annotation candidate and human confirmation terminals remain blocked and are reported false.",
            str(REPLAY_PATH.relative_to(ROOT)),
        ),
        "agent_behavior": metric(
            "DEVELOPMENT_RESULT",
            agent,
            "Thirty-six hand-authored development parent cases with 35 live LLM-ready responses; one draw per case, no seed guarantee and no independent adjudication.",
            str(AGENT_PATH.relative_to(ROOT)),
        ),
        "regression": metric(
            "CURRENT_MEASURED",
            {
                "focused_command": "python -m pytest -q tests/test_agent_tool_selection_v1.py tests/test_evidence_dashboard.py tests/test_notebook_provenance_links.py tests/test_research_composer_lifecycle.py tests/test_research_embedding_requests.py tests/test_research_input_binding.py tests/test_research_pca_binding.py tests/test_research_shell.py tests/test_research_source_links.py tests/test_semantic_primary_routing.py tests/test_workflow_plan_presentation.py tests/test_local_jupyter_service.py tests/test_research_chat_service.py",
                "passed": 189,
                "failed": 0,
                "warnings": 2,
                "duration_seconds": 56.54,
                "full_suite_current_head": "NOT_RUN",
                "historical_full_suite": v1["test_regression_status"]["values"],
            },
            "Focused P0/P1 validation is current. The full suite was not repeated; the earlier full-suite snapshot remains separately identifiable and was not all-green.",
            str(TEST_LOG.relative_to(ROOT)),
        ),
        "not_run": metric(
            "NOT_RUN",
            {
                "independent_retrieval_validation_30_to_50": None,
                "sealed_validation_subset": None,
                "external_benchmark_smoke": None,
                "dcs_deployment_readiness": None,
                "pbmc_human_review_decisions": None,
                "current_head_full_pytest_suite": None,
            },
            "No qualifying result; these fields must stay out of achieved-result claims.",
            "sprint execution boundary",
        ),
    }

    metrics_path = OUT / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    retrieval = metrics["retrieval"]["values"]["aggregate_metrics"]
    rows: list[dict[str, Any]] = []

    def add(section: str, name: str, value: Any, classification: str, source: str, limitation: str = "") -> None:
        rows.append(
            {
                "section": section,
                "metric": name,
                "value": ratio(value),
                "classification": classification,
                "source": source,
                "limitation": limitation,
            }
        )

    for profile in ["R0_bm25_only", "R1_dense_only", "R2_bm25_dense_rrf", "R3_kg_bm25_dense_rrf", "R4_kg_bm25_dense_rrf_governance"]:
        science = retrieval[profile]["R1_scientific_evidence"]
        add("Retrieval", f"{profile}.Recall@10", science["recall_at_10"], "DEVELOPMENT_RESULT", metrics["retrieval"]["source"], "45 known development questions")
        add("Retrieval", f"{profile}.nDCG@10", science["ndcg_at_10"], "DEVELOPMENT_RESULT", metrics["retrieval"]["source"], "45 known development questions")
    for key in ["llm_intent_correct", "governed_intent_correct", "governed_mode_correct", "action_selection_correct", "data_binding_correct", "clarification_correct", "block_correct", "unauthorized_execution", "structured_complete_without_run_evidence"]:
        add("Agent", key, agent["metrics"][key], "DEVELOPMENT_RESULT", metrics["agent_behavior"]["source"], "36 hand-authored cases; one draw")
    for layer in ["proposal_tools", "governed_tools", "actual_tools"]:
        add("Agent", f"{layer}.precision", agent["metrics"][layer]["precision"], "DEVELOPMENT_RESULT", metrics["agent_behavior"]["source"], "permissible-tool precision")
        add("Agent", f"{layer}.recall", agent["metrics"][layer]["recall"], "DEVELOPMENT_RESULT", metrics["agent_behavior"]["source"], "required-tool recall")
    add("Input binding", "INPUT_BINDING_CORRECT", binding["INPUT_BINDING_CORRECT"], "CURRENT_MEASURED", metrics["real_data_input_binding"]["source"])
    add("Input binding", "CROSS_SESSION_LEAKAGE", binding["CROSS_SESSION_LEAKAGE"], "CURRENT_MEASURED", metrics["real_data_input_binding"]["source"])
    add("Input binding", "SYNTHETIC_FALLBACK_WITHOUT_EXPLICIT_USER_CHOICE", binding["SYNTHETIC_FALLBACK_WITHOUT_EXPLICIT_USER_CHOICE"], "CURRENT_MEASURED", metrics["real_data_input_binding"]["source"])
    for name, item in replay["datasets"].items():
        for key in ["PLAN_COMPILED", "NOTEBOOK_COMPILED", "NOTEBOOK_EXECUTED", "CANDIDATE_TERMINAL_SATISFIED", "HUMAN_CONFIRMATION_COMPLETED", "FULL_SCIENTIFIC_TASK_COMPLETED"]:
            add("Real-data E2E", f"{name}.{key}", item[key], "CURRENT_MEASURED", metrics["real_data_e2e"]["source"])
    add("Regression", "focused_tests", {"numerator": 189, "denominator": 189}, "CURRENT_MEASURED", metrics["regression"]["source"])
    add("Regression", "full_suite_current_head", "NOT_RUN", "NOT_RUN", "sprint execution boundary")

    tables_path = OUT / "tables.csv"
    with tables_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    sources = [V1_PATH, INPUT_PATH, REPLAY_PATH, AGENT_PATH, DASHBOARD_PATH, TEST_LOG, metrics_path, tables_path]
    artifact_index = {
        "schema_version": "sckg-midterm-metrics-artifact-index-v2",
        "measurement_head": head,
        "artifacts": [
            {
                "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in sources
        ],
        "notes": [
            "artifact_index.json omits its own digest to avoid a circular hash.",
            "The failed first replay summary is preserved; metrics use summary.corrected.json after fixing list-form notebook source normalization in the audit script.",
        ],
    }
    (OUT / "artifact_index.json").write_text(
        json.dumps(artifact_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "PASS", "output": str(OUT.relative_to(ROOT)), "table_rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
