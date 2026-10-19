"""Budgets and a disposable SQL read lane used only by project diagnostics."""
from __future__ import annotations

import asyncio
import re
import socket
import threading
import time
from dataclasses import asdict, dataclass

from sqlalchemy import event

from empire.plugins.infra.mysql_store import make_engine


class DiagnosticLimit(RuntimeError):
    """The requested evidence cannot be obtained inside this diagnostic budget."""


@dataclass(frozen=True)
class Limits:
    sql: int = 10
    redis: int = 20
    io_seconds: float = 5
    total_seconds: float = 30
    report_bytes: int = 1024 * 1024
    errors: int = 50
    body_bytes: int = 64 * 1024

    def __post_init__(self):
        for name, maximum in (('sql', 10), ('redis', 20), ('report_bytes', 1048576),
                              ('errors', 50), ('body_bytes', 65536)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'Invalid diagnostic limit: {name}')
        if not 0 < self.io_seconds <= 5 or not 0 < self.total_seconds <= 30:
            raise ValueError('Invalid diagnostic timeout')


class Budget:
    def __init__(self, limits):
        self.limits, self.started = limits, time.monotonic()
        self.used = {'sql': 0, 'redis': 0}
        self.lock = threading.Lock()

    def remaining(self):
        return max(0, self.limits.total_seconds - (time.monotonic() - self.started))

    def timeout(self):
        value = min(self.limits.io_seconds, self.remaining())
        if value <= 0:
            raise DiagnosticLimit('整体诊断时间已达上限；未取得的证据保持未知')
        return value

    def claim(self, kind, count=1):
        with self.lock:
            self.timeout()
            if self.used[kind] + count > getattr(self.limits, kind):
                raise DiagnosticLimit(f'{kind} 读取次数已达上限')
            self.used[kind] += count

    async def redis_call(self, operation, *args, command_cost=1, **kwargs):
        self.claim('redis', command_cost)
        return await asyncio.wait_for(operation(*args, **kwargs), self.timeout())

    def report(self):
        return {'limits': asdict(self.limits), 'used': dict(self.used),
                'elapsed_seconds': round(time.monotonic() - self.started, 3),
                'counting': 'SQL 包含受守卫 SELECT 及每个物理连接五次驱动只读探测的保守预留；'
                            '连接协议、SET 会话初始化及事务清理不计为业务查询。'
                            'Redis 按脚本内 redis.call 读取命令的最大次数预留，包含返回前未使用预留。'}


def guard_select(statement):
    """Only the existing formal bounded SELECT path is available to this lane."""
    compact = re.sub(r'/\*.*?\*/', '', statement, flags=re.S).strip()
    if (not re.match(r'^SELECT\b', compact, re.I) or ';' in compact
            or re.search(r'\b(?:INTO|FOR\s+UPDATE|LOCK\s+IN|SLEEP|BENCHMARK|GET_LOCK|RELEASE_LOCK)\b', compact, re.I)):
        raise DiagnosticLimit('诊断 SQL 通道拒绝非只读语句或锁定读取')
    # A point lookup or bounded monthly calendar query is also finite. Broad
    # aggregate scans are not an acceptable shortcut for a project summary.
    initialization = compact.upper() in {
        'SELECT DATABASE()', 'SELECT @@SQL_MODE', 'SELECT @@LOWER_CASE_TABLE_NAMES'}
    if (not initialization and 'LIMIT' not in compact.upper()
            and not re.search(r'\b(?:namespace|project_id|trade_date)\b\s*(?:=|BETWEEN)', compact, re.I)):
        raise DiagnosticLimit('正式查询未声明有界范围；诊断没有执行全历史扫描')
    return compact


