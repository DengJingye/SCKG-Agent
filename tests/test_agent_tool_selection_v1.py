from eval.agent_tool_selection_v1 import aggregate, cases, score


def response(real=False):
    return {"state": {"mode": "ASK", "intent": "evidence_qa", "artifact_id": None},
        "status": "ANSWERED", "workspace_handoff": {"status": "not_applicable", "target_representations": []},
        "execution_handoff": {"artifact_id": None, "status": "not_requested", "execution_request_count": 0},
        "evidence_context_pack": {"semantic_parse": {"status": "ready" if real else "disabled",
            "provider_call_attempted": real, "intent": "evidence_qa", "tool_calls": []},
            "research_tool_plan": {"calls": [{"tool_name": "search_evidence", "query": "q", "tool_names": ["Scrublet"]}]},
            "research_tool_observations": [{"tool_name": "search_evidence", "status": "blocked"}]}}


def test_balanced_unique_parents():
    panel = cases()
    assert len(panel) == len({r['case_id'] for r in panel}) == len({r['query'] for r in panel}) == 36
    assert all(sum(r['group'] == group for r in panel) == 6 for group in {r['group'] for r in panel})


def test_offline_governance_does_not_count_as_llm_success():
    row = score(dict(cases()[0], artifact_id=None), response())
    assert row['scores']['llm_intent_correct'] is None
    assert row['scores']['proposal_tools'] is None
    assert row['scores']['governed_tools']['required_hit'] == 1
    assert row['scores']['actual_tools']['calls'] == 0


def test_empty_real_proposal_is_missed_trigger_not_na():
    row = score(dict(cases()[0], artifact_id=None), response(real=True))
    assert row['scores']['proposal_tools']['required_hit'] == 0
    assert row['scores']['proposal_tools']['required'] == 1


def test_failed_request_stays_in_action_denominator():
    summary = aggregate([{'case_id': 'failure', 'error': {'type': 'Timeout'}}], 1)
    assert summary['metrics']['action_selection_correct'] == {'numerator': 0, 'denominator': 1, 'value': 0}
    assert summary['real_llm_ready'] == 0


def test_false_completion_and_unauthorized_execution_are_separate():
    r = response(True)
    r['execution_handoff'].update(status='completed', execution_request_count=1)
    row = score(dict(cases()[0], artifact_id=None), r)
    assert row['scores']['unauthorized_execution']
    assert row['scores']['structured_complete_without_run_evidence']
