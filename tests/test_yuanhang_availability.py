"""Native absence is deferred only with a complete, exact prelisting response."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.yuanhang import availability
from empire.features.yuanhang import collector as module
from empire.sources import listing_scope
from empire.sources.yuanhang_history import IncompleteFinancialHistory
from empire.sources.yuanhang_wire import EmptyHistoryResponse
from tests.prefetch_source import prefetch_http
from tests.test_yuanhang_collector import collector


@pytest.mark.parametrize('financial', [False, True])
@pytest.mark.parametrize('mode', ['unlisted', 'future', 'listed', 'unknown', 'wrong_code', 'malformed', 'conflict'])
async def test_only_explicit_prelisting_can_defer_and_always_closes_metadata(monkeypatch, financial, mode):
    c = collector(monkeypatch)
    c.financial = financial
    c.query = SimpleNamespace(has_history=AsyncMock(return_value=mode == 'conflict'))
    today = datetime.now(listing_scope.CHINA).date()
    responses, calls = [], []
    async def request(method, url, **kwargs):
        calls.append(kwargs)
        row = dict(SECUCODE='001381.SZ', SECURITY_CODE='001381', LISTING_STATE='9', LISTING_DATE=None)
        if mode == 'future':
            row['LISTING_DATE'] = (today + timedelta(days=1)).isoformat() + ' 00:00:00'
        if mode == 'listed':
            row.update(LISTING_STATE='0', LISTING_DATE='2000-01-01 00:00:00')
        if mode == 'unknown':
            row['LISTING_STATE'] = '3'
        if mode == 'wrong_code':
            row.update(SECUCODE='001382.SZ', SECURITY_CODE='001382')
        payload = dict(success=True, result=dict(count=1, pages=1, data=[row]))
        if mode == 'malformed':
            payload['result']['count'] = 2
        response = httpx.Response(200, json=payload)
        responses.append(response)
        return response
    c.http = prefetch_http(request=request)
    monkeypatch.setattr(listing_scope, 'wait_for_capacity', AsyncMock())
    native = AsyncMock(side_effect=EmptyHistoryResponse(1, 211 if financial else 210))
    monkeypatch.setattr(module, 'fetch_history', native)
    lease = object()
    if mode in ('unlisted', 'future'):
        result = await c.fetch(('001381.SZ', 'node001', today.isoformat()), reservation=lease)
        assert isinstance(result, availability.DeferredSecurity)
        assert result.evidence()['status'] == 'deferred_prelisting'
        assert result.code == '001381.SZ'
    else:
        with pytest.raises(ValueError):
            await c.fetch(('001381.SZ', 'node001', today.isoformat()), reservation=lease)
    assert native.await_count == len(calls) == 1
    assert calls[0]['params']['filter'] == '(SECUCODE="001381.SZ")'
    assert calls[0]['reservation'] is lease
    assert all(r.is_closed for r in responses)
    assert c.identity.login.await_count == 1


async def test_valid_native_result_never_requests_listing_metadata(monkeypatch):
    c = collector(monkeypatch)
    monkeypatch.setattr(module, 'fetch_history', AsyncMock(return_value='native'))
    lookup = AsyncMock()
    monkeypatch.setattr(module, 'resolve_empty', lookup)
    assert await c.fetch(('001381.SZ', 'node001', '2026-10-23')) == 'native'
    lookup.assert_not_awaited()


@pytest.mark.parametrize('listed', [False, True])
async def test_validated_partial_capital_defers_only_before_listing(monkeypatch, listed):
    c = collector(monkeypatch)
    c.financial = True
    c.query = SimpleNamespace(has_history=AsyncMock(return_value=False))
    async def request(method, url, **kwargs):
        return httpx.Response(200, json=dict(success=True, result=dict(count=1, pages=1, data=[dict(
            SECUCODE='688827.SH', SECURITY_CODE='688827', LISTING_STATE='0' if listed else '9',
            LISTING_DATE='2025-01-01 00:00:00' if listed else None)])))
    c.http = prefetch_http(request=request)
    monkeypatch.setattr(listing_scope, 'wait_for_capacity', AsyncMock())
    monkeypatch.setattr(module, 'fetch_history', AsyncMock(side_effect=IncompleteFinancialHistory('688827.SH', date(2025, 6, 27))))
    if listed:
        with pytest.raises(IncompleteFinancialHistory):
            await c.fetch(('688827.SH', 'node001', '2026-10-23'))
    else:
        result = await c.fetch(('688827.SH', 'node001', '2026-10-23'))
        assert result.evidence()['native_status'] == 'partial_total_circulating'


async def test_arbitrary_parser_error_never_uses_listing_metadata(monkeypatch):
    c = collector(monkeypatch)
    c.financial = True
    monkeypatch.setattr(module, 'fetch_history', AsyncMock(side_effect=ValueError('bad wire')))
    lookup = AsyncMock()
    monkeypatch.setattr(module, 'resolve_empty', lookup)
    with pytest.raises(ValueError, match='bad wire'):
        await c.fetch(('688827.SH', 'node001', '2026-10-23'))
    lookup.assert_not_awaited()


@pytest.mark.parametrize('code', ['920085.BJ', '301718.SZ'])
@pytest.mark.parametrize('mode', ['initial', 'wrong_day', 'existing', 'empty', 'multiple'])
async def test_listed_initial_partial_capital_has_explicit_gap_only_with_exact_evidence(monkeypatch, code, mode):
    c = collector(monkeypatch)
    c.financial = True
    c.query = SimpleNamespace(has_history=AsyncMock(return_value=mode == 'existing'))
    response = httpx.Response(200, json=dict(success=True, result=dict(count=1, pages=1, data=[dict(
        SECUCODE=code, SECURITY_CODE=code[:6], LISTING_STATE='0', LISTING_DATE='2026-11-06 00:00:00') ])))
    c.http = prefetch_http(request=AsyncMock(return_value=response))
    monkeypatch.setattr(listing_scope, 'wait_for_capacity', AsyncMock())
    error = (EmptyHistoryResponse(1, 211) if mode == 'empty' else
             IncompleteFinancialHistory(code, date(2026, 11, 5 if mode == 'wrong_day' else 6),
                 first_source_date=date(2015, 12, 11) if mode == 'multiple' else None,
                 point_count=9 if mode == 'multiple' else 1))
    native = AsyncMock(side_effect=error)
    monkeypatch.setattr(module, 'fetch_history', native)
    if mode == 'initial':
        result = await c.fetch((code, 'node002', '2026-11-06'))
        proof = result.evidence()
        assert proof['status'] == 'deferred_initial_capital'
        assert proof['listing_date'] == proof['source_date'] == '2026-11-06'
        assert proof['missing_fields'] == [380] and proof['present_fields'] == [1, 402, 407]
        assert proof['node'] == 'node002'
    else:
        with pytest.raises(ValueError):
            await c.fetch((code, 'node002', '2026-11-06'))
    assert native.await_count == 1
    assert response.is_closed
    if isinstance(error, IncompleteFinancialHistory):
        assert error.yuanhang_diagnostics['node'] == 'node002'
        assert error.yuanhang_diagnostics['security'] == code
