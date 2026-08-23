from __future__ import annotations

import pytest

from core.evaluation_models import (
    EvaluationCase,
    EvaluationMetricStatus,
    EvaluatorResult,
    ExperimentManifest,
    JudgeRuntimeConfig,
)


def test_answer_metrics_require_atomic_source_bound_gold():
    with pytest.raises(ValueError, match="atomic reference claims"):
        EvaluationCase(
            case_id="case.answer",
            dataset_version="v1",
            source="test",
            split="evaluation",
            input={"query": "question"},
            applicable_metrics=["claim.scientific_precision"],
        )


def test_unmeasured_metric_cannot_carry_default_high_score():
    with pytest.raises(ValueError, match="cannot carry"):
        EvaluatorResult(
            evaluator_id="judge",
            metric_id="claim.precision",
            status=EvaluationMetricStatus.NOT_RUN,
            value=1.0,
        )


def test_same_generator_and_judge_are_rejected():
    judge = JudgeRuntimeConfig(
        provider="deepseek",
        model="deepseek-chat",
        api_base="https://example.invalid",
        prompt_digest="abc",
        calibration_case_count=20,
        calibration_accuracy=0.9,
        calibration_kappa=0.8,
    )
    with pytest.raises(ValueError, match="cannot be the same"):
        ExperimentManifest(
            experiment_id="exp",
            suite="nightly",
            git_head="head",
            worktree_dirty=False,
            dataset_digests={"d": "x"},
            prompt_digest="p",
            generator_provider="deepseek",
            generator_model="deepseek-chat",
            evaluator_digest="e",
            judge=judge,
        )


def test_judge_calibration_gate_is_explicit():
    config = JudgeRuntimeConfig(
        provider="judge-provider",
        model="judge-model",
        api_base="https://example.invalid",
        prompt_digest="abc",
        calibration_case_count=20,
        calibration_accuracy=0.8,
        calibration_kappa=0.7,
    )
    assert config.is_calibrated() is True
