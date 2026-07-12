from core.subagent_runtime import SubagentController


def test_subagent_default_is_blocked_and_read_only():
    controller = SubagentController()
    request = controller.build_request(
        parent_trace_id="trace_parent",
        task_type="evidence_search",
        query="find benchmark evidence",
    )
    result = controller.spawn(request)

    assert result.status == "blocked"
    assert "subagent_execution_disabled_v1" in result.warnings
    assert result.can_update_recommendation_rank is False
    assert result.can_update_formal_evidence is False
    assert result.can_update_trusted_evidence is False
    assert result.candidate_context["subagent_output_boundary"] == "blocked_or_read_only_candidate_context"
