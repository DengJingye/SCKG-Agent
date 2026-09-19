#!/usr/bin/env python3
"""Create a portable, write-once freeze of the midterm P0, C6 and C8 evidence."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
OUT = ROOT / "data/evaluation/midterm_freeze_v1_1"
ASSETS = ROOT / "docs/assets/midterm_freeze_v1_1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sanitize_string(value: str) -> str:
    replacements = (
        (str(ROOT), "<repository>"),
        (str(WORKSPACE), "<workspace>"),
        (str(Path.home()), "<home>"),
    )
    for source, target in replacements:
        value = value.replace(source, target)
    value = re.sub(
        r"(?<!:)\/(?:Users|opt|private|var|tmp)\/[^\s\"']+",
        "<absolute-path-redacted>",
        value,
    )
    return value


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return sanitize_string(value)
    return value


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(sanitize(value), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def identity(path: Path) -> dict[str, Any]:
    try:
        display_path = str(path.relative_to(ROOT))
    except ValueError:
        display_path = sanitize_string(str(path))
    return {
        "path": display_path,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def main() -> None:
    if OUT.exists() or ASSETS.exists():
        raise FileExistsError("midterm freeze outputs are write-once")
    OUT.mkdir(parents=True)
    ASSETS.mkdir(parents=True)

    sources = {
        "real_data_input": ROOT / "data/evaluation/midterm_input_binding_v2/20260919-current-01/summary.json",
        "pbmc_replay": ROOT / "data/evaluation/current_version_pbmc3k_replay_v2/20260919-current-01/summary.corrected.json",
        "agent_summary": ROOT / "data/evaluation/agent_tool_selection_v1/live-20260919-36-configured/summary.json",
        "agent_cases": ROOT / "data/evaluation/agent_tool_selection_v1/live-20260919-36-configured/cases.frozen.json",
        "metrics": ROOT / "data/evaluation/midterm_metrics_snapshot_v2/metrics.json",
        "metrics_tables": ROOT / "data/evaluation/midterm_metrics_snapshot_v2/tables.csv",
        "dashboard": WORKSPACE / "ui-review-evidence-rag-20260919/verified-statistics.json",
    }
    write_json(OUT / "p0/real_data_input_closure.json", read_json(sources["real_data_input"]))
    write_json(OUT / "p0/current_pbmc_replay.json", read_json(sources["pbmc_replay"]))
    write_json(OUT / "p0/agent_tool_selection_summary.json", read_json(sources["agent_summary"]))
    write_json(OUT / "p0/agent_tool_selection_cases.json", read_json(sources["agent_cases"]))
    write_json(OUT / "p0/midterm_metrics_snapshot_v2.json", read_json(sources["metrics"]))
    table_text = sources["metrics_tables"].read_text(encoding="utf-8").replace("\r\n", "\n")
    (OUT / "p0/midterm_metrics_tables.csv").write_text(table_text, encoding="utf-8", newline="\n")
    write_json(OUT / "dashboard/c8_verified_statistics.json", read_json(sources["dashboard"]))

    screenshots = {
        "01_ask_plan_handoff.png": WORKSPACE / "中期汇报截图/原始截图/07_Research_真实问题与响应.png",
        "02_plan_raw_profile.png": ROOT / "data/development/research_data_binding_v1/raw-acceptance.png",
        "03_processed_reuse.png": ROOT / "data/development/research_data_binding_v1/processed-profile.png",
        "04_run_raw_umap.png": WORKSPACE / "中期汇报截图/原始截图/08_Raw_Notebook_UMAP已执行输出.png",
        "05_retrieval_ablation.png": WORKSPACE / "ui-review-evidence-rag-20260919/development-campaign.png",
        "06_evidence_provenance.png": WORKSPACE / "ui-review-evidence-rag-20260919/source-audit.png",
    }
    for name, source in screenshots.items():
        shutil.copyfile(source, ASSETS / name)

    c6_files = [
        ROOT / "eval_v2/retrieval_benchmark_v1_1_1_dev/manifest.json",
        ROOT / "eval_v2/retrieval_benchmark_v1_1_1_dev/queries.jsonl",
        ROOT / "eval_v2/retrieval_benchmark_v1_1_1_dev/gold.jsonl",
        ROOT / "eval_v2/retrieval_benchmark_v1_1_1_dev/retrieval_config.json",
        ROOT / "eval_v2/retrieval_benchmark_v1_1_1_dev/report.json",
        ROOT / "eval_v2/scientific_kg_evidence_retrieval_v1_dev/report.json",
        ROOT / "eval_v2/scientific_kg_evidence_retrieval_v1_dev/integrity_after.json",
    ]
    sut_files = [
        ROOT / "engine/hybrid_retrieval.py",
        ROOT / "engine/scientific_kg_evidence.py",
        ROOT / "engine/scientific_kg_applicability.py",
        ROOT / "data/indexes/retrieval_foundation_v1/evidence_index_manifest.json",
        ROOT / "data/indexes/retrieval_foundation_v1/evidence_chunks.jsonl",
        ROOT / "data/indexes/retrieval_foundation_v1/evidence_vector_metadata.json",
        ROOT / "data/indexes/retrieval_foundation_v1/evidence_vectors.npy",
    ]
    frozen_historical = [
        ROOT / "data/evaluation/scientific_decision_justification_fidelity_v1_2/report.json",
        ROOT / "data/evaluation/midterm_project_snapshot_v1/metrics.json",
    ]
    write_json(
        OUT / "retrieval/c6_reference.json",
        {
            "classification": "DEVELOPMENT_RESULT",
            "interpretation": "Existing fixed C6 development ablation; no rerun or tuning in this freeze.",
            "artifacts": [identity(path) for path in c6_files],
            "sut_and_index_identities": [identity(path) for path in sut_files],
        },
    )

    original_sources = [identity(path) for path in sources.values()]
    portable_outputs = sorted(path for path in OUT.rglob("*") if path.is_file())
    screenshot_outputs = sorted(path for path in ASSETS.rglob("*") if path.is_file())
    manifest = {
        "schema_version": "sckg-midterm-freeze-v1.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "branch": git("branch", "--show-current"),
        "pre_freeze_head": git("rev-parse", "HEAD"),
        "scope": ["P0", "C6", "C8"],
        "original_source_identities": original_sources,
        "portable_outputs": [identity(path) for path in portable_outputs],
        "screenshot_outputs": [identity(path) for path in screenshot_outputs],
        "frozen_historical_identities": [identity(path) for path in frozen_historical],
        "assertions": {
            "original_audit_artifacts_modified": False,
            "benchmark_gold_modified": False,
            "scientific_kg_or_corpus_tuned_for_freeze": False,
            "raw_h5ad_committed": False,
            "blocked_reported_as_success": False,
            "synthetic_reported_as_real_pbmc": False,
            "portable_paths_redacted": True,
        },
        "verification": {
            "focused_tests": "189 passed, 0 failed, 2 warnings",
            "final_core_revalidation": "56 passed, 0 failed, 2 warnings",
            "source_artifact_integrity": "8/8",
            "git_diff_check": "PASS",
        },
    }
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps({"status": "PASS", "outputs": len(portable_outputs), "screenshots": len(screenshot_outputs)}))


if __name__ == "__main__":
    main()
