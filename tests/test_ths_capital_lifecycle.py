"""Ordered prefetch, failure frontier and no per-security archive waits."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.features.ths_capital.collector import CapitalPageCollector
from empire.features.ths_capital.contract import JOB, PROJECT, TABLES
from empire.features.ths_capital.transport import unpack
from tests.prefetch_source import prefetch_http
from tests.test_capital_lifecycle import Publisher
from tests.test_ths_capital import STOCK, source


def configured(stocks=None):
    c = CapitalPageCollector()
    c.ingest = Publisher()
    c.query = SimpleNamespace(securities=AsyncMock(return_value=stocks or [STOCK]))
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.session = SimpleNamespace(headers=lambda _: {})
    c.http = prefetch_http(request=AsyncMock(side_effect=lambda method, url, **kw:
        httpx.Response(200, content=source().replace('value="601139"', 'value="' + url.split('/')[-2] + '"').encode('gb18030'))))
    return c


async def test_download_and_atomic_publish_continue_without_archive_per_unit():
    stocks = [STOCK, {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}]
    c = configured(stocks)
    c.http.parallelism.return_value = 2
    gate = asyncio.Event()
    async def confirm(*args):
        assert c.http.request.await_count == 2 and len(c.ingest.events) == 3
        await gate.wait()
        return dict(status='complete')
    c.confirmation.page_status.side_effect = confirm
    task = asyncio.create_task(c.execute())
    async with asyncio.timeout(3):
        while c.stats['status'] != 'awaiting_archive':
            await asyncio.sleep(0)
    assert (await c.ingest.checkpoint(JOB))['cursor']['index'] == 2
    assert all(set(unpack(e.raw_payload['rows'])) == set(TABLES) for e in c.ingest.events)
    gate.set()
    assert (await task)['phase'] == 'complete'
    assert c.http.buffer_budget.used == 0


@pytest.mark.parametrize('bad_body', [
    b'invalid',
    source().replace('601139', '601140').replace('rowspan="2">A股', 'rowspan="2">未公布').encode('gb18030'),
    source().replace('601139', '601140').replace('500万美元', '500万未知币种').encode('gb18030'),
])
async def test_failure_retains_first_unpublished_security_and_resume_does_not_wait(bad_body):
    stocks = [STOCK, {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}]
    c = configured(stocks)
    request = c.http.request.side_effect
    c.http.request.side_effect = lambda method, url, **kw: (httpx.Response(200, content=bad_body)
        if '601140/' in url else request(method, url, **kw))
    with pytest.raises(ValueError):
        await c.execute()
    state = await c.ingest.checkpoint(JOB)
    assert state['cursor']['index'] == 1 and len(c.ingest.events) == 1
    c.confirmation.page_status.assert_not_awaited()
    c.http.request.side_effect = request
    assert (await c.execute(baseline_revision=state['revision']))['phase'] == 'complete'
    assert c.http.request.await_count == 3


async def test_cancel_waiting_resume_awaits_same_round_without_downloads():
    c = configured()
    c.confirmation.page_status.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    assert c.http.buffer_budget.used == 0
    c.confirmation.page_status.side_effect = None
    assert (await c.execute(fresh=True, baseline_revision=await c.checkpoint_revision()))['phase'] == 'complete'
    assert c.http.request.await_count == 1


async def test_redis_checkpoint_loss_rechecks_full_window_and_pool_changes_replan():
    c = configured()
    await c.execute()
    c.ingest = Publisher()
    await c.execute()
    assert c.http.request.await_count == 2
    c.query.securities.return_value = [STOCK, {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}]
    await c.execute(baseline_revision=await c.checkpoint_revision())
    assert c.http.request.await_count == 4


def test_one_task_defaults_and_nine_independent_preparation_outputs():
    m = build_manager(dict(redis={}, mysql={}, archive={}, ingest={}, rate_groups={}))
    task = m.entries['collection.control'].plugin.definitions[PROJECT]
    assert task.parallel_downloads and not task.default_enabled
    assert task.default_schedule.mode == 'daily' and task.default_schedule.daily_time == '18:30'
    q = m.entries['data.ths_capital'].plugin
    assert len(q.preparation) == 9 and len({p.requirement for p in q.preparation}) == 9
    assert all(p.response_group == 'ths.capital.security' for p in q.preparation)
