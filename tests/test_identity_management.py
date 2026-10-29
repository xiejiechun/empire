import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from test_yuanhang_profiles import Protection, Settings
from test_yuanhang_service import endpoint, make_service

from empire.plugins.collection.identities import IdentityQueries
from empire.plugins.collection.identity_runs import IdentityRuns
from empire.sources import yuanhang_recipe
from empire.sources.yuanhang_identity import GuestIdentity
from empire.sources.yuanhang_management import YuanhangManagement
from empire.sources.yuanhang_profiles import ProfileRegistry
from scripts.migrate_yuanhang_profiles import upgrade


class Records:
    def __init__(self):
        self.data = {}

    async def add_identity_run(self, platform, row):
        old = self.data.setdefault(platform, [])
        self.data[platform] = [copy.deepcopy(row), *[r for r in old if r['id'] != row['id']]][:100]

    async def list_identity_runs(self, platform):
        return copy.deepcopy(self.data.get(platform, []))


def adapter(service, records):
    result = YuanhangManagement.__new__(YuanhangManagement)
    result.registry, result.records = service.registry, records
    result.context = SimpleNamespace(optional=lambda key: {'yuanhang.identity': service,
                                                          'proxy.pool': service.pool}.get(key))
    return result


async def test_legacy_upgrade_preserves_ciphertext_accounts_devices_and_is_explicit_idempotent():
    settings = Settings()
    registry = ProfileRegistry(settings, Protection())
    original = (await registry.ensure(['node1']))['node1']
    await registry.bind('node1', GuestIdentity('thsguest_fixture', 'secret'), original.device)
    legacy = copy.deepcopy(settings.data)
    legacy['schema'] = 1
    del legacy['profiles']['node1']['creation']
    with pytest.raises(ValueError, match='迁移'):
        registry._read(legacy)
    migrated = upgrade(legacy, registry)
    assert migrated['profiles']['node1']['protected'] == legacy['profiles']['node1']['protected']
    profile = registry._read(migrated)['node1']
    assert profile.device == original.device and profile.profile_id == original.profile_id
    assert profile.creation['provenance'] == 'legacy-reconstructed'
    assert profile.creation['requested_at'] is None
    assert upgrade(migrated, registry) == migrated
    assert legacy['schema'] == 1 and 'creation' not in legacy['profiles']['node1']
    broken = copy.deepcopy(legacy)
    broken['profiles']['node1']['unrecognized'] = True
    with pytest.raises(ValueError):
        upgrade(broken, registry)


async def test_saved_recipe_survives_new_client_defaults_and_no_secret_in_projection(monkeypatch):
    service = make_service()
    service.pool.entries['a'] = endpoint('a')
    await service.reconcile()
    original = (await service.registry.load())['a']
    monkeypatch.setattr(yuanhang_recipe, 'VERSION', 'future-version')
    await service.registry.ensure(['a', 'b'])
    loaded = await service.registry.load()
    assert loaded['a'].creation == original.creation
    assert loaded['b'].creation['client_version'] == 'future-version'
    assert original.creation['requested_at'] is not None
    result = await adapter(service, Records()).snapshot(0, 50)
    serialized = json.dumps(result)
    assert 'secret' not in serialized and 'thsguest_' not in serialized and 'protected' not in serialized
    assert result['rows'][0]['creation']['imei'] == original.device.imei


async def test_previous_failure_remains_visible_during_next_operation_and_idle_scans():
    service, records = make_service(), Records()
    service.runs = IdentityRuns(records, 'ths-yuanhang-identity')
    service.pool.entries['a'] = endpoint('a')
    await service.reconcile()
    with pytest.raises(ValueError):
        async with service.runs.operation('a', 'login'):
            raise ValueError('password=supersecret')
    query = adapter(service, records)
    failed = (await query.snapshot(0, 50))['last_run']
    assert failed['status'] == 'failed'
    for _ in range(3):
        await service.reconcile()
    assert (await query.snapshot(0, 50))['last_run'] == failed
    async with service.runs.operation('a', 'login'):
        snapshot = await query.snapshot(0, 50)
        assert snapshot['last_run'] == failed and len(snapshot['current']) == 1
        assert snapshot['rows'][0]['last_run'] == failed
        assert 'supersecret' not in json.dumps(snapshot)
    assert (await query.snapshot(0, 50))['last_run']['status'] == 'success'


async def test_platform_isolation_and_stopped_service_query_never_authenticates():
    service, records = make_service(), Records()
    await service.registry.ensure(['offline'])
    first = adapter(service, records)
    first.context = SimpleNamespace(optional=lambda key: None)
    second = adapter(make_service(), records)
    second.id = 'other-platform'
    catalog = IdentityQueries([first, second])
    assert len(await catalog.catalog()) == 2
    assert (await catalog.snapshot(first.id))['rows'][0]['code'] == 'offline'
    assert (await catalog.snapshot(second.id))['total'] == 0
    assert not service.http.calls
    with pytest.raises(ValueError, match='Unknown'):
        await catalog.snapshot('not-registered')


async def test_interrupted_unknown_and_redis_failure_are_not_success():
    service, records = make_service(), Records()
    service.runs = IdentityRuns(records, 'ths-yuanhang-identity')
    with pytest.raises(asyncio.CancelledError):
        async with service.runs.operation('a', 'application'):
            raise asyncio.CancelledError()
    assert (await adapter(service, records).snapshot(0, 50))['last_run']['status'] == 'interrupted'
    await records.add_identity_run('ths-yuanhang-identity', dict(id='crashed', code='a', operation='login', status='running'))
    snapshot = await adapter(service, records).snapshot(0, 50)
    assert len(snapshot['unconfirmed']) == 1 and not snapshot['current']
    assert snapshot['last_run']['status'] == 'interrupted'

    async def broken(*args):
        raise ConnectionError('redis secret')

    records.list_identity_runs = broken
    assert 'Redis' in (await adapter(service, records).snapshot(0, 50))['warning']
    records.add_identity_run = broken
    with pytest.raises(ConnectionError):
        async with service.runs.operation('a', 'application'):
            pytest.fail('Must not send after Redis intent failure')
