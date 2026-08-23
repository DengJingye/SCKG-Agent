from eval.agent_quality_evaluation import load_cases
from eval.external_agent_stability import (
    EXPLICIT_SWITCH_CASE_IDS,
    select_representative_cases,
    run_external_evaluation,
)
from eval.run_ragas_diagnostic import diagnostic_status


class _ForbiddenService:
    def __init__(self):
        raise AssertionError("service must not initialize without explicit outbound consent")


def test_external_stability_eval_does_not_call_model_without_consent(tmp_path):
    summary = run_external_evaluation(
        load_cases(),
        authorize_outbound=False,
        service_factory=_ForbiddenService,
        output_dir=tmp_path,
    )

    assert summary.status == "not_run"
    assert summary.requested_call_count == 60
    assert summary.completed_call_count == 0
    assert (tmp_path / "runs.jsonl").read_text(encoding="utf-8") == ""


def test_external_stability_requires_passed_five_turn_smoke(tmp_path):
    summary = run_external_evaluation(
        load_cases(),
        authorize_outbound=True,
        confirmation_text="I AUTHORIZE 60 GOVERNED EVALUATION TURNS",
        runtime_config={"api_key": "never-used"},
        smoke_summary_path=tmp_path / "missing.json",
        service_factory=_ForbiddenService,
        output_dir=tmp_path / "output",
    )

    assert summary.status == "blocked"
    assert summary.reason == "live_llm_smoke_gate_missing"
    assert summary.attempted_model_call_count == 0


def test_external_case_bank_contains_explicit_task_switches():
    selected = select_representative_cases(load_cases())
    selected_ids = {case.case_id for case in selected}
    by_id = {case.case_id: case for case in selected}

    assert len(selected) == 20
    assert EXPLICIT_SWITCH_CASE_IDS <= selected_ids
    assert by_id["chat-hard-negative-protein-01"].expected_intent == "tool_recommendation"
    cellphonedb = by_id["chat-transition-doublet-to-unsupported-cellphonedb-02"]
    assert cellphonedb.expected_intent == "workflow"
    assert cellphonedb.expected_task == "cell_cell_communication"
    assert cellphonedb.expected_blocked is True


def test_ragas_is_secondary_and_not_run_without_consent():
    payload = diagnostic_status(authorize_outbound=False, confirmation_text="")

    assert payload["status"] == "not_run"
    assert payload["authority"] == "secondary_diagnostic_only"
