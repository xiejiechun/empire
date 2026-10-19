"""Safety and content counterexamples; no external service or source requests."""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from empire.core.redaction import Redactor


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    module = importlib.import_module('source_verification')
    return module


@pytest.fixture
def storage_module(verifier):
    return sys.modules['source_test_storage']


def pool(count=40):
    return [dict(unified_code=f'{number:06d}.SH', name=f'证券{number}') for number in range(count)]


def test_aliases_cannot_disguise_same_mysql_server(storage_module):
    with pytest.raises(ValueError, match='server_uuid'):
        storage_module.ensure_separate_server('ABC-server', 'abc-server')
    storage_module.ensure_separate_server('production-uuid', 'test-uuid')


def test_same_server_refused_before_any_ddl(storage_module, monkeypatch):
    conn = Mock()
    conn.execute.return_value.scalar_one.return_value = 'production-uuid'
    engine = Mock()
    engine.connect.return_value = conn
    monkeypatch.setattr(storage_module, 'make_engine', lambda *a, **k: engine)
    owned = storage_module.PrivateStorage(dict(host='alias', port=13348, user='test'), {},
                                          'a' * 32, 'b' * 64, 'production-uuid')
    with pytest.raises(ValueError, match='server_uuid'):
        owned.create_sql()
    assert [str(call.args[0]) for call in conn.execute.call_args_list] == ['SELECT @@server_uuid']
    assert not owned.created and not owned.locked


@pytest.mark.parametrize('port', [3307, '13348', True, None])
def test_explicit_test_service_required(storage_module, port):
    with pytest.raises(ValueError, match='13348'):
        storage_module.test_settings(dict(host='localhost', port=port, user='test'))


def test_target_database_is_generated_and_never_supplied(storage_module):
    owned = storage_module.PrivateStorage(dict(host='localhost', port=13348, user='test', database='empire'),
                                          {}, 'a' * 32, 'b' * 64, 'production-uuid')
    assert owned.settings['database'] == 'empire_verify_ths_' + 'a' * 32 + '_test'
    assert owned.namespace == 'empire:test:verify_ths:' + 'a' * 32


@pytest.mark.parametrize('statement', [
    'USE empire', 'INSERT INTO empire.income_statement VALUES (1)',
    'UPDATE `empire`.`income_statement` SET payload=1',
    'DELETE FROM empire.income_statement', 'DROP DATABASE empire',
    'SELECT 1; DELETE FROM stock', "SELECT 1 INTO OUTFILE 'file'",
    'UPDATE income_statement JOIN empire.income_statement x ON 1=1 SET x.payload=1',
    'SELECT * FROM empire.stock', 'SELECT * FROM `empire`.`stock`',
    'SELECT * FROM stock s, empire.stock p WHERE s.unified_code=p.unified_code',
    'SELECT * FROM (SELECT * FROM empire.stock) x',
    'UPDATE stock s, empire.stock p SET s.name=p.name',
    'UPDATE stock s, stock p SET s.name=p.name',
    'SELECT * FROM mysql.user', 'SELECT * FROM information_schema.unknown_table',
    'SELECT empire.stored_reader()', 'SELECT 1 /*! UNION SELECT * FROM empire.stock */',
    'INSERT empire.stock VALUES (1)', 'REPLACE empire.stock VALUES (1)',
    'REPLACE INTO stock VALUES (1)', 'ALTER TABLE stock RENAME TO empire.stock',
    'CREATE TABLE stock LIKE empire.stock', 'CREATE TABLE stock AS SELECT * FROM empire.stock',
    'DROP TABLE stock', 'UPDATE LOW_PRIORITY empire.stock SET name=1',
    'UPDATE IGNORE empire.stock SET name=1', 'DELETE FROM t USING empire.stock AS t',
    'SELECT * FROM (empire.stock)', 'SELECT * FROM stock JOIN (empire.stock) ON 1=1',
    'SELECT 1 # hidden comment',
    'WITH x AS (SELECT * FROM empire.stock) SELECT * FROM x',
    'EXPLAIN SELECT * FROM stock', 'SELECT * FROM stock UNION TABLE empire.stock',
    'SELECT * FROM stock STRAIGHT_JOIN empire.stock other ON 1=1',
    'SHOW VARIABLES WHERE 1=(SELECT COUNT(*) FROM empire.stock)',
    'SHOW COLLATION WHERE empire.stored_reader()=1', 'DESCRIBE stock foreign_column',
    'SELECT LOAD_FILE(%(path)s)',
])
def test_business_connection_rejects_switch_and_cross_database_writes(storage_module, statement):
    with pytest.raises(ValueError):
        storage_module.check_business_statement(statement)


