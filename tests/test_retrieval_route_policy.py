from __future__ import annotations

import json

from agent.research_chat_service import _dense_default_enabled
from eval.run_retrieval_evaluation_v2 import _route_decision


def _profile(**updates):
    payload = {
        "status": "passed",
        "recall_at_10": 0.91,
        "precision_at_10": 0.75,
        "mrr": 0.80,
        "source_span_hit_rate": 0.90,
        "false_support_rate": 0.0,
        "parameter_legality_rate": 1.0,
        "governance_leakage_count": 0,
        "latency_p95_ms": 100.0,
    }
    payload.update(updates)
    return payload


def test_hybrid_is_not_default_without_measured_primary_gain() -> None:
    same = _profile()
    decision = _route_decision(
        {"kg_bm25": same, "kg_hybrid_tool_contract": dict(same)}
    )

    assert decision["default_profile"] == "kg_bm25"
    assert decision["dense_default_enabled"] is False
    assert "no_primary_metric_improved_over_kg_bm25" in decision["decision_failures"]


def test_hybrid_can_be_default_only_after_all_gates_pass(tmp_path) -> None:
    decision = _route_decision(
        {
            "kg_bm25": _profile(recall_at_10=0.90),
            "kg_hybrid_tool_contract": _profile(recall_at_10=0.93),
        }
    )
    policy = tmp_path / "route.json"
    policy.write_text(json.dumps(decision), encoding="utf-8")

    assert decision["default_profile"] == "kg_hybrid_tool_contract"
    assert _dense_default_enabled(policy) is True


def test_missing_or_failed_policy_keeps_kg_bm25(tmp_path) -> None:
    assert _dense_default_enabled(tmp_path / "missing.json") is False
    failed = _route_decision(
        {
            "kg_bm25": _profile(),
            "kg_hybrid_tool_contract": _profile(latency_p95_ms=700.0),
        }
    )
    policy = tmp_path / "route.json"
    policy.write_text(json.dumps(failed), encoding="utf-8")

    assert _dense_default_enabled(policy) is False
