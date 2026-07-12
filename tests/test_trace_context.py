from core.trace_context import TraceCollector, TraceContext, load_traces


def test_trace_context_writes_valid_jsonl(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    trace = TraceContext(trace_type="agent_run", metadata={"query": "test"})
    trace.record_stage(
        "trigger",
        method="unit_test",
        output_summary={"accepted": True},
        elapsed_ms=1.25,
    )
    with trace.stage_timer("intent_parse", method="unit_test") as payload:
        payload["output_summary"] = {"task": "Data Integration"}
    TraceCollector(trace_path).collect(trace)

    rows = load_traces(trace_path)
    assert len(rows) == 1
    assert rows[0]["trace_type"] == "agent_run"
    assert rows[0]["elapsed_ms"] >= 0
    assert [stage["stage"] for stage in rows[0]["stages"]] == ["trigger", "intent_parse"]
    assert rows[0]["stages"][1]["data"]["output_summary"]["task"] == "Data Integration"
