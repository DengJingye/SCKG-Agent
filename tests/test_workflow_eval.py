from eval.run_workflow_eval import (
    evaluate_scenario,
    evidence_boundary_violations,
    one_line,
    term_matches_text,
)
from engine.workflow_recommender import build_minimal_workflow_recommendation


def test_workflow_eval_matches_doublet_scenario_without_evidence_leakage():
    scenario = {
        "id": "WF_TEST_doublet",
        "constraints": {
            "task": "Doublet Detection",
            "modality": "scRNA-seq",
            "data_object": "raw count matrix / AnnData",
            "output_goal": "doublet-filtered object and review report",
        },
        "candidate_tools": ["Scrublet", "DoubletFinder", "Scanpy", "Seurat"],
        "expected_step_terms": ["input validation", "doublet score", "threshold", "post-filter qc"],
        "expected_candidate_tools": ["Scrublet", "DoubletFinder"],
        "allowed_extra_step_terms": ["qc", "sample context"],
    }

    result = evaluate_scenario(scenario)

    assert result["passed"] is True
    assert result["required_step_recall"] == 1.0
    assert result["candidate_tool_recall"] == 1.0
    assert result["evidence_boundary_violation_count"] == 0
    assert result["missing_step_terms"] == []
    assert result["missing_candidate_tools"] == []


def test_workflow_eval_term_matching_supports_synonym_groups():
    assert term_matches_text(["reference-based annotation", "label transfer"], "reference-based annotation review")
    assert term_matches_text("FDR", "power and FDR review")
    assert not term_matches_text("spatial", "doublet score estimation")


def test_workflow_eval_keeps_zero_values_in_tsv_output():
    assert one_line(0) == "0"
    assert one_line(0.0) == "0.0"
    assert one_line(None) == ""


def test_internal_workflow_template_evidence_is_not_main_recommendation_evidence():
    workflow = build_minimal_workflow_recommendation(
        {
            "task": "Workflow Planning",
            "modality": "scRNA-seq",
            "data_object": "AnnData",
            "output_goal": "audited workflow plan",
        },
        candidate_tools=["Scanpy", "Seurat"],
    )

    all_evidence = list(workflow.evidence.items)
    for step in workflow.steps:
        all_evidence.extend(step.evidence.items)

    assert all_evidence
    assert all(evidence_boundary_violations(evidence) == [] for evidence in all_evidence)
