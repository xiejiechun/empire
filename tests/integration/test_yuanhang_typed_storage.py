"""Private MySQL tests for native history facts, proof, ordering and atomicity."""
import os
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import event, text

from empire.core.config import load_config
from empire.features.yuanhang import dataset
from empire.features.yuanhang.query import YuanhangDataPlugin
from empire.plugins.infra.collection_state_unit import read_unit, save_unit
from empire.plugins.infra.mysql_store import MySQLPlugin
from scripts.create_yuanhang_schema import (
    OLD_PRICE_CHECK,
    nullable_volume_revision,
    quality_revision,
)
from tests.test_yuanhang_payload import annual
from tests.test_yuanhang_storage import envelope

pytestmark = [pytest.mark.integration,
    pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit private database')]


async def test_explicit_quality_check_revision_preserves_values_and_rejects_unknown_shape(storage):
    mysql, query = storage
    e = envelope()
    with mysql.engine.begin() as conn:
        archive(conn, e)
        conn.exec_driver_sql('ALTER TABLE yuanhang_daily_price DROP CHECK ck_yuanhang_price_values, '
            'ADD CONSTRAINT ck_yuanhang_price_values CHECK (' + OLD_PRICE_CHECK + ')')
    before = await query.prices(e.raw_payload['history']['code'])
    with mysql.engine.connect() as conn:
        assert quality_revision(conn)
        assert not quality_revision(conn)
    assert await query.prices(e.raw_payload['history']['code']) == before
    with mysql.engine.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE yuanhang_daily_price ADD INDEX unexpected(close)')
    with mysql.engine.connect() as conn, pytest.raises(RuntimeError, match='拒绝修改'):
        quality_revision(conn)


async def test_explicit_nullable_volume_migration_preserves_facts_and_rejects_unknown(storage):
    mysql, q = storage
    e = envelope()
    with mysql.engine.begin() as conn:
        archive(conn, e)
        conn.exec_driver_sql('ALTER TABLE yuanhang_daily_price MODIFY volume_shares DECIMAL(28,10) NOT NULL')
    before = await q.prices(e.raw_payload['history']['code'])
    with mysql.engine.connect() as conn:
        assert nullable_volume_revision(conn)
        assert not nullable_volume_revision(conn)
    assert await q.prices(e.raw_payload['history']['code']) == before
    with mysql.engine.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE yuanhang_daily_price ADD INDEX unexpected(close)')
    with mysql.engine.connect() as conn, pytest.raises(RuntimeError, match='拒绝修改'):
        nullable_volume_revision(conn)


@pytest.fixture
async def storage():
    mysql = MySQLPlugin(load_config()['mysql'])
    await mysql.start(None)
    query = YuanhangDataPlugin()
    query.mysql = mysql
    try:
        yield mysql, query
    finally:
        await mysql.stop()


def archive(conn, e):
    d = dataset.normalize(e)
    unit = dataset.state_unit(d)
    previous, exists = read_unit(conn, 'test', e.job_key, e.source, unit)
    d['archive_state'] = previous
    outcome = dataset.write(conn, e, d)
    state = dataset.archive_state(e, d, outcome, previous)
    save_unit(conn, 'test', e.job_key, e.source, e.dataset, unit, state, previous, exists)
    return outcome


async def test_year_full_content_empty_year_formal_pagination_and_cross_section(storage):
    mysql, q = storage
    for p in annual():
        e = envelope(p)
        with mysql.engine.begin() as conn:
            archive(conn, e)
        assert await q.audit_price(p) == []
    rows = await q.prices('605336.SH', limit=1)
    assert rows['next'] == '2020-10-19' and rows['rows'][0]['amount_yuan'] is None
    assert (await q.prices('605336.SH', after=rows['next']))['rows'][0]['trade_date'].isoformat() == '2022-01-04'
    assert (await q.year_heads('605336.SH'))[2021]['row_count'] == 0
    assert (await q.price_day('2020-10-19'))['rows'][0]['unified_code'] == '605336.SH'


async def test_duplicate_zero_business_dml_revision_and_late_unchanged_version(storage):
    mysql, q = storage
    first = envelope()
    with mysql.engine.begin() as conn:
        archive(conn, first)
    statements = []
    def count(conn, cursor, sql, *args):
        if sql.startswith(('INSERT INTO yuanhang_', 'UPDATE yuanhang_', 'DELETE FROM yuanhang_')):
            statements.append(sql)
    event.listen(mysql.engine, 'before_cursor_execute', count)
    event.listen(mysql.archive_engine, 'before_cursor_execute', count)
    try:
        newer = first.model_copy(update=dict(observed_at=first.observed_at + timedelta(hours=2)))
        with mysql.engine.begin() as conn:
            assert archive(conn, newer)['written_count'] == 0
        assert statements == []
        h = deepcopy(first.raw_payload['history'])
        h['rows'][0][-1] = '100'
        late = envelope(h, observed=first.observed_at + timedelta(hours=1))
        with mysql.engine.begin() as conn:
            assert archive(conn, late)['confirmed'] == []
        assert statements == []
        revision = envelope(h, observed=first.observed_at + timedelta(hours=3))
        with mysql.engine.begin() as conn:
            assert archive(conn, revision)['written_count'] == 2
        assert len(statements) == 2
        with mysql.engine.begin() as conn:
            assert archive(conn, revision)['written_count'] == 0
        assert len(statements) == 2
        assert await q.audit_price(h) == []
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', count)
        event.remove(mysql.archive_engine, 'before_cursor_execute', count)


async def test_financial_atomic_replacement_future_asof_and_rollback(storage):
    mysql, q = storage
    e = envelope(financial_unit=True)
    with mysql.engine.begin() as conn:
        archive(conn, e)
    h = deepcopy(e.raw_payload['history'])
    assert await q.audit_financial(h) == []
    assert await q.capital_as_of(h['code'], 'total', '1998-12-31') is None
    h['actions'] = [['2027-01-01', '0', '1', '0', '0', '0.5']]
    for row in h['capital']:
        row[2] = '200'
    revised = envelope(h, financial_unit=True, observed=e.observed_at + timedelta(hours=1))
    with pytest.raises(RuntimeError, match='rollback'):
        with mysql.engine.begin() as conn:
            archive(conn, revised)
            raise RuntimeError('rollback')
    assert await q.audit_financial(e.raw_payload['history']) == []
    with mysql.engine.begin() as conn:
        archive(conn, revised)
    assert (await q.actions(h['code'], end='2026-12-31'))['rows'] == []
    assert len((await q.actions(h['code']))['rows']) == 1
    assert await q.audit_financial(h) == []
    # Corrupt one fact while keeping count/proofs: formal audit must detect it.
    with mysql.engine.begin() as conn:
        conn.execute(text("UPDATE yuanhang_capital SET shares=201 WHERE capital_kind='total'"))
    assert await q.audit_financial(h) == ['capital_content_mismatch']
