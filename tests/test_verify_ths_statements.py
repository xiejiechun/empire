"""Safety and content counterexamples; no external service or source requests."""
import asyncio
import importlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from empire.plugins.collection.unit_prefetch import DeferredResponse


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    module = importlib.import_module('verify_ths_statements')
    return module


def rows(code='000001', market='SH', value='1', day='2024-12-31'):
    return [dict(market=market, code=code, name='证券1', report_date=day,
                 basis='source_report', currency='CNY', period_basis='year_to_date', announcement_date=None,
                 fields={name: dict(value=value, resolution='1') for name in
                         ('*营业总收入', '*净利润', '*归属于母公司所有者的净利润')})]


@pytest.mark.asyncio
async def test_deferred_observer_preserves_object_reservation_and_close_owner(verifier):
    stock = dict(market='SH', code='000001', name='证券1')
    response = Mock()
    result = (rows(), datetime.now(UTC), 'https://basic.10jqka.com.cn/example')
    deferred = DeferredResponse(response, AsyncMock(return_value=result))
    original = AsyncMock(return_value=deferred)
    collector = SimpleNamespace(kind='income', fetch=original)
    summaries, reservation = {}, object()
    observed = verifier.observe_fetch(collector, [dict(unified_code='000001.SH')], summaries)
    returned = await observed(stock, reservation=reservation, defer=True)
    assert returned is deferred and not summaries
    original.assert_awaited_once_with(stock, reservation=reservation, defer=True)
    assert await returned.consume() is result
    response.close.assert_not_called()
    assert summaries['000001.SH']['digest'] == verifier.digest(rows())
    returned.close()
    returned.close()
    response.close.assert_called_once()


@pytest.mark.asyncio
async def test_observer_does_not_close_or_swallow_consumer_failure(verifier):
    response = Mock()
    deferred = DeferredResponse(response, AsyncMock(side_effect=asyncio.CancelledError))
    observed = verifier.observe_fetch(SimpleNamespace(kind='income', fetch=AsyncMock(return_value=deferred)),
                                      [dict(unified_code='000001.SH')], {})
    result = await observed(dict(market='SH', code='000001', name='证券1'), defer=True)
    with pytest.raises(asyncio.CancelledError):
        await result.consume()
    response.close.assert_not_called()
    result.close()
    response.close.assert_called_once()


@pytest.mark.asyncio
async def test_observer_rejects_duplicate_and_foreign_unit(verifier):
    stock = dict(market='SH', code='000001', name='证券1')
    raw = (rows(), datetime.now(UTC), 'https://basic.10jqka.com.cn/example')
    collector = SimpleNamespace(kind='income', fetch=AsyncMock(return_value=raw))
    wrapped = verifier.observe_fetch(collector, [dict(unified_code='000001.SH')], {})
    assert await wrapped(stock) is raw
    with pytest.raises(ValueError, match='重复消费'):
        await wrapped(stock)
    foreign = verifier.observe_fetch(collector, [dict(unified_code='000002.SH')], {})
    with pytest.raises(ValueError, match='样本外'):
        await foreign(stock)


def test_equal_counts_different_dates_or_amounts_have_different_proofs(verifier):
    stock = dict(market='SH', code='000001', name='证券1')
    first = verifier.row_summary('income', stock, rows())
    changed_date = verifier.row_summary('income', stock, rows(day='2024-09-30'))
    changed_amount = verifier.row_summary('income', stock, rows(value='2'))
    assert first['count'] == changed_date['count'] == changed_amount['count']
    assert first['dates'] != changed_date['dates']
    assert first['digest'] != changed_amount['digest']
    assert first['reports'] != changed_amount['reports']


def test_manifest_binds_order_keys_and_content_independently_of_arrival(verifier):
    stock = dict(market='SH', code='000001', name='证券1')
    a = verifier.row_summary('income', stock, rows())
    b = verifier.row_summary('income', dict(stock, code='000002'), rows(code='000002'))
    first = verifier.expected_manifest({'a': a, 'b': b})
    assert first == verifier.expected_manifest({'b': b, 'a': a})
    revised = {**b, 'digest': 'changed'}
    assert first != verifier.expected_manifest({'a': a, 'b': revised})
    assert first['count'] == a['count'] + b['count'] and first['units'] == 2


@pytest.mark.parametrize('proxy,random_count', [(False, 30), (True, 29)])
def test_cli_enforces_random_and_proxy_before_resource_creation(verifier, monkeypatch, tmp_path,
                                                              proxy, random_count):
    import json

    monkeypatch.setattr(verifier.verification, 'project_root', lambda: tmp_path)
    allocate = Mock(side_effect=AssertionError('must not create private resources'))
    monkeypatch.setattr(verifier.verification, 'PrivateStorage', allocate)
    output = tmp_path / 'build' / f'{proxy}-{random_count}.json'
    argv = ['--test-mysql-settings', str(tmp_path / 'absent.json'), '--output', str(output),
            '--random-count', str(random_count), '--seed', '20261019']
    if proxy:
        argv.append('--proxy-only')
    assert verifier.main(argv) == 1
    report = json.loads(output.read_text('utf-8'))
    assert not report['passed'] and not report['pipeline_verified']
    assert report['errors'][0]['stage'] == 'verification'
    allocate.assert_not_called()


def test_fixed_historical_failures_supplement_random_sample(verifier):
    assert {'920000.BJ', '000001.SZ', '600104.SH', '600018.SH', '601139.SH'} <= set(verifier.FIXED_CODES)
    stocks = [dict(unified_code=f'{n:06d}.SZ', name=str(n)) for n in range(1, 45)]
    chosen = verifier.verification.select_stocks(stocks, 30, 20261019, ['000044.SZ'])
    assert len(set(chosen['random'])) == 30
    assert '000044.SZ' in {s['unified_code'] for s in chosen['selected']}


@pytest.mark.asyncio
async def test_publish_observer_rejects_equal_count_different_content_before_redis(verifier):
    expected = verifier.row_summary('income', dict(market='SH', code='000001', name='证券1'), rows())
    original = AsyncMock(return_value=dict(revision=1, cursor={'index': 1}))
    collector = SimpleNamespace(publish=original)
    published = {}
    observe = verifier.observe_publish(collector, {'000001.SH': expected}, published)
    with pytest.raises(ValueError, match='入队集合或内容'):
        await observe({'revision': 0}, {'index': 1}, 'SH:000001', rows(value='2'), None, None, None)
    original.assert_not_awaited()
    await observe({'revision': 0}, {'index': 1}, 'SH:000001', rows(), None, None, None)
    assert published['SH:000001']['rows_digest'] == expected['digest']
    with pytest.raises(ValueError, match='重复'):
        await observe({'revision': 1}, {}, 'SH:000001', rows(), None, None, None)
    assert original.await_count == 1
