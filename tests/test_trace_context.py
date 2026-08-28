import json
import threading
from copy import deepcopy

import pytest

from core.trace_context import (
    MAX_REFS,
    TRACE_SCHEMA_VERSION,
    DecisionEvidence,
    TraceCollector,
    TraceContext,
    TraceKind,
    TraceLink,
    TraceLinkType,
    TraceRecordRef,
    TracePersistenceError,
    TraceStage,
    TraceStateError,
    TraceStatus,
    TraceValidationError,
    _validate_v0,
    load_traces,
)


def _valid_v0_row(request_id="validator-request"):
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id=request_id,
    )
    with trace.span(
        stage=TraceStage.ROUTING,
        component="router",
        operation="route",
    ):
        pass
    trace.finish()
    return trace.to_dict()


def _assert_invalid_v0(row):
    with pytest.raises(TraceValidationError):
        _validate_v0(row)


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


def test_legacy_collector_still_auto_finalizes_and_allows_repeated_collect(tmp_path):
    path = tmp_path / "legacy.jsonl"
    trace = TraceContext(metadata={"query": "legacy lifecycle"})
    collector = TraceCollector(path)
    collector.collect(trace)
    collector.collect(trace)
    rows = load_traces(path)
    assert len(rows) == 2
    assert trace.finished_at is not None
    assert all(row["metadata"]["query"] == "legacy lifecycle" for row in rows)


def test_v0_context_emits_owned_monotonic_spans_and_finalized_jsonl(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="research-request-01",
        conversation_id="conversation-01",
        links=[
            TraceLink(
                TraceLinkType.UNIFIED_AGENT_TRACE,
                "agent_run_trace",
                "agent-trace:abc123",
            )
        ],
    )
    collector = TraceCollector(trace_path)
    with collector.request_scope(trace):
        with trace.span(
            stage=TraceStage.ROUTING,
            component="research_chat_service",
            operation="resolve_route",
        ) as routing:
            routing.add_decision(
                DecisionEvidence(
                    decision_type="ROUTE",
                    outcome="PLAN",
                    reason_code="explicit_plan_intent",
                    rule_version="research-routing-v1",
                )
            )
            with trace.span(
                stage=TraceStage.RETRIEVAL,
                component="hybrid_retrieval",
                operation="retrieve",
                parent=routing,
            ) as retrieval:
                retrieval.add_output_ref(
                    TraceRecordRef("retrieval_result", "request:result-01", "produced")
                )
                retrieval.set_counter("candidate_count", 3)

    rows = load_traces(trace_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema_version"] == "sckg-trace-v0"
    assert row["status"] == "SUCCESS"
    assert [span["sequence"] for span in row["spans"]] == [1, 2, 3]
    assert row["spans"][2]["parent_span_id"] == row["spans"][1]["span_id"]
    assert trace.collected is True


def test_v0_guards_finalize_collect_parent_and_double_finish(tmp_path):
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="research-request-02",
    )
    collector = TraceCollector(tmp_path / "traces.jsonl")
    with pytest.raises(TraceStateError, match="finalize"):
        collector.collect(trace)

    other = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="research-request-other",
    )
    with trace.span(
        stage=TraceStage.ROUTING,
        component="router",
        operation="route",
    ) as routing:
        with pytest.raises(TraceStateError, match="parent"):
            trace.span(
                stage=TraceStage.RETRIEVAL,
                component="retriever",
                operation="retrieve",
                parent=other.span(
                    stage=TraceStage.ROUTING,
                    component="router",
                    operation="route",
                ),
            )
        routing.succeed()
        with pytest.raises(TraceStateError, match="active"):
            routing.succeed()

    trace.finish()
    collector.collect(trace)
    with pytest.raises(TraceStateError, match="already collected"):
        collector.collect(trace)


