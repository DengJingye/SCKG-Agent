from __future__ import annotations

import pytest

from core.evaluation_models import EvaluationCase
from eval.evaluation_dataset import EvaluationDatasetRegistry, audit_registry, validate_cases


def test_versioned_evaluation_registry_passes_schema_and_digest_audit():
    result = audit_registry(EvaluationDatasetRegistry())
    assert result["passed"] is True
    assert result["manifest_count"] == 3
    assert sum(result["visible_case_counts"].values()) == 8


def test_near_duplicate_queries_cannot_cross_splits():
    base = {
        "dataset_version": "v1",
        "source": "test",
        "conversation_state": [],
        "applicable_metrics": ["routing.domain"],
        "routing_gold": {"domain": "GENERAL"},
        "answer_gold": [],
        "safety_gold": None,
        "expected_trajectory": None,
        "expected_artifacts": [],
        "risk_level": "low",
        "metadata": {},
    }
    first = EvaluationCase(
        case_id="duplicate.dev",
        split="development",
        input={"query": "How should I detect doublets?"},
        **base,
    )
    second = EvaluationCase(
        case_id="duplicate.eval",
        split="evaluation",
        input={"query": "How should I detect doublets?"},
        **base,
    )
    with pytest.raises(ValueError, match="crosses evaluation splits"):
        validate_cases([first, second])