class ReadOnlyMySQL:
    """Reuse formal query callbacks and the engine factory, never start a plugin.

    A deadline closes only this diagnostic's sockets. Worker threads are daemon
    threads so cancellation cannot make asyncio.run wait on its default executor.
    Every later SQL statement still crosses the expired/closed budget guard.
    """
    def __init__(self, settings, budget, *, engine=None):
        self.budget = budget
        self.read_engine = engine or make_engine(
            {**settings, 'connect_timeout': max(1, int(budget.limits.io_seconds))},
            pool_size=1, read_timeout=max(1, int(budget.limits.io_seconds)))
        self.closed = False
        self.connections = set()
        self.owned = set()
        self.workers = set()
        self.guard = threading.Lock()
        event.listen(self.read_engine, 'before_cursor_execute', self._before, retval=True)
        if self.read_engine.dialect.name == 'mysql':
            event.listen(self.read_engine, 'do_connect', self._connect)
        event.listen(self.read_engine, 'checkout', self._checkout)
        event.listen(self.read_engine, 'checkin', self._checkin)

    def _connect(self, dialect, record, args, options):
        # The locked MySQL dialect performs five cold-connection SELECTs before
        # SQLAlchemy exposes before_cursor_execute: VERSION, DATABASE, isolation,
        # sql_mode and lower_case_table_names. Reserve all five before opening
        # each physical connection, even when a warm dialect needs fewer probes.
        self.budget.claim('sql', 5)
        options = {**options, 'read_timeout': self.budget.timeout(),
                   'write_timeout': self.budget.timeout()}
        connection = dialect.loaded_dbapi.connect(*args, **options)
        with self.guard:
            self.owned.add(connection)
        if self.closed:
            connection._force_close()
            raise DiagnosticLimit('诊断截止后建立的连接已关闭，未执行后续查询')
        return connection

    def _checkout(self, dbapi, record, proxy):
        with self.guard:
            self.connections.add(dbapi)
            self.owned.add(dbapi)
        if self.closed:
            dbapi.close()
            raise DiagnosticLimit('诊断连接已关闭')

    def _checkin(self, dbapi, record):
        with self.guard:
            self.connections.discard(dbapi)

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        if self.closed or executemany:
            raise DiagnosticLimit('诊断 SQL 通道已关闭或不接受批量语句')
        statement = guard_select(statement)
        self.budget.claim('sql')
        if conn.dialect.name == 'mysql':
            milliseconds = max(1, int(self.budget.timeout() * 1000))
            statement = re.sub(r'^SELECT\b', f'SELECT /*+ MAX_EXECUTION_TIME({milliseconds}) */',
                               statement, count=1, flags=re.I)
            dbapi = conn.connection.dbapi_connection
            if getattr(dbapi, '_sock', None):
                dbapi._sock.settimeout(self.budget.timeout())
        return statement, parameters

    async def read(self, operation, *args):
        if self.closed:
            raise DiagnosticLimit('诊断 SQL 通道已关闭；未重新建立连接重试')
        timeout = self.budget.timeout()
        loop, result = asyncio.get_running_loop(), asyncio.get_running_loop().create_future()

        def settle(value, error):
            if not result.done():
                if error is not None:
                    result.set_exception(error)
                else:
                    result.set_result(value)

        def run():
            try:
                value, error = operation(*args), None
            except Exception as exc:
                value, error = None, exc
            try:
                loop.call_soon_threadsafe(settle, value, error)
            except RuntimeError:
                pass  # The diagnostic has returned; no late report mutation.
            finally:
                with self.guard:
                    self.workers.discard(threading.current_thread())

        worker = threading.Thread(target=run, name='empire-diagnostic-read', daemon=True)
        with self.guard:
            self.workers.add(worker)
        worker.start()
        try:
            return await asyncio.wait_for(result, timeout)
        except (TimeoutError, asyncio.CancelledError):
            self.close()
            raise

    def close(self):
        self.closed = True
        with self.guard:
            connections, workers = tuple(self.owned), tuple(self.workers)
        for connection in connections:
            try:
                transport = getattr(connection, '_sock', None)
                if transport is not None:
                    # Shutdown interrupts a blocked read before PyMySQL can try
                    # QUIT with its normal (longer) write timeout.
                    try:
                        transport.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    connection._force_close()
                else:
                    connection.close()
            except Exception:
                pass
        self.read_engine.dispose()
        for worker in workers:
            worker.join(timeout=min(.05, self.budget.remaining()))

    def cleanup_status(self):
        with self.guard:
            outstanding = sum(t.is_alive() for t in self.workers)
        return {'closed_to_new_sql': self.closed, 'outstanding_workers': outstanding,
                'complete': self.closed and outstanding == 0}
