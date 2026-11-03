"""Range updates through the same queue/archive and formal query as full history."""
from dataclasses import replace
from datetime import date, timedelta

from sqlalchemy import event

from empire.core.time import mysql_time
from empire.features.yuanhang.repository import read_heads
from empire.sources.yuanhang_payload import daily_years
from empire.sources.yuanhang_range_payload import daily_ranges
from tests.integration.test_yuanhang_archive import native, publish, pytestmark  # noqa: F401
from tests.test_yuanhang_payload import CODE, bar, snapshot
from tests.test_yuanhang_storage import envelope


async def test_partial_initialization_keeps_recent_fresh_and_backfills_separately(native):  # noqa: F811
    _, c, q, store, archive = native
    initial = daily_years(snapshot((bar('2020-10-19'),)), code=CODE, through=date(2020, 12, 31))[0]
    await publish(c, archive, envelope(initial))
    payload = daily_ranges(snapshot((bar('2023-12-29'),)), code=CODE,
                           start=date(2023, 1, 1), through=date(2023, 12, 31))[0]
    await publish(c, archive, envelope(payload))
    recent = await q.daily_plans(store.prefix, [CODE], '2023-12-31', scope='recent')
    assert recent[CODE]['mode'] == 'skip'
    old = await q.daily_plans(store.prefix, [CODE], '2023-12-31', scope='backfill')
    assert old[CODE]['mode'] == 'range' and old[CODE]['start'] < '2021-01-01'
    assert await store.client.xlen(store.stream) == 0


async def test_range_delete_stale_full_disjoint_update_and_cold_replay(native):  # noqa: F811
    _, c, q, store, archive = native
    source = snapshot(tuple(bar(d) for d in ('2020-01-03', '2020-10-19', '2020-10-20', '2020-10-21')))
    initial = envelope(daily_years(source, code=CODE, through=date(2020,12,31))[0])
    await publish(c, archive, initial)
    changed = replace(bar('2020-10-20'), amount_yuan=123)
    payload = daily_ranges(snapshot((changed,)), code=CODE, start=date(2020,10,20), through=date(2020,10,21))[0]
    newer = envelope(payload, observed=initial.observed_at + timedelta(minutes=2))
    await publish(c, archive, newer)
    disjoint = daily_ranges(snapshot((replace(bar('2020-10-19'), amount_yuan=456),)),
                            code=CODE, start=date(2020,10,19), through=date(2020,10,19))[0]
    disjoint['native_market'] = 'USHA'
    await publish(c, archive, envelope(disjoint, observed=initial.observed_at + timedelta(minutes=1)))
    with q.mysql.engine.connect() as conn:
        head = read_heads(conn, CODE, year=2020)[2020]
    assert head['version_observed_at'] == mysql_time(newer.observed_at)
    assert head['native_market'] == payload['native_market']
    rows = (await q.prices(CODE))['rows']
    assert [str(r['trade_date']) for r in rows] == ['2020-01-03', '2020-10-19', '2020-10-20']
    assert rows[1]['amount_yuan'] == 456 and rows[2]['amount_yuan'] == 123
    # A cold stale full response must not resurrect the deleted day or overwrite
    # either newer point; this exercises SQL versions instead of a cache shortcut.
    keys = [k async for k in store.client.scan_iter(match=store.prefix + ':archive:fingerprint*')]
    if keys:
        await store.client.delete(*keys)
    await publish(c, archive, initial.model_copy(update=dict(observed_at=initial.observed_at + timedelta(seconds=30))))
    assert (await q.prices(CODE))['rows'] == rows
    writes = []
    def count(conn, cursor, sql, *args):
        if sql.startswith(('INSERT INTO yuanhang_', 'UPDATE yuanhang_', 'DELETE FROM yuanhang_')):
            writes.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', count)
    try:
        await publish(c, archive, newer)
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', count)
    assert not writes and await store.client.xlen(store.stream) == 0


async def test_planning_batches_sql_and_reuses_calendar_without_changing_scope(native):  # noqa: F811
    from sqlalchemy import text

    _, c, q, store, archive = native
    codes = [f'{600000+i:06}.SH' for i in range(1, 66)]
    payload = daily_years(snapshot((bar('2023-12-29'),)), code=CODE, through=date(2023, 12, 31))[0]
    for code in codes:
        await publish(c, archive, envelope({**payload, 'code': code}))
    reads = []
    def count(conn, cursor, sql, *args):
        if sql.startswith('SELECT'):
            reads.append(sql)
    event.listen(q.mysql.read_engine, 'before_cursor_execute', count)
    try:
        recent = await q.daily_plans(store.prefix, codes, '2023-12-31', scope='recent')
        assert set(recent) == set(codes) and all(p['mode'] == 'skip' for p in recent.values())
        assert len(reads) == 5  # Two head/coverage groups and one formal calendar.
        assert sum('FROM trade_calendar' in sql for sql in reads) == 1
        reads.clear()
        forced = await q.daily_plans(store.prefix, codes, '2023-12-31', force=True)
        assert all(p['mode'] == 'full' for p in forced.values()) and len(reads) == 2
        missing = '000099.SZ'
        assert (await q.daily_plans(store.prefix, [missing], '2023-12-31', scope='recent'))[missing]['mode'] == 'skip'
        assert (await q.daily_plans(store.prefix, [missing], '2023-12-31', scope='backfill'))[missing]['mode'] == 'full'
    finally:
        event.remove(q.mysql.read_engine, 'before_cursor_execute', count)
    with q.mysql.engine.begin() as conn:
        conn.execute(text('DELETE FROM collection_state WHERE namespace=:ns AND project_id=:p'),
                     dict(ns=store.prefix, p=c.project_id))
    import pytest
    with pytest.raises(ValueError, match='显式转换覆盖状态'):
        await q.daily_plans(store.prefix, codes, '2023-12-31')
