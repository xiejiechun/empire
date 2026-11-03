import asyncio
from types import SimpleNamespace

import pytest
from test_yuanhang_profiles import Http, Protection, Settings

from empire.contracts.plugin import PluginContext
from empire.core.manager import Registry
from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY
from empire.sources import yuanhang_service as module
from empire.sources.yuanhang_profiles import ProfileRegistry
from empire.sources.yuanhang_service import IdentityService, YuanhangIdentityPlugin


def endpoint(code, ip='192.0.2.1'):
    return SimpleNamespace(code=code, expires=float('inf'), cooldown=0, exit_ip=ip)


class Source(Http):
    async def request(self, *args, **kwargs):
        assert USE_PROXY.get() and not PROXY_FALLBACK.get()
        code = kwargs['proxy_code']
        self.body = f'<response><ret code="0"/><item account="thsguest_{code}" passwd="secret"/></response>'.encode()
        return await super().request(*args, **kwargs)


def make_service():
    registry = ProfileRegistry(Settings(), Protection())
    pool = SimpleNamespace(entries={})
    return IdentityService(registry, pool, Source(None))


async def test_new_node_later_arrival_restart_ip_change_and_offline_retention():
    service = make_service()
    await service.reconcile()
    assert service.registry.settings.writes == 0 and not service.http.calls
    service.pool.entries['a'] = endpoint('a')
    await service.reconcile()
    original = await service.registry.load()
    service.pool.entries.clear()
    await service.reconcile()
    service.pool.entries.update(a=endpoint('a', '192.0.2.2'), b=endpoint('b'))
    restarted = IdentityService(service.registry, service.pool, service.http)
    await restarted.reconcile()
    assert restarted.profiles['a'] == original['a']
    assert len(service.http.calls) == 2
    assert {options['proxy_code'] for _, options in service.http.calls} == {'a', 'b'}
    assert len({p.identity.account for p in restarted.profiles.values()}) == 2
    writes = service.registry.settings.writes
    for _ in range(5):
        await restarted.reconcile()
    assert service.registry.settings.writes == writes and len(service.http.calls) == 2
    assert restarted.health()['states'] == {'ready': 2}


@pytest.mark.parametrize('body,state', [
    (b'<response><ret code="-2"/></response>', 'rejected'),
    (TimeoutError('secret in transport error'), 'unknown'),
])
async def test_denial_or_unknown_blocks_rest_of_batch_and_survives_restart(body, state):
    service = make_service()
    service.pool.entries = {c: endpoint(c) for c in ('a', 'b')}
    service.http = Http(body)
    await service.reconcile()
    assert len(service.http.calls) == 1
    assert service.health()['blocked_nodes'] == {'a': state}
    assert 'secret' not in str(service.health())
    restarted = IdentityService(service.registry, service.pool, service.http)
    restarted.pool.entries['c'] = endpoint('c')
    await restarted.reconcile()
    assert set(restarted.profiles) == {'a', 'b', 'c'}  # Discovery still works.
    assert len(service.http.calls) == 1 and restarted.health()['automatic_application_paused']


async def test_cancel_during_application_does_not_register_again_after_restart():
    service = make_service()
    service.pool.entries['a'] = endpoint('a')
    entered = asyncio.Event()

    async def request(*args, **kwargs):
        entered.set()
        await asyncio.Future()

    service.http.request = request
    task = asyncio.create_task(service.reconcile())
    await asyncio.wait_for(entered.wait(), 1)
    await service.close()
    assert task.cancelled() and not service.inflight
    restarted = IdentityService(service.registry, service.pool, Source(None))
    await restarted.reconcile()
    assert restarted.health()['blocked_nodes'] == {'a': 'requested'}
    assert not restarted.http.calls


