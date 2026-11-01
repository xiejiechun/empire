import asyncio

import pytest

from empire.sources.yuanhang_auth import AuthenticationError
from empire.sources.yuanhang_sessions import NodeSessions


async def test_concurrent_projects_and_rounds_share_one_node_login():
    cache, calls = NodeSessions(), []

    async def login():
        await asyncio.sleep(0)
        calls.append(1)
        return object()

    values = await asyncio.gather(*(cache.get('a', 'profile', login) for _ in range(20)))
    assert len(calls) == 1 and all(v is values[0] for v in values)
    assert await cache.get('a', 'profile', login) is values[0]
    assert await cache.get('b', 'profile-b', login) is not values[0]
    assert len(calls) == 2


async def test_stale_rejection_does_not_refresh_new_session_and_second_rejection_blocks():
    cache, calls = NodeSessions(), []

    async def login():
        calls.append(1)
        return object()

    old = await cache.get('a', 'p', login)
    new = await cache.get('a', 'p', login, rejected=old)
    assert new is not old
    assert await cache.get('a', 'p', login, rejected=old) is new
    cache.reject('a', old)
    with pytest.raises(AuthenticationError):
        await cache.get('a', 'p', login, rejected=new)
    with pytest.raises(AuthenticationError):
        await cache.get('a', 'p', login)
    assert len(calls) == 2


async def test_confirmed_session_can_recover_later_expiry_and_profile_change():
    cache = NodeSessions()

    async def login():
        return object()

    old = await cache.get('a', 'p', login)
    current = await cache.get('a', 'p', login, rejected=old)
    cache.confirm('a', current)
    renewed = await cache.get('a', 'p', login, rejected=current)
    assert renewed is not current
    changed = await cache.get('a', 'new-profile', login)
    assert changed is not renewed
    cache.prune({})
    assert not cache.entries


async def test_failed_refresh_is_not_repeated_by_waiting_tasks():
    cache = NodeSessions()

    async def login():
        return object()

    old = await cache.get('a', 'p', login)
    calls = []

    async def denied():
        calls.append(1)
        raise AuthenticationError('login', -3)

    results = await asyncio.gather(*(cache.get('a', 'p', denied, rejected=old)
                                     for _ in range(10)), return_exceptions=True)
    assert all(isinstance(r, AuthenticationError) for r in results)
    assert len(calls) == 1
