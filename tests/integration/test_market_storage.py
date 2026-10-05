"""Typed relation integrity, bounded pages, revision fences and stopped migration drills."""
import copy
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from empire.contracts.market_storage import MARKET_TABLES, SERIES
from empire.core.config import load_config
from empire.plugins.data.kaipanla_products import KaipanlaProductDataPlugin
from empire.plugins.datasets.kaipanla_products import digest
from empire.plugins.datasets.market_repository import head_record, read_day, write_day
from empire.plugins.infra.mysql_store import make_engine
from scripts.market_migration import maintain
from tests.test_kaipanla_products import business_row

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


@pytest.mark.parametrize('kind', ['trend', 'auction', 'volume', 'trades', 'entrust', 'large_order', 'quote'])
async def test_typed_roundtrip_no_dml_diff_and_coverage_projection(kind):
    engine = make_engine(load_config()['mysql'])
    row = business_row(kind)
    now = datetime.now()
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        with engine.begin() as c:
            write_day(c, row, digest(row), now)
            assert read_day(c, head_record(c, kind, '000001.SZ', date(2021, 1, 4))) == row
        statements.clear()
        with engine.begin() as c:
            assert write_day(c, row, digest(row), now+timedelta(seconds=1))[1] == 0
        assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for s in statements)
        query = KaipanlaProductDataPlugin(kind)
        async def execute(fn, *args):
            return fn(*args)
        query.mysql = SimpleNamespace(read_engine=engine, read=execute)
        statements.clear()
        assert query._covered('SZ', '000001', date(2021, 1, 4), date(2021, 1, 4), row['lifecycle']) == {date(2021, 1, 4)}
        assert len(statements) == 1 and 'product_extra' not in statements[0] and 'SELECT *' not in statements[0]
        if kind in SERIES:
            first = await query.page('SZ', '000001', '2021-01-04', limit=1)
            assert len(first['points']) == 1
            if first['next_cursor']:
                second = await query.page('SZ', '000001', '2021-01-04', first['next_cursor'], limit=1)
                assert second['start'] == 1
            changed = copy.deepcopy(row)
            from empire.plugins.collectors.kaipanla_kinds import PRODUCTS
            changed['data'][PRODUCTS[kind].field][0][1] += 1
            with engine.begin() as c:
                accepted, count = write_day(c, changed, digest(changed), now+timedelta(seconds=2))
                assert accepted and count == 2  # Exactly one fact/block and its parent.
            if first['next_cursor']:
                with pytest.raises(ValueError, match='版本'):
                    await query.page('SZ', '000001', '2021-01-04', first['next_cursor'])
        with engine.begin() as c:
            c.exec_driver_sql("UPDATE stock_market_day SET key_set_hash=REPEAT('0',64) WHERE kind='"+kind+"'")
            with pytest.raises(ValueError, match='证明'):
                read_day(c, head_record(c, kind, '000001.SZ', date(2021, 1, 4)))
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
        engine.dispose()


def test_explicit_market_migration_resume_verify_and_reject_changed_rollback(tmp_path):
    engine = make_engine(load_config()['mysql'])
    row = business_row('trades')
    journal = tmp_path/'market.json'
    try:
        with engine.begin() as c:
            for table in MARKET_TABLES:
                c.exec_driver_sql('DROP TABLE '+table)
            c.exec_driver_sql(Path('sql/legacy/market-day-v1.sql').read_text('utf-8').split('\n', 1)[1])
            c.execute(text('INSERT INTO stock_market_day VALUES(:kind,:security,:day,:payload,:hash,:observed)'),
                dict(kind='trades', security='000001.SZ', day='2021-01-04', payload=json.dumps(row),
                     hash=digest(row), observed=datetime.now()))
        with pytest.raises(RuntimeError, match='injected'):
            maintain(engine, journal, fail_after=['trades', '000001.SZ', '2021-01-04'])
        assert maintain(engine, journal, 'resume')['phase'] == 'verified'
        assert maintain(engine, journal, 'verify')['passed']
        with engine.begin() as c:
            c.exec_driver_sql("UPDATE stock_market_day SET source_metadata=JSON_OBJECT('time',99)")
        with pytest.raises(ValueError, match='改变'):
            maintain(engine, journal, 'rollback')
    finally:
        engine.dispose()


async def test_trade_time_pages_preserve_duplicates_across_blocks():
    row = business_row('trades')
    point = row['data']['fb'][0]
    row['data']['fb'] = [["09:30:00", *point[1:]] for _ in range(210)] + [
        ["09:30:01", *point[1:]] for _ in range(410)]
    row['data'].update(Count=620, total=620)
    engine = make_engine(load_config()['mysql'])
    try:
        with engine.begin() as c:
            write_day(c, row, digest(row), datetime.now())
        query = KaipanlaProductDataPlugin('trades')
        async def execute(fn):
            return fn()
        query.mysql = SimpleNamespace(read_engine=engine, read=execute)
        points, cursor = [], None
        for _ in range(4):
            page = await query.page('SZ', '000001', '2021-01-04', cursor,
                                    start_time='09:30:01', end_time='09:30:01')
            points.extend(page['points'])
            cursor = page['next_cursor']
            if cursor is None:
                break
        assert points == row['data']['fb'][210:] and len(points) == 410
        page = await query.page('SZ', '000001', '2021-01-04', start_time='09:30:01', end_time='09:30:01')
        with pytest.raises(ValueError, match='游标'):
            await query.page('SZ', '000001', '2021-01-04', page['next_cursor'])
    finally:
        engine.dispose()


