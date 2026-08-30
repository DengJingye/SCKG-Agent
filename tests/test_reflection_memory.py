from core.reflection_memory import reflect_agent_run
from core.trace_context import TraceContext


def test_reflection_writes_private_memory_without_authority(tmp_path):
    trace_id = "trace_reflection_test"
    state = {
        "user_query": "recommend integration tool",
        "extracted_constraints": {
            "task": "Data Integration",
            "modality": "scRNA-seq",
            "platform": "10x",
            "species": "human",
            "strictness": "conservative",
        },
        "context_pack": {"missing_evidence": ["benchmark"]},
        "scored_tools": [],
        "migration_paths": [],
        "hallucination_audit": {"passed": True},
    }
    event = reflect_agent_run(
        state,
        trace_id,
        reflection_log=tmp_path / "reflection_events.jsonl",
        memory_db=tmp_path / "project_memory.sqlite",
        skill_candidates_dir=tmp_path / "skill_candidates",
    )

    assert event.can_affect_scientific_authority is False
    assert event.trace_id == trace_id
    assert event.memory_events
    assert all(item.can_affect_scientific_authority is False for item in event.memory_events)
    assert (tmp_path / "project_memory.sqlite").exists()
    assert list((tmp_path / "skill_candidates").glob("*.md"))
    assert not (tmp_path / "tool_publications.tsv").exists()
    assert not (tmp_path / "tool_benchmarks.tsv").exists()


def test_legacy_reflection_compatibility_consumes_only_trace_id(tmp_path):
    trace = TraceContext(metadata={"query": "must-not-be-used-as-query"})
    event = reflect_agent_run(
        {
            "user_query": "business query",
            "context_pack": {},
            "hallucination_audit": {"passed": True},
        },
        trace,
        reflection_log=tmp_path / "reflection_events.jsonl",
        memory_db=tmp_path / "project_memory.sqlite",
        skill_candidates_dir=tmp_path / "skill_candidates",
    )
    assert event.trace_id == trace.trace_id
    assert event.user_query == "business query"
