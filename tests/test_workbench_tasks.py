from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from sckg_workbench.storage import Workspace
from sckg_workbench.tasks import (
    BudgetExceeded, IdempotencyConflict, InvalidTransition, LeaseLost,
    TaskError, TaskQueue,
)


BUDGET = {"max_calls": 3, "max_tokens": 100, "max_cost": 0.5}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def setup_queue(tmp_path):
    clock = Clock()
    workspace = Workspace(tmp_path / "isolated")
    return TaskQueue(workspace, clock=clock), workspace, clock


def submit(queue, key="one", **overrides):
    args = {"kind": "extract", "input_snapshot": {"source": "source-new", "hash": "abc"},
            "profile_snapshot": {"model": "test-only", "prompt_revision": "p1"},
            "budget": BUDGET.copy(), "idempotency_key": key}
    args.update(overrides)
    return queue.submit(**args)


def test_restart_snapshots_and_real_checkpoint_events(setup_queue):
    queue, workspace, clock = setup_queue
    inputs = {"sources": ["new-source"]}
    task = submit(queue, input_snapshot=inputs)
    inputs["sources"].append("mutated-after-submit")
    claimed = queue.claim("worker-a")
    assert claimed["task_id"] == task["task_id"]
    queue.checkpoint(task["task_id"], claimed["fencing_token"], "parsed",
                     {"pages_completed": 2, "artifact_id": "new-ir"}, usage={"tokens": 20})
    del queue
    restarted = TaskQueue(workspace, clock=clock)
    found = restarted.get(task["task_id"])
    assert found["input_snapshot"] == {"sources": ["new-source"]}
    assert found["checkpoint"] == {"stage": "parsed", "detail": {"pages_completed": 2, "artifact_id": "new-ir"}}
    assert found["status"] == "running"
    assert found["usage"]["tokens"] == {"known": 20, "unknown": False}
    assert [e["event_type"] for e in restarted.events(task["task_id"])] == ["submitted", "claimed", "checkpoint"]
    assert [e["event_type"] for e in restarted.ledger.events(task["task_id"])] == ["task.submitted", "task.claimed", "task.checkpoint"]
    assert restarted.ledger.get_record("task_submission", task["task_id"])["input_snapshot"] == {"sources": ["new-source"]}


def test_credential_preflight_peek_and_exact_claim_preserve_queue_order(setup_queue):
    queue, _, clock = setup_queue
    first = submit(queue, key="first")
    clock.now += 1
    second = submit(queue, key="second")
    assert queue.peek_next()["task_id"] == first["task_id"]
    assert queue.get(first["task_id"])["attempt"] == 0
    assert queue.claim("worker", expected_task_id=second["task_id"]) is None
    claimed = queue.claim("worker", expected_task_id=first["task_id"])
    assert claimed["task_id"] == first["task_id"]
    assert queue.peek_next() is None
    queue.finish(first["task_id"], claimed["fencing_token"], "succeeded")
    assert queue.peek_next()["task_id"] == second["task_id"]


def test_idempotency_survives_restart_and_payload_change_conflicts(setup_queue):
    queue, workspace, clock = setup_queue
    original = submit(queue)
    repeated = submit(TaskQueue(workspace, clock=clock))
    assert repeated["task_id"] == original["task_id"]
    for change in ({"kind": "parse"}, {"input_snapshot": {"source": "other"}},
                   {"profile_snapshot": {"model": "changed"}}, {"budget": {**BUDGET, "max_calls": 4}}):
        with pytest.raises(IdempotencyConflict):
            submit(queue, **change)
    assert len(queue.list()) == 1
    assert len(queue.events(original["task_id"])) == 1


