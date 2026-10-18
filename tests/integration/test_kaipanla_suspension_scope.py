"""Actual event archive repairs a source gap without fabricating a quote day."""
import os
from datetime import date
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS
from empire.plugins.collectors.kaipanla_source import SourceError
from empire.plugins.datasets import suspensions
from empire.plugins.datasets.suspensions import normalize_source_row
from tests.test_kaipanla_intraday import STOCK, listing
from tests.test_kaipanla_products import product_collector, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private database opt in')]


@pytest.mark.parametrize('kind', PRODUCTS)
async def test_unknown_resume_start_day_gap_replans_and_archives_following_day(kind, monkeypatch):
    # This private scenario starts at 2021; the full historical boundary has
    # separate suspension archive tests.
    monkeypatch.setattr(suspensions, 'FIRST_DATE', date(2021, 1, 4))
    cfg = load_config()
    manager = build_manager(cfg)
    store = None
    try:
        await manager.start('collector.kaipanla_' + kind)
        c = manager.registry.get('collector.kaipanla_' + kind)
        query = c.query
        archive = manager.registry.get('archive.worker')
        ingest = manager.registry.get('ingest.publish')
        store = manager.registry.get('redis.store')
        days = [date(2021, 1, 4), date(2021, 1, 5)]
        monkeypatch.setattr(query, 'plan', AsyncMock(return_value=([STOCK], days)))
        c.http = product_collector(kind).http
        calls = []
        async def request(method, url, **options):
            if 'eastmoney.com' in url:
                return httpx.Response(200, json=listing())
            day = options['attempt_options']()['data']['Day']
            calls.append(day)
            return httpx.Response(200, json={'errcode': '1017'} if day == '2021-01-04'
                                  else source(kind, day.replace('-', '')))
        c.http.request = AsyncMock(side_effect=request)
        status = c.confirmation.page_status
        async def confirmed(*args):
            await archive.flush()
            return await status(*args)
        monkeypatch.setattr(c.confirmation, 'page_status', confirmed)
        with pytest.raises(SourceError, match='来源缺口'):
            await c.execute()
        before = await ingest.checkpoint(c.job_key)
        assert before['cursor']['index'] == 0 and before['cursor']['first_gap']['trade_date'] == '2021-01-04'
        assert await query.day('SZ', '000001', '2021-01-04') is None
        assert await query.day('SZ', '000001', '2021-01-05') is not None
        assert await store.client.xlen(store.stream) == 0

        row = normalize_source_row(dict(sc=0, code='000001', name='样本', tprq='2021-01-04 09:30',
            fprq=None, sj='连续停牌', sjcontent='重要公告'))
        batch = uuid4().hex
        envelope = make_envelope(source='tdx', dataset='suspensions.period', schema_version=3,
            job_key='tdx-suspensions-v1', business_key=batch, run_id=batch, batch_id=batch,
            payload=dict(page=1, period='2021-01', start_date='2021-01-04', end_date='2021-01-05',
                checked_dates=['2021-01-04', '2021-01-05'], rows=[{**row, 'source_dates': ['2021-01-04']}]))
        cp = await ingest.checkpoint('tdx-suspensions-v1')
        await ingest.publish_page([envelope], job_key='tdx-suspensions-v1', expected_revision=cp['revision'], cursor={})
        await archive.flush()
        assert await query.suspension_plan([STOCK], *days) == {'000001.SZ': {days[0]}}
        assert await query.suspended_days('SZ', '000001', *days) == {days[0]}
        calls.clear()
        result = await c.execute(baseline_revision=before['revision'])
        assert result['phase'] == 'complete' and result['scope'] != before['cursor']['scope']
        assert calls == ['2021-01-05']  # Unknown end never excludes the following day.
        assert await query.day('SZ', '000001', '2021-01-04') is None
        assert await query.day('SZ', '000001', '2021-01-05') is not None
        assert await store.client.xlen(store.stream) == 0
        evidence = await query.preparation_check(dict(codes=['000001'], start='2021-01-04', end='2021-01-05'))
        assert all(item.status == 'pass' for item in evidence)
    finally:
        if store and store.client:
            keys = [key async for key in store.client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(key.startswith(cfg['redis']['namespace'] + ':') for key in keys)
                await store.client.delete(*keys)
        await manager.shutdown()
