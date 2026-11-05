from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.yuanhang import collector as module
from empire.plugins.infra.sensitive_request import SensitiveRequestError
from empire.sources.yuanhang_auth import AuthenticationError, IdleConnectionError
from empire.sources.yuanhang_history import MissingFinancialValue
from empire.sources.yuanhang_sessions import NodeSessions


def collector(monkeypatch):
    c = module.YuanhangCollector()
    c.http, c.ingest = object(), object()
    c.identity = SimpleNamespace(
        sessions=NodeSessions(),
        get_profiles=AsyncMock(return_value={
            n: SimpleNamespace(provisioned=True) for n in ('node001', 'node002')}),
        online_codes=lambda: {'node001', 'node002'},
        login=AsyncMock(side_effect=lambda node, **kw: SimpleNamespace(proxy_code=node)))
    monkeypatch.setattr(module, 'wait_for_capacity', AsyncMock())
    monkeypatch.setattr(module, 'retry_delay', lambda n: 0)
    return c


async def test_node_failure_uses_other_nodes_own_account_and_one_retry_budget(monkeypatch):
    c = collector(monkeypatch)
    calls = []
    async def fetch(http, session, **kwargs):
        calls.append((session.proxy_code, kwargs['max_retries'], kwargs['reservation']))
        if session.proxy_code == 'node001':
            raise httpx.ProxyError('fixture')
        return 'snapshot'
    monkeypatch.setattr(module, 'fetch_history', fetch)
    lease = object()
    assert await c.fetch(('000001.SZ', 'node001', '2026-10-23'), reservation=lease) == 'snapshot'
    assert calls == [('node001', 0, lease), ('node002', 0, lease)]
    assert [x.args[0] for x in c.identity.login.await_args_list] == ['node001', 'node002']
    assert c.stats['node_transport_retries'] == 1


@pytest.mark.parametrize('error', [AuthenticationError('native-login', -1), ValueError('bad frame'),
                                   SensitiveRequestError(ValueError('bad auth response'))])
async def test_protocol_or_authentication_error_never_switches_identity(monkeypatch, error):
    c = collector(monkeypatch)
    fetch = AsyncMock(side_effect=error)
    monkeypatch.setattr(module, 'fetch_history', fetch)
    with pytest.raises(type(error)):
        await c.fetch(('000001.SZ', 'node001', '2026-10-23'))
    expected = 2 if isinstance(error, AuthenticationError) else 1
    assert fetch.await_count == c.identity.login.await_count == expected
    assert {call.args[0] for call in c.identity.login.await_args_list} == {'node001'}


@pytest.mark.parametrize('failure', [httpx.ConnectError('fixture'), TimeoutError('fixture')])
async def test_sensitive_transport_failure_can_retry_without_carrying_credentials(monkeypatch, failure):
    c = collector(monkeypatch)
    c.identity.login.side_effect = [SensitiveRequestError(failure), SimpleNamespace(proxy_code='node002')]
    fetch = AsyncMock(return_value='snapshot')
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('000001.SZ', 'node001', '2026-10-23')) == 'snapshot'
    assert fetch.await_args.args[1].proxy_code == 'node002'
    assert not hasattr(c, 'sessions')


async def test_offline_preferred_node_not_used_and_missing_identity_not_borrowed(monkeypatch):
    c = collector(monkeypatch)
    c.identity.online_codes = lambda: {'node002'}
    monkeypatch.setattr(module, 'fetch_history', AsyncMock(return_value='snapshot'))
    await c.fetch(('000001.SZ', 'node001', '2026-10-23'))
    assert c.identity.login.await_args.args[0] == 'node002'
    c.identity.get_profiles.return_value = {}
    with pytest.raises(ValueError, match='健康身份'):
        await c.fetch(('000001.SZ', 'node001', '2026-10-23'))


def test_sensitive_exception_only_exposes_transport_classification():
    error = SensitiveRequestError(httpx.ProxyError('password=secret'))
    assert error.retryable_transport
    assert 'secret' not in str(error)
    assert not SensitiveRequestError(ValueError('secret')).retryable_transport


@pytest.mark.parametrize('budget,expected', [(0, 1), (1, 2)])
async def test_native_timeout_uses_same_node_retry_budget(monkeypatch, budget, expected):
    c = collector(monkeypatch)
    c.request_retries = budget
    fetch = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(module, 'fetch_history', fetch)
    with pytest.raises(TimeoutError):
        await c.fetch(('000001.SZ', 'node001', '2026-10-23'))
    assert fetch.await_count == expected
    assert len(c.identity.login.await_args_list) == expected


