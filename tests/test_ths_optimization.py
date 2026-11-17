"""Costs and completeness at the ordinary THS maintenance boundaries."""
import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.holders import source as holders
from empire.features.industries.staging import IndustryStage
from tests.prefetch_source import prefetch_http
from tests.test_all_collector_prefetch import adapter
from tests.test_ths_capital_lifecycle import configured
from tests.test_ths_holders import STOCK, source
from tests.test_ths_industries import SNAPSHOT


def test_holder_tree_built_once_with_identical_reports(monkeypatch):
    expected = {k: holders.parse(source(), k, STOCK) for k in holders.KINDS}
    original, calls = holders.Document, []
    def document(body):
        calls.append(1)
        return original(body)
    monkeypatch.setattr(holders, 'Document', document)
    assert holders.parse_all(source().encode('gb18030'), STOCK) == expected
    assert len(calls) == 1


@pytest.mark.parametrize('family', ['income', 'balance', 'cashflow', 'capital'])
async def test_security_due_selection_reuses_confirmed_and_refreshes_due(family):
    c = configured() if family == 'capital' else adapter(family)[0]
    if family != 'capital':
        c.http = prefetch_http()
    stocks = await c.query.securities()
    keys = [s['unified_code'] if family == 'capital' else s['market'] + ':' + s['code'] for s in stocks]
    c.query.collection_units.return_value = {key: dict(stamp=datetime.now(UTC), count=1, digest='a' * 64) for key in keys}
    c.fetch = AsyncMock(side_effect=AssertionError('unnecessary request'))
    result = await c.execute()
    assert result['phase'] == 'complete' and not c.fetch.called
    assert c.stats['reused_units'] == len(keys)
    c.query.collection_units.return_value[keys[-1]]['stamp'] -= timedelta(days=2)
    with pytest.raises(AssertionError, match='unnecessary request'):
        await c.execute(baseline_revision=await c.checkpoint_revision())
    assert c.fetch.await_count == 1


def test_industry_stage_expiry_scope_and_copy_boundary():
    stage, now = IndustryStage(), datetime.now(UTC)
    catalog = [{k: v for k, v in r.items() if k != 'members'} for r in SNAPSHOT]
    stage.begin(catalog, now)
    stage.put(SNAPSHOT[0])
    stage.get(SNAPSHOT[0]['code']).clear()
    assert stage.get(SNAPSHOT[0]['code']) == SNAPSHOT[0]['members']
    stage.begin(catalog, now + timedelta(minutes=29))
    assert stage.units
    stage.begin(catalog, now + timedelta(minutes=31))
    assert not stage.units
    stage.put(SNAPSHOT[0])
    changed = copy.deepcopy(catalog)
    changed[0]['name'] = '其他行业'
    stage.begin(changed, now + timedelta(minutes=32))
    assert not stage.units


async def test_listing_empty_round_has_no_queue_or_confirmation():
    from empire.features.listings.contract import digest
    from tests.test_ths_listings import STOCKS, collector
    c, state = collector()
    keys = [s['market'] + ':' + s['code'] for s in STOCKS]
    c.query.plan.return_value = (STOCKS, set(keys), dict(scope_hash=digest(keys), units=len(keys),
        refresh_started_at=datetime.now(UTC).isoformat()))
    c.ingest.publish_page = AsyncMock(side_effect=AssertionError('empty queue publication'))
    await c.execute()
    assert state['cursor']['phase'] == 'complete'
    assert not c.fetch.called and not c.confirmation.page_status.called


async def test_industry_failure_reuses_successful_members_without_partial_publish():
    c, reply = adapter('industries')
    failing = True
    requested = []
    async def request(method, url, **kwargs):
        index, response = reply(method, url, kwargs)
        requested.append(index)
        if failing and index == 2:
            return httpx.Response(200, content=b'broken')
        return response
    c.http = prefetch_http(request=AsyncMock(side_effect=request))
    with pytest.raises(ValueError):
        await c.execute()
    assert not c.ingest.events and len(c.staging.units) == 2
    assert not c.confirmation.page_status.called
    failing = False
    await c.execute()
    assert requested == [None, 0, 1, 2, None, 2]
    assert len(c.ingest.events) == 1 and not c.staging.units
    assert c.http.buffer_budget.used == 0
