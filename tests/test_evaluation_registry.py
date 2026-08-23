from __future__ import annotations

import json

from eval.evaluation_registry import EvaluationExperimentRegistry


def test_registry_reads_latest_experiment_without_side_effects(tmp_path):
    experiment = tmp_path / ".sckg_exec/evaluations/eval-pr-1"
    experiment.mkdir(parents=True)
    (experiment / "experiment_manifest.json").write_text(
        json.dumps({"experiment_id": "eval-pr-1"}), encoding="utf-8"
    )
    (experiment / "release_gate.json").write_text(
        json.dumps({"status": "passed", "blockers": []}), encoding="utf-8"
    )
    (experiment / "regression_report.json").write_text("{}", encoding="utf-8")
    (experiment / "evaluator_scores.jsonl").write_text("", encoding="utf-8")
    (experiment / "failure_queue.jsonl").write_text("", encoding="utf-8")
    registry_root = tmp_path / ".sckg_exec/evaluations/registry"
    registry_root.mkdir()
    # A path outside the real project root is intentionally rejected.
    (registry_root / "latest_pr.json").write_text(
        json.dumps({"path": ".sckg_exec/evaluations/eval-pr-1", "suite": "pr"}), encoding="utf-8"
    )
    loaded = EvaluationExperimentRegistry(
        registry_root=registry_root, project_root=tmp_path
    ).latest("pr")
    assert loaded["release_gate"]["status"] == "passed"
