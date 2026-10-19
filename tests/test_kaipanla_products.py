"""Source semantics, independent registration and ordered lifecycle regression."""
import copy
from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS, project
from empire.plugins.collectors.kaipanla_products import KaipanlaProductCollector
from empire.plugins.collectors.kaipanla_products_source import options, parse
from empire.plugins.collectors.kaipanla_scope import lifecycle
from empire.plugins.collectors.kaipanla_source import TREND_TIMES, SourceError
from empire.plugins.datasets.kaipanla_products import validate
from tests.test_kaipanla_intraday import STOCK, collector, listing
from tests.test_kaipanla_source import sample


def source(kind, day='20210104'):
    if kind in ('trend', 'auction'):
        return {**sample(kind), 'day': day}
    result = dict(errcode='0', code='000001', day=day)
    if kind == 'quote':
        result.update(real=dict(last_px=10, open_px=10, high_px=11, low_px=9,
                                total_amount=100, total_turnover=1000, pe_rate=-5),
                      weituo={side + str(i): [10, 100] for side in ('b', 's') for i in range(1, 11)},
                      preclose_px=10, name='样本')
    elif kind == 'trades':
        result.pop('code')  # The actual source has no security echo.
        result.update(fb=[['09:30:00', 10, 1, 10, 0, 1, 0, 1],
                          ['09:30:00', 10, 1, 10, 0, 1, 0, 2]], Count=2, total=2)
    else:
        item = PRODUCTS[kind]
        result[item.field] = [[clock, *([1] * (item.width - 1))] for clock in TREND_TIMES]
        if kind == 'large_order':
            result[item.field][0][1] = -20
    return result


def business_row(kind, day='2021-01-04'):
    return {**parse(source(kind, day.replace('-', '')), STOCK['code'], date.fromisoformat(day), kind),
            'market': STOCK['market'], 'lifecycle': lifecycle(STOCK)}


@pytest.mark.parametrize('kind', PRODUCTS)
def test_complete_business_shape_and_single_interface(kind):
    row = business_row(kind)
    assert validate(row, kind) == row
    assert options('000001', date(2021, 1, 4), kind)['data']['a'] == PRODUCTS[kind].action
    bad = copy.deepcopy(row)
    bad['kind'] = 'quote' if kind != 'quote' else 'trend'
    with pytest.raises(ValueError):
        validate(bad, kind)


@pytest.mark.parametrize('kind', ('trend', 'volume', 'entrust', 'large_order'))
def test_equal_count_repeated_a_missing_b_rejected(kind):
    payload = source(kind)
    field = PRODUCTS[kind].field
    payload[field][1] = list(payload[field][0])
    with pytest.raises(SourceError):
        parse(payload, '000001', date(2021, 1, 4), kind)


def test_trades_counts_and_parallel_same_second_points_preserved():
    row = business_row('trades')
    assert len(row['data']['fb']) == 2
    assert row['source_code'] is None
    payload = source('trades')
    payload['total'] = 3
    with pytest.raises(SourceError):
        parse(payload, '000001', date(2021, 1, 4), 'trades')


@pytest.mark.parametrize('kind', PRODUCTS)
def test_wrong_day_empty_error_and_nonfinite_rejected(kind):
    payload = source(kind)
    payload['day'] = '20210105'
    with pytest.raises(SourceError):
        parse(payload, '000001', date(2021, 1, 4), kind)
    payload = source(kind)
    payload['errcode'] = 1017
    with pytest.raises(SourceError):
        parse(payload, '000001', date(2021, 1, 4), kind)


def test_seven_registered_plugins_tasks_and_preparation_are_independent():
    manager = build_manager(load_config())
    definitions = manager.entries['collection.control'].plugin.definitions
    for kind, item in PRODUCTS.items():
        assert 'collector.kaipanla_' + kind in manager.entries
        assert definitions[project(kind)].default_enabled is False
        query = manager.entries['data.kaipanla_' + kind].plugin
        assert query.preparation[0].requirement == item.requirement
    assert 'kaipanla-intraday' not in definitions
    assert 'collector.kaipanla_intraday' not in manager.entries


def product_collector(kind, days=None):
    old = collector(days)
    current = KaipanlaProductCollector(kind)
    for attr in ('ingest', 'query', 'records', 'confirmation', 'http'):
        setattr(current, attr, getattr(old, attr))
    async def request(method, url, **kwargs):
        if 'eastmoney.com' in url:
            return httpx.Response(200, json=listing())
        args = kwargs['attempt_options']()['data']
        assert args['a'] == PRODUCTS[kind].action
        return httpx.Response(200, json=source(kind, args['Day'].replace('-', '')))
    current.http.request = AsyncMock(side_effect=request)
    return current


