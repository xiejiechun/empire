from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.yuanhang import collector as module
from empire.plugins.infra.sensitive_request import SensitiveRequestError
from empire.sources.yuanhang_auth import AuthenticationError


def collector(monkeypatch):
    c = module.YuanhangCollector()
    c.http, c.ingest = object(), object()
    c.identity = SimpleNamespace(
        registry=SimpleNamespace(load=AsyncMock(return_value={
            n: SimpleNamespace(provisioned=True) for n in ('node001', 'node002')})),
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
    assert fetch.await_count == c.identity.login.await_count == 1


@pytest.mark.parametrize('failure', [httpx.ConnectError('fixture'), TimeoutError('fixture')])
async def test_sensitive_transport_failure_can_retry_without_carrying_credentials(monkeypatch, failure):
    c = collector(monkeypatch)
    c.identity.login.side_effect = [SensitiveRequestError(failure), SimpleNamespace(proxy_code='node002')]
    fetch = AsyncMock(return_value='snapshot')
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('000001.SZ', 'node001', '2026-10-23')) == 'snapshot'
    assert fetch.await_args.args[1].proxy_code == 'node002'
    assert set(c.sessions) == {'node002'}


async def test_offline_preferred_node_not_used_and_missing_identity_not_borrowed(monkeypatch):
    c = collector(monkeypatch)
    c.identity.online_codes = lambda: {'node002'}
    monkeypatch.setattr(module, 'fetch_history', AsyncMock(return_value='snapshot'))
    await c.fetch(('000001.SZ', 'node001', '2026-10-23'))
    assert c.identity.login.await_args.args[0] == 'node002'
    c.identity.registry.load.return_value = {}
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
