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


async def test_failure_evidence_keeps_states_binding_and_safe_cause(timer, monkeypatch):
    import json

    from empire.features.yuanhang import node_diagnostics
    from empire.plugins.collection.records import RecordsPlugin

    monkeypatch.setattr(node_diagnostics, 'monotonic', lambda: timer[0])
    service = identity()
    service.get_profiles.return_value.update({n: SimpleNamespace(provisioned=True)
        for n in ['expired', 'cooling', 'bound', 'missing']})
    service.pool = SimpleNamespace(entries={
        'expired': SimpleNamespace(expires=-1, cooldown=0),
        'cooling': SimpleNamespace(expires=1000, cooldown=200),
        'bound': SimpleNamespace(expires=1000, cooldown=0)},
        error='credential must never be copied', refreshed_at=0, invalid=2)
    service.online_codes = lambda: {'bound'}
    cause = httpx.ProxyError('user:secret@host')
    cause.__cause__ = OSError(10061, 'secret connection string')
    detail = dict(security='000001.SZ', failures=[node_diagnostics.failure('cooling', cause, 2)])
    with pytest.raises(ValueError) as caught:
        await module.select_node(service, 'cooling', {'cooling': 1}, last_error=cause,
                                 required_node='cooling', diagnostics=detail)
    error = caught.value
    assert '最后失败节点：cooling' in str(error) and '限定节点：cooling' in str(error)
    stored = RecordsPlugin()._bounded_metadata(error.yuanhang_diagnostics)
    assert stored['wait_finished']['counts'] == dict(missing_directory=2, identity_not_ready=1,
        lease_expired=1, cooldown=1, excluded_by_binding=1)
    assert stored['wait_started']['directory_age_seconds'] == 0
    assert stored['wait_finished']['directory_age_seconds'] == 125
    assert stored['wait_finished']['directory_error'] is True
    assert 'errno=10061' in stored['failures'][0]['causes'][1]
    assert 'secret' not in json.dumps(stored) and 'credential' not in json.dumps(stored)


def test_large_directory_is_bounded_and_retains_target_nodes(monkeypatch):
    from empire.features.yuanhang import node_diagnostics
    from empire.plugins.collection.records import RecordsPlugin

    monkeypatch.setattr(node_diagnostics, 'monotonic', lambda: 0)
    profiles = {f'node{i:04}': SimpleNamespace(provisioned=True) for i in range(1000)}
    service = SimpleNamespace(pool=SimpleNamespace(entries={}))
    detail = node_diagnostics.snapshot(service, profiles, 'node0999', 'node0998')
    assert detail['counts'] == {'missing_directory': 1000}
    assert len(detail['nodes']) == 4 and detail['omitted_nodes'] == 996
    stored = RecordsPlugin()._bounded_metadata(dict(wait_started=detail, wait_finished=detail,
        failures=[node_diagnostics.failure('node0998', httpx.ProxyError('secret'), i) for i in range(5)]))
    assert stored['wait_finished']['nodes'][-1]['node'] == 'node0999'
    assert stored['failures'][-1]['attempt'] == 4