@pytest.mark.parametrize('statement', [
    'SELECT payload FROM income_statement WHERE unified_code=%(security)s ORDER BY report_date DESC LIMIT 501',
    'SELECT s.payload FROM income_statement s JOIN (SELECT unified_code,report_date FROM income_statement '
    'ORDER BY report_date DESC LIMIT %(limit)s OFFSET %(offset)s) chosen USING (unified_code,report_date)',
    'SELECT s.report_date,s.payload FROM income_statement s JOIN stock t ON t.unified_code=s.unified_code '
    'WHERE s.unified_code=%(code)s ORDER BY s.report_date DESC',
    'SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()',
    'SHOW FULL TABLES FROM `owned_test`', 'SHOW CREATE TABLE `owned_test`.`stock`', 'DESCRIBE `stock`',
    "SHOW VARIABLES LIKE 'sql_mode'", 'SHOW COLLATION',
    'SELECT s.unified_code FROM stock s WHERE EXISTS (SELECT 1 FROM stock t WHERE t.unified_code=s.unified_code)',
    'INSERT INTO collection_state(namespace,payload) VALUES(%(namespace)s,%(payload)s) '
    'ON DUPLICATE KEY UPDATE payload=VALUES(payload),updated_at=VALUES(updated_at)',
    'UPDATE collection_state SET payload=JSON_SET(payload,%(p0)s,CAST(%(v0)s AS JSON)),updated_at=%(time)s '
    'WHERE namespace=%(namespace)s AND project_id=%(project_id)s',
])
def test_current_formal_queries_metadata_and_writers_remain_allowed(storage_module, statement):
    storage_module.check_business_statement(statement, 'owned_test')


def test_current_explicit_schema_initializer_is_accepted_without_database(storage_module):
    schema = (Path(__file__).resolve().parents[1] / 'sql/schema.sql').read_text(encoding='utf-8')
    schema = '\n'.join(line for line in schema.splitlines() if not line.lstrip().startswith('--'))
    for statement in schema.split(';'):
        if statement.strip():
            storage_module.check_business_statement(statement, 'owned_test')


def test_business_guard_reads_actual_session_database(storage_module):
    owned = storage_module.PrivateStorage(dict(host='localhost', port=13348, user='test'), {},
                                          'a' * 32, 'b' * 64, 'production-uuid')
    owned.server_uuid = 'test-uuid'
    conn = Mock()
    conn.engine.url.database = owned.database
    conn.connection.cursor.return_value.fetchone.return_value = ('test-uuid', 'other_database')
    with pytest.raises(ValueError, match='实际实例或数据库'):
        owned.guard(conn, None, 'INSERT INTO stock VALUES (1)', None, None, False)


def test_business_guard_rejects_any_unowned_engine(storage_module):
    owned = storage_module.PrivateStorage(dict(host='localhost', port=13348, user='test'), {},
                                          'a' * 32, 'b' * 64, 'production-uuid')
    conn = Mock()
    conn.engine.url.database = 'production'
    with pytest.raises(ValueError, match='只能使用本轮'):
        owned.guard(conn, None, 'SELECT 1', None, None, False)
    conn.connection.cursor.assert_not_called()


