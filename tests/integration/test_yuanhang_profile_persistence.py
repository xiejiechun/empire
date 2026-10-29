"""Real isolated SQL configuration persistence, independent of source requests."""
import asyncio
import copy
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from empire.core.config import load_config
from empire.core.protected_values import WindowsProtection
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.settings import SettingsStore
from empire.sources.yuanhang_identity import GuestIdentity
from empire.sources.yuanhang_profiles import ProfileRegistry
from empire.sources.yuanhang_service import IdentityService
from scripts.migrate_yuanhang_profiles import migrate_database

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1' or os.name != 'nt',
    reason='Explicit isolated SQL and Windows DPAPI required')]


class SQL:
    def __init__(self, engine):
        self.engine = engine

    async def control(self, callback, *args):
        return await asyncio.to_thread(callback, *args)


async def test_restart_idempotence_and_concurrent_transaction_union():
    cfg = load_config()
    engine = make_engine(cfg['mysql'])
    settings = SettingsStore(SQL(engine), cfg['redis']['namespace'])
    registry = ProfileRegistry(settings, WindowsProtection())
    try:
        original = await registry.ensure(['node1'])
        identity = GuestIdentity('thsguest_sql_fixture', 'fixture-secret')
        await registry.bind('node1', identity, original['node1'].device)
        writes = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)

        event.listen(engine, 'before_cursor_execute', capture)
        try:
            restarted = ProfileRegistry(SettingsStore(SQL(engine), settings.namespace), WindowsProtection())
            saved = await restarted.ensure(['node1'])
            assert saved['node1'].identity == identity and saved['node1'].profile_id == original['node1'].profile_id
            await restarted.bind('node1', identity, saved['node1'].device)
            assert not writes
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        await asyncio.gather(registry.ensure(['node2']), restarted.ensure(['node3']))
        assert set(await registry.load()) == {'node1', 'node2', 'node3'}
        snapshot = await registry.load()

        def rejected(old):
            old['profiles'].clear()
            raise ValueError('fixture rollback')

        with pytest.raises(ValueError, match='rollback'):
            await settings.mutate('yuanhang', 'guest-profiles', rejected)
        assert await registry.load() == snapshot
    finally:
        engine.dispose()


async def test_automatic_service_commits_intent_before_source_and_restart_is_read_only():
    cfg = load_config()
    engine = make_engine(cfg['mysql'])
    registry = ProfileRegistry(SettingsStore(SQL(engine), cfg['redis']['namespace']), WindowsProtection())
    pool = SimpleNamespace(entries={})
    requests, writes = [], []

    class Source:
        async def request(self, *args, **kwargs):
            code = kwargs['proxy_code']
            # A separate SQL read must see committed intent before source I/O.
            profile = (await registry.load())[code]
            assert profile.registration == 'requested' and profile.device is not None
            requests.append(code)
            content = f'<response><ret code="0"/><item account="thsguest_{code}" passwd="secret"/></response>'.encode()
            return SimpleNamespace(content=content, close=lambda: None)

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)

    service = IdentityService(registry, pool, Source())
    restarted = None
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        await service.reconcile()
        assert not writes
        pool.entries['a'] = SimpleNamespace(code='a', expires=float('inf'), cooldown=0)
        await service.reconcile()
        original = (await registry.load())['a']
        assert requests == ['a'] and original.provisioned
        writes.clear()
        await service.close()
        restarted = IdentityService(
            ProfileRegistry(SettingsStore(SQL(engine), cfg['redis']['namespace']), WindowsProtection()),
            pool, Source())
        await restarted.reconcile()
        await restarted.reconcile()
        assert restarted.profiles['a'] == original and not writes and requests == ['a']
        pool.entries['b'] = SimpleNamespace(code='b', expires=float('inf'), cooldown=0)
        await restarted.reconcile()
        assert requests == ['a', 'b'] and set(restarted.profiles) == {'a', 'b'}
    finally:
        await service.close()
        if restarted:
            await restarted.close()
        event.remove(engine, 'before_cursor_execute', capture)
        engine.dispose()


async def test_explicit_profile_migration_preserves_sql_identities_and_second_apply_is_noop():
    cfg = load_config()
    engine = make_engine(cfg['mysql'])
    store = SettingsStore(SQL(engine), cfg['redis']['namespace'])
    registry = ProfileRegistry(store, WindowsProtection())
    try:
        original = (await registry.ensure(['a']))['a']
        await registry.bind('a', GuestIdentity('thsguest_migration', 'fixture-secret'), original.device)
        legacy = copy.deepcopy((await store.load('yuanhang'))['guest-profiles'])
        legacy['schema'] = 1
        del legacy['profiles']['a']['creation']
        await store.save('yuanhang', 'guest-profiles', legacy)
        preview = await asyncio.to_thread(migrate_database, engine, store.namespace, WindowsProtection())
        assert preview['changed'] and not preview['applied']
        assert (await store.load('yuanhang'))['guest-profiles'] == legacy
        result = await asyncio.to_thread(migrate_database, engine, store.namespace, WindowsProtection(), apply=True)
        assert result['profiles'] == 1 and result['identities_preserved'] and result['source_requests'] == 0
        after = (await registry.load())['a']
        assert after.device == original.device and after.identity.account == 'thsguest_migration'
        assert (await store.load('yuanhang'))['guest-profiles']['profiles']['a']['protected'] == legacy['profiles']['a']['protected']
        writes = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)

        event.listen(engine, 'before_cursor_execute', capture)
        try:
            second = await asyncio.to_thread(migrate_database, engine, store.namespace, WindowsProtection(), apply=True)
            assert not second['changed'] and not writes
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
    finally:
        engine.dispose()
