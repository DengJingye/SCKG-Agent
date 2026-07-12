from data_pipeline.build_decision_workflow_demo import build_decision_workflow_demo


def test_decision_workflow_demo_builds_plan_only_workflow(tmp_path):
    def fake_search_fn(*, constraints, tool_names, max_snippets):
        return {
            "mode": "unit_test",
            "pipeline": ["fake"],
            "matched_tools": list(tool_names),
            "snippets": [
                {
                    "tool_name": tool_names[0],
                    "source_kind": "source_docs",
                    "title": "Fake source",
                    "source_span": "paragraph:1",
                    "claim_span": "Fake source-bound snippet.",
                    "claim_boundary": "Retrieval only.",
                    "relevance_score": 0.5,
                    "chunk_id": f"fake:{constraints.get('workflow_step')}",
                }
            ],
        }

    demo = build_decision_workflow_demo(
        search_fn=fake_search_fn,
        representation_path=tmp_path / "missing_reps.jsonl",
        algorithm_audit_path=tmp_path / "missing_audit.tsv",
    )

    assert demo["demo"] == "decision_workflow_demo_v1"
    assert demo["global_evidence_coverage"]["workflow_steps"] == 7
    assert demo["global_evidence_coverage"]["formal_main_recommendation_evidence_count"] == 0
    assert demo["global_evidence_coverage"]["status"] == "evidence_limited_plan_only"
    assert demo["workflow_steps"][0]["status"] == "plan_only_evidence_limited"
    assert demo["workflow_steps"][0]["retrieval"]["snippets"][0]["source_kind"] == "source_docs"
    assert "scanpy_python" in demo["code_skeletons"]
