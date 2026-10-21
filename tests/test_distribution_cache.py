"""Product results obey the existing dated, scope-bound readiness cache."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests import test_preparation_cache

plugin_for, setup = test_preparation_cache.plugin_for, test_preparation_cache.setup


async def test_dated_product_cached_force_recheck_and_scope_change(setup):
    _, _, registry, _ = setup
    result = dict(id='nominal_dividends', title='名义派息', state='已计算', checked_at='first',
                  securities=[dict(cash_per_share='0.609')])
    service = SimpleNamespace(distribution_summary=AsyncMock(return_value=deepcopy(result)))
    registry['dividends.query'] = service
    plugin = await plugin_for(registry)
    request = dict(codes=['000001'], start='2026-01-01', end='2026-10-20')
    first = await plugin.report(request)
    service.distribution_summary.return_value = {**result, 'checked_at': 'rechecked'}
    cached = await plugin.report(request)
    assert cached['products'][0]['checked_at'] == 'rechecked'
    assert cached['rows'][0]['id'] == first['rows'][0]['id']
    assert service.distribution_summary.await_count == 2
    forced = await plugin.report(request, force=True)
    assert forced['products'][0]['checked_at'] == 'rechecked'
    await plugin.report({**request, 'end': '2026-06-11'})
    await plugin.report({**request, 'codes': ['600000']})
    assert service.distribution_summary.await_count == 5


async def test_unspecified_range_stays_unchecked_instead_of_zero_or_error(setup):
    _, _, registry, _ = setup
    service = SimpleNamespace(distribution_summary=AsyncMock())
    registry['dividends.query'] = service
    report = await (await plugin_for(registry)).report()
    assert report['products'][0]['state'] == '未检查'
    service.distribution_summary.assert_not_awaited()


async def test_cached_report_rechecks_yield_inputs_without_disabling_nominal_product(setup):
    _, _, registry, _ = setup
    nominal = dict(id='nominal_dividends', title='名义派息', state='已计算', securities=[])
    result = dict(id='dividend_yield', title='区间名义现金股息率', state='已计算',
                  input_hash='old-price', securities=[dict(yield_percent='5.075')])
    service = SimpleNamespace(distribution_summary=AsyncMock(return_value=nominal),
                              dividend_yield=AsyncMock(return_value=result))
    registry['dividends.query'] = service
    plugin = await plugin_for(registry)
    request = dict(codes=['000001'], start='2026-01-01', end='2026-10-20')
    first = await plugin.report(request)
    assert first['products'][1]['input_hash'] == 'old-price'
    service.dividend_yield.return_value = {**result, 'state': '数据阻断',
        'input_hash': '', 'securities': [], 'problem': '当前价格证据不完整'}
    cached = await plugin.report(request)
    assert cached['products'][0]['state'] == '已计算'
    assert cached['products'][1]['state'] == '数据阻断'
    assert service.dividend_yield.await_count == 2
