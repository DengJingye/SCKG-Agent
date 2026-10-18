"""Synthetic integration checks, not scientific evaluation gold."""
import json

import pytest

from sckg_workbench.catalog import Catalog
from sckg_workbench.model_service import ModelService
from sckg_workbench.sources import SourceService
from sckg_workbench.storage import Ledger, Workspace
from sckg_workbench.worker import Worker


PASSPHRASE = "synthetic-test-passphrase"
REQUEST = {"max_input_tokens": 64000, "max_output_tokens": 4000, "timeout_seconds": 5}
BUDGET = {"max_calls": 5, "max_tokens": 256000, "max_cost": 3}


def response(value, usage=True):
    result = {"model": "fixture-model-version", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]}
    if usage:
        result["usage"] = {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}
    return result


def extraction(payload, *, wrong_quote=False):
    ir = json.loads(payload["messages"][-1]["content"])["document"]
    b = ir["blocks"][0]
    quote = b["exact_text"]
    if wrong_quote:
        quote = "X" + quote[1:]
    return {"units": [{"proposition": "Fixture A has property B under condition C.", "subject": "Fixture A", "predicate": "has",
                       "object": "property B", "polarity": "positive", "conditions": ["condition C"],
                       "unknowns": ["Other conditions were not measured"], "assertion_kind": "source_assertion",
                       "anchors": [{"ir_id": ir["id"], "block_id": b["id"], "start": 0, "end": len(quote), "quote": quote}],
                       "proposed_terms": ["Fixture A"], "model_self_score": .8}], "gaps": [], "source_summary": "Synthetic fixture only"}


ASSESSMENT = {"relation": "support", "extent": "full", "rationale": "Synthetic quoted text explicitly states the scoped claim.", "limitations": []}


def build_fixture(tmp_path, *, mutate=None):
    ledger = Ledger(Workspace(tmp_path / "workbench"))
    source = SourceService(ledger).register_bytes("fixture.md", b"Fixture A has property B under condition C.")
    calls = []
    def transport(url, headers, payload, timeout):
        calls.append(payload)
        result = extraction(payload) if payload["model"] == "extract-fixture" else ASSESSMENT
        if mutate:
            return mutate(payload, result, calls)
        return response(result)
    models = ModelService(ledger.workspace, ledger, transport=transport)
    connection = models.create_connection("Fixture", "https://fixture.invalid/v1", "fake-test-key", PASSPHRASE)
    profiles = [models.create_profile(kind, kind, connection["id"], model, input_usd_per_million=1, output_usd_per_million=1)
                for kind, model in [("extraction", "extract-fixture"), ("assessment", "assess-fixture")]]
    worker = Worker(ledger, models)
    return worker, ledger, source, profiles, calls


def submit(worker, source, profiles, *, budget=None):
    return worker.submit_ingestion(source["id"], profiles[0]["id"], profiles[1]["id"],
                                   budget=budget or BUDGET, request_budget=REQUEST, idempotency_key="fixture-run")


def test_full_offline_production_review_publish_suspend_restart(tmp_path):
    worker, ledger, source, profiles, calls = build_fixture(tmp_path)
    first = submit(worker, source, profiles)
    assert submit(worker, source, profiles)["task_id"] == first["task_id"]
    result = worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert result["status"] == "succeeded", result
    assert len(calls) == 2 and result["usage"]["tokens"]["known"] == 280
    assert result["usage"]["cost"]["known"] == pytest.approx(.00028)
    assert worker.knowledge.search("Fixture").units == []
    candidate = worker.knowledge.list_candidates()[0]
    assert candidate["assessment"]["result"] == ASSESSMENT and candidate["review"] is None
    worker.knowledge.review(candidate["id"], actor="test reviewer", decision="approve", allowed_uses=["explanation"],
                            reason="Synthetic test assertion only", expected_hash=candidate["content_hash"],
                            expected_assessment_id=candidate["assessment"]["id"])
    release = worker.knowledge.publish([candidate["id"]], actor="test reviewer")
    package = Worker(Ledger(ledger.workspace)).knowledge.search("Fixture")
    assert package.release_id == release["id"] and len(package.units) == 1
    assert package.units[0]["evidence"][0]["quote"] == "Fixture A has property B under condition C."
    worker.knowledge.suspend("source", source["id"], actor="test reviewer", reason="Synthetic recall")
    worker.knowledge.rollback(release["id"], actor="test reviewer", reason="Exercise rollback")
    assert not worker.knowledge.search("Fixture").units
    assert Catalog(ledger).ledger.list_records("development_use")


def test_env_worker_extracts_and_verifies_without_vault_unlock(tmp_path, monkeypatch):
    worker, ledger, source, _, calls = build_fixture(tmp_path)
    env_file = tmp_path / "synthetic.env"
    env_file.write_text("DCS_KEY=synthetic-provider-key\n")
    connection = worker.models.create_env_connection("DCS fixture", "https://fixture.invalid/v1", env_file, "DCS_KEY")
    profiles = [worker.models.create_profile(kind, kind, connection["id"], model,
                    input_usd_per_million=1, output_usd_per_million=1)
                for kind, model in [("extraction", "extract-fixture"), ("assessment", "assess-fixture")]]
    task = submit(worker, source, profiles)
    def forbidden(*args, **kwargs):
        raise AssertionError("Environment credentials must not unlock the vault")
    monkeypatch.setattr(worker.models.vault, "unlock", forbidden)
    assert not worker.requires_passphrase()
    result = worker.run_once(outbound_authorized=True)
    assert result["task_id"] == task["task_id"] and result["status"] == "succeeded"
    assert len(calls) == 2 and all(payload["stream"] is False for payload in calls)


