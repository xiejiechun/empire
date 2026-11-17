"""Required NULL uses one bounded retry budget and each node's own identity."""
import asyncio
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.yuanhang import collector as module
from empire.sources.yuanhang_history import MissingFinancialValue
from tests.test_yuanhang_collector import collector


def packet(code='300560.SZ', *, missing=False):
    values = {1: 20161101, 402: 70120000., 407: 17530000., 380: 16000000.,
              454: 0., 455: 0., 456: 0., 460: 0., 463: 0.}
    descriptors = b''.join(struct.pack('<IBBH', f, 4 if f == 1 else 3, 0, 4 if f == 1 else 8) for f in values)
    data = struct.pack('<i', values[1]) + b''.join(
        b'\xff' * 8 if missing and f == 402 else struct.pack('<d', value)
        for f, value in values.items() if f != 1)
    security = ('USHA' if code.endswith('.SH') else 'USZA') + code[:6]
    extra = struct.pack('<IBBH', 5, 1, 0, 11) + security.encode() + b'\0'
    table = b'hx1.0\0' + struct.pack('<iIHHI', 1, 22 + len(descriptors), len(data), len(values), len(extra))
    table += descriptors + data + extra
    body = struct.pack('<I', len(table)) + table
    return struct.pack('<HiIHiB', 17, 1, 211, 1, len(body), 1) + body


async def test_null_rotates_three_ready_nodes_and_only_accepts_whole_valid_snapshot(monkeypatch):
    c = collector(monkeypatch)
    c.financial, c.request_retries = True, 3
    c.identity.get_profiles.return_value['node003'] = SimpleNamespace(provisioned=True)
    c.identity.online_codes = lambda: {'node001', 'node002', 'node003'}
    value = object()
    fetch = AsyncMock(side_effect=[MissingFinancialValue(402, 20161101, '300560.SZ'),
        MissingFinancialValue(380, 20161101, '300560.SZ'), value])
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('300560.SZ', 'node001', '2026-11-11')) is value
    assert [call.args[1].proxy_code for call in fetch.await_args_list] == ['node001', 'node002', 'node003']
    assert [call.kwargs['fresh_connection'] for call in fetch.await_args_list] == [False, True, True]
    assert c.stats['financial_null_retries'] == 2


async def test_one_ready_node_can_reconnect_until_configured_budget(monkeypatch):
    c = collector(monkeypatch)
    c.financial, c.request_retries = True, 30
    c.identity.online_codes = lambda: {'node001'}
    fetch = AsyncMock(side_effect=MissingFinancialValue(402, 20161101, '300560.SZ'))
    monkeypatch.setattr(module, 'fetch_history', fetch)
    with pytest.raises(MissingFinancialValue) as caught:
        await c.fetch(('300560.SZ', 'node001', '2026-11-11'))
    assert fetch.await_count == 31 and c.stats['financial_null_retries'] == 30
    assert all(call.args[1].proxy_code == 'node001' for call in fetch.await_args_list)
    assert caught.value.yuanhang_diagnostics['remaining_retries'] == 0
    assert len(caught.value.yuanhang_diagnostics['null_observations']) == 5


async def test_transport_after_null_does_not_pin_retry_to_failed_node(monkeypatch):
    c = collector(monkeypatch)
    c.financial, c.request_retries = True, 2
    fetch = AsyncMock(side_effect=[MissingFinancialValue(402, 20161101, '300560.SZ'),
        httpx.ProxyError('fixture'), 'valid'])
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('300560.SZ', 'node001', '2026-11-11')) == 'valid'
    assert [call.args[1].proxy_code for call in fetch.await_args_list] == ['node001', 'node002', 'node001']
    assert c.stats['financial_null_retries'] == c.stats['node_transport_retries'] == 1


async def test_null_can_recover_on_last_allowed_attempt(monkeypatch):
    c = collector(monkeypatch)
    c.financial, c.request_retries = True, 30
    fetch = AsyncMock(side_effect=[MissingFinancialValue(402, 20161101, '300560.SZ') for _ in range(30)] + ['valid'])
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('300560.SZ', 'node001', '2026-11-11')) == 'valid'
    assert fetch.await_count == 31 and c.stats['financial_null_retries'] == 30


async def test_null_retry_uses_updated_online_directory(monkeypatch):
    c = collector(monkeypatch)
    c.financial = True
    async def fetch(http, session, **kwargs):
        if session.proxy_code == 'node001':
            c.identity.online_codes = lambda: {'node002'}
            raise MissingFinancialValue(402, 20161101, '300560.SZ')
        return 'valid'
    monkeypatch.setattr(module, 'fetch_history', fetch)
    assert await c.fetch(('300560.SZ', 'node001', '2026-11-11')) == 'valid'
    assert [call.args[0] for call in c.identity.login.await_args_list] == ['node001', 'node002']


async def test_null_retry_preserves_cancellation(monkeypatch):
    c = collector(monkeypatch)
    c.financial = True
    async def fetch(http, session, **kwargs):
        c.identity.online_codes = lambda: {'node002'}
        raise MissingFinancialValue(402, 20161101, '300560.SZ')
    wire = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(module, 'fetch_history', wire)
    async def cancel(_):
        raise asyncio.CancelledError
    monkeypatch.setattr(module.asyncio, 'sleep', cancel)
    with pytest.raises(asyncio.CancelledError):
        await c.fetch(('300560.SZ', 'node001', '2026-11-11'))
    assert wire.await_count == 1
