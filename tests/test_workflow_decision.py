from engine.workflow_decision import (
    build_workflow_decision_response,
    infer_task_from_query,
)


def test_workflow_decision_response_keeps_plan_only_boundary():
    def fake_rag_fn(*, constraints, tool_names, max_snippets):
        return {
            "mode": "unit_test",
            "pipeline": ["fake_sparse", "fake_rerank"],
            "snippets": [
                {
                    "tool_name": list(tool_names)[0],
                    "source_kind": "source_docs",
                    "title": "Fake source",
                    "source_span": "paragraph:1",
                    "claim_span": f"Fake snippet for {constraints.get('workflow_step')}.",
                    "claim_boundary": "Retrieval context only; cannot promote formal evidence.",
                    "relevance_score": 0.8,
                    "chunk_id": f"fake:{constraints.get('workflow_step')}",
                }
            ],
        }

    response = build_workflow_decision_response(
        query=(
            "Plan a multi-sample PBMC workflow with doublet detection, "
            "batch integration, annotation, and trajectory review."
        ),
        constraints={
            "task": "Workflow Planning",
            "modality": "scRNA-seq",
            "data_object": "AnnData",
            "output_goal": "auditable PBMC workflow",
        },
        candidate_tools=["Scanpy", "Scrublet", "Harmony", "CellTypist", "scVelo"],
        rag_fn=fake_rag_fn,
        max_snippets_per_step=2,
    )

    assert response["response_type"] == "workflow_decision_v0_1"
    assert response["metrics"]["workflow_steps"] >= 5
    assert response["metrics"]["retrieval_snippets"] == response["metrics"]["workflow_steps"]
    assert response["metrics"]["source_bound_retrieval_snippets"] == response["metrics"]["workflow_steps"]
    assert response["metrics"]["evidence_boundary_violation_count"] == 0
    assert response["metrics"]["formal_main_recommendation_evidence_count"] == 0
    assert "does not promote formal evidence" in response["guardrail"]
    assert "scKG Workflow Decision Report" in response["markdown_report"]


def test_workflow_decision_next_actions_call_out_missing_retrieval():
    def empty_rag_fn(*, constraints, tool_names, max_snippets):
        return {"mode": "empty", "pipeline": ["fake"], "snippets": []}

    response = build_workflow_decision_response(
        query="Detect doublets in droplet scRNA-seq.",
        constraints={"task": "Doublet Detection", "modality": "scRNA-seq"},
        candidate_tools=["Scrublet", "DoubletFinder"],
        rag_fn=empty_rag_fn,
    )

    assert response["metrics"]["retrieval_snippets"] == 0
    assert "Add source chunks for steps with zero retrieval snippets." in response["next_actions"]


def test_workflow_decision_task_inference():
    assert infer_task_from_query("Convert h5ad to SeuratObject") == "Workflow Compatibility"
    assert infer_task_from_query("Run RNA velocity with spliced layers") == "RNA Velocity"
    assert infer_task_from_query("Remove ambient RNA contamination") == "Ambient RNA Removal"
