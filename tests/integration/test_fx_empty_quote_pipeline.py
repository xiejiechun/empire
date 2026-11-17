"""Empty quote heads preserve Redis values and never access SQL."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.contracts.collector import CollectionSourceGap
from empire.features.fx.source import realtime
from tests.integration.test_fx_archive import fx, pytestmark  # noqa: F401
from tests.prefetch_source import prefetch_http
from tests.test_fx import live_source
from tests.test_fx_empty_quote import empty


async def test_empty_preserves_old_timestamp_first_empty_absent_and_recovery(fx):  # noqa: F811
    m, _, _, redis, _ = fx
    await m.start('collector.ths_fx_live')
    c, latest = m.registry.get('collector.ths_fx_live'), m.registry.get('fx.latest.query')
    c.selected_codes = ['USDCNY', 'USDIND', 'EURUSD']
    stamp = datetime.now(UTC) - timedelta(minutes=10)
    await latest.save(realtime(live_source('USDCNY'), 'USDCNY', datetime.now(UTC)) | {'observed_at': stamp.isoformat()})
    old = await redis.client.hget(latest.key, 'USDCNY')
    def reject(*args):
        raise AssertionError('Realtime round accessed SQL')
    async def response(method, url, **kw):
        code = url.split('wh_')[1].split('/')[0]
        body = live_source(code) if code == 'EURUSD' else empty(code, **{'6': ''})
        return httpx.Response(200, content=body.encode())
    c.http = prefetch_http(request=response)
    event.listen(Engine, 'before_cursor_execute', reject)
    try:
        with pytest.raises(CollectionSourceGap, match='1/3'):
            await c.execute()
        assert await redis.client.hget(latest.key, 'USDCNY') == old
        rows = {r['symbol']: r for r in (await latest.browse())['rows']}
        assert set(rows) == {'USDCNY', 'EURUSD'}
        assert rows['USDCNY']['sampling_stale'] is True
        assert rows['USDCNY']['observed_at'] == json.loads(old)['observed_at']
        assert await redis.client.xlen(redis.stream) == 0
        assert (await c.records.list_error_summaries(c.project_id))['total'] == 0
        c.http.request = lambda method, url, **kw: httpx.Response(200,
            content=live_source(url.split('wh_')[1].split('/')[0]).encode())
        # The test downloader accepts asynchronous requests only.
        from unittest.mock import AsyncMock
        c.http.request = AsyncMock(side_effect=c.http.request)
        assert (await c.execute())['collected'] == 3
        assert len((await latest.browse())['rows']) == 3
        assert await redis.client.hget(latest.key, 'USDCNY') != old
        assert await redis.client.xlen(redis.stream) == 0
    finally:
        event.remove(Engine, 'before_cursor_execute', reject)
