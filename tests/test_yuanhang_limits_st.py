"""ST shares pool requests; historical scope cannot authorize new coverage."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from empire.contracts.data import make_envelope
from empire.desktop_bridge.preview import read
from empire.features.yuanhang_limits.contract import FILTER
from empire.features.yuanhang_limits.model import member
from empire.features.yuanhang_limits.query import LimitQuery, pool_result
from empire.features.yuanhang_limits.source import fetch_pool
from empire.features.yuanhang_limits.storage import pool_payload, pool_proof
from scripts.migrate_yuanhang_limits_st import pending_scope
from tests.test_yuanhang_limits_source import client, page, row


@pytest.mark.parametrize('total,requests', [(52, 1), (100, 1), (101, 2)])
async def test_st_uses_one_combined_request_per_necessary_page(total, requests):
    rows = [{**row(f'{i:06}'), 'name': '*ST样本' if i == 1 else '普通样本'} for i in range(1, total + 1)]
    http, responses = client(*(page(rows[i:i + 100], total, i // 100 + 1) for i in range(0, total, 100)))
    unit = await fetch_pool(http, 'limit_up_pool', '2026-07-15', project_id='test')
    assert unit['requests'] == http.request.call_count == requests
    assert len(unit['rows']) == total and unit['rows'][0]['name'] == '*ST样本'
    for call in http.request.call_args_list:
        assert parse_qs(urlsplit(call.args[1]).query)['filter'] == [FILTER]
    assert all(response.close.call_count == 1 for response in responses)


def test_old_scope_is_readable_but_cannot_be_published_as_complete_with_st():
    old = dict(trade_date='2026-07-15', pool_type='limit_up_pool', filter='HS,GEM2STAR',
               source_total=1, rows=[member(row(), '2026-07-15')])
    assert pool_payload(old, require_current=False) == old
    assert pool_proof(old)['contract_version'] == 1
    with pytest.raises(ValueError, match='过滤'):
        pool_payload(old)
    new = pool_payload({**old, 'filter': FILTER})
    assert pool_proof(new)['contract_version'] == 2
    assert pool_proof(new)['content_sha256'] != pool_proof(old)['content_sha256']


async def test_combined_pool_preserves_shenzhen_delisting_market_without_lookup():
    raw = {**row('002731'), 'market_id': 37, 'name': '萃华退'}
    http, _ = client(page([raw]))
    unit = await fetch_pool(http, 'limit_up_pool', '2026-07-15', project_id='test')
    value = pool_payload({k: unit[k] for k in ('trade_date', 'pool_type', 'filter', 'source_total', 'rows')})
    assert value['rows'][0]['unified_code'] == '002731.SZ'
    assert value['rows'][0]['source_market_id'] == 37
    assert value['rows'][0]['identity_basis'] == 'market_id'
    assert http.request.call_count == unit['requests'] == 1


async def test_old_head_and_fresh_sql_version_still_require_st_backfill():
    days = ['2026-07-13', '2026-07-14', '2026-07-15']
    query = LimitQuery('test')
    heads = [dict(trade_date=date.fromisoformat(day), filter_text='HS,GEM2STAR',
                  contract_version=1, content_sha256='a' * 64) for day in days]
    query.read = AsyncMock(return_value=(days[-1], days, heads, {d: '2026-07-15T16:00:00+08:00' for d in days}))
    query.cache_proofs = AsyncMock(return_value={})
    result = await query.collection_plan('limit_up_pool', scope='recent')
    assert result['units'] == list(reversed(days))
    query.cache_proofs.assert_not_awaited()


@pytest.mark.parametrize('filter_text,scope', [(FILTER, '含ST'), ('HS,GEM2STAR', '未补充ST')])
async def test_preview_reports_pool_total_instead_of_first_page_count(filter_text, scope):
    service = SimpleNamespace(members=AsyncMock(return_value=pool_result(
        dict(source_total=52, filter_text=filter_text),
        [{'unified_code': f'{i:06}.SZ'} for i in range(1, 51)], '000050.SZ')))
    result = await read(SimpleNamespace(get=lambda _: service), 'ths-yuanhang-limit-up-pool',
                        'daily', {'day': '2026-07-15'})
    assert len(result['rows']) == 50 and result['total'] == 52 and result['next']
    assert scope in result['message']


async def test_migration_keeps_other_projects_pending_and_rejects_pool_messages():
    def message(dataset, job):
        envelope = make_envelope(source='tdx', dataset=dataset, job_key=job,
                                 business_key='000001.SZ', run_id='test', batch_id='test', payload={})
        return ('1-0', {'envelope': envelope.model_dump_json()})
    redis = SimpleNamespace(xrange=AsyncMock(side_effect=[
        [message('holder_count.tdx_unit', 'tdx-holder-count-v1')], []]))
    assert await pending_scope(redis, 'test:ingest') == {'holder_count.tdx_unit': 1}
    redis.xrange = AsyncMock(return_value=[message('yuanhang.limits.limit_up_pool', 'ths-yuanhang-limit-up-pool-v1')])
    with pytest.raises(ValueError, match='五池仍有'):
        await pending_scope(redis, 'test:ingest')