def test_deterministic_random_30_preserves_market_identity_and_fixed_extra(verifier):
    stocks = pool() + [dict(unified_code='000001.BJ', name='同代码北交所')]
    first = verifier.select_stocks(stocks, 30, 12345, ['000001.BJ', '000001.SH'])
    second = verifier.select_stocks(list(reversed(stocks)), 30, 12345, ['000001.BJ', '000001.SH'])
    assert first == second
    assert len(first['random']) == len(set(first['random'])) == 30
    assert {'000001.BJ', '000001.SH'} <= {row['unified_code'] for row in first['selected']}
    assert first['pool_digest'] == verifier.digest(first['pool'])


@pytest.mark.parametrize('count,seed,fixed', [(30, None, []), (41, 1, []), (0, None, []),
                                            (1, 1, ['999999.SH']), (1, 1, ['000001.SH'] * 2)])
def test_selection_rejects_unknown_missing_or_replacement_pool(verifier, count, seed, fixed):
    with pytest.raises(ValueError):
        verifier.select_stocks(pool(), count, seed, fixed)


@pytest.mark.parametrize('counts', [{}, {'proxy_requests': 29},
                                  {'proxy_requests': 30, 'direct_requests': 1},
                                  {'proxy_requests': 30, 'fallback_requests': 1}])
def test_direct_or_insufficient_routes_never_pass_proxy_acceptance(verifier, counts):
    assert not verifier.strict_proxy(counts, 30)
    assert verifier.strict_proxy({'proxy_requests': 31}, 30)


def test_sql_owner_mismatch_refuses_drop(storage_module):
    owned = storage_module.PrivateStorage(dict(host='localhost', port=13348, user='test'), {},
                                          'a' * 32, 'b' * 64, 'production-uuid')
    owned.server_uuid = 'test-uuid'
    owned.created = owned.marked = owned.locked = True
    owned.conn = Mock()
    owned.conn.execute.return_value.one.return_value = ('test-uuid', 22, 22)
    owned.conn.execute.return_value.all.return_value = [('foreign', 'foreign', 'test-uuid', owned.database)]
    with pytest.raises(ValueError, match='owner'):
        owned.cleanup_sql()
    assert not any('DROP' in str(call.args[0]) for call in owned.conn.execute.call_args_list)


@pytest.mark.asyncio
async def test_redis_owner_change_preserves_all_keys(storage_module):
    owned = storage_module.PrivateStorage(dict(host='localhost', port=13348, user='test'), {},
                                          'a' * 32, 'b' * 64, 'production-uuid')
    owned.redis_owned = True
    async def scan(**kwargs):
        yield owned.namespace + ':ingest'
    owned.client = SimpleNamespace(scan_iter=scan, eval=AsyncMock(side_effect=RuntimeError('owner mismatch')))
    with pytest.raises(RuntimeError, match='owner mismatch'):
        await owned.cleanup_redis()
    args = owned.client.eval.await_args.args
    assert args[0] == storage_module.DELETE_OWNED
    assert args[2:4] == (owned.owner_key, owned.namespace + ':ingest')
    assert owned.redis_owned


@pytest.mark.asyncio
async def test_sql_cleanup_failure_does_not_skip_redis_or_hide_primary_error(verifier):
    owned = SimpleNamespace(cleanup_sql=Mock(side_effect=RuntimeError('sql failed')),
                            cleanup_redis=AsyncMock(), release_sql=Mock(), client=None,
                            remove_guard=Mock(), created=True, redis_owned=False)
    report = dict(errors=[dict(stage='verification', message='source failure')], cleanup={})
    await verifier.finish(None, owned, None, report, Redactor())
    owned.cleanup_redis.assert_awaited_once()
    owned.release_sql.assert_called_once()
    assert report['cleanup']['sql'] is False and report['cleanup']['redis'] is True
    assert [row['stage'] for row in report['errors']] == ['verification', 'sql']


