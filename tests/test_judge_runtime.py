from __future__ import annotations

from eval.judge_runtime import calibrate_labels


def test_judge_requires_at_least_twenty_calibration_cases():
    result = calibrate_labels(["correct"] * 19, ["correct"] * 19)
    assert result.status == "insufficient_data"
    assert result.calibrated is False


def test_balanced_judge_calibration_reports_accuracy_and_kappa():
    gold = ["correct", "partial", "incorrect"] * 7
    result = calibrate_labels(gold, list(gold))
    assert result.case_count == 21
    assert result.accuracy == 1.0
    assert result.cohen_kappa == 1.0
    assert result.calibrated is True
