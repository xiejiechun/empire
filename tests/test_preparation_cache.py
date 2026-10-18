import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_catalog import REQUIREMENTS
from empire.contracts.preparation_scope import PreparationScope
from empire.plugins.data.preparation import PreparationPlugin
from empire.plugins.data.preparation_cache import TTL_SECONDS, PreparationCache
from tests.test_preparation import contribution


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr('empire.plugins.data.preparation.load_evidence', lambda: ({}, '未执行本版本测试'))
    values = {}
    async def save(key, value, ex):
        assert ex == 604800
        values[key] = value
    store = SimpleNamespace(prefix='test', client=SimpleNamespace(
        get=AsyncMock(side_effect=values.get), set=AsyncMock(side_effect=save)))
    service = SimpleNamespace(preparation_check=AsyncMock(return_value=(CheckEvidence('keys', 'pass', '通过'),)))
    registry = {'redis.store': store, 'stocks.query': service}
    return store, service, registry, values


async def plugin_for(registry):
    plugin = PreparationPlugin([contribution()])
    await plugin.start(SimpleNamespace(optional=registry.get))
    return plugin


async def test_cached_report_survives_page_and_plugin_recreation_without_provider_reads(setup):
    store, service, registry, values = setup
    first = await (await plugin_for(registry)).report()
    cached = await (await plugin_for(registry)).report()
    service.preparation_check.assert_awaited_once()
    assert cached['checked_at'] == first['checked_at']
    assert cached['rows'] == first['rows']
    assert cached['rows'][0]['specification'] is REQUIREMENTS[0]
    assert '已读取 Redis' in cached['cache_note']
    store.client.set.assert_awaited_once()  # Reading never extends the seven-day TTL.
    assert len(values) == 1 and TTL_SECONDS == 604800


async def test_manual_recheck_replaces_result_and_resets_ttl(setup):
    store, service, registry, _ = setup
    plugin = await plugin_for(registry)
    await plugin.report()
    service.preparation_check.return_value = (CheckEvidence('keys', 'fail', '缺失'),)
    refreshed = await plugin.report(force=True)
    cached = await plugin.report()
    assert service.preparation_check.await_count == 2
    assert cached['rows'] == refreshed['rows']
    assert cached['rows'][0]['data'] == 0
    assert store.client.set.await_count == 2


async def test_different_scopes_are_isolated_and_release_evidence_does_not_recheck(setup, monkeypatch):
    _, service, registry, values = setup
    plugin = await plugin_for(registry)
    for request in (None, {'codes': ['601139']}, {'purpose': 'historical_signal'}, {'start': '2020-01-01'}):
        await plugin.report(request)
    monkeypatch.setattr('empire.plugins.data.preparation.load_evidence', lambda: ({}, '新发布的开发证据'))
    report = await plugin.report()
    assert report['test_evidence'] == '新发布的开发证据'
    assert service.preparation_check.await_count == 4 and len(values) == 4


@pytest.mark.parametrize('quality_status', ['pass', 'fail'])
async def test_all_four_business_dimensions_survive_unrelated_plugin_and_test_changes(setup, monkeypatch, quality_status):
    store, service, registry, _ = setup
    service.preparation_check.return_value = tuple(
        CheckEvidence(c.id, quality_status if c.id == 'fields' else 'pass', '明确的检查结果')
        for c in REQUIREMENTS[0].criteria)
    first = await (await plugin_for(registry)).report()
    unrelated = SimpleNamespace(manifest=SimpleNamespace(id='ui.other', provides=('ui.other',)))
    plugin = PreparationPlugin([replace(contribution(), source_tests=('tests/new_release_test.py',))], [unrelated])
    registry['ui.other'] = object()
    await plugin.start(SimpleNamespace(optional=registry.get))
    monkeypatch.setattr('empire.plugins.data.preparation.load_evidence', lambda: ({}, '本次版本开发证据失效'))
    cached = await plugin.report()
    for old, current in zip(first['rows'], cached['rows'], strict=True):
        for dimension in ('integrity', 'quality', 'usage', 'use_state', 'usable'):
            assert current['assessment'][dimension] == old['assessment'][dimension]
    assert cached['checked_at'] == first['checked_at']
    assert cached['rows'][0]['assessment']['integrity'] == '通过'
    assert cached['rows'][0]['assessment']['quality'] == ('通过' if quality_status == 'pass' else '有异常')
    assert cached['rows'][0]['assessment']['usage'] == '通过'
    assert cached['rows'][0]['assessment']['use_state'] == ('可用' if quality_status == 'pass' else '不可用')
    assert cached['test_evidence'] == '本次版本开发证据失效'
    service.preparation_check.assert_awaited_once()
    store.client.set.assert_awaited_once()


async def test_business_revision_and_query_availability_revoke_cached_checks(setup):
    _, service, registry, values = setup
    await (await plugin_for(registry)).report()
    plugin = PreparationPlugin([replace(contribution(), cache_revision=2)])
    await plugin.start(SimpleNamespace(optional=registry.get))
    await plugin.report()
    assert service.preparation_check.await_count == 2 and len(values) == 2
    registry.pop('stocks.query')
    report = await plugin.report()
    assert report['rows'][0]['data'] == 0
    assert '已读取 Redis' not in report['cache_note']


@pytest.mark.parametrize('corruption', ['expired', 'broken', 'partial', 'modified', 'retired_catalog',
                                      'retired_share_capital', 'retired_free_float'])
async def test_invalid_or_expired_cache_is_rechecked(setup, corruption):
    _, service, registry, values = setup
    plugin = await plugin_for(registry)
    await plugin.report()
    key = next(iter(values))
    if corruption == 'expired':
        values.clear()
    elif corruption == 'broken':
        values[key] = '{'
    else:
        report = json.loads(values[key])
        if corruption == 'partial':
            report['checking'] = True
        elif corruption.startswith('retired_'):
            ident = {'retired_catalog': 'news', 'retired_share_capital': 'share_capital',
                     'retired_free_float': 'free_float'}[corruption]
            report['rows'].append({**report['rows'][0], 'id': ident})
            report['checked_requirements'] += 1
            report['total_requirements'] += 1
            report.pop('cache_sha256')
            report['cache_sha256'] = PreparationCache.checksum(report)
        else:
            report['rows'][0]['data'] = 99
        values[key] = json.dumps(report)
    await plugin.report()
    assert service.preparation_check.await_count == 2


async def test_cancellation_never_stores_partial_report(setup):
    store, service, registry, values = setup
    entered = asyncio.Event()
    async def slow():
        entered.set()
        await asyncio.Event().wait()
    service.preparation_check.side_effect = slow
    task = asyncio.create_task((await plugin_for(registry)).report())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not values
    store.client.set.assert_not_awaited()


async def test_redis_failure_preserves_check_result_and_displays_cache_failure(setup):
    store, _, registry, _ = setup
    store.client.get.side_effect = RuntimeError('offline')
    store.client.set.side_effect = RuntimeError('offline')
    report = await (await plugin_for(registry)).report()
    assert report['rows'][0]['data'] == 1
    assert '缓存保存失败' in report['cache_note']


def test_normalized_scope_uses_same_key(setup):
    store, _, _, _ = setup
    first = PreparationScope.parse({'codes': ['601139', '000001', '601139']})
    second = PreparationScope.parse({'codes': ['000001', '601139']})
    assert PreparationCache(store, 'version', first).key == PreparationCache(store, 'version', second).key