@pytest.mark.asyncio
async def test_shutdown_failure_blocks_all_destructive_cleanup(verifier):
    manager = SimpleNamespace(shutdown=AsyncMock(side_effect=RuntimeError('producer active')))
    owned = SimpleNamespace(cleanup_sql=Mock(), cleanup_redis=AsyncMock(), release_sql=Mock(),
                            client=None, remove_guard=Mock(), created=True, redis_owned=True)
    lock = Mock()
    report = dict(errors=[], cleanup={})
    await verifier.finish(manager, owned, lock, report, Redactor())
    owned.cleanup_sql.assert_not_called()
    owned.cleanup_redis.assert_not_awaited()
    owned.release_sql.assert_not_called()
    owned.remove_guard.assert_not_called()
    lock.unlock.assert_not_called()
    assert report['cleanup']['shutdown'] is False
    assert report['cleanup']['instance_lock'] is False
    assert report['cleanup']['sql_lock'] is False
    assert report['cleanup']['connections'] is False
    assert (manager, owned, lock) in verifier._UNSETTLED_RUNS


def test_pass_requires_cleanup_and_no_original_failure(verifier):
    report = dict(pipeline_verified=True, strict_proxy_verified=True, errors=[],
                  cleanup=dict(shutdown=True, sql=True, redis=False, instance_lock=True,
                               sql_lock=True, connections=True))
    assert not verifier.final_pass(report, True)
    report['cleanup']['redis'] = True
    assert verifier.final_pass(report, True)
    report['errors'].append(dict(stage='verification', message='failure'))
    assert not verifier.final_pass(report, True)


def test_final_report_redacts_both_database_passwords(verifier, tmp_path):
    output = tmp_path / 'report.json'
    output.write_text('{}', encoding='utf-8')
    report = dict(run_id='a' * 32, passed=False,
                  errors=[dict(message='failure prod-p4ss test-p4ss')])
    verifier.write_report(output, report, Redactor(['prod-p4ss', 'test-p4ss']))
    saved = output.read_text(encoding='utf-8')
    assert 'prod-p4ss' not in saved and 'test-p4ss' not in saved
    assert json.loads(saved)['passed'] is False


def test_failed_atomic_write_keeps_previous_failed_evidence(verifier, tmp_path, monkeypatch):
    output = tmp_path / 'report.json'
    output.write_text('{"passed": false}', encoding='utf-8')
    monkeypatch.setattr(verifier.os, 'replace', Mock(side_effect=OSError('disk failure')))
    with pytest.raises(OSError, match='disk failure'):
        verifier.write_report(output, dict(run_id='a' * 32, passed=True), Redactor())
    assert json.loads(output.read_text(encoding='utf-8'))['passed'] is False


