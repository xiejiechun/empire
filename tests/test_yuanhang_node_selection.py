import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.yuanhang import node_selection as module
from empire.sources.yuanhang_service import IdentityService


def identity():
    return SimpleNamespace(get_profiles=AsyncMock(return_value={
        'one': SimpleNamespace(provisioned=True),
        'two': SimpleNamespace(provisioned=False)}), online_codes=lambda: set())


@pytest.fixture
def timer(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(module, 'monotonic', lambda: clock[0])
    async def sleep(seconds):
        clock[0] += seconds
    monkeypatch.setattr(module, 'sleep', sleep)
    return clock


async def test_cooldown_recovers_without_using_unprovisioned_online_identity(timer):
    service = identity()
    service.online_codes = lambda: {'two'} | ({'one'} if timer[0] >= 120 else set())
    assert await module.select_node(service, 'two', {'one': 1}) == 'one'
    assert timer[0] == 120


async def test_timeout_retains_cause_without_exposing_transport_credentials(timer):
    cause = httpx.ProxyError('user:secret@host')
    with pytest.raises(ValueError, match='125秒') as caught:
        await module.select_node(identity(), 'one', {}, last_error=cause)
    assert caught.value.__cause__ is cause
    assert 'ProxyError' in str(caught.value) and 'secret' not in str(caught.value)
    assert timer[0] == 125


async def test_cancel_wait_is_not_retried(monkeypatch):
    sleeping = asyncio.Event()
    async def sleep(seconds):
        sleeping.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(module, 'sleep', sleep)
    service = identity()
    task = asyncio.create_task(module.select_node(service, 'one', {}))
    await sleeping.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert service.get_profiles.await_count == 1


async def test_wait_uses_shared_snapshot_without_sql_reload_each_second(timer, monkeypatch):
    from empire.sources import yuanhang_service
    monkeypatch.setattr(yuanhang_service, 'monotonic', lambda: timer[0])
    registry = SimpleNamespace(load=AsyncMock(return_value={'one': SimpleNamespace(provisioned=True)}))
    service = IdentityService(registry, SimpleNamespace(entries={}), None)
    service.sessions.prune = lambda profiles: None
    with pytest.raises(ValueError, match='125秒'):
        await module.select_node(service, 'one', {})
    assert registry.load.await_count == 3  # t=0,60,120; no refresh on each poll


async def test_confirmation_does_not_switch_to_other_healthy_node(timer):
    service = identity()
    service.get_profiles.return_value['two'].provisioned = True
    service.online_codes = lambda: {'two'} | ({'one'} if timer[0] >= 10 else set())
    assert await module.select_node(service, 'two', {'one': 5}, required_node='one') == 'one'
    assert timer[0] == 10