@pytest.mark.parametrize('kind', PRODUCTS)
async def test_two_days_use_two_responses_and_only_final_archive_wait(kind):
    c = product_collector(kind)
    async def status(*args):
        assert len(c.ingest.published) == 2
        return {'status': 'complete'}
    c.confirmation.page_status = AsyncMock(side_effect=status)
    result = await c.execute()
    assert result['phase'] == 'complete'
    assert len(c.ingest.published) == 2
    requests = [call for call in c.http.request.call_args_list if 'longhuvip' in call.args[1]]
    assert len(requests) == 2


async def test_failure_does_not_advance_frontier_and_other_product_is_independent():
    c = product_collector('volume')
    real = c.http.request.side_effect
    async def request(method, url, **kwargs):
        if 'longhuvip' in url and kwargs['attempt_options']()['data']['Day'] == '2021-01-04':
            return httpx.Response(200, json={'errcode': '1017'})
        return await real(method, url, **kwargs)
    c.http.request.side_effect = request
    with pytest.raises(SourceError):
        await c.execute()
    assert c.ingest.state['cursor']['index'] == 0
    assert len(c.ingest.published) == 1
    other = product_collector('auction')
    assert (await other.execute())['phase'] == 'complete'


async def test_default_disabled_policy_survives_start_and_explicit_saved_choice():
    from empire.contracts.plugin import PluginContext
    from empire.contracts.task import TaskContribution
    from empire.core.redaction import Redactor
    from empire.plugins.collection.control import CollectionControl
    from tests.test_collection_control import setup
    old, collector, redis, http = await setup()
    await old.stop()
    definition = TaskContribution('kaipanla-volume', '量额', 'source', 'sina',
                                  'test', default_enabled=False)
    control = CollectionControl([definition])
    context = PluginContext('control', old.context.services, sanitize_error=Redactor().text)
    await control.start(context)
    try:
        policy = control.state['jobs'][definition.id]['policy']
        assert policy['enabled'] is False
        assert control.state['jobs'][definition.id]['next_due'] is None
        with pytest.raises(ValueError):
            await control.run(definition.id)
        assert collector.calls == []
        await control.configure(definition.id, {**policy, 'enabled': True})
        await control.stop()
        control = CollectionControl([definition])
        await control.start(context)
        assert control.state['jobs'][definition.id]['policy']['enabled'] is True
        assert collector.calls == []  # Manual plan stays idle even after re-enable.
    finally:
        await control.stop()
        await http.close()


async def test_product_legacy_alias_releases_response_and_validates_official_proof():
    import asyncio
    import json

    from empire.plugins.collectors.kaipanla_products_source import consume
    from empire.plugins.infra.http import HttpService
    from empire.plugins.infra.resources import ByteBudget
    from tests.test_http import MemoryPermits
    hosts = []
    async def respond(request):
        hosts.append(request.url.host)
        if request.url.host == 'www.bse.cn':
            page = dict(totalElements=1, content=[dict(xxzqdm='920000', xxfcbj='2',
                xxisin='CNE1000048X1', fxssrq='20201223')])
            return httpx.Response(200, content=('securityMasterCallback(' + json.dumps([page]) + ');').encode())
        return httpx.Response(200, json={**sample('auction'), 'code': '832000', 'day': '20211115'})
    service = HttpService(MemoryPermits(), 'test', {
        'kaipanla': {'domains': ['longhuvip.com'], 'min_interval_ms': 1},
        'bse': {'domains': ['bse.cn'], 'min_interval_ms': 1}}, transport=httpx.MockTransport(respond),
        resources=dict(generic_response_bytes=16384, buffer_budget_bytes=3 * 16384 + 262144))
    c = product_collector('auction')
    c.http = service
    stock = dict(code='920000', market='BJ', listing_date='2020-12-23')
    policy = service.response_policy('generic')
    service.buffer_budget = ByteBudget(policy.reservation_bytes)
    try:
        response = await service.request('POST', 'https://apphis.longhuvip.com/w1/api/index.php',
            allowed_domains=('longhuvip.com',), policy=policy)
        value = await asyncio.wait_for(consume(c, response, stock, date(2021, 11, 15)), 2)
        row = {**value, 'market': 'BJ', 'lifecycle': lifecycle(stock)}
        validate(row, 'auction')
        assert value['source_code'] == '832000'
        assert value['aliases']['832000']['current_code'] == '920000'
        assert hosts == ['apphis.longhuvip.com', 'www.bse.cn']
        assert service.buffer_budget.used == 0
    finally:
        await service.close()