@pytest.mark.parametrize('ddl', [
    'ALTER TABLE stock_daily_quote MODIFY last_px DECIMAL(29,12)',
    'ALTER TABLE stock_daily_quote DROP INDEX ix_quote_date',
    'ALTER TABLE stock_intraday_trade_block DROP CHECK ck_trade_block',
])
def test_public_schema_gate_rejects_real_shape_changes(ddl):
    from empire.plugins.infra.schema_manifest import validate_shapes
    engine = make_engine(load_config()['mysql'])
    try:
        with engine.begin() as c:
            validate_shapes(c, MARKET_TABLES)
            c.exec_driver_sql(ddl)
            with pytest.raises(RuntimeError, match='契约'):
                validate_shapes(c, MARKET_TABLES)
    finally:
        engine.dispose()


@pytest.mark.parametrize('phase', ['ready_to_switch', 'switched'])
def test_switch_interruption_resume_and_exact_rollback(tmp_path, monkeypatch, phase):
    import scripts.market_migration as migration
    engine = make_engine(load_config()['mysql'])
    row = business_row('auction')
    journal = tmp_path/'switch.json'
    original_save = migration.save
    def interrupt(path, state):
        if state['phase'] == phase:
            raise RuntimeError('injected switch interruption')
        original_save(path, state)
    try:
        with engine.begin() as c:
            for table in MARKET_TABLES:
                c.exec_driver_sql('DROP TABLE '+table)
            c.exec_driver_sql(Path('sql/legacy/market-day-v1.sql').read_text('utf-8').split('\n', 1)[1])
            c.execute(text('INSERT INTO stock_market_day VALUES(:kind,:security,:day,:payload,:hash,:observed)'),
                dict(kind='auction', security='000001.SZ', day='2021-01-04', payload=json.dumps(row),
                     hash=digest(row), observed=datetime.now()))
        monkeypatch.setattr(migration, 'save', interrupt)
        with pytest.raises(RuntimeError, match='switch interruption'):
            migration.maintain(engine, journal)
        monkeypatch.setattr(migration, 'save', original_save)
        assert migration.maintain(engine, journal, 'resume')['phase'] == 'verified'
        assert migration.maintain(engine, journal, 'rollback')['phase'] == 'rolled_back'
        with engine.connect() as c:
            actual = json.loads(c.exec_driver_sql('SELECT payload FROM stock_market_day').scalar_one())
            assert actual == row
    finally:
        engine.dispose()


def test_concurrent_first_write_and_fact_failure_are_atomic():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local

    from sqlalchemy.exc import DBAPIError
    engine = make_engine(load_config()['mysql'])
    older = business_row('trades')
    newer = copy.deepcopy(older)
    newer['data']['fb'][0][1] += 1
    now, rendezvous, thread = datetime.now(), Barrier(2), local()
    def meet(conn, cursor, statement, parameters, context, executemany):
        if 'stock_market_day' in statement and 'FOR UPDATE' in statement and not getattr(thread, 'met', False):
            thread.met = True
            rendezvous.wait(timeout=10)
    def store(row, observed):
        for attempt in range(3):
            try:
                with engine.begin() as c:
                    write_day(c, row, digest(row), observed)
                return
            except DBAPIError as exc:
                if exc.orig.args[0] not in (1213, 1062) or attempt == 2:
                    raise
    event.listen(engine, 'after_cursor_execute', meet)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(store, older, now), pool.submit(store, newer, now+timedelta(seconds=1))]
            for future in futures:
                future.result(timeout=20)
        event.remove(engine, 'after_cursor_execute', meet)
        with engine.connect() as c:
            assert read_day(c, head_record(c, 'trades', '000001.SZ', date(2021, 1, 4))) == newer
        failed = copy.deepcopy(newer)
        failed['data']['fb'][0][1] += 1
        def fail_head(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith('UPDATE stock_market_day'):
                raise RuntimeError('injected parent failure')
        event.listen(engine, 'before_cursor_execute', fail_head)
        with pytest.raises(RuntimeError, match='parent failure'), engine.begin() as c:
            write_day(c, failed, digest(failed), now+timedelta(seconds=2))
        event.remove(engine, 'before_cursor_execute', fail_head)
        with engine.connect() as c:
            assert read_day(c, head_record(c, 'trades', '000001.SZ', date(2021, 1, 4))) == newer
    finally:
        if event.contains(engine, 'after_cursor_execute', meet):
            event.remove(engine, 'after_cursor_execute', meet)
        engine.dispose()