@pytest.fixture
def full_run(verifier, tmp_path, monkeypatch):
    """Fake external boundaries only; exercise real verifier finalization/report flow."""
    build = tmp_path / 'build'
    build.mkdir()
    settings = tmp_path / 'test-settings.json'
    settings.write_text(json.dumps(dict(host='localhost', port=13348, user='test', password='test-p4ss')),
                        encoding='utf-8')
    config_path = tmp_path / 'config.toml'
    config_path.write_text('# fake config', encoding='utf-8')
    args = SimpleNamespace(output=str(build / 'result.json'), pool_config=str(config_path),
                           test_mysql_settings=str(settings), random_count=30, seed=123,
                           codes=[], kinds=['income'], proxy_only=True, timeout=10)
    events = []
    config = dict(mysql=dict(password='prod-p4ss'), redis=dict(password='redis-p4ss', namespace='empire'))
    monkeypatch.setattr(verifier, 'project_root', lambda: tmp_path)
    monkeypatch.setattr(verifier, 'load_config', lambda path: config)
    monkeypatch.setattr(verifier, 'read_pool', lambda cfg: dict(server_uuid='production', stocks=pool(), settings=[]))
    monkeypatch.setattr(verifier, 'source_digest', lambda root: 'a' * 64)
    lock = SimpleNamespace(unlock=lambda: events.append('unlock'), isLocked=lambda: False)
    monkeypatch.setattr(verifier, 'acquire_instance_lock', lambda: lock)

    async def shutdown():
        events.append('shutdown')

    manager = SimpleNamespace(start=AsyncMock(), shutdown=shutdown, entries={})
    monkeypatch.setattr(verifier, 'build_manager', lambda cfg: manager)

    def storage_factory(mysql, redis, run_id, owner, production_uuid):
        return SimpleNamespace(identity=lambda: dict(run_id=run_id, database='owned', namespace='owned'),
            owner=owner, owner_key='owned:owner', settings=dict(database='owned'), namespace='owned',
            client=SimpleNamespace(get=AsyncMock(return_value=owner), aclose=AsyncMock()),
            create_sql=lambda before_create: (before_create(), events.append('create_sql')),
            create_redis=AsyncMock(), seed=Mock(),
            cleanup_sql=lambda: events.append('cleanup_sql'), cleanup_redis=AsyncMock(side_effect=lambda: events.append('cleanup_redis')),
            release_sql=lambda: events.append('release_sql'), remove_guard=Mock(), created=False, redis_owned=False)

    factory = Mock(side_effect=storage_factory)
    monkeypatch.setattr(verifier, 'PrivateStorage', factory)

    async def verify_scope(manager, selection, args, report):
        events.append('collect')
        report['results']['example'] = dict(pipeline_verified=True, strict_proxy_verified=True)

    args.pipeline = verify_scope
    write = verifier.write_report

    def record_write(path, report, redactor):
        events.append('final_pass' if report['passed'] else 'failed_or_frozen_report')
        write(path, report, redactor)

    monkeypatch.setattr(verifier, 'write_report', record_write)
    return args, events, factory


@pytest.mark.asyncio
async def test_full_success_is_written_only_after_shutdown_cleanup_and_unlock(verifier, full_run):
    args, events, _ = full_run
    assert await verifier.verify(args, args.pipeline)
    assert events.index('failed_or_frozen_report') < events.index('create_sql') < events.index('collect')
    assert events[-6:] == ['shutdown', 'cleanup_sql', 'cleanup_redis', 'release_sql', 'unlock', 'final_pass']
    report = json.loads(Path(args.output).read_text(encoding='utf-8'))
    assert report['passed'] and report['sample_30_met']


@pytest.mark.asyncio
async def test_full_source_failure_writes_redacted_failure_and_still_cleans(verifier, full_run, monkeypatch):
    args, events, _ = full_run
    args.pipeline = AsyncMock(side_effect=RuntimeError('prod-p4ss test-p4ss'))
    assert not await verifier.verify(args, args.pipeline)
    saved = Path(args.output).read_text(encoding='utf-8')
    assert 'prod-p4ss' not in saved and 'test-p4ss' not in saved
    report = json.loads(saved)
    assert report['passed'] is False and all(report['cleanup'].values())
    assert 'cleanup_sql' in events and 'cleanup_redis' in events and 'final_pass' not in events


@pytest.mark.asyncio
async def test_source_change_during_shutdown_or_cleanup_cannot_pass(verifier, full_run, monkeypatch):
    args, events, _ = full_run
    monkeypatch.setattr(verifier, 'source_digest', Mock(side_effect=['a' * 64, 'a' * 64, 'b' * 64]))
    assert not await verifier.verify(args, args.pipeline)
    report = json.loads(Path(args.output).read_text(encoding='utf-8'))
    assert all(report['cleanup'].values())
    assert any(error['stage'] == 'final_source_identity' for error in report['errors'])
    assert 'unlock' in events and 'final_pass' not in events


