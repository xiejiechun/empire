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


async def test_recent_and_backfill_share_calendar_and_return_bounded_missing_units(limits, monkeypatch):
    from sqlalchemy import event
    manager, c, q = limits
    await calendar(q, monkeypatch)
    with q.mysql.engine.begin() as conn:
        conn.execute(text("UPDATE trade_calendar SET is_trade=1 WHERE trade_date BETWEEN '2026-01-01' AND '2026-07-15'"))
    q.collection_plan = LimitQuery.collection_plan.__get__(q)
    statements = []
    def capture(conn, cursor, sql, parameters, context, many):
        statements.append(sql)
    event.listen(q.mysql.read_engine, 'before_cursor_execute', capture)
    try:
        cache = {}
        recent = await q.collection_plan(c.pool, scope='recent', calendar_cache=cache)
        backfill = await q.collection_plan(c.pool, scope='backfill', calendar_cache=cache)
    finally:
        event.remove(q.mysql.read_engine, 'before_cursor_execute', capture)
    assert len(recent['units']) == 10 and recent['units'][0] == '2026-07-15'
    assert len(backfill['units']) == 64 and backfill['units'][0] == '2026-01-01'
    assert backfill['remaining'] == 196 - 10 - 64
    assert sum('SELECT trade_date,is_trade FROM trade_calendar WHERE trade_date BETWEEN' in s for s in statements) == 1
    assert any('COUNT(*) OVER()' in s for s in statements)
    assert any('JSON_OBJECT(' in s for s in statements)


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
    unit = dict(trade_date='2026-07-15', pool_type='limit_up_pool', filter='HS,GEM2STAR,ST', source_total=300, rows=values)
    with q.mysql.engine.begin() as conn:
        replace_pool(conn, unit, datetime.now(UTC), None)
    q.collection_plan = LimitQuery.collection_plan.__get__(q)
    cache = {}
    first = await q.collection_plan('reason', calendar_cache=cache)
    assert len(first['units']) == 256 and first['remaining'] is None
    relation = cache[(first['cutoff'], 'all', 'reason_dates')]
    second = await q.collection_plan('reason', through=first['cutoff'], scan_after=first['scan_after'], calendar_cache=cache)
    assert cache[(first['cutoff'], 'all', 'reason_dates')] is relation
    assert len(second['units']) == 44 and second['remaining'] == 0
    assert [v[1] for v in first['units'] + second['units']] == [v['unified_code'] for v in values]


async def test_preparation_uses_ten_day_tail_without_old_history_rotation(limits, monkeypatch):
    from empire.features.yuanhang_limits.model import member
    from empire.features.yuanhang_limits.repository import replace_pool, replace_reason

    _, _, q = limits
    await calendar(q, monkeypatch)
    days = [date(2026, 6, 21) + timedelta(days=i) for i in range(25)]
    cutoff = datetime(2026, 7, 15, 16, tzinfo=CHINA)
    stale_day = days[-8]
    q.cache_proofs = AsyncMock(return_value={})
    with q.mysql.engine.begin() as conn:
        # An explicitly synthetic, source-declared 25-trade-day fixture.
        conn.execute(text('UPDATE trade_calendar SET is_trade=1 WHERE trade_date BETWEEN :first AND :last'),
                     dict(first=days[0], last=days[-1]))
        for i, day in enumerate(days):
            stamp = cutoff if i >= len(days) - 10 else datetime.combine(day, cutoff.timetz())
            for pool in POOLS:
                rows = [member({**row(), 'first_limit_up_time': None}, day.isoformat())] if (
                    pool == 'limit_up_pool' and day in (days[0], stale_day)) else []
                replace_pool(conn, dict(trade_date=day.isoformat(), pool_type=pool,
                    filter='HS,GEM2STAR,ST', source_total=len(rows), rows=rows), stamp, None)
            if day in (days[0], stale_day):
                reason = dict(trade_date=day.isoformat(), unified_code='000001.SZ', name=None,
                              reason_text=None, reason_kind=None, availability='no_content')
                replace_reason(conn, reason, datetime.combine(day, cutoff.timetz()), None)
    scope = dict(start=days[0].isoformat(), end=days[-1].isoformat())
    assert all(e.status == 'pass' for e in await q.check_limit_up_pool(scope))
    checks = await q.check_reason(scope)
    assert all(e.status == 'pass' for e in checks if e.criterion != 'freshness')
    assert next(e for e in checks if e.criterion == 'freshness').measured.endswith('1个单元')
    with q.mysql.engine.begin() as conn:
        conn.execute(text('UPDATE yuanhang_limit_reason SET observed_at=:stamp WHERE trade_date=:day'),
                     dict(stamp=cutoff.replace(tzinfo=None), day=stale_day))
    # The old reason retains its original date/version; only the stale tail changes.
    assert all(e.status == 'pass' for e in await q.check_reason(scope))
