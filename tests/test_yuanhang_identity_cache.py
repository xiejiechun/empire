import asyncio
from unittest.mock import AsyncMock

import pytest

from empire.sources import yuanhang_service as module
from tests.test_identity_management import Records, adapter
from tests.test_yuanhang_service import endpoint, make_service


async def test_download_login_and_management_share_one_verified_snapshot(monkeypatch):
    service = make_service()
    service.pool.entries['a'] = endpoint('a')
    await service.reconcile()
    load = AsyncMock(wraps=service.registry.load)
    monkeypatch.setattr(service.registry, 'load', load)
    login = AsyncMock(return_value=object())
    monkeypatch.setattr(module, 'login_profile', login)
    query = adapter(service, Records())
    async def request():
        assert (await service.get_profiles())['a'].provisioned
        await service.login('a', project_id='test')
        assert (await query.snapshot(0, 50))['total'] == 1
    await asyncio.gather(*(request() for _ in range(100)))
    load.assert_not_awaited()
    login.assert_awaited_once()
    service.next_reload = 0
    await asyncio.gather(*(request() for _ in range(100)))
    load.assert_awaited_once()
    login.assert_awaited_once()
    await service.close()


async def test_refresh_failure_is_shared_and_never_uses_expired_identity(monkeypatch):
    service = make_service()
    service.pool.entries['a'] = endpoint('a')
    await service.reconcile()
    original = service.registry.load
    load = AsyncMock(side_effect=ValueError('invalid persisted profile'))
    monkeypatch.setattr(service.registry, 'load', load)
    login = AsyncMock()
    monkeypatch.setattr(module, 'login_profile', login)
    service.next_reload = 0
    results = await asyncio.gather(*(service.login('a', project_id='test') for _ in range(50)),
                                   return_exceptions=True)
    assert all(isinstance(r, (ValueError, RuntimeError)) for r in results)
    load.assert_awaited_once()
    login.assert_not_awaited()
    monkeypatch.setattr(service.registry, 'load', original)
    service.next_reload = 0
    assert (await service.get_profiles())['a'].provisioned
    await service.close()


async def test_external_profile_removal_invalidates_session_on_refresh(monkeypatch):
    service = make_service()
    service.pool.entries['a'] = endpoint('a')
    await service.reconcile()
    login = AsyncMock(return_value=object())
    monkeypatch.setattr(module, 'login_profile', login)
    await service.login('a', project_id='test')
    service.registry.settings.data['profiles'].clear()
    service.next_reload = 0
    with pytest.raises(ValueError, match='尚未就绪'):
        await service.login('a', project_id='test')
    assert not service.sessions.entries
    login.assert_awaited_once()
    await service.close()


async def test_cancelled_refresh_blocks_stale_identity_until_success(monkeypatch):
    service = make_service()
    await service.reload()
    entered = asyncio.Event()
    async def blocked():
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(service.registry, 'load', blocked)
    service.next_reload = 0
    task = asyncio.create_task(service.get_profiles())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(RuntimeError, match='核验失败'):
        await service.get_profiles()
    await service.close()


async def test_close_during_refresh_cannot_repopulate_profiles(monkeypatch):
    service = make_service()
    entered, release = asyncio.Event(), asyncio.Event()
    async def blocked():
        entered.set()
        await release.wait()
        return {'unexpected': object()}
    monkeypatch.setattr(service.registry, 'load', blocked)
    task = asyncio.create_task(service.get_profiles())
    await entered.wait()
    await service.close()
    release.set()
    with pytest.raises(RuntimeError, match='已停止'):
        await task
    assert not service.profiles
