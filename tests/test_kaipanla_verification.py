"""Verifier counterexamples: set/content identity, scope and strict CLI cannot be relaxed."""
import asyncio
import copy
import importlib
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.test_kaipanla_intraday import STOCK
from tests.test_kaipanla_products import business_row


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('kaipanla_verification')


@pytest.mark.parametrize('days', [[], ['2026-09-30', '2026-09-30'], ['2026-09-30', '2026-09-28'],
                                 ['2020-12-31'], ['9999-01-01'], ['2026-02-30']])
def test_scope_rejects_unordered_duplicate_and_unclosed_dates(verifier, days):
    with pytest.raises(ValueError):
        verifier.checked_days(days)
    assert verifier.checked_days(['2026-09-30']) == [date(2026, 9, 30)]


@pytest.mark.parametrize('change', ['dataset', 'key', 'content', 'listing'])
def test_equal_count_does_not_hide_wrong_source_or_lifecycle(verifier, change):
    row = business_row('trend')
    key = '000001.SZ/2021-01-04'
    sources = {key: {k: v for k, v in row.items() if k not in ('market', 'lifecycle')}}
    listings = {'000001.SZ': STOCK}
    envelope = SimpleNamespace(dataset='kaipanla.trend.day', raw_payload=dict(rows=[copy.deepcopy(row)]))
    assert verifier.compare_payload(envelope, sources, listings, 'trend')[0] == key
    if change == 'dataset':
        envelope.dataset = 'kaipanla.volume.day'
    elif change == 'key':
        envelope.raw_payload['rows'][0]['code'] = '000002'
    elif change == 'content':
        envelope.raw_payload['rows'][0]['data']['trend'][0][1] += 1
    else:
        envelope.raw_payload['rows'][0]['lifecycle']['listing_date'] = '2000-01-01'
    with pytest.raises(ValueError):
        verifier.compare_payload(envelope, sources, listings, 'trend')


def test_strict_entry_keeps_random_and_all_known_failures(verifier):
    cli = importlib.import_module('verify_kaipanla')
    args = cli.parser().parse_args(['--test-mysql-settings', 'private.json', '--output', 'build/new.json'])
    assert args.random_count == 30
    assert args.fixed_days == ['2026-09-28', '2026-09-29', '2026-09-30']
    assert set(verifier.FIXED_CODES) == {'002731.SZ', '920112.BJ', '920175.BJ', '920304.BJ', '605333.SH'}


@pytest.mark.parametrize('change', ['source_gap', 'wrong_key', 'changed_content', 'no_unit'])
def test_thirty_pipeline_units_do_not_imply_thirty_successful_stocks(verifier, change):
    codes = [f'{number:06d}.SZ' for number in range(30)]
    units = [code + '/2026-09-30' for code in codes]
    values = {key: dict(digest='a' * 64, points=241) for key in units}
    result = dict(expected_units=units, source_units=copy.deepcopy(values),
                  query_units=copy.deepcopy(values), failures={})
    assert verifier.random_coverage(result, codes)['complete']
    if change == 'source_gap':
        result['failures'][units[0]] = {'type': 'SourceError'}
    elif change == 'wrong_key':
        result['query_units'][units[0] + 'wrong'] = result['query_units'].pop(units[0])
    elif change == 'changed_content':
        result['query_units'][units[0]]['digest'] = 'b' * 64
    else:
        result['expected_units'] = units[1:]
    assert not verifier.random_coverage(result, codes)['complete']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [asyncio.CancelledError(), RuntimeError('checkpoint failed')])
async def test_cancel_or_checkpoint_error_restores_observers_and_routing(verifier, failure):
    from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
    query = SimpleNamespace(plan=object(), suspension_plan=object())
    ingest = SimpleNamespace(checkpoint=AsyncMock(return_value={'revision': 0}), publish_page=object())
    collector = SimpleNamespace(query=query, ingest=ingest, job_key='kaipanla-trend-v1',
        execute=AsyncMock(side_effect=failure))
    if isinstance(failure, RuntimeError):
        ingest.checkpoint.side_effect = failure
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=lambda _: collector))
    before = (query.plan, query.suspension_plan, ingest.publish_page,
              verifier.download_module.consume, verifier.collector_module.attach_listing_dates)
    routing = USE_PROXY.get(), PROXY_FALLBACK.get(), ROUTE_COUNTS.get()
    with pytest.raises(type(failure)) as caught:
        await verifier.verify_kind(manager, 'trend', [{'unified_code': '000001.SZ', 'name': '样本'}],
                                   [date(2021, 1, 4)], [{'unified_code': '000002.SZ'}], True, {})
    assert caught.value is failure
    assert before == (query.plan, query.suspension_plan, ingest.publish_page,
                      verifier.download_module.consume, verifier.collector_module.attach_listing_dates)
    assert routing == (USE_PROXY.get(), PROXY_FALLBACK.get(), ROUTE_COUNTS.get())