def test_real_repository_id_shapes_are_allowed_but_paths_and_urls_are_not():
    for value in (
        "agent-trace:abc123",
        "trace_f318a7b370ab45d6b1ebc3624f4e9b52",
        "cap-plan-20260827",
        "application-graph:abcd1234",
        "research-chat-a1.b2:c3",
    ):
        TraceRecordRef("logical_record", value, "related")
    for value in ("/tmp/private.json", "https://local.invalid/a", "folder/file"):
        with pytest.raises(TraceValidationError):
            TraceRecordRef("logical_record", value, "related")


def test_mixed_loader_keeps_legacy_and_valid_v0_but_skips_invalid_v0(tmp_path):
    path = tmp_path / "mixed.jsonl"
    legacy = TraceContext(metadata={"query": "legacy compatibility"})
    TraceCollector(path).collect(legacy)
    trace = TraceContext.new_request(trace_kind=TraceKind.RESEARCH, request_id="mixed-v0")
    with TraceCollector(path).request_scope(trace):
        pass
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"schema_version": "sckg-trace-v0", "trace_id": "trace_bad"}) + "\n")
        handle.write("not-json\n")
    rows = load_traces(path)
    assert len(rows) == 2
    assert rows[0]["metadata"]["query"] == "legacy compatibility"
    assert rows[1]["schema_version"] == "sckg-trace-v0"


def test_trace_failures_do_not_replace_primary_business_outcome(tmp_path, monkeypatch):
    class PrimaryBusinessError(RuntimeError):
        pass

    trace = TraceContext.new_request(trace_kind=TraceKind.RESEARCH, request_id="primary-error")
    monkeypatch.setattr(trace, "_finish_request", lambda *args, **kwargs: (_ for _ in ()).throw(TraceStateError("secondary")))
    with pytest.raises(PrimaryBusinessError, match="primary"):
        with TraceCollector(tmp_path / "trace.jsonl").request_scope(trace):
            raise PrimaryBusinessError("primary")
    assert "trace_finalization_failed" in trace.observability_error_codes


def test_persistence_failure_does_not_fail_successful_business_result(tmp_path):
    unwritable_target = tmp_path / "directory-target"
    unwritable_target.mkdir()
    trace = TraceContext.new_request(trace_kind=TraceKind.RESEARCH, request_id="io-failure")
    result = None
    with TraceCollector(unwritable_target).request_scope(trace):
        result = "business-success"
    assert result == "business-success"
    assert trace.status is TraceStatus.SUCCESS
    assert trace.collected is False
    assert "trace_persistence_failed" in trace.observability_error_codes


def test_schema_version_mutation_cannot_switch_v0_to_legacy(tmp_path):
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="mode-v0",
    )
    trace.schema_version = None

    assert trace.is_v0 is True
    with pytest.raises(TraceStateError, match="legacy-only"):
        trace.record_stage("forbidden")
    with pytest.raises(TraceValidationError, match="invariant"):
        trace.finish()

    trace.schema_version = TRACE_SCHEMA_VERSION
    trace.finish()
    trace.schema_version = None
    with pytest.raises(TraceValidationError, match="invariant"):
        trace.to_dict()
    with pytest.raises(TraceValidationError, match="invariant"):
        TraceCollector(tmp_path / "trace.jsonl").collect(trace)


def test_legacy_schema_mutation_cannot_masquerade_as_v0(tmp_path):
    trace = TraceContext(metadata={"query": "legacy"})
    trace.schema_version = TRACE_SCHEMA_VERSION

    assert trace.is_v0 is False
    assert trace.root_span_id is None
    with pytest.raises(TraceValidationError, match="invariant"):
        trace.finish()
    with pytest.raises(TraceValidationError, match="invariant"):
        trace.to_dict()
    with pytest.raises(TraceValidationError, match="invariant"):
        TraceCollector(tmp_path / "legacy.jsonl").collect(trace)


def test_finalized_snapshot_is_independent_from_live_mutation(tmp_path):
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="snapshot-finalized",
    )
    trace.finish()
    canonical = trace.to_dict()

    trace.spans[0].operation = "mutated_after_finalize"
    trace.spans[0].status = TraceStatus.FAILED
    trace.spans[0].counters["mutated"] = 1
    trace.spans[0].decision_evidence.append(
        DecisionEvidence("MUTATION", "IGNORED", "post_finalize", "test-v1")
    )
    trace.links.append(
        TraceLink(TraceLinkType.RELATED_TRACE, "trace", "trace_mutated")
    )

    assert trace.to_dict() == canonical
    path = tmp_path / "snapshot.jsonl"
    TraceCollector(path).collect(trace)
    assert load_traces(path) == [canonical]


