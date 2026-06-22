from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.constraints import parse_research_constraints
from core.evidence_policy import audit_evidence, is_main_recommendation_evidence
from core.models import (
    Evidence,
    EvidenceBundle,
    EvidenceContextPack,
    MigrationPath,
    ScoredTool,
    ToolCandidate,
    WorkflowRecommendation,
    derived_evidence,
    github_evidence,
)
from engine.context_pack_builder import build_evidence_context_pack


def main() -> None:
    constraints = parse_research_constraints(
        {"task": "Spatial Deconvolution", "modality": "Spatial Transcriptomics"},
        user_query="Need a trusted spatial deconvolution recommendation and benchmark DOI.",
    ).model_dump(mode="json")

    trusted_benchmark = Evidence(
        evidence_id="e1",
        source_type="benchmark",
        source_title="Benchmark paper",
        metric_name="benchmark_result",
        metric_value="top-tier",
        dataset_scope="smoke dataset",
        evidence_strength="strong",
        confidence=0.9,
        trust_level="verified",
        graph_layer="trusted_core",
        use_for=["retrieval", "recommendation"],
        extraction_method="human_review",
        review_status="human_reviewed",
    )
    retr_only_docs = github_evidence(
        tool_name="cell2location",
        metric_name="github_stars",
        metric_value=1000,
    )
    bundle = EvidenceBundle(items=[trusted_benchmark, retr_only_docs], missing_evidence=["benchmark", "literature"])
    tool = ScoredTool(
        tool_name="cell2location",
        score=0.8,
        rank=1,
        evidence=bundle,
        evidence_breakdown={"note": "smoke"},
        recommendation_confidence="high",
    )
    migration = MigrationPath(
        tool_name="moscot",
        score=0.42,
        features="exploratory",
        source_task="Optimal Transport Trajectory",
        target_task="Spatial Deconvolution",
        transferable_mechanism="FGW coupling",
        compatibility_gaps=["needs tuned cost matrix"],
        reviewer_decision="accept_exploratory",
        evidence=EvidenceBundle(
            items=[
                derived_evidence(
                    evidence_id="mig1",
                    metric_name="migration_plausibility_score",
                    metric_value=0.42,
                    extraction_method="smoke",
                    source_title="Migration hypothesis",
                    confidence=0.5,
                    trust_level="inferred",
                    graph_layer="experimental",
                    evidence_strength="exploratory",
                    use_for=["retrieval"],
                )
            ],
            missing_evidence=["full_benchmark_validation"],
        ),
    )
    workflow = WorkflowRecommendation(
        name="spatial workflow",
        steps=[],
        evidence=EvidenceBundle(items=[trusted_benchmark], missing_evidence=[]),
    )
    pack = build_evidence_context_pack(
        user_query="Need a trusted spatial deconvolution recommendation and benchmark DOI.",
        constraints=constraints,
        recommendation_type="workflow",
        scored_tools=[tool],
        tool_candidates=[ToolCandidate(tool_name="cell2location", evidence=bundle)],
        workflow=workflow,
        migration_paths=[migration],
        evidence_bundle=bundle,
        missing_components=["benchmark", "literature"],
        blocked_tools=["Scanpy"],
    )

    assert pack.trusted_recommendation_context["can_rank"] is True
    assert any(item["context_role"] == "trusted_recommendation" for item in pack.trusted_recommendation_context["evidence_items"])
    assert all(not item["context_can_rank"] for item in pack.retrieval_context["evidence_items"])
    assert pack.migration_context["can_rank"] is False
    assert pack.migration_context["accepted_decisions"] == ["accept_exploratory"]
    assert "Scanpy" in pack.blocked_context["blocked_tools"]
    assert "benchmark" in pack.missing_evidence
    assert pack.prompt_policy["forbidden"]
    assert is_main_recommendation_evidence(trusted_benchmark)
    assert audit_evidence(bundle).has_main_recommendation_evidence

    print("context_pack_v0_12_smoke_ok")


if __name__ == "__main__":
    main()
