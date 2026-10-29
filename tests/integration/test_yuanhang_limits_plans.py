"""SQL-backed planning and preparation, using only a test-owned database."""
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
from sqlalchemy import text

from empire.core.time import CHINA
from empire.features.yuanhang_limits.contract import POOLS
from empire.features.yuanhang_limits.query import LimitQuery
from tests.integration.test_yuanhang_limits_archive import collect
from tests.integration.test_yuanhang_limits_archive import limits as limits
from tests.integration.test_yuanhang_limits_archive import pytestmark as pytestmark
from tests.prefetch_source import prefetch_http
from tests.test_yuanhang_limits_source import page, row


async def calendar(q, monkeypatch):
    from empire.features.yuanhang_limits import preparation, query, reason_planning
    cutoff = datetime(2026, 7, 15, 15, 30, tzinfo=CHINA)
    for module in (preparation, query, reason_planning):
        monkeypatch.setattr(module, 'read_trade_day_cutoff', lambda *_: (cutoff, 'test calendar'))
    first = date(1990, 12, 19)
    rows = [dict(day=first + timedelta(days=i), flag=int(first + timedelta(days=i) == cutoff.date()))
            for i in range((cutoff.date() - first).days + 1)]
    # Source-declared synthetic test calendar; no production calendar generated.
    with q.mysql.engine.begin() as conn:
        for offset in range(0, len(rows), 500):
            conn.execute(text('INSERT INTO trade_calendar VALUES (:day,:flag,NOW(6))'), rows[offset:offset + 500])


async def test_sql_plan_initial_nochange_new_day_and_lost_cache(limits, monkeypatch):
    manager, c, q = limits
    await calendar(q, monkeypatch)
    q.collection_plan = LimitQuery.collection_plan.__get__(q)
    assert (await q.collection_plan(c.pool))['units'] == ['2026-07-15']
    await collect(c)
    q.cache_proofs = AsyncMock(return_value={})  # SQL is sufficient after volatile state loss.
    assert (await q.collection_plan(c.pool))['units'] == []
    assert (await q.collection_plan('reason'))['units'] == [['2026-07-15', '000001.SZ']]
    from empire.features.yuanhang_limits import query
    monkeypatch.setattr(query, 'read_trade_day_cutoff', lambda *_: (datetime(2026, 7, 16, 15, 30, tzinfo=CHINA), 'test'))
    with q.mysql.engine.begin() as conn:
        conn.execute(text("INSERT INTO trade_calendar VALUES ('2026-07-16',1,NOW(6))"))
    # Existing unit was verified after the test cutoff, so only the new unit is due.
    assert (await q.collection_plan(c.pool))['units'] == ['2026-07-16']
    with q.mysql.engine.begin() as conn:
        conn.execute(text("DELETE FROM yuanhang_limit_member WHERE trade_date='2026-07-15'"))
        conn.execute(text("DELETE FROM yuanhang_limit_pool WHERE trade_date='2026-07-15'"))
    assert set((await q.collection_plan(c.pool))['units']) == {'2026-07-15', '2026-07-16'}


async def test_preparation_rejects_missing_or_corrupt_reason_input_pools(limits, monkeypatch):
    manager, c, q = limits
    await calendar(q, monkeypatch)
    scope = dict(start='2026-07-15', end='2026-07-15')
    assert any(e.status == 'fail' for e in await q.check_reason(scope))

    for pool in POOLS:
        await manager.start('collector.yuanhang_limits_' + pool)
        collector = manager.registry.get('collector.yuanhang_limits_' + pool)
        collector.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, json=page([]))))
        await collect(collector)
    assert all(e.status == 'pass' for e in await q.check_reason(scope))
    # Same five headers are no longer enough: an unproved extra member invalidates the input universe.
    from empire.features.yuanhang_limits.model import member
    from empire.features.yuanhang_limits.repository import upsert
    value = member({**row(), 'first_limit_up_time': None}, '2026-07-15')
    with q.mysql.engine.begin() as conn:
        upsert(conn, 'yuanhang_limit_member', ('trade_date', 'pool_type', 'unified_code'),
               [dict(value, trade_date='2026-07-15', pool_type='limit_up_pool')])
    assert any(e.status == 'fail' for e in await q.check_reason(scope))


async def test_reason_key_cursor_visits_over_one_plan_without_dropping_members(limits, monkeypatch):
    from datetime import UTC

    from empire.features.yuanhang_limits.model import member
    from empire.features.yuanhang_limits.repository import replace_pool

    _, _, q = limits
    await calendar(q, monkeypatch)
    values = [member({**row(f'{i:06}'), 'first_limit_up_time': None}, '2026-07-15') for i in range(1, 301)]
    unit = dict(trade_date='2026-07-15', pool_type='limit_up_pool', filter='HS,GEM2STAR', source_total=300, rows=values)
    with q.mysql.engine.begin() as conn:
        replace_pool(conn, unit, datetime.now(UTC), None)
    q.collection_plan = LimitQuery.collection_plan.__get__(q)
    first = await q.collection_plan('reason')
    assert len(first['units']) == 256 and first['remaining'] is None
    second = await q.collection_plan('reason', through=first['cutoff'], scan_after=first['scan_after'])
    assert len(second['units']) == 44 and second['remaining'] == 0
    assert [v[1] for v in first['units'] + second['units']] == [v['unified_code'] for v in values]