async def test_concurrent_services_issue_only_one_application():
    service = make_service()
    service.pool.entries['a'] = endpoint('a')
    second = IdentityService(service.registry, service.pool, service.http)
    entered, release = asyncio.Event(), asyncio.Event()
    request = service.http.request

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await request(*args, **kwargs)

    service.http.request = delayed
    first = asyncio.create_task(service.reconcile())
    await asyncio.wait_for(entered.wait(), 1)
    await second.reconcile()
    assert second.health()['blocked_nodes'] == {'a': 'requested'}
    release.set()
    await first
    await service.reconcile()
    assert len(service.http.calls) == 1
    assert (await service.registry.load())['a'].provisioned


async def test_configuration_failure_never_sends_then_recovers(monkeypatch):
    service = make_service()
    service.pool.entries['a'] = endpoint('a')
    original = service.registry.ensure

    async def broken(codes):
        raise RuntimeError('sql password secret')

    monkeypatch.setattr(service.registry, 'ensure', broken)
    await service.reconcile()
    assert not service.http.calls and service.health()['automatic_application_paused']
    assert 'secret' not in str(service.health())
    monkeypatch.setattr(service.registry, 'ensure', original)
    service.next_reload = 0  # Retry after the short configuration-failure backoff.
    await service.reconcile()
    assert len(service.http.calls) == 1 and not service.health()['automatic_application_paused']


async def test_expired_and_cooling_nodes_not_registered():
    service = make_service()
    service.pool.entries = {c: endpoint(c) for c in ('expired', 'cooling')}
    service.pool.entries['expired'].expires = 0
    service.pool.entries['cooling'].cooldown = float('inf')
    await service.reconcile()
    assert not service.profiles and not service.http.calls


async def test_login_reuses_ready_profile_with_fixed_route_and_no_registration(monkeypatch):
    service = make_service()
    service.pool.entries['a'] = endpoint('a')
    await service.reconcile()
    calls = []

    async def login(http, profile, *, project_id):
        assert USE_PROXY.get() and not PROXY_FALLBACK.get()
        calls.append(profile)
        return SimpleNamespace(proxy_code=profile.code)

    monkeypatch.setattr(module, 'login_profile', login)
    before = service.registry.settings.writes
    assert (await service.login('a', project_id='fixture')).proxy_code == 'a'
    assert (await service.login('a', project_id='fixture')).proxy_code == 'a'
    assert len(calls) == 1 and len(service.http.calls) == 1
    assert before == service.registry.settings.writes
    with pytest.raises(ValueError, match='尚未就绪'):
        await service.login('missing', project_id='fixture')
    await service.close()
    with pytest.raises(RuntimeError, match='停止'):
        await service.login('a', project_id='fixture')


async def test_plugin_monitor_stop_restart_and_pure_declaration(monkeypatch):
    service = make_service()
    monkeypatch.setattr(module, 'ProfileRegistry', lambda *args: service.registry)
    registry = Registry()
    registry.values = {'mysql.store': None, 'redis.store': SimpleNamespace(prefix='fixture'),
                       'proxy.pool': service.pool, 'http.fetch': service.http, 'collection.records': None}
    plugin = YuanhangIdentityPlugin()
    assert plugin.service is None and plugin.monitor is None and not service.http.calls
    context = PluginContext(plugin.manifest.id, registry, sanitize_error=lambda v: str(v))
    capability = await plugin.start(context)
    assert 'yuanhang.identity' in capability
    await asyncio.sleep(0)
    assert not service.http.calls
    context.begin_stop()
    await plugin.stop()
    context.reap_finished()
    assert not context.tasks and not context.critical_failures and not plugin.health()


async def test_running_monitor_discovers_arrival_without_restart():
    service = make_service()
    task = asyncio.create_task(service.watch())
    try:
        await asyncio.sleep(0)
        service.pool.entries['a'] = endpoint('a')
        async with asyncio.timeout(7):
            while not service.profiles.get('a', SimpleNamespace(provisioned=False)).provisioned:
                await asyncio.sleep(.05)
        assert len(service.http.calls) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service.close()
