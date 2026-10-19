"""Project diagnostics retain partial evidence and cannot start business work."""
import asyncio
import copy
import json
import re
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import create_engine, event, text

from empire.contracts.dataset import DatasetContribution
from empire.contracts.plugin import PluginManifest
from empire.contracts.task import TaskContribution
from empire.diagnostics.declarations import project_declaration, query_preview
from empire.diagnostics.project import diagnose_project, isolation, render_report
from empire.diagnostics.readonly import Budget, DiagnosticLimit, Limits, ReadOnlyMySQL, guard_select
from empire.diagnostics.redis_evidence import (
    CHECKPOINT,
    COMMAND_COST,
    CONTROL,
    ERROR_DETAIL,
    LIST_ERROR_SUMMARIES,
    PROGRESS,
    QUEUE,
    READ_SCRIPTS,
    RedisEvidence,
)
from empire.features.news.query import NewsDataPlugin
from empire.plugins.pipeline.archive import ArchivePlugin

CFG = {'redis': {'namespace': 'empire:test:diagnostic', 'password': 'RedisCredential'},
       'mysql': {'password': 'SQLCredential'}, 'archive': {}, 'ingest': {}, 'rate_groups': {}}
PROJECT = 'sina-news'
JOB = 'sina-news-v1'


class MemoryRedis:
    def __init__(self):
        self.commands = []
        self.fail = False
        self.pause = False
        self.state = {
            'errors': [{'id': 'exact-error', 'project_id': PROJECT, 'stage': 'parse',
                        'error': 'bad password=RedisCredential', 'body': 'SECRET-BODY',
                        'created_at': '2026-10-19T12:00:00+08:00'}],
            'control': {'job': {'last_status': 'paused', 'next_due': None, 'active': None,
                                'policy': {'enabled': False}}, 'history': []},
            'checkpoint': {'revision': '5', 'cursor': json.dumps({'next': 17})},
            'progress': {'status': 'source_gap', 'page': 16},
            'queue': {'stream_total': 1, 'project_lower_bound': 1, 'scanned': 1,
                      'exact': True, 'truncated': False, 'stream_ids': ['123-0']},
            'fingerprint': {'content': 'untouched', 'expires_at': 'unchanged'},
        }

    async def eval(self, script, count, *args):
        assert script in READ_SCRIPTS
        self.commands.append((script, count, args))
        if self.pause:
            await asyncio.Event().wait()
        if self.fail:
            raise ConnectionError('redis://someone:RedisCredential@invalid; SQLCredential')
        if script == LIST_ERROR_SUMMARIES:
            values = self.state['errors'][:int(args[-1])]
            return ['1', str(len(self.state['errors'])), '1', '0', *(
                json.dumps({k: row.get(k) for k in ('id', 'project_id', 'created_at', 'stage', 'error', 'status_code')})
                for row in values)]
        if script == ERROR_DETAIL:
            return next((json.dumps(row) for row in self.state['errors'] if row['id'] == args[-1]), None)
        name = {CONTROL: 'control', CHECKPOINT: 'checkpoint', PROGRESS: 'progress', QUEUE: 'queue'}[script]
        return json.dumps(self.state[name])


