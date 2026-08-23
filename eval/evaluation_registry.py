from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.settings import PROJECT_ROOT


class EvaluationExperimentRegistry:
    """Read-only index of immutable unified evaluation experiments."""

    def __init__(
        self,
        *,
        registry_root: Path = PROJECT_ROOT / ".sckg_exec/evaluations/registry",
        project_root: Path = PROJECT_ROOT,
    ) -> None:
        self.registry_root = Path(registry_root)
        self.project_root = Path(project_root).resolve()

    def latest(self, suite: str = "pr") -> dict[str, Any]:
        pointer = self.registry_root / f"latest_{suite}.json"
        if not pointer.is_file():
            return {}
        try:
            entry = json.loads(pointer.read_text(encoding="utf-8"))
            experiment = (self.project_root / str(entry.get("path") or "")).resolve()
            if not _within(experiment, self.project_root / ".sckg_exec/evaluations"):
                return {}
            return {
                **entry,
                "manifest": _read_json(experiment / "experiment_manifest.json"),
                "release_gate": _read_json(experiment / "release_gate.json"),
                "regression": _read_json(experiment / "regression_report.json"),
                "metrics": _read_jsonl(experiment / "evaluator_scores.jsonl"),
                "failures": _read_jsonl(experiment / "failure_queue.jsonl"),
            }
        except (OSError, ValueError, json.JSONDecodeError):
            return {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False