@pytest.mark.asyncio
async def test_config_change_during_cleanup_cannot_pass(verifier, full_run, monkeypatch):
    args, events, _ = full_run
    original = verifier.finish

    async def changed(*values):
        await original(*values)
        Path(args.pool_config).write_text('# changed config', encoding='utf-8')

    monkeypatch.setattr(verifier, 'finish', changed)
    assert not await verifier.verify(args, args.pipeline)
    report = json.loads(Path(args.output).read_text(encoding='utf-8'))
    assert all(report['cleanup'].values())
    assert any(error['stage'] == 'final_config_identity' for error in report['errors'])
    assert 'final_pass' not in events


@pytest.mark.asyncio
async def test_known_source_gap_does_not_turn_verified_partial_pipeline_into_pass(verifier, full_run):
    args, _, _ = full_run

    async def source_gap(manager, selection, args, report):
        report['results']['holders'] = dict(pipeline_verified=True, strict_proxy_verified=True,
            acceptance_complete=False, random_samples_complete=True,
            source_gaps={'300398.SZ': [{'reason': 'instrument_name_missing'}]})

    assert not await verifier.verify(args, source_gap)
    report = json.loads(Path(args.output).read_text(encoding='utf-8'))
    assert report['pipeline_verified'] and report['sample_30_met']
    assert not report['acceptance_complete'] and not report['passed']
    assert all(report['cleanup'].values())


@pytest.mark.asyncio
async def test_random_gap_prevents_random_30_acceptance(verifier, full_run):
    args, _, _ = full_run

    async def source_gap(manager, selection, args, report):
        report['results']['holders'] = dict(pipeline_verified=True, strict_proxy_verified=True,
            acceptance_complete=False, random_samples_complete=False)

    assert not await verifier.verify(args, source_gap)
    report = json.loads(Path(args.output).read_text(encoding='utf-8'))
    assert not report['sample_30_met'] and not report['passed']


@pytest.mark.asyncio
async def test_freeze_write_failure_prevents_test_resource_creation_and_requests(verifier, full_run, monkeypatch):
    args, events, factory = full_run
    monkeypatch.setattr(verifier, 'write_report', Mock(side_effect=OSError('disk failure')))
    assert not await verifier.verify(args, args.pipeline)
    factory.assert_not_called()
    assert 'collect' not in events
    assert json.loads(Path(args.output).read_text(encoding='utf-8'))['passed'] is False


@pytest.mark.parametrize('field,replacement', [('database', 'empire'), ('namespace', 'router:proxies'),
                                              ('owner_sha256', '0' * 64)])
def test_recovery_refuses_tampered_resource_identity(verifier, storage_module, field, replacement):
    settings = dict(host='localhost', port=13348, user='test')
    owned = storage_module.PrivateStorage(settings, {}, 'a' * 32, 'b' * 64, 'production')
    record = {**owned.identity(), 'owner': owned.owner, field: replacement}
    with pytest.raises(ValueError, match='派生身份不匹配'):
        verifier.restored_storage(record, settings, {}, 'production')


def test_recovery_requires_recorded_verified_uuid(verifier, tmp_path, monkeypatch):
    build = tmp_path / 'build'
    build.mkdir()
    record = build / 'owner.json'
    record.write_text('{"schema":1,"server_uuid":""}', encoding='utf-8')
    monkeypatch.setattr(verifier, 'project_root', lambda: tmp_path)
    with pytest.raises(ValueError, match='server_uuid'):
        verifier.recovery_record(record)


@pytest.mark.parametrize('actual,lock_result,match', [('other-instance', 1, 'server_uuid'),
                                                   ('test-instance', 0, '独占锁')])
