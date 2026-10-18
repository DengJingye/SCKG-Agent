"""Actual Chat/ModelService across threads; explicit scripted gateways, no network/fit.

Uses the established temporary local KB fixture for grounded cancellation; its
synthetic source reviews/semantics are not new production authority or gold.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest

from sckg_workbench.chat_runs import ChatRunService
from sckg_workbench.storage import content_hash, utcnow
from tests.test_workbench_chat import app, BUDGET, PASSPHRASE
from tests.test_workbench_chat_grounded import case as grounded_case, setup
from tests.test_workbench_grounded_chat import BUDGET as GROUNDED_BUDGET


def register(app, *, request_id='background-event', prompt='Synthetic background discussion', conversation_id=None):
    return app.chat.submit_send(conversation_id or app.conversation['id'], prompt,
        profile_id=app.profile['id'], use_knowledge=False, budget=deepcopy(BUDGET), request_id=request_id)


def start(runs, chat, turn, passphrase):
    done, errors = Event(), []
    def work(token):
        try:
            chat.process_registered_send(turn['id'], token, passphrase=passphrase)
        except BaseException as error:
            errors.append(error)
        finally:
            done.set()
    launched = runs.launch(turn['id'], work)
    return launched, done, errors


def blocking_gateway(app):
    entered, release, arrivals = Event(), Event(), []
    def transport(*args):
        arrivals.append('one-scripted-gateway-entry')
        entered.set()
        assert release.wait(5), 'test must release the scripted gateway'
        return app.transport(*args)
    app.models.transport = transport
    return entered, release, arrivals


def test_submit_registers_real_request_and_control_without_dispatch_or_secret_in_ledger(app, monkeypatch):
    monkeypatch.setattr(app.models, 'invoke', lambda *a, **k: pytest.fail('register invoked a model'))
    turn = register(app)
    assert turn['status'] == 'pending' and turn['run_control']['started'] is False
    assert 'owner_token' not in turn['run_control'] and 'passphrase' not in turn
    assert app.calls == [] and app.ledger.list_records('model_request') == []
    assert register(app) == turn
    assert app.chat.view_turn(turn)['answer'] is None


def test_background_cancel_retains_actual_late_receipt_and_replay_is_stable_zero_new_call(app):
    entered, release, arrivals = blocking_gateway(app)
    turn = register(app)
    runs = ChatRunService(app.ledger)
    _, done, errors = start(runs, app.chat, turn, PASSPHRASE)
    try:
        assert entered.wait(5)
        assert app.chat.view_turn(turn)['status'] == 'running'
        assert len(arrivals) == 1 and app.calls == []
        requested = runs.request_cancel(app.conversation['id'], turn['id'])
        assert requested['status'] == 'cancel_requested'
    finally:
        release.set()
        assert done.wait(5)
    assert errors == [] and len(arrivals) == len(app.calls) == 1
    final = app.chat.turns(app.conversation['id'])[0]
    assert final['status'] == 'cancelled' and final['answer'] is None
    assert final['receipt']['status'] == 'succeeded'
    assert final['receipt']['usage']['total_tokens'] == 102
    assert app.ledger.get_record('model_call', final['receipt']['call_id']) == final['receipt']
    assert not app.chat.view_turn(final)['usable']
    assert register(app) == final and app.chat.view_turn(final)['answer'] is None
    assert len(app.calls) == 1 and app.ledger.list_records('task_submission') == []


def test_cancel_during_actual_grounded_planner_retains_one_receipt_and_never_calls_selector_or_answer(grounded_case):
    case = grounded_case
    entered, release = Event(), Event()
    def pause_first(index):
        assert index == 0, 'cancellation must prevent any second gateway request'
        entered.set()
        assert release.wait(5)
    case.state['during'] = pause_first
    prompt = 'Which fictional FixtureTool conditions apply?'
    kwargs = dict(profile_id=case.profile['id'], use_knowledge=True, budget=deepcopy(GROUNDED_BUDGET),
                  request_id='cancel-grounded-planner', grounded_mode=True)
    turn = case.chat.submit_send(case.conversation['id'], prompt, **kwargs)
    runs = ChatRunService(case.ledger)
    _, done, errors = start(runs, case.chat, turn, 'fixture-pass')
    try:
        assert entered.wait(5) and len(case.calls) == 1
        runs.request_cancel(case.conversation['id'], turn['id'])
    finally:
        release.set()
        assert done.wait(5)
    assert errors == [] and len(case.calls) == 1
    final = case.chat.turns(case.conversation['id'])[0]
    assert final['status'] == 'cancelled' and final['answer'] is None
    run = final['grounded_run']
    assert len(run['receipts']) == 1 and run['receipts'][0]['status'] == 'succeeded'
    assert run['agent_budget']['model_calls'] == 1
    assert run['selection'] is None and run['answer_run'] is None
    assert [step['stage'] for step in run['stage_trace']] == ['planner']
    assert case.chat.submit_send(case.conversation['id'], prompt, **kwargs) == final
    assert not case.chat.view_turn(final)['usable'] and len(case.calls) == 1


def test_concurrent_same_request_is_one_actual_owner_and_gateway_receipt(app):
    entered, release, arrivals = blocking_gateway(app)
    kwargs = dict(profile_id=app.profile['id'], passphrase=PASSPHRASE,
                  use_knowledge=False, budget=BUDGET, request_id='concurrent-same-request')
    prompt = 'Synthetic concurrent same-request discussion'
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(app.chat.send, app.conversation['id'], prompt, **kwargs)
        try:
            assert entered.wait(5)
            second = pool.submit(app.chat.send, app.conversation['id'], prompt, **kwargs)
            duplicate = second.result(timeout=5)
            assert duplicate['status'] == 'running' and len(arrivals) == 1
        finally:
            release.set()
        final = first.result(timeout=5)
    assert duplicate['id'] == final['id'] and final['status'] == 'succeeded'
    assert len(app.calls) == 1 and len(app.ledger.list_records('chat_run_started')) == 1
    assert len(app.ledger.list_records('model_call')) == 1
    assert app.chat.send(app.conversation['id'], prompt, **kwargs) == final


def test_repeated_processing_same_token_while_marker_active_never_invokes_twice(app):
    entered, release, arrivals = blocking_gateway(app)
    turn = register(app)
    runs = ChatRunService(app.ledger)
    owner = runs.claim(turn['id'], lease_seconds=900)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(app.chat.process_registered_send, turn['id'], owner['owner_token'], passphrase=PASSPHRASE)
        try:
            assert entered.wait(5)
            duplicate = app.chat.process_registered_send(turn['id'], owner['owner_token'], passphrase=PASSPHRASE)
            assert duplicate['status'] == 'running' and len(arrivals) == 1
        finally:
            release.set()
        final = first.result(timeout=5)
    assert final['status'] == 'succeeded' and len(app.calls) == 1
    assert app.chat.process_registered_send(turn['id'], owner['owner_token'], passphrase=PASSPHRASE) == final
    assert len(app.calls) == 1


def test_existing_interrupted_execution_marker_cannot_restart_actual_chat_gateway(app):
    turn = register(app)
    runs = ChatRunService(app.ledger, owner_probe=lambda identity: False)
    owner = runs.claim(turn['id'], lease_seconds=900)
    app.ledger.put_record('chat_execution_started', turn['id'], {
        'turn_id': turn['id'], 'owner_token_hash': content_hash(owner['owner_token']),
        'request_hash': turn['request_hash'], 'started_at': utcnow(), 'automatic_retry': False})
    # Explicit synthetic interrupted marker, not an assertion that a real
    # request occurred; the point is that it can never authorize redispatch.
    before = app.chat.process_registered_send(turn['id'], owner['owner_token'], passphrase=PASSPHRASE)
    assert before['status'] == 'running' and app.calls == []
    recovered = runs.reconcile(app.conversation['id'], turn['id'])
    assert recovered['status'] == 'result_unknown' and recovered['cleanup_verified'] is False
    assert register(app)['status'] == 'result_unknown' and app.calls == []
    assert app.ledger.list_records('model_request') == []
    assert app.ledger.get_state('chat_active:' + app.conversation['id']) == turn['id']


def test_workspace_busy_registration_is_pending_not_started_and_not_automatically_drained(app):
    entered, release, arrivals = blocking_gateway(app)
    turn = register(app)
    runs = ChatRunService(app.ledger)
    _, done, errors = start(runs, app.chat, turn, PASSPHRASE)
    try:
        assert entered.wait(5)
        other = app.chat.create_conversation('Other explicit synthetic send')
        pending = register(app, request_id='busy-other', conversation_id=other['id'])
        launch = runs.launch(pending['id'], lambda token: pytest.fail('busy pending turn was automatically executed'))
        assert launch['dispatch_status'] == 'workspace_busy_not_started'
        assert launch['status'] == 'pending' and launch['started'] is False
        assert app.chat.view_turn(pending)['status'] == 'pending' and len(arrivals) == 1
    finally:
        release.set()
        assert done.wait(5)
    assert errors == [] and len(app.calls) == 1
    snapshot = runs.snapshot(pending['id'])
    assert snapshot['status'] == 'pending' and snapshot['started'] is False
    assert runs.request_cancel(other['id'], pending['id'])['status'] == 'cancelled'
    assert len(app.calls) == 1


def test_base_exception_after_request_persistence_is_unknown_and_same_request_never_restarts(app):
    arrivals = []
    def interrupt(*args):
        arrivals.append('synthetic-interrupted-dispatch')
        raise KeyboardInterrupt('Explicit synthetic interruption, no real provider')
    app.models.transport = interrupt
    kwargs = dict(profile_id=app.profile['id'], passphrase=PASSPHRASE,
                  use_knowledge=False, budget=BUDGET, request_id='interrupted-model-request')
    with pytest.raises(KeyboardInterrupt):
        app.chat.send(app.conversation['id'], 'Synthetic interrupted question', **kwargs)
    turn = app.chat.turns(app.conversation['id'])[0]
    assert turn['status'] == 'result_unknown' and turn['answer'] is None
    assert len(app.ledger.list_records('model_request')) == 1
    assert app.ledger.list_records('model_call') == []
    assert app.chat.send(app.conversation['id'], 'Synthetic interrupted question', **kwargs) == turn
    assert len(arrivals) == 1
    assert app.ledger.get_state('chat_active:' + app.conversation['id']) == turn['id']