@pytest.mark.parametrize('financial', [False, True])
async def test_idle_backlog_reconnects_same_node_without_refreshing_identity(monkeypatch, financial):
    c = collector(monkeypatch)
    c.financial = financial
    fetch = AsyncMock(side_effect=[IdleConnectionError(), 'snapshot'])
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('000001.SZ', 'node001', '2026-10-30')) == 'snapshot'
    assert fetch.await_count == 2
    assert all(call.kwargs['max_retries'] == 0 for call in fetch.await_args_list)
    assert all(call.kwargs['dataset'] == ('financial' if financial else 'daily')
               for call in fetch.await_args_list)
    assert [call.args[0] for call in c.identity.login.await_args_list] == ['node001', 'node001']
    assert all('rejected' not in call.kwargs for call in c.identity.login.await_args_list)
    assert c.stats['idle_connection_retries'] == 1
    assert c.stats.get('node_transport_retries', 0) == 0


@pytest.mark.parametrize('budget', [0, 1, 30])
async def test_idle_backlog_exhausts_original_budget(monkeypatch, budget):
    c = collector(monkeypatch)
    c.request_retries = budget
    fetch = AsyncMock(side_effect=IdleConnectionError())
    monkeypatch.setattr(module, 'fetch_history', fetch)
    with pytest.raises(IdleConnectionError):
        await c.fetch(('000001.SZ', 'node001', '2026-10-30'))
    assert fetch.await_count == budget + 1
    assert {call.args[0] for call in c.identity.login.await_args_list} == {'node001'}
    assert c.stats.get('idle_connection_retries', 0) == budget


async def test_idle_and_transport_failures_share_one_retry_budget(monkeypatch):
    c = collector(monkeypatch)
    c.request_retries = 2
    fetch = AsyncMock(side_effect=[IdleConnectionError(), httpx.ProxyError('fixture'), 'snapshot'])
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('000001.SZ', 'node001', '2026-10-30')) == 'snapshot'
    assert fetch.await_count == 3
    assert [call.args[0] for call in c.identity.login.await_args_list] == ['node001', 'node001', 'node002']


@pytest.mark.parametrize('financial', [False, True])
@pytest.mark.parametrize('budget', [0, 1, 30])
async def test_single_recovered_node_uses_entire_transport_budget(monkeypatch, financial, budget):
    c = collector(monkeypatch)
    c.financial, c.request_retries = financial, budget
    c.identity.online_codes = lambda: {'node001'}
    fetch = AsyncMock(side_effect=httpx.ProxyError('fixture'))
    monkeypatch.setattr(module, 'fetch_history', fetch)
    with pytest.raises(httpx.ProxyError, match='fixture'):
        await c.fetch(('000001.SZ', 'node001', '2026-11-03'))
    assert fetch.await_count == budget + 1
    assert {call.args[0] for call in c.identity.login.await_args_list} == {'node001'}


async def test_all_nodes_failed_once_can_recover_with_remaining_budget(monkeypatch):
    c = collector(monkeypatch)
    fetch = AsyncMock(side_effect=[httpx.ProxyError('one'), httpx.ProxyError('two'), 'snapshot'])
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('000001.SZ', 'node001', '2026-11-03')) == 'snapshot'
    assert [call.args[0] for call in c.identity.login.await_args_list] == ['node001', 'node002', 'node001']


async def test_financial_null_confirms_once_on_same_node_without_merging(monkeypatch):
    c = collector(monkeypatch)
    c.financial = True
    fetch = AsyncMock(side_effect=[MissingFinancialValue(402, 20261105, '002346.SZ'), 'complete'])
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('002346.SZ', 'node001', '2026-11-05')) == 'complete'
    assert [call.args[0] for call in c.identity.login.await_args_list] == ['node001', 'node001']
    assert c.stats['financial_null_confirmations'] == 1


@pytest.mark.parametrize('budget,expected', [(0, 1), (1, 2), (30, 2)])
async def test_persistent_null_is_not_retried_until_accidentally_valid(monkeypatch, budget, expected):
    c = collector(monkeypatch)
    c.financial, c.request_retries = True, budget
    fetch = AsyncMock(side_effect=MissingFinancialValue(460, 20261105, '603303.SH'))
    monkeypatch.setattr(module, 'fetch_history', fetch)
    with pytest.raises(MissingFinancialValue, match='field=460, date=20261105'):
        await c.fetch(('603303.SH', 'node001', '2026-11-05'))
    assert fetch.await_count == expected


async def test_null_confirmation_uses_remaining_transport_budget_and_current_node(monkeypatch):
    c = collector(monkeypatch)
    c.financial = True
    fetch = AsyncMock(side_effect=[httpx.ProxyError('fixture'),
        MissingFinancialValue(402, 20261105, '002346.SZ'), 'complete'])
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('002346.SZ', 'node001', '2026-11-05')) == 'complete'
    assert [call.args[0] for call in c.identity.login.await_args_list] == ['node001', 'node002', 'node002']
