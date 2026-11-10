from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from empire.sources import yuanhang_client as client
from empire.sources.yuanhang_auth import AuthenticationError
from empire.sources.yuanhang_wire import EmptyHistoryResponse

BOUNDS = dict(unified_code='605336.SH', dataset='daily', start=date(1990, 1, 1), end=date(2026, 10, 23))


async def test_empty_primary_resolves_risk_market_and_next_request_reuses_hint(monkeypatch):
    calls = []
    async def fetch(http, session, **kwargs):
        calls.append(kwargs)
        if kwargs['native_market'] == 'USHA':
            raise EmptyHistoryResponse(1, 210)
        return ('fixture',)
    monkeypatch.setattr(client, '_fetch_market', fetch)
    begin = datetime.now(UTC)
    result = await client.fetch_history(None, SimpleNamespace(proxy_code='node002'), **BOUNDS)
    assert result.native_market == 'USHT' and result.data == ('fixture',)
    assert begin <= result.observed_at <= datetime.now(UTC)
    assert [c['native_market'] for c in calls] == ['USHA', 'USHT']
    calls.clear()
    await client.fetch_history(None, SimpleNamespace(proxy_code='node002'), native_market=result.native_market, **BOUNDS)
    assert [c['native_market'] for c in calls] == ['USHT']


@pytest.mark.parametrize('error', [AuthenticationError('native-login', -1), ValueError('bad table'), TimeoutError()])
async def test_failure_never_turns_into_market_switch_or_empty_success(monkeypatch, error):
    calls = []
    async def fetch(*args, **kwargs):
        calls.append(kwargs['native_market'])
        raise error
    monkeypatch.setattr(client, '_fetch_market', fetch)
    with pytest.raises(type(error)):
        await client.fetch_history(None, SimpleNamespace(proxy_code='node002'), **BOUNDS)
    assert calls == ['USHA']


async def test_two_empty_markets_remain_unknown_and_unbound_identity_never_requests(monkeypatch):
    calls = []
    async def fetch(*args, **kwargs):
        calls.append(kwargs['native_market'])
        raise EmptyHistoryResponse(1, 210)
    monkeypatch.setattr(client, '_fetch_market', fetch)
    with pytest.raises(ValueError, match='绑定'):
        await client.fetch_history(None, SimpleNamespace(proxy_code=None), **BOUNDS)
    assert not calls
    with pytest.raises(EmptyHistoryResponse):
        await client.fetch_history(None, SimpleNamespace(proxy_code='node002'), **BOUNDS)
    assert calls == ['USHA', 'USHT']

@pytest.mark.parametrize('special', ['empty', 'incomplete', 'invalid', 'null'])
async def test_native_validation_context_preserves_availability_types_and_closes(monkeypatch, special):
    from unittest.mock import AsyncMock, Mock

    from empire.sources.yuanhang_history import IncompleteFinancialHistory, MissingFinancialValue
    error = {'empty': EmptyHistoryResponse(1, 211), 'incomplete': IncompleteFinancialHistory('300645.SZ', date(2026, 11, 5)),
             'null': MissingFinancialValue(402, 20261105, '300645.SZ'),
             'invalid': ValueError('Nonfinite HX double; field=407, date=20261028')}[special]
    response = SimpleNamespace(content=b'fixture', close=Mock(), reserve_decoded=Mock())
    http = SimpleNamespace(response_policy=lambda _: SimpleNamespace(max_body_bytes=1048576),
                           request_stream=AsyncMock(return_value=response))
    monkeypatch.setattr(client, 'decode_response', Mock(side_effect=error))
    with pytest.raises(type(error)) as caught:
        await client._fetch_market(http, SimpleNamespace(servers=['fixture'], proxy_code='node001'),
            unified_code='300645.SZ', dataset='financial', start=date(1900, 1, 1),
            end=date(2100, 12, 31), instance=1, max_retries=0, native_market='USZA', reservation=None)
    if special == 'invalid':
        assert '300645.SZ/financial/USZA' in str(caught.value)
        assert 'field=407' in str(caught.value)
    else:
        assert caught.value is error
    response.close.assert_called_once()
    http.request_stream.assert_awaited_once()


async def test_financial_null_keeps_bounded_business_evidence_and_fresh_flag(monkeypatch):
    import hashlib
    from unittest.mock import AsyncMock, Mock

    from empire.sources.yuanhang_history import MissingFinancialValue

    tables = [dict(version='hx1.0', row_count=1, decoded_bytes=42,
        fields=[(1, 4, 0, 4), (402, 3, 0, 8)], rows=[{1: 20190802, 402: None}])]
    response = SimpleNamespace(content=b'business frame', close=Mock(), reserve_decoded=Mock())
    http = SimpleNamespace(response_policy=lambda _: SimpleNamespace(max_body_bytes=1048576),
                           request_stream=AsyncMock(return_value=response))
    monkeypatch.setattr(client, 'decode_response', Mock(return_value=tables))
    monkeypatch.setattr(client, 'normalize_financial', Mock(side_effect=MissingFinancialValue(402, 20190802, '002966.SZ')))
    with pytest.raises(MissingFinancialValue) as caught:
        await client._fetch_market(http, SimpleNamespace(servers=['secret endpoint'], proxy_code='node001'),
            unified_code='002966.SZ', dataset='financial', start=date(1900, 1, 1), end=date(2100, 12, 31),
            instance=1, max_retries=0, native_market='USZA', reservation=None, fresh_connection=True)
    proof = caught.value.yuanhang_diagnostics
    assert proof['response_sha256'] == hashlib.sha256(response.content).hexdigest()
    assert proof['null_tables'] == [dict(version='hx1.0', row_count=1,
        descriptor=[402, 3, 0, 8], null_dates=[20190802])]
    assert proof['fresh_connection'] and proof['node'] == 'node001'
    assert 'secret' not in str(proof) and 'business frame' not in str(proof)
    assert http.request_stream.await_args.kwargs['fresh_connection'] is True
    response.close.assert_called_once()