@pytest.fixture
def manager():
    news = NewsDataPlugin(namespace=CFG['redis']['namespace'])
    task = TaskContribution(PROJECT, '新闻', 'collector.news', 'sina', '增量快讯窗口')
    mapping = SimpleNamespace(DATASETS={'news.flash.page'}, FINGERPRINT_NAMESPACE='news')
    catalog = SimpleNamespace(contributions=(DatasetContribution(mapping, 'incremental', {JOB: PROJECT}),))
    collector = SimpleNamespace(manifest=PluginManifest('collector.news', '新闻采集', requires=('news.schema',)))
    entries = {ident: SimpleNamespace(plugin=plugin) for ident, plugin in (
        ('control', SimpleNamespace(definitions={PROJECT: task})), ('catalog', catalog),
        ('collector.news', collector), ('data.news', news))}
    return SimpleNamespace(entries=entries, providers={'collection.control': 'control',
        'dataset.catalog': 'catalog', 'collector.news': 'collector.news', 'news.schema': 'data.news'})


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'diagnostics.sqlite'
    engine = create_engine('sqlite:///' + str(path), connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def functions(connection, record):
        connection.create_function('OCTET_LENGTH', 1, lambda value: len(str(value).encode()) if value is not None else None)
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE collection_state(namespace TEXT,project_id TEXT,source TEXT,dataset TEXT,payload TEXT,updated_at TEXT)')
        conn.exec_driver_sql('CREATE TABLE app_setting(namespace TEXT,kind TEXT,setting_key TEXT,payload TEXT,updated_at TEXT)')
        conn.execute(text('INSERT INTO collection_state VALUES(:ns,:p,\'sina\',\'news.flash.page\',:payload,\'2026-10-19\')'),
            dict(ns=CFG['redis']['namespace'], p=PROJECT, payload=json.dumps({'progress': {'status': 'source_gap'}})))
        conn.execute(text('INSERT INTO app_setting VALUES(:ns,\'task\',:p,:payload,\'2026-10-19\')'),
            dict(ns=CFG['redis']['namespace'], p=PROJECT, payload=json.dumps({'enabled': False})))
        conn.exec_driver_sql('CREATE TABLE finance_news(source TEXT,news_id INTEGER,title TEXT,content TEXT,published_at TEXT,source_updated_at TEXT,is_important INTEGER,tags TEXT,url TEXT,version_observed_at TEXT)')
    yield engine, path
    engine.dispose()


def frozen_db(path):
    with sqlite3.connect(path) as conn:
        return list(conn.iterdump())


async def test_project_reads_paused_gap_pending_and_exact_ids_without_mutation(manager, database):
    engine, path = database
    redis = MemoryRedis()
    before, sql_before = copy.deepcopy(redis.state), frozen_db(path)
    original_query = manager.entries['data.news'].plugin
    original_mysql = original_query.mysql = object()
    budget = Budget(Limits())
    mysql = ReadOnlyMySQL({}, budget, engine=engine)
    try:
        report = await diagnose_project(CFG, PROJECT, manager=manager, client=redis, mysql=mysql,
            runtime_snapshot={'plugins': [{'id': 'pipeline.archive', 'state': 'DEGRADED',
                'health': {'blocked': False, 'blocked_projects': [PROJECT]}}]})
        sections = report['sections']
        assert sections['errors']['data']['rows'][0]['id'] == 'exact-error'
        assert sections['task_state']['data']['job']['last_status'] == 'paused'
        assert sections['task_state']['data']['job']['next_due'] is None
        assert sections['checkpoint:' + JOB]['data']['cursor'] == {'next': 17}
        assert sections['queue']['data']['project_lower_bound'] == 1
        assert sections['archive_progress:' + JOB]['data']['status'] == 'source_gap'
        assert sections['isolation']['data']['project_blocked'] is True
        assert sections['isolation']['data']['global_blocked'] is False
        assert sections['sql_state']['status'] == 'ok'
        assert sections['query:news.query']['status'] == 'ok'
        assert sections['query:news.query']['data']['arguments']['include_total'] is False
        assert 'SECRET-BODY' not in render_report(report)
        assert 'RedisCredential' not in render_report(report)
        assert redis.state == before and frozen_db(path) == sql_before
        assert original_query.mysql is original_mysql
        assert all(v['acquired_at'] and v['started_at'] for v in sections.values())
        assert report['budget']['used']['sql'] == 3
        assert report['budget']['used']['redis'] <= 20
    finally:
        mysql.close()


@pytest.mark.parametrize('failure', ['connection', 'driver_timeout', 'timeout'])
async def test_redis_failure_retains_sql_and_never_retries_or_leaks(manager, database, failure):
    failure_types = {'connection': ConnectionError, 'driver_timeout': RedisTimeoutError,
                     'timeout': TimeoutError}

    class FailedRedis(MemoryRedis):
        async def eval(self, script, count, *args):
            assert script in READ_SCRIPTS
            self.commands.append((script, count, args))
            raise failure_types[failure]('redis://someone:RedisCredential@invalid; SQLCredential')

    redis = FailedRedis()
    # This verifies service independence with the real bounded SQL reader.
    # SQLite worker scheduling is not required to finish inside the Redis timer.
    limits = Limits()
    mysql = ReadOnlyMySQL({}, Budget(limits), engine=database[0])
    try:
        result = await diagnose_project(CFG, PROJECT, manager=manager, client=redis,
                                        mysql=mysql, limits=limits)
        assert result['status'] == 'partial'
        assert len(redis.commands) == 1
        assert result['sections']['errors']['status'] == ('partial' if failure == 'timeout' else 'error')
        assert result['sections']['sql_state']['status'] == 'ok'
        assert result['sections']['query:news.query']['status'] == 'ok'
        assert result['sections']['isolation']['status'] == 'unknown'
        assert result['budget']['used'] == {'sql': 3, 'redis': COMMAND_COST[LIST_ERROR_SUMMARIES]}
        assert all(secret not in render_report(result) for secret in ('SQLCredential', 'RedisCredential'))
    finally:
        mysql.close()


async def test_redis_real_deadline_cancels_inflight_read_and_blocks_followup():
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class PausedRedis(MemoryRedis):
        async def eval(self, script, count, *args):
            assert script in READ_SCRIPTS
            self.commands.append((script, count, args))
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    redis = PausedRedis()
    budget = Budget(Limits(io_seconds=.02))
    evidence = RedisEvidence(redis, CFG['redis']['namespace'], budget)
    task = asyncio.create_task(evidence.errors(PROJECT))
    try:
        # This is a test deadlock guard, not a performance acceptance threshold.
        # Assert the production timer completed the task, so the guard itself
        # cannot be mistaken for a successfully observed Redis timeout.
        done, pending = await asyncio.wait({task}, timeout=5)
        assert task in done and not pending
        with pytest.raises(TimeoutError):
            task.result()
        assert entered.is_set() and cancelled.is_set()
        assert evidence.unavailable
        with pytest.raises(DiagnosticLimit, match='没有重复连接或重试'):
            await evidence.control(PROJECT)
        assert len(redis.commands) == 1
        assert budget.used == {'sql': 0, 'redis': COMMAND_COST[LIST_ERROR_SUMMARIES]}
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_sql_failure_keeps_redis_errors_and_checkpoint(manager):
    class Broken:
        async def read(self, *args):
            raise ConnectionError('mysql://user:SQLCredential@unavailable')
    query = manager.entries['data.news'].plugin
    original = query.mysql = object()
    result = await diagnose_project(CFG, PROJECT, manager=manager, client=MemoryRedis(), mysql=Broken())
    assert result['sections']['errors']['status'] == 'ok'
    assert result['sections']['checkpoint:' + JOB]['data']['revision'] == '5'
    assert result['sections']['sql_state']['status'] == 'error'
    assert 'SQLCredential' not in render_report(result)
    assert query.mysql is original


async def test_cancellation_does_not_replace_query_plugin_connection(manager, monkeypatch):
    class Reader:
        async def read(self, *args):
            return None
    entered = asyncio.Event()
    async def blocked(self, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(NewsDataPlugin, 'list_news', blocked)
    query = manager.entries['data.news'].plugin
    original = query.mysql = object()
    # The normal method signature is part of public query selection; retain it.
    import inspect
    blocked.__signature__ = inspect.Signature([
        inspect.Parameter('self', inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter('limit', inspect.Parameter.POSITIONAL_OR_KEYWORD, default=20)])
    task = asyncio.create_task(diagnose_project(CFG, PROJECT, manager=manager,
                                               client=MemoryRedis(), mysql=Reader()))
    await asyncio.wait_for(entered.wait(), .5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert query.mysql is original


async def test_oversized_sql_state_projection_is_partial_not_missing(manager, database):
    engine, _ = database
    with engine.begin() as conn:
        conn.execute(text('UPDATE collection_state SET payload=:value'),
                     {'value': json.dumps({'progress': {'value': 'x' * 140000}, 'coverage': {'from': '2026'}})})
    mysql = ReadOnlyMySQL({}, Budget(Limits()), engine=engine)
    try:
        result = await diagnose_project(CFG, PROJECT, manager=manager, client=MemoryRedis(), mysql=mysql)
        state = result['sections']['sql_state']
        assert state['status'] == 'partial'
        assert state['data']['progress'] is None and state['data']['progress_truncated'] == 1
        assert state['data']['coverage_truncated'] == 0
    finally:
        mysql.close()


async def test_summary_cap_and_explicit_error_body_byte_limit(manager, database):
    redis = MemoryRedis()
    redis.state['errors'] *= 60
    redis.state['errors'][0] = {**redis.state['errors'][0], 'body': '汉' * 40000}
    mysql = ReadOnlyMySQL({}, Budget(Limits()), engine=database[0])
    try:
        result = await diagnose_project(CFG, PROJECT, manager=manager, client=redis, mysql=mysql,
                                        error_id='exact-error')
        assert len(result['sections']['errors']['data']['rows']) == 50
        assert result['sections']['errors']['status'] == 'partial'
        detail = result['sections']['error_detail']
        assert detail['status'] == 'partial'
        assert len(detail['data']['body'].encode()) <= 65536
        assert detail['data']['body_truncated']
        assert len(render_report(result).encode()) <= 1048576
    finally:
        mysql.close()


async def test_budget_exhaustion_is_partial_and_queue_sample_never_claims_zero(manager, database):
    redis = MemoryRedis()
    redis.state['queue'].update(project_lower_bound=0, stream_total=100, exact=False, truncated=True)
    mysql = ReadOnlyMySQL({}, Budget(Limits()), engine=database[0])
    try:
        result = await diagnose_project(CFG, PROJECT, manager=manager, client=redis, mysql=mysql)
        queue = result['sections']['queue']
        assert queue['status'] == 'partial' and queue['data']['exact'] is False
        assert queue['data']['project_lower_bound'] == 0
        limited = await diagnose_project(CFG, PROJECT, manager=manager, client=redis, mysql=mysql,
                                         limits=Limits(redis=3))
        assert limited['budget']['used']['redis'] == 3
        assert limited['sections']['checkpoint:' + JOB]['status'] == 'partial'
    finally:
        mysql.close()


async def test_sql_guard_rejects_writes_locks_scans_and_enforces_real_statement_budget(database):
    engine, path = database
    before = frozen_db(path)
    budget = Budget(Limits(sql=1))
    mysql = ReadOnlyMySQL({}, budget, engine=engine)
    try:
        def execute(sql):
            with mysql.read_engine.connect() as conn:
                return conn.execute(text(sql)).all()
        for statement in ('DELETE FROM finance_news', 'UPDATE app_setting SET payload=\'{}\'',
                          'SELECT * FROM finance_news FOR UPDATE', 'SELECT COUNT(*) FROM finance_news',
                          'SELECT 1; SELECT 2', 'SELECT SLEEP(10) LIMIT 1'):
            with pytest.raises(DiagnosticLimit):
                await mysql.read(execute, statement)
        await mysql.read(execute, 'SELECT * FROM finance_news LIMIT 1')
        with pytest.raises(DiagnosticLimit, match='次数'):
            await mysql.read(execute, 'SELECT * FROM finance_news LIMIT 1')
        assert budget.used['sql'] == 1
        assert frozen_db(path) == before
    finally:
        mysql.close()


async def test_read_deadline_closes_only_diagnostic_lane_and_blocks_followup(database):
    import threading
    engine, _ = database
    release = threading.Event()
    mysql = ReadOnlyMySQL({}, Budget(Limits(io_seconds=.02)), engine=engine)
    try:
        with pytest.raises(TimeoutError):
            await mysql.read(lambda: release.wait(.5))
        assert mysql.closed
        with pytest.raises(DiagnosticLimit, match='关闭'):
            await mysql.read(lambda: 1)
    finally:
        release.set()
        mysql.close()
        assert mysql.cleanup_status()['complete']


async def test_overall_deadline_marks_remaining_sections_and_preserves_earlier_evidence(manager):
    class Slow:
        async def read(self, *args):
            await asyncio.Event().wait()
    started = asyncio.get_running_loop().time()
    result = await diagnose_project(CFG, PROJECT, manager=manager, client=MemoryRedis(), mysql=Slow(),
                                    limits=Limits(io_seconds=.02, total_seconds=.05))
    assert asyncio.get_running_loop().time() - started < .2
    assert result['sections']['errors']['status'] == 'ok'
    assert result['sections']['sql_state']['status'] == 'partial'
    assert result['sections']['saved_policy']['status'] == 'partial'
    assert result['sections']['query:news.query']['status'] == 'partial'


def test_socket_shutdown_precedes_connection_close_and_cleanup_reports_owned_worker(database):
    events = []
    class Transport:
        def shutdown(self, how):
            events.append('shutdown')
    class Connection:
        _sock = Transport()
        def _force_close(self):
            events.append('force-close')
        def close(self):
            raise AssertionError('QUIT could block after timeout')
    mysql = ReadOnlyMySQL({}, Budget(Limits()), engine=database[0])
    mysql.owned.add(Connection())
    mysql.close()
    assert events == ['shutdown', 'force-close']
    assert mysql.cleanup_status() == {'closed_to_new_sql': True, 'outstanding_workers': 0, 'complete': True}


def test_mysql_fixed_initialization_queries_are_bounded_and_driver_probes_reserved(database):
    for statement in ('SELECT DATABASE()', 'SELECT @@sql_mode', 'SELECT @@lower_case_table_names'):
        assert guard_select(statement) == statement
    with pytest.raises(DiagnosticLimit):
        guard_select('SELECT @@arbitrary_setting')
    mysql = ReadOnlyMySQL({}, Budget(Limits()), engine=database[0])
    calls = []
    class Connection:
        def close(self):
            pass
    def connect(*args, **kwargs):
        calls.append(kwargs)
        return Connection()
    dialect = SimpleNamespace(loaded_dbapi=SimpleNamespace(connect=connect))
    mysql._connect(dialect, None, (), {'host': 'isolated'})
    assert mysql.budget.used['sql'] == 5
    assert calls[0]['read_timeout'] <= 5 and calls[0]['write_timeout'] <= 5
    mysql.close()


def test_redis_scripts_only_call_bounded_read_commands_and_unknown_script_is_rejected():
    allow = {'GET', 'STRLEN', 'HSTRLEN', 'HMGET', 'LLEN', 'LRANGE', 'XLEN', 'XRANGE'}
    for script in READ_SCRIPTS:
        assert set(re.findall(r"redis.call\('([^']+)'", script)) <= allow
        assert 'SCAN' not in script and 'KEYS' not in script.replace('KEYS[', '')
    assert "'COUNT', 1" in QUEUE and 'for slot=1,5' in QUEUE
    assert "0, 299" in ERROR_DETAIL
    assert COMMAND_COST[QUEUE] == 6


async def test_unknown_script_never_reaches_redis():
    redis = MemoryRedis()
    evidence = RedisEvidence(redis, 'empire:test', Budget(Limits()))
    with pytest.raises(ValueError, match='拒绝'):
        await evidence.evaluate("return redis.call('DEL', KEYS[1])", 1, 'some-key')
    assert not redis.commands


def test_declarations_never_start_manager_and_all_registered_projects_resolve(monkeypatch):
    from empire.bootstrap import build_manager
    from empire.core.manager import PluginManager
    async def forbidden(*args):
        raise AssertionError('diagnostic started a plugin')
    monkeypatch.setattr(PluginManager, 'start', forbidden)
    actual = build_manager(CFG)
    for project in actual.entries['collection.control'].plugin.definitions:
        declaration, _ = project_declaration(CFG, project, actual)
        assert declaration['job_keys'] and declaration['datasets']
        assert declaration['declared_scope']
    assert all(entry.state == 'STOPPED' and entry.context is None for entry in actual.entries.values())
    actual.entries['collection.control'].context = object()
    with pytest.raises(ValueError, match='未启动'):
        project_declaration(CFG, PROJECT, actual)


def test_isolation_uses_current_snapshot_not_old_errors_and_archive_health_exposes_global():
    assert isolation(None, PROJECT)['status'] == 'unknown'
    archive = ArchivePlugin({})
    archive.blocked = True
    assert archive.health()['blocked'] is True
    state = {'plugins': [{'id': 'pipeline.archive', 'state': 'DEGRADED', 'health': archive.health()}]}
    assert isolation(state, PROJECT)['global_blocked'] is True


def test_formal_preview_preserves_security_identity_and_explicit_split_contract():
    from empire.features.holders.query import HolderDataPlugin
    from empire.plugins.data.financial_statements import FinancialDataPlugin
    from empire.plugins.data.suspensions import SuspensionDataPlugin
    method, kwargs = query_preview(HolderDataPlugin('top_holders'), '000001.SZ', '2026-09-30')
    assert method == 'browse' and kwargs['code'] == '000001.SZ'
    assert kwargs['start'] == kwargs['end'] == '2026-09-30'
    _, kwargs = query_preview(SuspensionDataPlugin(), '000001.SZ', '2026-09-30')
    assert kwargs['code'] == '000001' and kwargs['market'] == 'SZ'
    _, kwargs = query_preview(FinancialDataPlugin('income'), '000001.SZ')
    assert kwargs['code'] == '000001'


@pytest.mark.parametrize('kind', ('trend', 'auction', 'volume', 'trades', 'entrust', 'large_order', 'quote'))
def test_market_preview_uses_bounded_reader_for_requested_day(kind):
    from empire.plugins.data.kaipanla_products import KaipanlaProductDataPlugin
    method, kwargs = query_preview(KaipanlaProductDataPlugin(kind), '000001.SZ', '2020-01-01')
    assert method == ('day' if kind == 'quote' else 'page')
    assert kwargs == {'market': 'SZ', 'code': '000001', 'trade_date': '2020-01-01',
                      **({} if kind == 'quote' else {'limit': 20})}
    with pytest.raises(DiagnosticLimit, match='未改查最新日期'):
        query_preview(SimpleNamespace(archived_date=lambda: None), '000001.SZ', '2020-01-01')


async def test_market_preview_reads_requested_old_day_when_a_newer_day_exists(database):
    from empire.plugins.data.kaipanla_products import KaipanlaProductDataPlugin
    engine, _ = database
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE stock_market_day(kind TEXT,unified_code TEXT,trade_date TEXT,'
                             'content_hash TEXT,point_count INTEGER,version_observed_at TEXT)')
        conn.exec_driver_sql('CREATE TABLE stock_intraday_trend(unified_code TEXT,trade_date TEXT,seq INTEGER,'
                             'source_time TEXT,price INTEGER,average_price INTEGER,source_volume INTEGER,'
                             'source_flag INTEGER,float_mask INTEGER)')
        for day, price in (('2020-01-01', 10), ('2026-10-19', 20)):
            conn.execute(text("INSERT INTO stock_market_day VALUES('trend','000001.SZ',:day,'hash',1,:day)"),
                         {'day': day})
            conn.execute(text("INSERT INTO stock_intraday_trend VALUES('000001.SZ',:day,0,'09:30',:price,1,1,1,0)"),
                         {'day': day, 'price': price})
    mysql = ReadOnlyMySQL({}, Budget(Limits()), engine=engine)
    plugin = KaipanlaProductDataPlugin('trend')
    plugin.mysql = mysql
    try:
        method, kwargs = query_preview(plugin, '000001.SZ', '2020-01-01')
        result = await getattr(plugin, method)(**kwargs)
        assert result['points'] == [['09:30', 10, 1, 1, 1]]
        assert result['observed_at'] == '2020-01-01'
        assert mysql.budget.used['sql'] == 2
    finally:
        mysql.close()


def test_report_cap_retains_status_times_and_marks_dropped_evidence():
    report = {'status': 'ok', 'sections': {
        f'section-{i}': {'status': 'ok', 'started_at': 'a', 'acquired_at': 'b', 'data': '字' * 1000}
        for i in range(8)}}
    value = render_report(report, 2000)
    assert len(value.encode()) <= 2000 and report['status'] == 'partial'
    assert report['truncated'] is True
    assert all(item['acquired_at'] == 'b' for item in report['sections'].values())


def test_cli_project_diagnostic_is_read_only_and_output_refuses_overwrite(monkeypatch, tmp_path):
    import empire.__main__ as cli
    import empire.diagnostics.project as diagnostic
    output = tmp_path / 'report.json'
    def forbidden(*args, **kwargs):
        raise AssertionError('read-only diagnostic started logging or desktop')
    async def diagnose(*args, **kwargs):
        return {'status': 'partial', 'read_only': True, 'sections': {}}
    monkeypatch.setattr(cli, 'load_config', lambda path: CFG)
    monkeypatch.setattr(cli, 'configure_logging', forbidden)
    monkeypatch.setattr(cli, 'run_gui', forbidden)
    monkeypatch.setattr(diagnostic, 'diagnose_project', diagnose)
    monkeypatch.setattr(sys, 'argv', ['empire', 'doctor', '--project', PROJECT, '--output', str(output)])
    assert cli.main() == 2
    original = output.read_bytes()
    assert cli.main() == 1
    assert output.read_bytes() == original


def test_missing_config_diagnostic_never_creates_template(monkeypatch, tmp_path):
    import empire.__main__ as cli
    import empire.core.config as config
    missing = tmp_path / 'missing.toml'
    monkeypatch.setattr(config, 'default_config_path', lambda: missing)
    monkeypatch.setattr(sys, 'argv', ['empire', 'doctor', '--project', PROJECT])
    assert cli.main() == 1 and not missing.exists()
