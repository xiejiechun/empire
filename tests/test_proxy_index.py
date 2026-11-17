import asyncio
import json
from ipaddress import IPv4Address
from time import monotonic

import pytest

from empire.plugins.infra.proxy_index import ExitIndex
from empire.plugins.infra.proxy_pool import Endpoint


def entries(count):
    now = monotonic()
    return {str(i): Endpoint(str(i), '', '', now + 180, exit_ip=str(IPv4Address(0x0A000001 + i)))
            for i in range(count)}


@pytest.mark.parametrize('count', [1000, 3000, 5000])
def test_ready_selection_and_health_do_not_scan_directory(count):
    index = ExitIndex()
    devices = entries(count)
    index.sync(devices, [])
    ready = index.site('sina')
    before = ready.operations
    selected = []
    for _ in range(100):
        assert index.healthy_count() == count
        entry = ready.take(set(), monotonic())
        assert entry is not None
        entry.active_sites.add('sina')
        index.reserve(entry, 'sina')
        selected.append(entry)
    assert len({entry.exit_ip for entry in selected}) == 100
    assert ready.operations - before <= 201
    # A different site's inventory is independent of sina's active leases.
    other = index.site('ths').take(set(), monotonic())
    assert other is not None
    for entry in selected:
        entry.active_sites.remove('sina')
        index.release(entry, 'sina')
    assert not index.busy['sina']


def test_shared_exit_deferral_retired_code_and_stale_heap_bound():
    index = ExitIndex()
    devices = entries(2)
    devices['1'].exit_ip = devices['0'].exit_ip
    index.sync(devices, [])
    ready = index.site('sina')
    entry = ready.take(set(), monotonic())
    entry.active_sites.add('sina')
    index.reserve(entry, 'sina')
    assert ready.take(set(), monotonic()) is None
    assert index.healthy_count() == 1
    entry.active_sites.clear()
    index.release(entry, 'sina')
    for _ in range(10000):
        index.changed(entry.exit_ip)
    assert len(ready.ready) + len(ready.timers) <= 64
    assert len(index.health_timers) <= 64
    assert ready.take({entry.code}, monotonic()).code != entry.code


async def test_release_wakes_only_one_waiter_in_same_site():
    from empire.plugins.infra.proxy_pool import ProxyPool
    pool = ProxyPool(None)
    first = asyncio.create_task(pool._wait('sina', 2))
    second = asyncio.create_task(pool._wait('sina', 2))
    other = asyncio.create_task(pool._wait('ths', 2))
    try:
        await asyncio.sleep(0)
        pool._wake('sina')
        await asyncio.wait_for(first, 1)
        assert not second.done() and not other.done()
    finally:
        for task in (first, second, other):
            task.cancel()
        await asyncio.gather(first, second, other, return_exceptions=True)
    assert not any(pool.waiters.values())


async def test_shared_deadline_wakes_one_and_bound_identity_has_separate_timer():
    from empire.plugins.infra.proxy_pool import ProxyPool
    pool = ProxyPool(None)
    generic = [asyncio.create_task(pool._wait('sina', 60)) for _ in range(1000)]
    bound = asyncio.create_task(pool._wait('sina', 60, device_code='bound'))
    try:
        await asyncio.sleep(0)
        assert len(pool.wait_timers) == 2
        pool.wait_timers['sina', 'bound'].cancel()
        pool._timer_wake(('sina', 'bound'))
        await asyncio.wait_for(bound, 1)
        assert not any(task.done() for task in generic)
        pool.wait_timers['sina', None].cancel()
        pool._timer_wake(('sina', None))
        await asyncio.wait_for(generic[0], 1)
        assert sum(task.done() for task in generic) == 1
    finally:
        for task in [*generic, bound]:
            task.cancel()
        await asyncio.gather(*generic, bound, return_exceptions=True)
    assert not pool.wait_timers and not any(pool.waiters.values())


def test_oversize_candidate_rejected_without_body():
    from empire.plugins.infra.proxy_pool import parse_endpoint
    raw = json.dumps({'code': 'x', 'proxy': 'u:secret@localhost:1', 'exit_ip': '10.0.0.1',
                      'extra': 'a' * 4096})
    with pytest.raises(ValueError) as caught:
        parse_endpoint('x', raw, 180)
    assert 'secret' not in str(caught.value)
