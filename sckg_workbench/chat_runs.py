"""One durable owner for an explicitly registered chat turn, not a parent job.

The existing TaskQueue remains the scientific child queue. Owner expiry never
authorizes takeover, redispatch or retry. Public reads do not expire any lease.
Background threads are process-local convenience, not SIGKILL cleanup proof.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import math
import os
import sys
import threading
import time

from .storage import content_hash, new_id, utcnow


TERMINAL = frozenset({'succeeded', 'failed', 'partial', 'blocked', 'cancelled', 'result_unknown'})
_THREAD_LOCK = threading.Lock()
_THREADS = {}


class ChatRunError(ValueError):
    pass


class ChatRunFenceError(PermissionError):
    pass


class ChatRunCancelled(PermissionError):
    pass


def _process_identity():
    import psutil
    return {'pid': os.getpid(), 'create_time': psutil.Process().create_time(),
            'thread_ident': threading.get_ident(),
            'native_thread_id': threading.get_native_id()}


def _owner_alive(identity):
    """True/False/None for the original process and owner thread, never just PID."""
    import psutil
    if not isinstance(identity, dict) or not identity.get('pid') or not identity.get('create_time'):
        return None
    try:
        process = psutil.Process(identity['pid'])
        if process.create_time() != identity['create_time']:
            return False
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        native_id = identity.get('native_thread_id')
        if isinstance(native_id, bool) or not isinstance(native_id, int) or native_id <= 0:
            return None
        if identity['pid'] == os.getpid():
            if not identity.get('thread_ident'):
                return None
            return any(thread.ident == identity['thread_ident'] and thread.native_id == native_id
                       and thread.is_alive()
                       for thread in threading.enumerate())
        # Darwin psutil thread ids are not threading.get_native_id values;
        # privilege can also prevent the foreign thread snapshot entirely.
        # Only platforms with matching native thread-id semantics are mapped.
        if not (sys.platform.startswith('linux') or sys.platform == 'win32'):
            return None
        return any(thread.id == native_id for thread in process.threads())
    except psutil.NoSuchProcess:
        return False
    except (psutil.Error, OSError, TypeError):
        return None


class ChatRunService:
    def __init__(self, ledger, *, clock=time.time, owner_probe=None, task_queue=None):
        # No schema initialization or second connection here: guards also run
        # inside the original TaskQueue submission/claim write transaction.
        self.ledger = ledger
        self.clock = clock
        self.owner_probe = owner_probe or _owner_alive
        self.task_queue = task_queue

    @contextmanager
    def _transaction(self, conn=None):
        if conn is not None:
            yield conn
        else:
            with self.ledger.transaction() as tx:
                yield tx

    @staticmethod
    def _key(turn_id):
        return 'chat_run:' + turn_id

    def _request(self, turn_id, conn, conversation_id=None):
        request = self.ledger.get_record('chat_request', turn_id, conn=conn)
        if (not request or request.get('namespace') != self.ledger.workspace.namespace
                or conversation_id is not None and request.get('conversation_id') != conversation_id):
            raise ChatRunError('Unknown turn in this conversation/workspace')
        return request

    def _control(self, turn_id, conn):
        request = self._request(turn_id, conn)
        value = self.ledger.get_state(self._key(turn_id), conn=conn)
        if value is not None and (value.get('request_hash') != request.get('request_hash')
                or value.get('namespace') != self.ledger.workspace.namespace):
            raise ChatRunFenceError('Chat run no longer binds its registered request')
        return value

    def _public(self, value):
        if value is None:
            return None
        public = {key: deepcopy(item) for key, item in value.items() if key != 'owner_token'}
        public['automatic_resume'] = False
        return public

    def snapshot(self, turn_id, *, conversation_id=None, conn=None):
        """Pure selected-turn read; unmanaged historical turns return None."""
        if conn is None:
            with self.ledger.connect() as tx:
                return self.snapshot(turn_id, conversation_id=conversation_id, conn=tx)
        self._request(turn_id, conn, conversation_id)
        return self._public(self._control(turn_id, conn))

    def register(self, request, *, conn=None):
        with self._transaction(conn) as tx:
            authoritative = self._request(request['id'], tx, request['conversation_id'])
            if request.get('request_hash') != authoritative.get('request_hash'):
                raise ChatRunFenceError('Registered request differs')
            control = self._control(request['id'], tx)
            if control is None:
                existing = self.ledger.get_record('chat_result', request['id'], conn=tx)
                control = {'schema_version': 'chat-owner-control-v1', 'turn_id': request['id'],
                    'namespace': self.ledger.workspace.namespace, 'conversation_id': request['conversation_id'],
                    'request_hash': request['request_hash'], 'status': existing['status'] if existing else 'pending',
                    'started': existing is not None, 'cancel_requested': False, 'owner_token': None,
                    'owner_id': None, 'owner_process': None, 'lease_expires_at': None,
                    'child_binding': None, 'created_at': utcnow()}
                self.ledger.set_state(self._key(request['id']), control, conn=tx)
            return self._public(control)

    initialize = register

    def claim(self, turn_id, *, owner_id=None, lease_seconds=30, process_identity=None):
        self._lease(lease_seconds)
        with self.ledger.transaction() as tx:
            control = self._control(turn_id, tx)
            if control is None:
                raise ChatRunError('Register the turn before claiming it')
            if control['status'] != 'pending' or control['started']:
                return None  # Never transfer an expired or previously started owner.
            token = new_id('chat-owner-token')
            control.update(status='running', started=True, owner_id=owner_id or new_id('chat-owner'),
                owner_token=token, owner_process=deepcopy(process_identity) if process_identity is not None else _process_identity(),
                lease_expires_at=self.clock()+lease_seconds, started_at=utcnow())
            self.ledger.put_record('chat_run_started', turn_id, {
                'turn_id': turn_id, 'request_hash': control['request_hash'],
                'owner_id': control['owner_id'], 'owner_token_hash': content_hash(token),
                'owner_process': control['owner_process'], 'started_at': control['started_at']}, conn=tx)
            self.ledger.set_state(self._key(turn_id), control, conn=tx)
            return {'turn_id': turn_id, 'owner_token': token, 'owner_id': control['owner_id'],
                    'lease_expires_at': control['lease_expires_at']}

    @staticmethod
    def _lease(seconds):
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 < seconds <= 3600:
            raise ChatRunError('Owner lease must be positive and bounded')

    def check_owner(self, turn_id, owner_token, *, conn=None, allow_cancel=False):
        if conn is None:
            with self.ledger.connect() as tx:
                return self.check_owner(turn_id, owner_token, conn=tx, allow_cancel=allow_cancel)
        control = self._control(turn_id, conn)
        if (not control or not owner_token or control.get('owner_token') != owner_token
                or control['status'] not in {'running', 'cancel_requested'}
                or self.clock() >= control['lease_expires_at']):
            raise ChatRunFenceError('Chat owner is stale, expired, or already terminal')
        started = self.ledger.get_record('chat_run_started', turn_id, conn=conn)
        if (not started or control.get('turn_id') != turn_id
                or started.get('turn_id') != turn_id
                or started.get('request_hash') != control.get('request_hash')
                or started.get('owner_id') != control.get('owner_id')
                or started.get('owner_process') != control.get('owner_process')
                or started.get('owner_token_hash') != content_hash(owner_token)):
            raise ChatRunFenceError('Chat owner differs from its immutable started identity')
        if control.get('cancel_requested') and not allow_cancel:
            raise ChatRunCancelled('Cancellation requested; do not dispatch further work')
        return deepcopy(control)

    def heartbeat(self, turn_id, owner_token, *, lease_seconds=30):
        self._lease(lease_seconds)
        with self.ledger.transaction() as tx:
            control = self.check_owner(turn_id, owner_token, conn=tx, allow_cancel=True)
            control['lease_expires_at'] = self.clock()+lease_seconds
            self.ledger.set_state(self._key(turn_id), control, conn=tx)
            return self._public(control)

    def bind_child(self, turn_id, owner_token, task, *, conn):
        """Only the original TaskQueue.submit transaction may call this hook."""
        if conn is None:
            raise ChatRunError('Child binding requires the original submission transaction')
        control = self.check_owner(turn_id, owner_token, conn=conn)
        row = conn.execute('SELECT * FROM workbench_tasks WHERE namespace=? AND task_id=?',
            (self.ledger.workspace.namespace, task['task_id'])).fetchone()
        submission = self.ledger.get_record('task_submission', task['task_id'], conn=conn)
        if (row is None or not submission or row['payload_digest'] != task.get('payload_digest')
                or submission['payload_digest'] != row['payload_digest']):
            raise ChatRunFenceError('Child is not the authoritative submitted task')
        expected = row['attempt'] + (row['status'] == 'queued')
        if expected < 1:
            raise ChatRunFenceError('Child has no owned execution generation')
        binding = {'schema_version': 'chat-child-binding-v1', 'turn_id': turn_id,
            'conversation_id': control['conversation_id'], 'namespace': self.ledger.workspace.namespace,
            'task_id': row['task_id'], 'expected_attempt': expected, 'payload_digest': row['payload_digest'],
            'submission_hash': content_hash(submission), 'owner_token_hash': content_hash(owner_token)}
        reverse_key = f"chat_child_owner:{row['task_id']}:attempt:{expected}"
        reverse = self.ledger.get_state(reverse_key, conn=conn)
        pointer = {'turn_id': turn_id, 'binding_hash': content_hash(binding)}
        if reverse is not None and reverse != pointer:
            raise ChatRunFenceError('Child generation is already bound to another turn')
        self.ledger.put_record('chat_child_binding', turn_id, binding, conn=conn)
        self.ledger.set_state(reverse_key, pointer, conn=conn)
        control['child_binding'] = binding
        self.ledger.set_state(self._key(turn_id), control, conn=conn)
        return deepcopy(binding)

    def _bound_owner(self, conn, task):
        attempt = task['attempt'] + (task['status'] == 'queued')
        reverse = self.ledger.get_state(f"chat_child_owner:{task['task_id']}:attempt:{attempt}", conn=conn)
        if reverse is None:
            return None
        binding = self.ledger.get_record('chat_child_binding', reverse['turn_id'], conn=conn)
        control = self._control(reverse['turn_id'], conn)
        if (not binding or content_hash(binding) != reverse['binding_hash']
                or binding['task_id'] != task['task_id'] or binding['expected_attempt'] != attempt
                or binding['payload_digest'] != task['payload_digest'] or not control
                or binding['owner_token_hash'] != content_hash(control.get('owner_token'))):
            raise ChatRunFenceError('Child execution binding differs from its chat owner')
        return binding, self.check_owner(binding['turn_id'], control['owner_token'], conn=conn)

    def task_execution_guard(self, conn, task):
        """Default original-queue guard; ordinary non-chat generations are untouched."""
        bound = self._bound_owner(conn, task)
        if bound is None:
            return
        _, owned = bound
        # A future lease does not authorize an orphaned queued child. The
        # mandatory queue/execute guard must positively identify the original
        # owner thread; absence or inaccessible identity fails closed.
        if self.owner_probe(owned.get('owner_process')) is not True:
            raise ChatRunFenceError('Original chat owner thread is dead or cannot be verified')

    def _worker_start_binding(self, conn, task):
        """Reconstruct current claimed-child and immutable launch bindings."""
        bound = self._bound_owner(conn, task)
        if bound is None:
            return None
        binding, control = bound
        row = conn.execute('SELECT * FROM workbench_tasks WHERE namespace=? AND task_id=?',
            (self.ledger.workspace.namespace, task['task_id'])).fetchone()
        if (not row or row['status'] != 'running' or task['status'] != 'running'
                or row['attempt'] != task['attempt'] or row['payload_digest'] != task['payload_digest']
                or not task.get('fencing_token') or row['fencing_token'] != task['fencing_token']
                or not row['lease_expires_at'] or self.clock() >= row['lease_expires_at']):
            raise ChatRunFenceError('Worker start requires the original live claimed child generation')
        key = f"{task['task_id']}:attempt:{task['attempt']}"
        started = self.ledger.get_record('analysis_process_started', key, conn=conn)
        if (not started or started.get('namespace') != self.ledger.workspace.namespace
                or started.get('task_id') != task['task_id'] or started.get('attempt') != task['attempt']
                or started.get('payload_digest') != task['payload_digest']
                or started.get('fencing_token_digest') != content_hash(task['fencing_token'])
                or not isinstance(started.get('root'), dict) or not started['root'].get('pid')
                or not started['root'].get('create_time')):
            raise ChatRunFenceError('Worker start has no matching immutable process launch')
        owner = control['owner_process']
        supervisor = started.get('supervisor') or {}
        if any(supervisor.get(field) != owner.get(field)
               for field in ('pid', 'create_time', 'native_thread_id')):
            raise ChatRunFenceError('Worker supervisor is not the original chat owner thread')
        fields = {'schema_version': 'chat-worker-start-grant-v1', 'grant_key': key,
            'namespace': self.ledger.workspace.namespace, 'turn_id': control['turn_id'],
            'request_hash': control['request_hash'], 'owner_id': control['owner_id'],
            'owner_token_hash': content_hash(control['owner_token']), 'owner_process': deepcopy(owner),
            'task_id': task['task_id'], 'attempt': task['attempt'], 'payload_digest': task['payload_digest'],
            'fencing_token_digest': content_hash(task['fencing_token']),
            'child_binding_hash': content_hash(binding), 'analysis_started_hash': content_hash(started),
            'worker_process': deepcopy(started['root'])}
        return key, fields, control, row

    def issue_worker_start_grant(self, conn, task):
        """Original owner thread authorizes one already-spawned worker via stdin.

        Issuance is the dispatch authorization point, not a promise of future
        thread liveness or an OS security boundary. Never relaxes queue claims.
        """
        bound = self._worker_start_binding(conn, task)
        if bound is None:
            return None
        key, fields, control, row = bound
        current = _process_identity()
        if any(current.get(field) != control['owner_process'].get(field)
               for field in ('pid', 'create_time', 'thread_ident', 'native_thread_id')):
            raise ChatRunFenceError('Only the original owner thread may issue worker start authorization')
        self.task_execution_guard(conn, task)
        if self.ledger.get_record('chat_worker_start_grant', key, conn=conn) is not None:
            raise ChatRunFenceError('Worker start authorization was already issued; do not resend')
        now = self.clock()
        grant = {**fields, 'grant_id': new_id('worker-start'), 'issued_at_epoch': now,
            'deadline_epoch': min(now + 30.0, control['lease_expires_at'], row['lease_expires_at']),
            'authorization_scope': 'one_owner_thread_authorized_dispatch_not_future_liveness'}
        self.ledger.put_record('chat_worker_start_grant', key, grant, conn=conn)
        return deepcopy(grant)

    def consume_worker_start_grant(self, conn, task, grant):
        """Worker-only one-shot authorization, with the parent's exact stdin wire."""
        bound = self._worker_start_binding(conn, task)
        if bound is None:
            if grant is not None:
                raise ChatRunFenceError('Unbound task cannot consume a chat worker authorization')
            return None
        key, fields, control, _ = bound
        issued = self.ledger.get_record('chat_worker_start_grant', key, conn=conn)
        if (not isinstance(grant, dict) or issued != grant
                or any(grant.get(field) != value for field, value in fields.items())):
            raise ChatRunFenceError('Worker stdin authorization differs from its immutable issuance')
        now = self.clock()
        issued_at, deadline = grant.get('issued_at_epoch'), grant.get('deadline_epoch')
        if (type(issued_at) not in (int, float) or type(deadline) not in (int, float)
                or not math.isfinite(issued_at) or not math.isfinite(deadline)
                or not issued_at <= now < deadline <= issued_at + 30.0):
            raise ChatRunFenceError('Worker start authorization is expired or invalid')
        current = _process_identity()
        if any(current.get(field) != grant['worker_process'].get(field) for field in ('pid', 'create_time')):
            raise ChatRunFenceError('Worker authorization belongs to another actual process')
        observed = self.owner_probe(control['owner_process'])
        if observed is False:
            raise ChatRunFenceError('Original chat owner is known dead; worker start is refused')
        # Unknown foreign thread visibility is not process-liveness proof. A
        # fresh original-thread grant is required above; known-dead/reused owner
        # processes remain independently forbidden even with that grant.
        import psutil
        try:
            owner_process = psutil.Process(control['owner_process']['pid'])
            process_live = (owner_process.create_time() == control['owner_process']['create_time']
                and owner_process.is_running() and owner_process.status() != psutil.STATUS_ZOMBIE)
        except (psutil.Error, OSError, TypeError):
            process_live = False
        if process_live is not True or (observed is not True and observed is not None):
            raise ChatRunFenceError('Original owner process cannot be verified for this dispatch')
        if self.ledger.get_record('chat_worker_start_consumed', key, conn=conn) is not None:
            raise ChatRunFenceError('Worker start authorization was already consumed')
        audit = {'schema_version': 'chat-worker-start-consumed-v1', 'grant_hash': content_hash(grant),
            'grant_id': grant['grant_id'], 'task_id': task['task_id'], 'attempt': task['attempt'],
            'turn_id': control['turn_id'], 'worker_process': deepcopy(grant['worker_process']),
            'consumed_at': utcnow(), 'owner_thread_observation': 'live' if observed is True else 'unknown',
            'authorization_scope': grant['authorization_scope'], 'foreign_thread_observation_restored': False}
        self.ledger.put_record('chat_worker_start_consumed', key, audit, conn=conn)
        return deepcopy(audit)

    def _clear_active(self, control, conn):
        key = 'chat_active:' + control['conversation_id']
        if self.ledger.get_state(key, conn=conn) == control['turn_id']:
            self.ledger.set_state(key, None, conn=conn)

    def request_cancel(self, conversation_id, turn_id):
        # Construct the existing queue only for an explicit mutation, outside
        # the shared write TX. snapshot/view never initializes this dependency.
        queue = self.task_queue
        with self.ledger.connect() as read:
            self._request(turn_id, read, conversation_id)
            current = self._control(turn_id, read)
        if current and current['status'] not in TERMINAL and queue is None:
            from .tasks import TaskQueue
            queue = TaskQueue(self.ledger.workspace)
        from .tasks import InvalidTransition
        with self.ledger.transaction() as tx:
            self._request(turn_id, tx, conversation_id)
            control = self._control(turn_id, tx)
            if not control:
                raise ChatRunError('This historical turn has no managed owner')
            if control['status'] in TERMINAL:
                return self._public(control)
            control.update(cancel_requested=True, status='cancel_requested' if control['started'] else 'cancelled')
            binding = control.get('child_binding')
            if binding:
                if queue is None:
                    raise ChatRunError('Conditional child cancellation is unavailable')
                try:
                    child = queue.request_cancel(binding['task_id'], expected_attempt=binding['expected_attempt'],
                        expected_payload_digest=binding['payload_digest'], conn=tx)
                    control['child_cancel_status'] = child['status']
                except InvalidTransition:
                    control['child_cancel_status'] = 'generation_mismatch_not_cancelled'
            if not control['started']:
                self.ledger.put_record('chat_result', turn_id, {'status': 'cancelled', 'answer': None,
                    'receipt': None, 'error': {'type': 'ChatRunCancelled', 'message': 'Cancelled before execution.'},
                    'finished_at': utcnow(), 'answer_validation': 'not_semantically_verified'}, conn=tx)
                self._clear_active(control, tx)
            self.ledger.set_state(self._key(turn_id), control, conn=tx)
            return self._public(control)

    @staticmethod
    def _unknown_result(result):
        receipts = list(result.get('receipts') or [])
        if isinstance(result.get('receipt'), dict):
            receipts.append(result['receipt'])
        return (result.get('status') == 'result_unknown' or (result.get('error') or {}).get('outcome') == 'result_unknown'
                or any(receipt.get('outcome') == 'result_unknown' for receipt in receipts)
                or (result.get('agent_budget') or {}).get('dispatch_unknown') is True)

    def _child_cleanup_confirmed(self, control, conn):
        binding = control.get('child_binding')
        if not binding:
            return True
        row = conn.execute('SELECT * FROM workbench_tasks WHERE namespace=? AND task_id=?',
            (self.ledger.workspace.namespace, binding['task_id'])).fetchone()
        if (row is None or row['payload_digest'] != binding['payload_digest']
                or row['status'] in {'running', 'cancel_requested', 'queued'}):
            return False
        if row['status'] == 'cancelled' and row['attempt'] == binding['expected_attempt']-1:
            return True  # Atomic cancel of the unclaimed queued generation.
        if row['kind'] == 'analysis.scrublet.program.v1':
            from .code_program import CodeProgramService
            return CodeProgramService(self.ledger.workspace).cleanup_confirmed(
                binding['task_id'], binding['expected_attempt'], conn=conn)
        proof = self.ledger.get_state(f"analysis_process:{binding['task_id']}:attempt:{binding['expected_attempt']}", conn=conn)
        record_id = f"{binding['task_id']}:attempt:{binding['expected_attempt']}"
        started = self.ledger.get_record('analysis_process_started', record_id, conn=conn)
        original_cleanup = self.ledger.get_record('analysis_process_cleanup', record_id, conn=conn)
        recorded = proof is not None and (proof == original_cleanup or any(
            candidate == proof for candidate in self.ledger.list_records('analysis_process_recovery', conn=conn)))
        return bool(recorded and started and proof and proof.get('namespace') == self.ledger.workspace.namespace
            and proof.get('task_id') == binding['task_id'] and proof.get('attempt') == binding['expected_attempt']
            and proof.get('payload_digest') == binding['payload_digest'] and proof.get('root')
            and started.get('root') == proof.get('root') and started.get('supervisor') == proof.get('supervisor')
            and started.get('fencing_token_digest') == proof.get('fencing_token_digest')
            and proof.get('status') == 'known_owned_processes_stopped' and proof.get('cleanup_verified') is True
            and not proof.get('residual_processes') and not (proof.get('cleanup') or {}).get('residual_processes'))

    def finish(self, turn_id, owner_token, result, *, conn=None, cancellation_confirmed=False):
        with self._transaction(conn) as tx:
            control = self._control(turn_id, tx)
            existing = self.ledger.get_record('chat_result', turn_id, conn=tx)
            if existing is not None and control and control.get('owner_token') == owner_token and control['status'] in TERMINAL:
                return existing
            control = self.check_owner(turn_id, owner_token, conn=tx, allow_cancel=True)
            final = deepcopy(result)
            if final.get('status') not in TERMINAL:
                raise ChatRunError('Finish requires a terminal result')
            unknown = self._unknown_result(final)
            if control['cancel_requested']:
                confirmed = cancellation_confirmed is True and not unknown and self._child_cleanup_confirmed(control, tx)
                final.update(status='cancelled' if confirmed else 'result_unknown', answer=None)
                final['error'] = {'type': 'ChatRunCancelled', 'message': 'Cancelled; existing receipts and effects are retained.',
                                  'outcome': 'cancelled' if confirmed else 'result_unknown'}
            elif unknown:
                final.update(status='result_unknown', answer=None)
            final.setdefault('finished_at', utcnow())
            final.setdefault('answer_validation', 'not_semantically_verified')
            self.ledger.put_record('chat_result', turn_id, final, conn=tx)
            self.ledger.put_record('chat_run_finished', turn_id, {'turn_id': turn_id,
                'owner_token_hash': content_hash(owner_token), 'result_hash': content_hash(final),
                'status': final['status']}, conn=tx)
            control['status'] = final['status']
            self.ledger.set_state(self._key(turn_id), control, conn=tx)
            if final['status'] != 'result_unknown':
                self._clear_active(control, tx)
            self.ledger.append_event('chat_send_finished', turn_id, {'status': final['status']}, conn=tx)
            return deepcopy(final)

    def _mark_unknown(self, turn_id, owner_token, reason):
        with self.ledger.transaction() as tx:
            control = self._control(turn_id, tx)
            if control and control.get('owner_token') == owner_token and control['status'] not in TERMINAL:
                control.update(status='result_unknown', interruption_reason=reason)
                self.ledger.set_state(self._key(turn_id), control, conn=tx)

    def reconcile(self, conversation_id, turn_id, *, analysis=None):
        control = self.snapshot(turn_id, conversation_id=conversation_id)
        if not control or not control['started'] or control['status'] in TERMINAL - {'result_unknown'}:
            return control
        owner_alive = self.owner_probe(control.get('owner_process'))
        if owner_alive is not False:
            expired = (control.get('lease_expires_at') is not None
                       and self.clock() >= control['lease_expires_at'])
            if expired:
                # A stale owner cannot finish or dispatch, but a still-live
                # process is not ours to kill merely because its lease expired.
                # Explicit reconciliation classifies uncertainty, never takes
                # over, resumes a model call, or releases this active turn.
                with self.ledger.transaction() as tx:
                    current = self._control(turn_id, tx)
                    if (current and current['status'] in {'running', 'cancel_requested', 'result_unknown'}
                            and current.get('owner_process') == control.get('owner_process')
                            and self.clock() >= current['lease_expires_at']):
                        current.update(status='result_unknown', cleanup_status='cleanup_unknown',
                            cleanup_verified=False, recovery_action='expired_owner_classified_no_restart')
                        self.ledger.set_state(self._key(turn_id), current, conn=tx)
                    return {**self._public(current), 'owner_observation': 'live' if owner_alive else 'unknown',
                            'new_execution': False}
            return {**control, 'owner_observation': 'live' if owner_alive else 'unknown', 'new_execution': False}
        # A dead chat owner can have entered the existing data-profile process
        # supervisor before any analysis child binding. Absence of a binding
        # cannot prove that no process was spawned or that it was cleaned up.
        cleanup = {'status': 'cleanup_unknown', 'cleanup_verified': False}
        result_available = False
        binding = control.get('child_binding')
        if binding:
            if analysis is None:
                with self.ledger.connect() as tx:
                    row = tx.execute('SELECT kind FROM workbench_tasks WHERE namespace=? AND task_id=?',
                        (self.ledger.workspace.namespace, binding['task_id'])).fetchone()
                if row is not None and row['kind'] == 'analysis.scrublet.program.v1':
                    from .code_program import CodeProgramService
                    analysis = CodeProgramService(self.ledger.workspace)
                else:
                    from .analysis import AnalysisService
                    analysis = AnalysisService(self.ledger.workspace)
            cleanup = analysis.cleanup_owned_processes(binding['task_id'], attempt=binding['expected_attempt'],
                expected_payload_digest=binding['payload_digest'])
            try:
                # Readback accepts both authoritative kinds; acquiring a new
                # controller object never authorizes another patch execution.
                if hasattr(analysis, 'get_result'):
                    reader = analysis
                else:
                    from .analysis import AnalysisService
                    reader = AnalysisService(self.ledger.workspace)
                child = reader.get_result(binding['task_id'], attempt=binding['expected_attempt'])
                result_available = bool(child and child.get('product_completed'))
            except (ValueError, KeyError, OSError):
                result_available = False
        with self.ledger.transaction() as tx:
            current = self._control(turn_id, tx)
            if current and current['status'] in {'running', 'cancel_requested', 'result_unknown'} and current.get('owner_process') == control.get('owner_process'):
                current.update(status='result_unknown', cleanup_status=cleanup.get('status', 'cleanup_unknown'),
                    cleanup_verified=cleanup.get('cleanup_verified') is True,
                    child_result_available=result_available, recovery_action='reconcile_only_no_restart')
                self.ledger.set_state(self._key(turn_id), current, conn=tx)
            return {**self._public(current), 'new_execution': False}

    def launch(self, turn_id, target, *, owner_id=None, lease_seconds=30):
        """Launch only this explicit turn. Never scan/drain pending ledger rows."""
        self._lease(lease_seconds)
        key = (str(self.ledger.workspace.root), self.ledger.workspace.namespace)
        with _THREAD_LOCK:
            previous = _THREADS.get(key)
            if previous is not None and previous.is_alive():
                return {**(self.snapshot(turn_id) or {}), 'dispatch_status': 'workspace_busy_not_started'}

            def work():
                claim = self.claim(turn_id, owner_id=owner_id, lease_seconds=lease_seconds)
                if claim is None:
                    return
                token, stop = claim['owner_token'], threading.Event()
                def heartbeat():
                    while not stop.wait(min(5.0, lease_seconds/3)):
                        try:
                            self.heartbeat(turn_id, token, lease_seconds=lease_seconds)
                        except (ChatRunFenceError, ChatRunError):
                            return
                pulse = threading.Thread(target=heartbeat, name='sckg-chat-heartbeat', daemon=True)
                pulse.start()
                try:
                    target(token)
                    self._mark_unknown(turn_id, token, 'owner_returned_without_terminal_commit')
                except BaseException as error:
                    self._mark_unknown(turn_id, token, 'owner_interrupted:' + type(error).__name__)
                finally:
                    stop.set()
                    pulse.join(timeout=1)

            thread = threading.Thread(target=work, name='sckg-chat-owner', daemon=True)
            _THREADS[key] = thread
            thread.start()
        return {**(self.snapshot(turn_id) or {}), 'dispatch_status': 'explicit_background_launch'}