def test_collected_snapshot_remains_canonical_after_live_mutation(tmp_path):
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="snapshot-collected",
    )
    trace.finish()
    canonical = trace.to_dict()
    path = tmp_path / "snapshot.jsonl"
    TraceCollector(path).collect(trace)

    trace.spans[0].component = "mutated_after_collect"
    trace.spans[0].input_refs.append(
        TraceRecordRef("logical_record", "trace_mutation", "related")
    )

    assert trace.to_dict() == canonical
    assert load_traces(path) == [canonical]


def test_strict_mutators_reject_after_finalize():
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="finalized-mutators",
    )
    trace.finish()

    with pytest.raises(TraceStateError, match="finalized"):
        trace.span(
            stage=TraceStage.ROUTING,
            component="router",
            operation="route",
        )
    with pytest.raises(TraceStateError, match="finalized"):
        trace.add_link(
            TraceLink(TraceLinkType.RELATED_TRACE, "trace", "trace_related")
        )
    with pytest.raises(TraceStateError, match="finalized"):
        trace.set_request_outcome(TraceStatus.SUCCESS)


def test_safe_emission_failure_preserves_successful_business_result(tmp_path):
    invalid_value = "/private/result"
    path = tmp_path / "safe.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="safe-success",
    )
    result = None
    with TraceCollector(path).request_scope(trace):
        with trace.instrumentation().span(
            stage=TraceStage.ROUTING,
            component="router",
            operation="route",
        ) as span:
            result = "business-success"
            assert span.record is not None
            assert span.add_output_ref(
                record_type="result",
                record_id=invalid_value,
                relation="produced",
            ) is False

    assert result == "business-success"
    assert trace.status is TraceStatus.SUCCESS
    assert trace.collected is True
    assert "trace_emission_rejected" in trace.observability_error_codes
    assert invalid_value not in path.read_text(encoding="utf-8")


def test_safe_invalid_ref_preserves_original_business_exception(tmp_path):
    class PrimaryBusinessError(RuntimeError):
        pass

    invalid_value = "/private/business-input.h5ad"
    path = tmp_path / "safe-business-error.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="safe-emission-primary-error",
    )

    with pytest.raises(PrimaryBusinessError, match="primary"):
        with TraceCollector(path).request_scope(trace):
            with trace.instrumentation().span(
                stage=TraceStage.ROUTING,
                component="router",
                operation="route",
            ) as span:
                assert span.record is not None
                assert span.add_input_ref(
                    record_type="dataset",
                    record_id=invalid_value,
                    relation="consumed",
                ) is False
                raise PrimaryBusinessError("primary")

    assert trace.collected is True
    assert "trace_emission_rejected" in trace.observability_error_codes
    assert invalid_value not in path.read_text(encoding="utf-8")


def test_safe_nested_decision_ref_is_constructed_inside_boundary(tmp_path):
    invalid_value = "/private/decision.json"
    path = tmp_path / "safe-decision.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="safe-decision-ref",
    )

    with TraceCollector(path).request_scope(trace):
        with trace.instrumentation().span(
            stage=TraceStage.DECISION,
            component="router",
            operation="select_route",
        ) as span:
            assert span.record is not None
            assert span.add_decision(
                decision_type="ROUTE",
                outcome="PLAN",
                reason_code="selected",
                rule_version="routing-v1",
                record_ref={
                    "record_type": "decision_record",
                    "record_id": invalid_value,
                    "relation": "supports",
                },
            ) is False

    assert trace.collected is True
    assert "trace_emission_rejected" in trace.observability_error_codes
    assert invalid_value not in path.read_text(encoding="utf-8")