def test_invalid_env_credential_keeps_task_queued_before_any_model_call(tmp_path):
    worker, ledger, source, _, calls = build_fixture(tmp_path)
    env_file = tmp_path / "synthetic.env"
    env_file.write_text("DCS_KEY=synthetic-provider-key\n")
    connection = worker.models.create_env_connection("DCS fixture", "https://fixture.invalid/v1", env_file, "DCS_KEY")
    profiles = [worker.models.create_profile(kind, kind, connection["id"], model,
                    input_usd_per_million=1, output_usd_per_million=1)
                for kind, model in [("extraction", "extract-fixture"), ("assessment", "assess-fixture")]]
    task = submit(worker, source, profiles)
    env_file.write_text("OTHER_KEY=not-the-credential\n")
    with pytest.raises(ValueError, match="Credential file"):
        worker.run_once(outbound_authorized=True)
    found = worker.queue.get(task["task_id"])
    assert found["status"] == "queued" and found["attempt"] == 0
    assert calls == [] and ledger.list_records("model_request") == []


def test_malformed_quote_cannot_be_assessed_or_published(tmp_path):
    def mutate(payload, result, calls):
        return response(extraction(payload, wrong_quote=True))
    worker, _, source, profiles, calls = build_fixture(tmp_path, mutate=mutate)
    submit(worker, source, profiles)
    result = worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert result["status"] == "partial" and len(calls) == 1
    assert result["result"]["rejected"] and not worker.knowledge.list_candidates()


def test_budget_stops_before_second_call_and_retains_unassessed_candidate(tmp_path):
    worker, _, source, profiles, calls = build_fixture(tmp_path)
    submit(worker, source, profiles, budget={**BUDGET, "max_calls": 1})
    result = worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert result["status"] == "partial" and len(calls) == 1
    assert result["error"]["type"] == "BudgetExceeded"
    assert worker.knowledge.list_candidates()[0]["assessment"] is None
    assert not worker.knowledge.search("").units


def test_unknown_usage_stops_further_calls_instead_of_free_cost(tmp_path):
    worker, _, source, profiles, calls = build_fixture(tmp_path, mutate=lambda p, r, c: response(r, usage=False))
    submit(worker, source, profiles)
    result = worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert result["status"] == "failed" and len(calls) == 1
    assert result["usage"]["tokens"]["unknown"] and result["usage"]["cost"]["unknown"]
    assert not worker.knowledge.list_candidates()


def test_failed_assessment_resume_reuses_completed_extraction(tmp_path):
    def mutate(payload, result, calls):
        if len(calls) == 2:
            return response({"malformed": "assessment"})
        return response(result)
    worker, _, source, profiles, calls = build_fixture(tmp_path, mutate=mutate)
    task = submit(worker, source, profiles)
    result = worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert result["status"] == "partial" and result["usage"]["calls"]["known"] == 2
    assert not result["usage"]["tokens"]["unknown"]  # malformed JSON schema still has real usage
    worker.queue.retry(task["task_id"], confirm_no_duplicate=True)
    retried = worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert retried["status"] == "succeeded" and len(calls) == 3
    assert sum(p["model"] == "extract-fixture" for p in calls) == 1
    assert len(worker.knowledge.list_candidates()) == 1 and retried["usage"]["calls"]["known"] == 3


def test_timeout_unknown_has_no_automatic_retry(tmp_path):
    def mutate(*args):
        raise TimeoutError("provider failed")
    worker, _, source, profiles, calls = build_fixture(tmp_path, mutate=mutate)
    submit(worker, source, profiles)
    result = worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert result["status"] == "result_unknown" and result["usage"]["cost"]["unknown"]
    assert worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True) is None and len(calls) == 1


def test_no_authorization_no_claim_or_outbound(tmp_path):
    worker, _, source, profiles, calls = build_fixture(tmp_path)
    task = submit(worker, source, profiles)
    with pytest.raises(ValueError, match="Authorize"):
        worker.run_once(passphrase=PASSPHRASE, outbound_authorized=False)
    assert worker.queue.get(task["task_id"])["status"] == "queued" and not calls


def test_cancellation_after_return_retains_usage_not_candidate(tmp_path):
    state = {}
    def mutate(payload, result, calls):
        state["worker"].queue.request_cancel(state["task"]["task_id"])
        return response(result)
    worker, _, source, profiles, calls = build_fixture(tmp_path, mutate=mutate)
    state.update(worker=worker, task=submit(worker, source, profiles))
    result = worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert result["status"] == "cancelled" and len(calls) == 1
    assert result["usage"]["calls"]["known"] == 1 and not worker.knowledge.list_candidates()


def test_holdout_cannot_be_submitted(tmp_path):
    worker, ledger, source, profiles, calls = build_fixture(tmp_path)
    Catalog(ledger).freeze_split([{"source_id": source["id"], "work_family": "synthetic-family", "partition": "holdout",
                                   "prior_development_use": False}], reviewer="Fixture reviewer")
    with pytest.raises(ValueError):
        submit(worker, source, profiles)
    assert not calls and not worker.queue.list()


def test_expired_lease_during_model_failure_returns_recoverable_state(tmp_path):
    clock = [1000.0]
    def mutate(*args):
        clock[0] += 1000
        raise TimeoutError("remote outcome unknown")
    worker, _, source, profiles, calls = build_fixture(tmp_path, mutate=mutate)
    worker.queue._clock = lambda: clock[0]
    submit(worker, source, profiles)
    result = worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert result["status"] == "result_unknown" and len(calls) == 1
    assert result["error"]["reason"] == "lease_expired" and not worker.knowledge.list_candidates()
