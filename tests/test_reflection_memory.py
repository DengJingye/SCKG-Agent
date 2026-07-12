from core.reflection_memory import reflect_agent_run
from core.trace_context import TraceContext


def test_reflection_writes_private_memory_without_authority(tmp_path):
    trace = TraceContext(trace_type="agent_run", metadata={"query": "recommend integration tool"})
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
        trace,
        reflection_log=tmp_path / "reflection_events.jsonl",
        memory_db=tmp_path / "project_memory.sqlite",
        skill_candidates_dir=tmp_path / "skill_candidates",
    )

    assert event.can_affect_scientific_authority is False
    assert event.memory_events
    assert all(item.can_affect_scientific_authority is False for item in event.memory_events)
    assert (tmp_path / "project_memory.sqlite").exists()
    assert list((tmp_path / "skill_candidates").glob("*.md"))
    assert not (tmp_path / "tool_publications.tsv").exists()
    assert not (tmp_path / "tool_benchmarks.tsv").exists()