def test_safe_request_outcome_ref_is_constructed_inside_boundary(tmp_path):
    invalid_value = "https://private.invalid/outcome"
    path = tmp_path / "safe-outcome.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="safe-outcome-ref",
    )

    with TraceCollector(path).request_scope(trace):
        assert trace.instrumentation().set_request_outcome(
            TraceStatus.BLOCKED,
            decision_type="REQUEST",
            outcome="BLOCKED",
            reason_code="policy_block",
            rule_version="request-v1",
            record_ref={
                "record_type": "policy_record",
                "record_id": invalid_value,
                "relation": "supports",
            },
        ) is False

    assert trace.status is TraceStatus.SUCCESS
    assert trace.collected is True
    assert "trace_emission_rejected" in trace.observability_error_codes
    assert invalid_value not in path.read_text(encoding="utf-8")


def test_safe_input_ref_construction_failure_degrades_to_noop(tmp_path):
    invalid_value = "/private/input.h5ad"
    path = tmp_path / "safe-input-ref.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="safe-input-ref",
    )
    executions = 0

    with TraceCollector(path).request_scope(trace):
        with trace.instrumentation().span(
            stage=TraceStage.ROUTING,
            component="router",
            operation="route",
            input_refs=[
                {
                    "record_type": "dataset",
                    "record_id": invalid_value,
                    "relation": "consumed",
                }
            ],
        ) as span:
            executions += 1
            assert span.record is None

    assert executions == 1
    assert trace.collected is True
    assert "trace_emission_rejected" in trace.observability_error_codes
    assert invalid_value not in path.read_text(encoding="utf-8")


def test_safe_cleanup_failure_preserves_original_business_exception(
    tmp_path, monkeypatch
):
    class PrimaryBusinessError(RuntimeError):
        pass

    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="safe-primary-error",
    )
    with pytest.raises(PrimaryBusinessError, match="primary"):
        with TraceCollector(tmp_path / "safe-error.jsonl").request_scope(trace):
            with trace.instrumentation().span(
                stage=TraceStage.ROUTING,
                component="router",
                operation="route",
            ) as span:
                monkeypatch.setattr(
                    span._strict_scope,
                    "__exit__",
                    lambda *args: (_ for _ in ()).throw(
                        TraceStateError("secondary")
                    ),
                )
                raise PrimaryBusinessError("primary")

    assert "span_cleanup_failed" in trace.observability_error_codes
    assert "trace_finalization_failed" in trace.observability_error_codes


def test_safe_span_degrades_to_noop_when_strict_span_cannot_start(
    tmp_path, monkeypatch
):
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="safe-noop",
    )
    monkeypatch.setattr(
        trace,
        "span",
        lambda **kwargs: (_ for _ in ()).throw(TraceStateError("secondary")),
    )
    executions = 0
    with TraceCollector(tmp_path / "safe-noop.jsonl").request_scope(trace):
        with trace.instrumentation().span(
            stage=TraceStage.ROUTING,
            component="router",
            operation="route",
        ) as span:
            executions += 1
            assert span.record is None
            assert span.set_counter("candidate_count", 1) is False

    assert executions == 1
    assert trace.collected is True
    assert "trace_emission_rejected" in trace.observability_error_codes


def test_valid_v0_has_one_request_root_with_sequence_one():
    row = _valid_v0_row("valid-root")
    _validate_v0(row)
    roots = [span for span in row["spans"] if span["parent_span_id"] is None]
    assert len(roots) == 1
    assert roots[0]["span_id"] == row["root_span_id"]
    assert roots[0]["stage"] == "REQUEST"
    assert roots[0]["sequence"] == 1


def test_validator_rejects_multiple_roots():
    row = _valid_v0_row("multiple-roots")
    row["spans"][1]["parent_span_id"] = None
    _assert_invalid_v0(row)


def test_validator_rejects_dangling_parent():
    row = _valid_v0_row("dangling-parent")
    row["spans"][1]["parent_span_id"] = "span_missing"
    _assert_invalid_v0(row)


def test_validator_rejects_parent_that_does_not_precede_child():
    row = _valid_v0_row("parent-sequence")
    row["spans"][1]["parent_span_id"] = row["spans"][1]["span_id"]
    _assert_invalid_v0(row)


