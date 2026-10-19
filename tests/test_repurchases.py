import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.contracts.repurchases import (
    DATASET,
    PAGE_SIZE,
    SOURCE_FIELDS,
    URL,
    digest,
    extend_digest,
    normalize,
    number,
    parse,
)
from empire.plugins.collectors.eastmoney_repurchase import RepurchaseCollector
from tests.catalog_factory import builtin_catalog
from tests.prefetch_source import prefetch_http
from tests.test_sina_news import Diagnostics, MemoryIngest


def source_row(ident='1', **extra):
    row = dict.fromkeys(SOURCE_FIELDS.values())
    row.update(REPURCODE=ident, SECUCODE='600000.SH', SECURITYSHORTNAME='测试公司',
               SHARETYPE='流通A股', DIM_DATE='2025-01-01 00:00:00', UPD='2026-10-12 00:00:00',
               REPURPROGRESS='004', REPUROBJECTIVE='股权激励或注销', REPURAMOUNTLOWER=100000,
               REPURAMOUNTLIMIT=200000, REPURNUM=100, REPURAMOUNT=1010.25)
    row.update(extra)
    return row


def feed(rows, count=None):
    count = len(rows) if count is None else count
    return dict(success=True, result=dict(count=count, pages=(count+PAGE_SIZE-1)//PAGE_SIZE, data=rows))


def collector(rows):
    item = RepurchaseCollector()
    item.ingest, item.records = MemoryIngest(), Diagnostics()
    async def request(method, url, **kw):
        assert method == 'GET' and url == URL and kw['allowed_domains'] == ('eastmoney.com',)
        p = kw['params']
        assert p['pageNumber'] == 1 and p['sortColumns'] == 'REPURCODE' and 'callback' not in p
        after = p.get('filter', '').split('"')[1] if 'filter' in p else ''
        available = [r for r in rows if r['REPURCODE'] > after]
        return httpx.Response(200, request=httpx.Request('GET', URL), json=feed(available[:PAGE_SIZE], len(available)))
    item.http = prefetch_http(request=AsyncMock(side_effect=request))
    async def archived(*args):
        assert item.ingest.state['cursor']['phase'] == 'awaiting_archive'
        return {'status': 'complete'}
    item.confirmation = SimpleNamespace(page_status=AsyncMock(side_effect=archived))
    return item


def test_field_contract_null_decimal_and_excluding_quotes():
    row = normalize(source_row(NEWPRICE=999, REPURPRICECAP=10.00000001))
    assert row['plan_price_upper'] == '10.00000001' and row['finish_date'] is None
    assert 'NEWPRICE' not in row and row['actual_quantity'] == '100'
    assert digest(row) == digest(normalize(source_row(NEWPRICE=1, REPURPRICECAP='10.000000010')))
    for value in (True, float('nan'), -1, '0.000000001', '1e20'):
        with pytest.raises(ValueError):
            number(value)
    with pytest.raises(ValueError):
        normalize(source_row(REPURAMOUNTLOWER=300000))


def test_duplicates_missing_count_tail_and_boundary_fail():
    for body in (feed([source_row(), source_row()], 2), feed([source_row()], 2),
                 feed([source_row('2'), source_row('1')]), {}, None):
        with pytest.raises(ValueError):
            parse(body)
    with pytest.raises(ValueError):
        parse(feed([source_row('1')]), after='1')
    with pytest.raises(ValueError):
        parse(feed([source_row('2')]), after='1', remaining=2)
    rows, count = parse(feed([]))
    assert rows == [] and count == 0


async def test_two_source_pages_stream_without_batch_archive_wait():
    item = collector([source_row(str(i)) for i in range(1, 602)])
    # Server sorts ID as a string; dates are deliberately identical for all rows.
    async def request(*args, **kw):
        # Rebuild the source page by the lexicographic protocol.
        after = kw['params'].get('filter', '').split('"')[1] if 'filter' in kw['params'] else ''
        available = sorted([source_row(str(i)) for i in range(1, 602) if str(i) > after], key=lambda r: r['REPURCODE'])
        assert item.confirmation.page_status.await_count == 0
        return httpx.Response(200, request=httpx.Request('GET', URL), json=feed(available[:500], len(available)))
    item.http.request.side_effect = request
    result = await item.execute()
    assert result['collected'] == 601 and item.http.request.await_count == 2
    assert item.confirmation.page_status.await_count == 1
    rows = [r for e in item.ingest.events for r in e.raw_payload['rows']]
    assert result['digest'] == extend_digest('0'*64, rows)
    assert len({r['plan_id'] for r in rows}) == 601
    assert len(str(result).encode()) < 16384


async def test_capacity_splits_cancel_resume_and_bad_page_does_not_advance():
    source = [source_row(str(i), REMARK='说明'*500) for i in range(1, 6)]
    item = collector(source)
    item.ingest.settings = dict(max_page_bytes=10000)
    publish = item.ingest.publish_page
    async def interrupted(*args, **kw):
        if item.ingest.events:
            raise asyncio.CancelledError
        return await publish(*args, **kw)
    item.ingest.publish_page = interrupted
    with pytest.raises(asyncio.CancelledError):
        await item.execute()
    checkpoint = copy.deepcopy(item.ingest.state)
    assert checkpoint['cursor']['phase'] == 'fetch' and checkpoint['cursor']['collected'] < 5
    item.ingest.publish_page = publish
    await item.execute(baseline_revision=checkpoint['revision'])
    assert item.ingest.state['cursor']['collected'] == 5
    assert all(len(e.model_dump_json().encode()) <= 10000 for e in item.ingest.events)
    before = copy.deepcopy(item.ingest.state)
    item.http.request.side_effect = lambda *a, **kw: httpx.Response(200, request=httpx.Request('GET', URL), json=feed([source_row(), source_row()]))
    with pytest.raises(ValueError):
        await item.execute(baseline_revision=before['revision'])
    assert item.ingest.state == before
    assert item.records.errors


async def test_waiting_stage_resume_no_download_and_catalog_identity():
    item = collector([source_row()])
    item.confirmation.page_status.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await item.execute()
    assert item.ingest.state['cursor']['phase'] == 'awaiting_archive'
    calls = item.http.request.await_count
    item.confirmation.page_status.side_effect = None
    item.confirmation.page_status.return_value = {'status': 'complete'}
    await item.execute(baseline_revision=item.ingest.state['revision'])
    assert item.http.request.await_count == calls
    contribution = builtin_catalog().datasets[DATASET]
    assert contribution.projects == {'eastmoney-repurchases-v1': 'eastmoney-repurchases'}