def test_recovery_wrong_server_or_live_owner_never_mutates_sql(storage_module, monkeypatch, actual, lock_result, match):
    conn = Mock()
    conn.execute.return_value.scalar_one.side_effect = [actual, lock_result]
    engine = Mock()
    engine.connect.return_value = conn
    monkeypatch.setattr(storage_module, 'make_engine', lambda *a, **k: engine)
    owned = storage_module.PrivateStorage(dict(host='localhost', port=13348, user='test'), {},
                                          'a' * 32, 'b' * 64, 'production')
    with pytest.raises((ValueError, RuntimeError), match=match):
        owned.attach_sql('test-instance')
    assert all(str(call.args[0]).startswith('SELECT ') for call in conn.execute.call_args_list)
    assert not owned.created


@pytest.mark.asyncio
async def test_recovery_missing_redis_marker_with_residual_data_refuses_deletion(storage_module):
    owned = storage_module.PrivateStorage(dict(host='localhost', port=13348, user='test'), {},
                                          'a' * 32, 'b' * 64, 'production')
    async def scan(**kwargs):
        yield owned.namespace + ':ingest'
    client = SimpleNamespace(get=AsyncMock(return_value=None), scan_iter=scan, eval=AsyncMock())
    original = storage_module.create_client
    storage_module.create_client = lambda cfg: client
    try:
        with pytest.raises(ValueError, match='owner 缺失'):
            await owned.attach_redis()
        with pytest.raises(ValueError, match='尚未证实'):
            await owned.cleanup_redis()
    finally:
        storage_module.create_client = original
    client.eval.assert_not_awaited()
    assert owned.redis_residual and not owned.redis_owned


@pytest.mark.asyncio
@pytest.mark.parametrize('config_drift', [False, True])
async def test_recovery_never_initializes_or_collects_and_cannot_claim_sampling(verifier, full_run, monkeypatch, config_drift):
    args, events, _ = full_run
    args.run_state = str(Path(args.output).with_name('old.ownership.json'))
    record = dict(run_id='b' * 32, database='owned', namespace='owned',
                  server_uuid='test-instance', owner_sha256='c' * 64, owner='d' * 64)
    monkeypatch.setattr(verifier, 'recovery_record', lambda path: record)
    monkeypatch.setattr(verifier, 'read_server_uuid', lambda settings: 'production')
    monkeypatch.setattr(verifier, 'read_pool', Mock(side_effect=AssertionError('no stock read in cleanup')))
    monkeypatch.setattr(verifier, 'build_manager', Mock(side_effect=AssertionError('no manager in cleanup')))
    args.pipeline = AsyncMock(side_effect=AssertionError('no source in cleanup'))
    storage = SimpleNamespace(attach_sql=lambda server: events.append('attach_sql'),
                              attach_redis=AsyncMock(side_effect=lambda: events.append('attach_redis')),
                              cleanup_sql=lambda: events.append('cleanup_sql'),
                              cleanup_redis=AsyncMock(side_effect=lambda: events.append('cleanup_redis')),
                              release_sql=lambda: events.append('release_sql'), client=None,
                              remove_guard=Mock(), created=False, redis_owned=False)
    monkeypatch.setattr(verifier, 'restored_storage', lambda *args: storage)
    if config_drift:
        finish = verifier.finish

        async def changed(*values):
            await finish(*values)
            Path(args.test_mysql_settings).write_text('{"changed": true}', encoding='utf-8')

        monkeypatch.setattr(verifier, 'finish', changed)
    assert await verifier.recover(args) == (not config_drift)
    report = json.loads(Path(args.output).read_text(encoding='utf-8'))
    assert report['mode'] == 'cleanup_only' and report['recovery_verified']
    assert report['pipeline_verified'] is False and report['sample_30_met'] is False
    assert report['passed'] == (not config_drift)
    if config_drift:
        assert any(error['stage'] == 'final_config_identity' for error in report['errors'])
    assert events == ['attach_sql', 'attach_redis', 'cleanup_sql', 'cleanup_redis',
                      'release_sql', 'unlock', 'failed_or_frozen_report' if config_drift else 'final_pass']