def test_concurrent_submit_and_claim_use_one_record_and_one_worker(setup_queue):
    queue, workspace, clock = setup_queue
    # Construct distinct clients before racing so this tests queue arbitration.
    clients = [TaskQueue(workspace, clock=clock) for _ in range(6)]
    barrier = Barrier(len(clients))

    def simultaneous_submit(client):
        barrier.wait()
        return submit(client)["task_id"]

    with ThreadPoolExecutor(max_workers=len(clients)) as pool:
        identifiers = list(pool.map(simultaneous_submit, clients))
    assert len(set(identifiers)) == 1
    submit(queue, key="another")
    barrier = Barrier(len(clients))

    def simultaneous_claim(pair):
        index, client = pair
        barrier.wait()
        return client.claim(f"worker-{index}")

    with ThreadPoolExecutor(max_workers=len(clients)) as pool:
        results = list(pool.map(simultaneous_claim, enumerate(clients)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert len(queue.list("running")) == 1
    assert len(queue.list("queued")) == 1


def test_expired_lease_becomes_unknown_and_is_not_automatically_retried(setup_queue):
    queue, workspace, clock = setup_queue
    task = submit(queue)
    first = queue.claim("old", lease_seconds=5)
    queue.checkpoint(task["task_id"], first["fencing_token"], "call_started", {"request_id": "request-1"},
                     usage={"calls": 1})
    clock.now += 6
    restarted = TaskQueue(workspace, clock=clock)
    assert restarted.recover_expired() == [task["task_id"]]
    assert restarted.recover_expired() == []
    assert restarted.claim("replacement") is None
    expired = restarted.get(task["task_id"])
    assert expired["status"] == "result_unknown"
    assert expired["usage"]["calls"] == {"known": 1, "unknown": True}
    assert expired["budget_status"] == "usage_unknown"
    for operation in (
        lambda: queue.finish(task["task_id"], first["fencing_token"], "succeeded", {"late": True}),
        lambda: queue.checkpoint(task["task_id"], first["fencing_token"], "late", {}),
        lambda: queue.heartbeat(task["task_id"], first["fencing_token"]),
    ):
        with pytest.raises(LeaseLost):
            operation()
    assert restarted.get(task["task_id"])["result"] is None


def test_retry_requires_confirmation_fences_old_attempt_and_preserves_usage(setup_queue):
    queue, _, _ = setup_queue
    task = submit(queue)
    first = queue.claim("worker")
    queue.finish(task["task_id"], first["fencing_token"], "partial", result={"completed": ["chunk-a"]},
                 usage={"calls": 1, "tokens": 10, "cost": 0.1})
    with pytest.raises(InvalidTransition):
        queue.retry(task["task_id"])
    retried = queue.retry(task["task_id"], confirm_no_duplicate=True)
    assert retried["status"] == "queued"
    assert retried["result"] is None
    second = queue.claim("worker")
    assert second["attempt"] == 2
    assert second["fencing_token"] != first["fencing_token"]
    with pytest.raises(LeaseLost):
        queue.finish(task["task_id"], first["fencing_token"], "succeeded")
    final = queue.finish(task["task_id"], second["fencing_token"], "succeeded", result={"completed": ["chunk-a", "chunk-b"]},
                         usage={"calls": 1, "tokens": 30, "cost": 0.2})
    assert final["usage"]["cost"] == {"known": 0.3, "unknown": False}
    assert final["usage"]["calls"]["known"] == 2
    assert final["attempt"] == 2
    retry_event = next(e for e in queue.events(task["task_id"]) if e["event_type"] == "retry_requested")
    assert retry_event["detail"]["previous_result"] == {"completed": ["chunk-a"]}
    with pytest.raises(InvalidTransition):
        queue.retry(task["task_id"], confirm_no_duplicate=True)


@pytest.mark.parametrize("status", ["failed", "partial", "result_unknown"])
def test_only_explicit_retryable_terminal_states_can_be_retried(setup_queue, status):
    queue, _, _ = setup_queue
    task = submit(queue)
    claimed = queue.claim("worker")
    queue.finish(task["task_id"], claimed["fencing_token"], status, error={"reason": "fixture"})
    assert queue.retry(task["task_id"], confirm_no_duplicate=True)["status"] == "queued"


def test_cancel_before_claim_is_terminal_and_running_cancel_is_advisory(setup_queue):
    queue, _, _ = setup_queue
    queued = submit(queue)
    assert queue.request_cancel(queued["task_id"])["status"] == "cancelled"
    assert queue.claim("worker") is None
    with pytest.raises(InvalidTransition):
        queue.retry(queued["task_id"], confirm_no_duplicate=True)
    running = submit(queue, key="running")
    claimed = queue.claim("worker")
    cancellation = queue.request_cancel(running["task_id"])
    assert cancellation["status"] == "cancel_requested"
    assert cancellation["fencing_token"] == claimed["fencing_token"]
    assert queue.claim("another") is None
    with pytest.raises(InvalidTransition):
        queue.finish(running["task_id"], claimed["fencing_token"], "succeeded")
    with pytest.raises(InvalidTransition):
        queue.check_budget(running["task_id"], claimed["fencing_token"], {"calls": 1, "tokens": 1, "cost": 0})
    finished = queue.finish(running["task_id"], claimed["fencing_token"], "cancelled",
                            usage={"calls": 1, "tokens": None, "cost": None})
    assert finished["status"] == "cancelled"
    assert finished["usage"]["tokens"] == {"known": 0, "unknown": True}
    assert queue.request_cancel(running["task_id"])["status"] == "cancelled"


def test_heartbeat_extends_lease_without_claiming_progress(setup_queue):
    queue, _, clock = setup_queue
    task = submit(queue)
    claimed = queue.claim("worker", lease_seconds=5)
    clock.now += 4
    queue.heartbeat(task["task_id"], claimed["fencing_token"], lease_seconds=10)
    clock.now += 2
    assert queue.recover_expired() == []
    found = queue.get(task["task_id"])
    assert found["checkpoint"] is None
    assert found["lease_expires_at"] == 1014
    assert queue.events(task["task_id"])[-1]["event_type"] == "heartbeat"


@pytest.mark.parametrize("budget", [
    None, {}, {"max_calls": 1, "max_tokens": 10}, {**BUDGET, "extra": 1},
    {**BUDGET, "max_calls": True}, {**BUDGET, "max_calls": 1.5},
    {**BUDGET, "max_tokens": -1}, {**BUDGET, "max_tokens": "100"},
    {**BUDGET, "max_cost": float("nan")}, {**BUDGET, "max_cost": float("inf")},
    {**BUDGET, "max_cost": -0.01}, {**BUDGET, "max_cost": False},
])
def test_invalid_budgets_never_create_tasks(setup_queue, budget):
    queue, _, _ = setup_queue
    with pytest.raises(TaskError):
        submit(queue, budget=budget)
    assert queue.list() == []


def test_zero_budget_is_explicit_and_actual_overspend_is_not_hidden(setup_queue):
    queue, _, _ = setup_queue
    task = submit(queue, budget={"max_calls": 0, "max_tokens": 0, "max_cost": 0})
    claimed = queue.claim("worker")
    assert queue.check_budget(task["task_id"], claimed["fencing_token"], {"calls": 0, "tokens": 0, "cost": 0})["allowed"]
    with pytest.raises(BudgetExceeded):
        queue.check_budget(task["task_id"], claimed["fencing_token"], {"calls": 1, "tokens": 0, "cost": 0})
    recorded = queue.checkpoint(task["task_id"], claimed["fencing_token"], "unexpected_provider_usage", {}, usage={"cost": 0.1})
    assert recorded["budget_status"] == "exceeded"
    assert recorded["usage"]["cost"]["known"] == 0.1


def test_unknown_usage_cannot_be_treated_as_zero_budget_after_retry(setup_queue):
    queue, _, _ = setup_queue
    task = submit(queue)
    claimed = queue.claim("worker")
    queue.finish(task["task_id"], claimed["fencing_token"], "result_unknown")
    queue.retry(task["task_id"], confirm_no_duplicate=True)
    claimed = queue.claim("worker")
    with pytest.raises(BudgetExceeded):
        queue.check_budget(task["task_id"], claimed["fencing_token"], {"calls": 0, "tokens": 0, "cost": 0})


@pytest.mark.parametrize("usage", [{"calls": True}, {"tokens": -1}, {"tokens": 1.5},
                                    {"cost": float("nan")}, {"cost": float("inf")}, {"bill": 3}])
def test_invalid_usage_does_not_write_a_fake_checkpoint(setup_queue, usage):
    queue, _, _ = setup_queue
    task = submit(queue)
    claimed = queue.claim("worker")
    with pytest.raises(TaskError):
        queue.checkpoint(task["task_id"], claimed["fencing_token"], "not_recorded", {}, usage=usage)
    assert queue.get(task["task_id"])["checkpoint"] is None
    assert len(queue.events(task["task_id"])) == 2


def test_finish_after_lease_expiry_does_not_need_recovery_call_first(setup_queue):
    queue, _, clock = setup_queue
    task = submit(queue)
    claimed = queue.claim("worker", lease_seconds=1)
    clock.now += 2
    with pytest.raises(LeaseLost):
        queue.finish(task["task_id"], claimed["fencing_token"], "succeeded")
    assert queue.get(task["task_id"])["status"] == "result_unknown"


def test_separate_workspace_isolation(tmp_path):
    left = TaskQueue(Workspace(tmp_path / "left"))
    right = TaskQueue(Workspace(tmp_path / "right"))
    task = submit(left)
    other = submit(right)
    assert task["task_id"] != other["task_id"]
    assert task["namespace"] != other["namespace"]
    with pytest.raises(KeyError):
        right.get(task["task_id"])
