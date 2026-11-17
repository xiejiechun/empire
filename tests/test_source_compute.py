"""Spawned parsing preserves business data and retains result ownership."""
import asyncio
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from empire.contracts.data import BackpressureError
from empire.features.ths_capital.source import parse
from empire.plugins.infra.resources import ByteBudget
from tests.catalog_factory import builtin_catalog
from tests.test_ths_capital import STOCK, source
from tests.test_ths_capital_lifecycle import configured


def complete_body():
    return source().replace('项目完整&lt;br&gt;简介', '完整详情' * 3000).encode('gb18030')


async def started_catalog(budget=None):
    catalog = builtin_catalog()
    budget = budget or ByteBudget(64 * 1024 * 1024)
    await catalog.start(SimpleNamespace(get=lambda name: SimpleNamespace(buffer_budget=budget)))
    return catalog, budget


async def test_spawned_source_preserves_all_rows_details_dates_and_availability():
    catalog, budget = await started_catalog()
    body, today = complete_body(), date(2026, 11, 6)
    try:
        result = await catalog.compute_source('ths.capital', body, STOCK, today)
        assert result.value == parse(body, STOCK, today)
        assert result.value['rows']['capital_project'][0]['description'] == '完整详情' * 3000
        assert 0 < budget.used <= budget.peak <= budget.limit
        assert catalog.compute_lane.health()['started']
        result.close()
        result.close()
        assert result.value is None and budget.used == 0
    finally:
        await catalog.stop()


async def test_source_exception_and_exhaustion_release_only_owned_bytes():
    catalog, budget = await started_catalog()
    body, today = complete_body(), date(2026, 11, 6)
    held = budget.try_reserve(budget.limit)
    try:
        with pytest.raises(BackpressureError, match='共享缓冲'):
            await catalog.compute_source('ths.capital', body, STOCK, today)
        assert budget.used == held.size and not catalog.compute_lane.health()['started']
        held.release()
        with pytest.raises(ValueError):
            await catalog.compute_source('ths.capital', body, {**STOCK, 'code': '600001'}, today)
        assert budget.used == 0 and catalog.compute_lane.pending == 0
        with pytest.raises(ValueError, match='未知来源'):
            await catalog.compute_source('unknown', body, STOCK, today)
        assert budget.used == 0
    finally:
        held.release()
        await catalog.stop()


async def test_deferred_source_keeps_budget_until_ordered_publication_finishes():
    collector = configured()
    catalog, budget = await started_catalog(collector.http.buffer_budget)
    collector.catalog = catalog
    collector.http.request.side_effect = lambda *a, **kw: httpx.Response(200, content=complete_body())
    original = collector.ingest.publish_page
    seen = []

    async def publish(*args, **kwargs):
        if args[0][0].business_key != 'manifest':
            seen.append(budget.used)
            assert budget.used > 100000
        return await original(*args, **kwargs)

    collector.ingest.publish_page = publish
    try:
        await collector.execute()
        assert seen and budget.used == 0 and catalog.compute_lane.pending == 0
    finally:
        await catalog.stop()


async def test_cancel_waiting_for_source_slot_reclaims_lease_without_publication():
    collector = configured()
    catalog, budget = await started_catalog(collector.http.buffer_budget)
    collector.catalog = catalog
    collector.http.request.side_effect = lambda *a, **kw: httpx.Response(200, content=complete_body())
    for _ in range(catalog.compute_lane.workers):
        await catalog.compute_lane.slots.acquire()
    task = asyncio.create_task(collector.execute())
    try:
        async with asyncio.timeout(5):
            while not catalog.compute_lane.pending:
                await asyncio.sleep(.001)
        assert budget.used > 100000
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not collector.ingest.events
        assert budget.used == 0 and catalog.compute_lane.pending == 0
    finally:
        for _ in range(catalog.compute_lane.workers):
            catalog.compute_lane.slots.release()
        await catalog.stop()
