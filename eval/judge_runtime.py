from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from core.evaluation_models import JudgeRuntimeConfig


@dataclass(frozen=True)
class JudgeCalibrationResult:
    status: str
    case_count: int
    accuracy: float | None
    cohen_kappa: float | None
    calibrated: bool
    reason: str = ""


def resolve_judge_config_from_environment() -> tuple[JudgeRuntimeConfig | None, str]:
    provider = os.getenv("SCKG_JUDGE_PROVIDER", "").strip()
    model = os.getenv("SCKG_JUDGE_MODEL", "").strip()
    api_base = os.getenv("SCKG_JUDGE_API_BASE", "").strip()
    prompt_digest = os.getenv("SCKG_JUDGE_PROMPT_DIGEST", "").strip()
    api_key = os.getenv("SCKG_JUDGE_API_KEY", "").strip()
    if not all((provider, model, api_base, prompt_digest, api_key)):
        return None, "judge_credentials_or_configuration_missing"
    return (
        JudgeRuntimeConfig(
            provider=provider,
            model=model,
            api_base=api_base,
            prompt_digest=prompt_digest,
        ),
        "",
    )


def calibrate_labels(
    gold_labels: Iterable[str], predicted_labels: Iterable[str]
) -> JudgeCalibrationResult:
    gold = list(gold_labels)
    predicted = list(predicted_labels)
    if len(gold) != len(predicted):
        return JudgeCalibrationResult(
            status="error",
            case_count=len(gold),
            accuracy=None,
            cohen_kappa=None,
            calibrated=False,
            reason="gold_prediction_length_mismatch",
        )
    if len(gold) < 20:
        return JudgeCalibrationResult(
            status="insufficient_data",
            case_count=len(gold),
            accuracy=None,
            cohen_kappa=None,
            calibrated=False,
            reason="at_least_20_balanced_cases_required",
        )
    accuracy = sum(left == right for left, right in zip(gold, predicted)) / len(gold)
    kappa = cohen_kappa(gold, predicted)
    return JudgeCalibrationResult(
        status="completed",
        case_count=len(gold),
        accuracy=round(accuracy, 6),
        cohen_kappa=round(kappa, 6),
        calibrated=accuracy >= 0.80 and kappa >= 0.70,
        reason="" if accuracy >= 0.80 and kappa >= 0.70 else "calibration_gate_failed",
    )


def cohen_kappa(gold: list[str], predicted: list[str]) -> float:
    if not gold:
        return 0.0
    labels = set(gold) | set(predicted)
    observed = sum(left == right for left, right in zip(gold, predicted)) / len(gold)
    expected = sum(
        (gold.count(label) / len(gold)) * (predicted.count(label) / len(predicted))
        for label in labels
    )
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def run_calibration_file(
    path: Path,
    *,
    judge: Callable[[dict], dict],
) -> JudgeCalibrationResult:
    rows = json.loads(path.read_text(encoding="utf-8"))
    gold: list[str] = []
    predicted: list[str] = []
    for row in rows:
        result = judge(
            {
                "reference_claim": row["reference_claim"],
                "candidate_claim": row["candidate_claim"],
                "allowed_labels": ["correct", "partial", "incorrect"],
                "response_schema": {
                    "label": "correct|partial|incorrect",
                    "evidence_reason": "brief source-grounded reason",
                },
            }
        )
        gold.append(str(row["gold_label"]))
        predicted.append(str(result.get("label") or "invalid"))
    return calibrate_labels(gold, predicted)
