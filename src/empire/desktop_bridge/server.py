"""Bounded concurrent queries and session-local, non-replayed mutation receipts."""
import asyncio
import hashlib
import json
import threading
from collections import OrderedDict
from concurrent.futures import CancelledError
from uuid import uuid4

from pydantic import ValidationError

from .operations import execute
from .protocol import encode_frame, read_frame
from .schemas import READS, WRITES, Cancel, Empty, Request


class Server:
    def __init__(self, runtime, source, destination):
        self.runtime, self.source, self.destination = runtime, source, destination
        self.session = uuid4().hex
        self.lock = threading.RLock()
        self.output_lock = threading.Lock()
        self.pending = {}
        self.commands = OrderedDict()
        self.closing = False
        self.output_closed = False

    def send(self, ident, result=None, error=None):
        message = dict(id=ident, session_id=self.session, result=result, error=error)
        try:
            packet = encode_frame(message)
        except (ValueError, TypeError):
            packet = encode_frame(dict(id=ident, session_id=self.session, error={
                'code': 'RESULT_TOO_LARGE', 'message': '结果不可传输，请缩小查询范围；写入结果须重新核实',
                'outcome': 'unknown'}))
        with self.output_lock:
            if not self.output_closed:
                try:
                    self.destination.write(packet)
                    self.destination.flush()
                except (OSError, ValueError):
                    self.output_closed = True

    def error(self, code, message, outcome='rejected'):
        return dict(code=code, message=self.runtime.redactor.text(message), outcome=outcome)

    def accept(self, raw):
        request = Request.model_validate(raw)
        if request.operation == 'session.handshake':
            Empty.model_validate(request.params)
            self.send(request.id, dict(protocol=1, session_id=self.session,
                                       operations=sorted(READS.keys() | WRITES.keys())))
            return
        if request.session_id != self.session:
            raise ValueError('Session mismatch; reconnect without replaying commands')
        if request.operation == 'desktop.shutdown':
            Empty.model_validate(request.params)
            self.closing = True
            return request.id
        if request.operation == 'request.cancel':
            cancel = Cancel.model_validate(request.params)
            with self.lock:
                pending = self.pending.get(cancel.request_id)
                if pending and not pending[1]:
                    pending[0].cancel()
            self.send(request.id, {'cancelled': bool(pending and not pending[1])})
            return
        mutation = request.operation in WRITES
        schema = (WRITES if mutation else READS).get(request.operation)
        if schema is None:
            raise ValueError('Unknown operation')
        params = schema.model_validate(request.params).model_dump()
        fingerprint = hashlib.sha256(json.dumps([request.operation, params], sort_keys=True).encode()).hexdigest()
        with self.lock:
            if request.id in self.pending:
                raise ValueError('Duplicate request ID')
            if mutation:
                if not request.operation_id:
                    raise ValueError('Mutation requires operation_id')
                prior = self.commands.get(request.operation_id)
                if prior:
                    if prior['fingerprint'] != fingerprint:
                        raise ValueError('Operation ID reused with different parameters')
                    if prior['done']:
                        self.send(request.id, prior['result'], prior['error'])
                    else:
                        self.send(request.id, error=self.error('IN_PROGRESS', '相同命令仍在处理，请读取实际状态', 'unknown'))
                    return
            if sum(item[1] == mutation for item in self.pending.values()) >= (16 if mutation else 8):
                self.send(request.id, error=self.error('BUSY', '后台请求繁忙，请稍后重试'))
                return
            if mutation:
                # Never evict receipts and silently allow an old command ID to execute twice.
                if len(self.commands) >= 1024:
                    self.send(request.id, error=self.error('SESSION_LIMIT', '本会话命令回执已满，请正常重启后继续'))
                    return
                self.commands[request.operation_id] = dict(fingerprint=fingerprint, done=False, result=None, error=None)
            future = asyncio.run_coroutine_threadsafe(execute(self.runtime, request.operation, params), self.runtime.loop)
            self.pending[request.id] = (future, mutation)
            future.add_done_callback(lambda done: self.complete(request, mutation, done))

    def complete(self, request, mutation, future):
        result, error = None, None
        try:
            result = self.runtime.redactor.value(future.result())
        except CancelledError:
            error = self.error('CANCELLED', '查询已取消')
        except Exception as exc:
            error = self.error('OPERATION_FAILED', exc, 'unknown' if mutation else 'rejected')
        with self.lock:
            self.pending.pop(request.id, None)
            if mutation:
                self.commands[request.operation_id].update(done=True, result=result, error=error)
        self.send(request.id, result, error)

    def serve(self):
        closing_id = None
        try:
            while not self.closing:
                raw = read_frame(self.source)
                if raw is None:
                    break
                try:
                    closing_id = self.accept(raw)
                except (ValidationError, ValueError) as exc:
                    # Do not include pydantic's raw input echo in diagnostics.
                    message = '请求字段不符合契约' if isinstance(exc, ValidationError) else str(exc)
                    ident = raw.get('id')
                    self.send(ident if isinstance(ident, str) and len(ident) <= 100 else None,
                              error=self.error('INVALID_REQUEST', message))
        finally:
            self.closing = True
            with self.lock:
                pending = list(self.pending.values())
            for future, mutation in pending:
                if not mutation:
                    future.cancel()
            for future, mutation in pending:
                if mutation:
                    try:
                        future.result()
                    except Exception:
                        pass  # The callback sends the true error receipt.
            self.runtime.command('shutdown').result()
            self.runtime.thread.join()
            if closing_id:
                self.send(closing_id, {'closed': True})
