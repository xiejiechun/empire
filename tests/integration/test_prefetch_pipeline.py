"""All newly parallel source families traverse the real queue/archive/formal query."""
import asyncio
import json
import os
from datetime import date
from unittest.mock import AsyncMock

import pytest

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.plugins.infra.redis_store import create_client
from tests.prefetch_source import prefetch_http
from tests.test_all_collector_prefetch import FAMILIES, adapter, until
from tests.test_tdx_suspensions import response as day_response

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit isolated integration opt-in')]


@pytest.mark.parametrize('family', FAMILIES)
async def test_out_of_order_source_to_real_archive_and_formal_query(family):
    cfg = load_config()
    assert cfg['redis']['namespace'].startswith('empire:test:')
    manager = build_manager(cfg)
    c, reply = adapter(family)
    if family == 'suspensions':
        # Its actual archive contract starts a new coverage proof at FIRST_DATE.
        c.query.plan.return_value.update(start_date='2004-12-27', end_date='2004-12-29')
        def reply(method, url, kwargs):
            day = json.loads(kwargs['content'])['Params'][2]
            return int(day[-2:]) - 27, day_response(day, 1, [], count=0)
    release, finished, task = asyncio.Event(), [], None
    async def request(method, url, **kwargs):
        index, response = reply(method, url, kwargs)
        if index == 0:
            try:
                await release.wait()
            except asyncio.CancelledError:
                response.close()
                raise
        if index is not None:
            finished.append(index)
        return response
    c.http = prefetch_http(request=AsyncMock(side_effect=request))
    c.http.parallelism.return_value = 3
    store = None
    try:
        await manager.start(c.manifest.id)
        await manager.start('pipeline.archive')
        registered = manager.entries[c.manifest.id].plugin
        query = getattr(registered, 'query', None)
        c.ingest = manager.registry.get('ingest.publish')
        c.confirmation = manager.registry.get('archive.confirmation')
        c.records = manager.registry.get('collection.records')
        store = manager.registry.get('redis.store')
        async with manager.registry.get('archive.worker').lock:
            task = asyncio.create_task(c.execute())
            await until(lambda: 1 in finished and 2 in finished)
            assert await store.client.xlen(store.stream) == 0
            release.set()
            await until(lambda: c.stats['status'] == 'awaiting_archive')
            assert await store.client.xlen(store.stream) > 0 and not task.done()
        result = await asyncio.wait_for(task, 15)
        assert result.get('phase', 'complete') == 'complete'
        assert await store.client.xlen(store.stream) == 0
        assert c.http.buffer_budget.used == 0
        if family in ('balance', 'income', 'cashflow'):
            assert len(await query.list_statements(limit=51)) == 6
        elif family == 'listings':
            assert len((await query.list_records())['rows']) == 3
        elif family == 'industries':
            query = manager.registry.get('industries.query')
            assert len((await query.list_members())['rows']) == 3
        elif family == 'calendar':
            for month in ('2026-09', '2026-10', '2026-11'):
                assert len((await query.month(month))['rows']) >= 30
        elif family == 'listing_status':
            assert (await query.list_events())['rows'] == []
            assert await query.plan(date(1991, 1, 3), False) == ['1990-12', '1991-01']
        elif family == 'suspensions':
            assert await query.list_events() == []
            assert (await query.calendar_coverage())['through'] == '2004-12-29'
            assert result['dates_checked'] == 3
        else:
            assert len(await query.list_events()) == 3
    finally:
        release.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await manager.shutdown()
        if store:
            client = create_client(cfg['redis'])
            try:
                keys = [k async for k in client.scan_iter(match=store.prefix + ':*')]
                assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                if keys:
                    await client.delete(*keys)
            finally:
                await client.aclose()
