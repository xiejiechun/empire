"""Formal optional query, real private Redis, SQL month read and plugin lifecycle."""
from datetime import datetime, timedelta

from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.core.time import CHINA
from empire.features.fx.source import realtime
from tests.integration.test_fx_archive import fx, pytestmark  # noqa: F401
from tests.test_fx import live_source


async def test_today_formal_query_read_only_optional_plugin_stop_and_restart(fx):  # noqa: F811
    m, _, _, redis, _ = fx
    await m.start('data.observation_calendar')
    await m.start('data.fx_latest')
    query, latest = m.registry.get('observation.query'), m.registry.get('fx.latest.query')
    now = datetime.now(CHINA)
    quote = realtime(live_source('USDCNH', time=now.strftime('%Y-%m-%d %H:%M:%S 北京时间'),
        updateTime=now.strftime('%Y-%m-%d %H:%M')), 'USDCNH', now)
    quote['observed_at'] = (now - timedelta(minutes=5)).isoformat()
    await latest.save(quote)
    original = await redis.client.hgetall(latest.key)
    ttl = await redis.client.ttl(latest.key)
    writes = []
    def capture(conn, cursor, sql, *args):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')):
            writes.append(sql)
    event.listen(Engine, 'before_cursor_execute', capture)
    try:
        result = await query.month(now.strftime('%Y-%m'), '1A0001', '99', include_fx=['fx_USDCNH'])
        today = next(r for r in result['rows'] if r['date'] == now.date().isoformat())
        assert str(today['values']['fx_USDCNH']) == quote['latest']
        assert today['sources']['fx_USDCNH']['sampling_stale']
        assert today['values']['amount'] is None
        assert not writes and await redis.client.hgetall(latest.key) == original
        assert await redis.client.ttl(latest.key) <= ttl
        assert await redis.client.xlen(redis.stream) == 0
        def reject_sql(*args):
            raise AssertionError('Redis incremental refresh accessed SQL')
        event.listen(Engine, 'before_cursor_execute', reject_sql)
        try:
            refreshed = await query.live(today['date'], today['live_basis'])
            assert refreshed['values'] == {'fx_USDCNH': today['values']['fx_USDCNH']}
            assert refreshed['sources'] == today['sources']
            assert await redis.client.hgetall(latest.key) == original
            assert await redis.client.ttl(latest.key) <= ttl
            assert await redis.client.xlen(redis.stream) == 0
        finally:
            event.remove(Engine, 'before_cursor_execute', reject_sql)
        await m.stop('data.fx_latest')
        result = await query.month(now.strftime('%Y-%m'), '1A0001', '99', include_fx=['fx_USDCNH'])
        assert any('未启用' in w for w in result['warnings'])
        assert all('sources' not in r for r in result['rows'])
        assert m.registry.get('observation.query') is query
        await m.start('data.fx_latest')
        result = await query.month(now.strftime('%Y-%m'), '1A0001', '99', include_fx=['fx_USDCNH'])
        assert next(r for r in result['rows'] if r['date'] == now.date().isoformat())['sources']['fx_USDCNH']
        assert not writes
    finally:
        event.remove(Engine, 'before_cursor_execute', capture)
