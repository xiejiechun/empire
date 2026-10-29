import asyncio
import json
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from empire.core.protected_values import WindowsProtection
from empire.sources.yuanhang_auth import AuthenticationError
from empire.sources.yuanhang_client import provision_guest
from empire.sources.yuanhang_identity import GuestIdentity
from empire.sources.yuanhang_profiles import ProfileRegistry


class Settings:
    namespace = 'test-yuanhang-profiles'

    def __init__(self):
        self.data, self.writes, self.lock = None, 0, asyncio.Lock()

    async def load(self, kind):
        return {} if self.data is None else {'guest-profiles': json.loads(json.dumps(self.data))}

    async def mutate(self, kind, key, transform):
        async with self.lock:
            updated = transform(json.loads(json.dumps(self.data)))
            if updated != self.data:
                self.writes += 1
                self.data = json.loads(json.dumps(updated))
            return updated


class Protection:
    def seal(self, value, context):
        return AESGCM(b'x' * 32).encrypt(b'0' * 12, value, context)

    def open(self, value, context):
        try:
            return AESGCM(b'x' * 32).decrypt(b'0' * 12, value, context)
        except Exception:
            raise ValueError('fixture protection failed') from None


async def test_nodes_keep_distinct_persisted_logical_identities_across_restart_and_offline():
    settings = Settings()
    first = await ProfileRegistry(settings, Protection()).ensure(['node1', 'node2'])
    assert len({p.profile_id for p in first.values()}) == len({p.device.mac for p in first.values()}) == 2
    assert all(p.device.mac.startswith('02-') and not p.provisioned for p in first.values())
    second = await ProfileRegistry(settings, Protection()).ensure(['node2'])
    assert first == second and settings.writes == 1  # Offline node1 retained.
    assert await ProfileRegistry(settings, Protection()).load() == first


async def test_bind_is_idempotent_encrypted_and_cannot_reuse_account_or_swap_profile():
    settings, protect = Settings(), Protection()
    registry = ProfileRegistry(settings, protect)
    profiles = await registry.ensure(['node1', 'node2'])
    identity = GuestIdentity('thsguest_fixture1', 'fixture-secret')
    bound = await registry.bind('node1', identity, profiles['node1'].device)
    assert bound.provisioned and bound.profile_id == profiles['node1'].profile_id
    assert 'fixture-secret' not in json.dumps(settings.data) and 'thsguest_' not in json.dumps(settings.data)
    assert await registry.bind('node1', identity, profiles['node1'].device) == bound
    assert settings.writes == 2
    with pytest.raises(ValueError, match='多个节点'):
        await registry.bind('node2', identity, profiles['node2'].device)
    with pytest.raises(ValueError, match='替换'):
        await registry.bind('node1', GuestIdentity('thsguest_new', 'new-secret'), profiles['node1'].device)
    settings.data['profiles']['node2'] = {**settings.data['profiles']['node2'], 'registration': 'ready',
                                        'protected': settings.data['profiles']['node1']['protected']}
    with pytest.raises(ValueError, match='损坏'):
        await registry.load()


async def test_concurrent_allocations_preserve_union_and_no_identity_rotation():
    settings = Settings()
    first, second = ProfileRegistry(settings, Protection()), ProfileRegistry(settings, Protection())
    await asyncio.gather(first.ensure(['a', 'b']), second.ensure(['b', 'c']))
    assert set(await first.load()) == {'a', 'b', 'c'}
    before = await first.load()
    await second.ensure(['a', 'b', 'c'])
    assert before == await second.load() and settings.writes == 2


class Http:
    def __init__(self, body):
        self.body, self.calls, self.closed = body, [], False

    async def request(self, *args, **options):
        self.calls.append((args, options))
        if isinstance(self.body, BaseException):
            raise self.body
        self.content = self.body
        return self

    def close(self):
        self.closed = True


async def test_initial_application_is_once_then_reuses_saved_account():
    registry = ProfileRegistry(Settings(), Protection())
    await registry.ensure(['node1'])
    http = Http(b'<response><ret code="0"/><item account="thsguest_fixture" passwd="secret"/></response>')
    bound = await provision_guest(http, registry, 'node1', project_id='test')
    assert bound.provisioned and http.closed
    assert http.calls[0][1]['proxy_code'] == 'node1' and http.calls[0][1]['sensitive']
    assert http.calls[0][1]['max_retries'] == 0
    assert await provision_guest(http, registry, 'node1', project_id='test') == bound
    assert len(http.calls) == 1


@pytest.mark.parametrize('body,state', [
    (b'<response><ret code="-2">rejected</ret></response>', 'rejected'),
    (TimeoutError('transport'), 'unknown'),
    (asyncio.CancelledError(), 'requested'),
])
async def test_refusal_unknown_or_cancelled_request_never_registers_again(body, state):
    registry = ProfileRegistry(Settings(), Protection())
    original = (await registry.ensure(['node1']))['node1']
    http = Http(body)
    with pytest.raises((AuthenticationError, TimeoutError, asyncio.CancelledError)):
        await provision_guest(http, registry, 'node1', project_id='test')
    saved = (await registry.load())['node1']
    assert saved.registration == state and saved.profile_id == original.profile_id
    with pytest.raises(ValueError, match='不重复'):
        await provision_guest(http, registry, 'node1', project_id='test')
    assert len(http.calls) == 1


@pytest.mark.skipif(os.name != 'nt', reason='DPAPI is a Windows current-user contract')
def test_real_windows_dpapi_roundtrip_and_context_binding():
    protector = WindowsProtection()
    sealed = protector.seal(b'fixture-secret', b'namespace:node1:profile1')
    assert b'fixture-secret' not in sealed
    assert WindowsProtection().open(sealed, b'namespace:node1:profile1') == b'fixture-secret'
    with pytest.raises(ValueError, match='保护失败'):
        protector.open(sealed, b'namespace:node2:profile1')
