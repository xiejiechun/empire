"""Explicit opt-in; all writes target a newly created private drill database."""
import copy
import json
import os
import statistics
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.core.config import load_config
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.collection_state_unit import read_unit, save_unit
from empire.plugins.infra.mysql_store import make_engine

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_UPGRADE_DRILL') != '1', reason='Explicit isolated drill opt-in required')]


@pytest.fixture
def isolated_db():
    production = load_config()['mysql']
    path = os.environ.get('EMPIRE_UPGRADE_MYSQL_SETTINGS')
    if not path:
        raise RuntimeError('EMPIRE_UPGRADE_MYSQL_SETTINGS must point to isolated MySQL settings JSON')
    settings = copy.deepcopy(json.loads(Path(path).read_text(encoding='utf-8')))
    if (settings.get('host', '127.0.0.1'), settings.get('port', 3306)) == (
            production.get('host', '127.0.0.1'), production.get('port', 3306)):
        raise RuntimeError('Drill tests require a separate MySQL server')
    admin = make_engine(settings)
    database = 'empire_' + uuid4().hex + '_upgrade_drill'
    engine = None
    created = False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            created = True
        settings['database'] = database
        engine = make_engine(settings)
        sql = (Path(__file__).resolve().parents[2] / 'sql/legacy/business-v1.sql').read_text(encoding='utf-8')
        sql = '\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--'))
        with engine.begin() as conn:
            for statement in sql.split(';'):
                if statement.strip():
                    conn.execute(text(statement))
        yield engine
    finally:
        if engine:
            engine.dispose()
        if created:
            assert database.endswith('_upgrade_drill') and settings['database'] == database
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{database}`')
        admin.dispose()


def initial(engine, payload):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO collection_state VALUES('test','ths-income','ths','ths_income',"
                          ":payload,'2026-10-03 00:00:00')"), {'payload': json.dumps(payload)})


def update(engine, unit, value, *, fail=False):
    with engine.begin() as conn:
        previous, exists = read_unit(conn, 'test', 'ths-income', 'ths', unit)
        result = {**previous, 'units': {unit: value}}
        save_unit(conn, 'test', 'ths-income', 'ths', 'ths_income', unit, result, previous, exists)
        if fail:
            raise RuntimeError('injected transaction failure')


def test_large_state_bounded_transfer_and_other_unit_preserved(isolated_db):
    engine = isolated_db
    units = {f'SH:{i:06d}': {'dates': [f'{year}-12-31' for year in range(2014, 2026)], 'digest': 'a' * 64,
                           'observed_at': '2026-10-03T00:00:00+00:00'} for i in range(15000)}
    initial(engine, {'contract_version': 1, 'units': units, 'manifest': {'digest': 'b' * 64}})
    measurements = {}
    for name in ('whole_state', 'unit_state'):
        samples, transferred, peaks = [], [], []
        for _ in range(5):
            tracemalloc.start()
            started = time.perf_counter()
            with engine.begin() as conn:
                value = (read_state(conn, 'test', 'ths-income', 'ths') if name == 'whole_state' else
                         read_unit(conn, 'test', 'ths-income', 'ths', 'SH:000001')[0])
            samples.append(time.perf_counter() - started)
            transferred.append(len(json.dumps(value).encode()))
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()
        measurements[name] = dict(seconds=samples, median_seconds=statistics.median(samples),
                                  decoded_json_bytes=transferred, python_traced_peak_bytes=peaks)
        del value
    sizes, sqls = [], []
    def capture(conn, cursor, statement, parameters, context, executemany):
        sqls.append(statement)
        sizes.append(len(json.dumps(parameters, default=str).encode()))
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        with engine.begin() as conn:
            previous, exists = read_unit(conn, 'test', 'ths-income', 'ths', 'SH:000001')
            assert len(json.dumps(previous).encode()) < 1024
            result = {**previous, 'units': {'SH:000001': {**units['SH:000001'], 'dates': ['2026-06-30']}}}
            save_unit(conn, 'test', 'ths-income', 'ths', 'ths_income', 'SH:000001', result, previous, exists)
        assert max(sizes) < 1024
        assert all('SELECT source,payload' not in sql for sql in sqls)
        assert any('JSON_SET' in sql for sql in sqls)
        measurements['update'] = dict(statements=len(sqls), parameter_bytes=sizes,
                                      max_parameter_bytes=max(sizes))
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    with engine.connect() as conn:
        after = read_state(conn, 'test', 'ths-income', 'ths')
    assert after['units']['SH:000001']['dates'] == ['2026-06-30']
    assert after['units']['SH:000002'] == units['SH:000002']
    assert len(after['units']) == 15000
    assert after['manifest'] == {'digest': 'b' * 64}
    evidence = Path(__file__).resolve().parents[2] / 'build/mysql-upgrade-20261003/state-performance.json'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({
        'server': 'private MySQL instance', 'units': 15000, 'measurements': measurements,
        'cache': 'same connection pool, sequential warm reads, no buffer-pool reset',
        'limitations': ['decoded JSON size, not network packet byte count',
                        'Python traced allocation, not total process memory',
                        'synthetic state only; no physical disk benefit measurement'],
    }, indent=2), encoding='utf-8')


def test_concurrency_and_rollback(isolated_db):
    initial(isolated_db, {'units': {'SH:000001': {'dates': []}, 'SZ:000001': {'dates': []}}})
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(update, isolated_db, unit, {'dates': [day]})
                   for unit, day in [('SH:000001', '2025-12-31'), ('SZ:000001', '2026-06-30')]]
        for future in futures:
            future.result()
    with pytest.raises(RuntimeError, match='injected'):
        update(isolated_db, 'SH:000001', {'dates': ['2026-09-30']}, fail=True)
    with isolated_db.connect() as conn:
        after = read_state(conn, 'test', 'ths-income', 'ths')
    assert after['units'] == {'SH:000001': {'dates': ['2025-12-31']}, 'SZ:000001': {'dates': ['2026-06-30']}}


def test_missing_units_manifest_and_noop(isolated_db):
    initial(isolated_db, {'contract_version': 1})
    update(isolated_db, 'SZ:000001', {'dates': []})
    with isolated_db.begin() as conn:
        prior, exists = read_unit(conn, 'test', 'ths-income', 'ths', 'manifest')
        save_unit(conn, 'test', 'ths-income', 'ths', 'ths_income', 'manifest',
                  {**prior, 'manifest': {'count': 0}}, prior, exists)
    with isolated_db.connect() as conn:
        value = read_state(conn, 'test', 'ths-income', 'ths')
    assert value['units'] == {'SZ:000001': {'dates': []}}
    assert value['manifest'] == {'count': 0}


def test_initial_unit_state_and_owner_validation(isolated_db):
    with isolated_db.begin() as conn:
        previous, exists = read_unit(conn, 'test', 'ths-income', 'ths', 'SZ:000001')
        assert previous == {} and exists is False
        save_unit(conn, 'test', 'ths-income', 'ths', 'ths_income', 'SZ:000001',
                  {'contract_version': 1, 'units': {'SZ:000001': {'dates': ['2025-12-31']}}},
                  previous, exists)
    with isolated_db.begin() as conn:
        with pytest.raises(ValueError, match='来源'):
            read_unit(conn, 'test', 'ths-income', 'tdx', 'SZ:000001')


def test_preflight_is_read_only_allowlisted_and_rejects_extra_source(isolated_db):
    from scripts.migrate_business_schema import inspect_database
    with isolated_db.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE router_test_secret(id INT PRIMARY KEY, secret TEXT)')
        conn.exec_driver_sql("INSERT INTO router_test_secret VALUES(1,'private-test-marker')")
        conn.exec_driver_sql("INSERT INTO industry VALUES('ths','000001','正常行业')")
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(isolated_db, 'before_cursor_execute', capture)
    try:
        normal = inspect_database(isolated_db)
    finally:
        event.remove(isolated_db, 'before_cursor_execute', capture)
    assert normal['passed'] and not normal['migration_ready']
    assert 'router_test_secret' not in normal['tables']
    assert not any('router_test_secret' in sql for sql in statements)
    assert not any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'DROP'))
                   for sql in statements)
    with isolated_db.begin() as conn:
        conn.exec_driver_sql("INSERT INTO industry VALUES('extra-source','000002','保留的其他来源')")
    invalid = inspect_database(isolated_db)
    assert not invalid['passed']
    assert invalid['failures'] == ['industry 额外来源 extra-source：1 行']
    with isolated_db.connect() as conn:
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM industry').scalar_one() == 2
        assert conn.exec_driver_sql('SELECT secret FROM router_test_secret').scalar_one() == 'private-test-marker'