@pytest.mark.parametrize(
    "timestamp",
    ["2026-08-28T10:00:00", "2026-08-28T10:00:00+01:00"],
)
def test_validator_requires_timezone_aware_utc(timestamp):
    row = _valid_v0_row("utc-validation")
    row["spans"][0]["started_at"] = timestamp
    _assert_invalid_v0(row)


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf"), float("-inf"), "1.0", True])
def test_validator_rejects_invalid_duration(duration):
    row = _valid_v0_row("duration-validation")
    row["spans"][1]["duration_ms"] = duration
    _assert_invalid_v0(row)


def test_validator_rejects_out_of_order_serialized_sequences():
    row = _valid_v0_row("sequence-order")
    row["spans"] = list(reversed(row["spans"]))
    _assert_invalid_v0(row)


def test_validator_rejects_extra_span_fields():
    row = _valid_v0_row("span-schema")
    row["spans"][0]["unexpected"] = "value"
    _assert_invalid_v0(row)


@pytest.mark.parametrize(
    "unknown_version",
    ["sckg-trace-v999", "sckg-trace-vo", ""],
)
def test_loader_rejects_unknown_schema_without_legacy_fallback(
    tmp_path, unknown_version
):
    path = tmp_path / "unknown-schema.jsonl"
    legacy = TraceContext(metadata={"query": "legacy"})
    TraceCollector(path).collect(legacy)
    valid = _valid_v0_row("known-schema")
    unknown = deepcopy(valid)
    unknown["schema_version"] = unknown_version
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(unknown) + "\n")
        handle.write(json.dumps(valid) + "\n")

    rows = load_traces(path)
    assert len(rows) == 2
    assert "schema_version" not in rows[0]
    assert rows[1]["schema_version"] == TRACE_SCHEMA_VERSION


def test_concurrent_duplicate_collect_appends_exactly_once(tmp_path, monkeypatch):
    path = tmp_path / "concurrent.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="concurrent-collect",
    )
    trace.finish()
    collector = TraceCollector(path)
    original_append = collector._append_encoded
    append_started = threading.Event()
    release_append = threading.Event()

    def slow_append(encoded):
        append_started.set()
        assert release_append.wait(timeout=5)
        original_append(encoded)

    monkeypatch.setattr(collector, "_append_encoded", slow_append)
    outcomes = []

    def collect_once():
        try:
            collector.collect(trace)
            outcomes.append("success")
        except TraceStateError:
            outcomes.append("state-error")

    first = threading.Thread(target=collect_once)
    second = threading.Thread(target=collect_once)
    first.start()
    assert append_started.wait(timeout=5)
    second.start()
    second.join(timeout=5)
    release_append.set()
    first.join(timeout=5)

    assert sorted(outcomes) == ["state-error", "success"]
    assert path.read_text(encoding="utf-8").count("\n") == 1


def test_collection_reservation_rolls_back_after_io_failure(tmp_path, monkeypatch):
    path = tmp_path / "retry.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="collection-retry",
    )
    trace.finish()
    collector = TraceCollector(path)
    original_append = collector._append_encoded
    attempts = 0

    def fail_once(encoded):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TracePersistenceError("bounded failure")
        original_append(encoded)

    monkeypatch.setattr(collector, "_append_encoded", fail_once)
    with pytest.raises(TracePersistenceError):
        collector.collect(trace)
    assert trace.collected is False
    assert not path.exists()

    collector.collect(trace)
    assert trace.collected is True
    assert path.read_text(encoding="utf-8").count("\n") == 1


def test_live_api_enforces_combined_reference_limit():
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="combined-ref-bound",
    )
    ref = TraceRecordRef("logical_record", "record-bound", "related")
    with trace.span(
        stage=TraceStage.ROUTING,
        component="router",
        operation="route",
        input_refs=[ref] * MAX_REFS,
    ) as span:
        with pytest.raises(TraceValidationError, match="bound"):
            span.add_output_ref(ref)
