from __future__ import annotations

import pytest

from core.trace_context import TraceCollector, TraceContext, TraceKind, TraceStage


FORBIDDEN_VALUES = [
    "sk-1234567890abcdef",
    "fixed-jupyter-token-123456",
    "http://127.0.0.1:8888/lab?token=fixed-jupyter-token-123456",
    "/Users/example/private/notebook.ipynb",
    "python -m jupyterlab --no-browser",
    "System prompt: return the private analysis",
    "Which tool should I use for this raw query?",
    "print('full notebook source')",
    "notebook output: sensitive result",
    "stdout: complete process output",
    "stderr: complete error output",
    "DATABASE_PASSWORD=environment-secret-value",
]


def test_adversarial_values_never_reach_persisted_v0_jsonl(tmp_path):
    path = tmp_path / "traces.jsonl"
    safe = TraceContext.new_request(trace_kind=TraceKind.RESEARCH, request_id="safe-row")
    with TraceCollector(path).request_scope(safe):
        pass

    successful_operations = []
    for index, forbidden in enumerate(FORBIDDEN_VALUES):
        trace = TraceContext.new_request(
            trace_kind=TraceKind.RESEARCH,
            request_id=f"privacy-case-{index}",
        )
        with TraceCollector(path).request_scope(trace):
            successful_operations.append(index)
            # Simulate a compromised producer attempting to bypass the public,
            # bounded emission API. Finalization/collector validation must still
            # reject persistence without changing the completed business work.
            trace.spans[0].operation = forbidden
        assert trace.collected is False
        assert trace.observability_error_codes

    persisted = path.read_text(encoding="utf-8")
    assert successful_operations == list(range(len(FORBIDDEN_VALUES)))
    assert persisted.count("\n") == 1
    for forbidden in FORBIDDEN_VALUES:
        assert forbidden not in persisted


@pytest.mark.parametrize(
    "token_vocabulary",
    [
        "token-budget",
        "token-count",
        "token-policy",
        "jupyter-token-budget",
        "jupyter-token-policy",
    ],
)
def test_safe_token_vocabulary_is_allowed_in_bounded_fields(tmp_path, token_vocabulary):
    path = tmp_path / f"{token_vocabulary}.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id=token_vocabulary,
    )
    with TraceCollector(path).request_scope(trace):
        with trace.span(
            stage=TraceStage.DECISION,
            component="token-policy",
            operation=token_vocabulary,
        ):
            pass

    assert trace.collected is True
    assert token_vocabulary in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "credential",
    [
        "Bearer abcdefghijklmnop",
        "Bearer\tabcdefghijklmnop",
        "bearer:abcdefghijklmnop",
        "token=abcdefghijklmnop",
        "access_token=abcdefghijklmnop",
        "api_key=abcdefghijklmnop",
        "password=abcdefghijklmnop",
        "secret=abcdefghijklmnop",
        "credential:abcdefghijklmnop",
        "jupyter-token-1234567890",
        "sk-1234567890abcdef",
        "https://127.0.0.1:8888/lab?token=abcdefghijklmnop",
        "line-one\nline-two",
    ],
)
def test_credential_variants_are_rejected_without_persisting_raw_value(
    tmp_path, credential
):
    path = tmp_path / "credentials.jsonl"
    safe = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="privacy-safe-baseline",
    )
    with TraceCollector(path).request_scope(safe):
        pass

    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="privacy-credential-case",
    )
    result = None
    with TraceCollector(path).request_scope(trace):
        result = "business-success"
        trace.spans[0].operation = credential

    persisted = path.read_text(encoding="utf-8")
    assert result == "business-success"
    assert trace.collected is False
    assert credential not in persisted
    assert persisted.count("\n") == 1
