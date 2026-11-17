import asyncio
from collections import Counter

import pytest

from empire.plugins.infra.download_admission import DownloadAdmission


async def test_continuously_ready_projects_round_robin_and_idle_capacity_is_borrowed():
    gate = DownloadAdmission(1)
    await gate.acquire('site', 'holder')
    order = []

    async def request(project):
        await gate.acquire('site', project)
        order.append(project)
        await asyncio.sleep(0)
        gate.release()

    tasks = [asyncio.create_task(request(project))
             for project in ('large', 'small', 'third') for _ in range(100)]
    await asyncio.sleep(0)
    gate.release()
    await asyncio.gather(*tasks)
    for index in range(0, 300, 3):
        assert Counter(order[index:index + 3]) == Counter(large=1, small=1, third=1)
    assert not gate.waiting and gate.active == 0
    gate = DownloadAdmission(8)
    await asyncio.gather(*(gate.acquire('site', 'single') for _ in range(8)))
    assert gate.active == 8
    for _ in range(8):
        gate.release()


async def test_cancellation_before_and_after_grant_returns_ownership():
    gate = DownloadAdmission(1)
    await gate.acquire('site', 'first')
    cancelled = asyncio.create_task(gate.acquire('site', 'cancelled'))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert not gate.waiting and gate.active == 1
    granted = asyncio.create_task(gate.acquire('site', 'granted'))
    await asyncio.sleep(0)
    gate.release()
    granted.cancel()
    with pytest.raises(asyncio.CancelledError):
        await granted
    assert gate.active == 0 and not gate.waiting


def test_feedback_hysteresis_keeps_completion_capacity_and_saved_ceiling():
    gate = DownloadAdmission(128)
    for _ in range(2):
        gate.sample(pending=100, oldest_seconds=31)
        assert gate.limit == 128
    gate.sample(pending=100, oldest_seconds=31)
    assert gate.limit == 96 and gate.ceiling == 128
    for _ in range(100):
        gate.sample(pending=100, oldest_seconds=31)
    assert gate.limit == 1
    for _ in range(9):
        gate.sample()
    assert gate.limit == 1
    gate.sample()
    assert gate.limit == 2
    for _ in range(2000):
        gate.sample()
    assert gate.limit == gate.ceiling == 128 and not gate.reason


def test_unfinished_aggregate_is_not_counted_as_downstream_pressure():
    gate = DownloadAdmission(128)
    # Archive reports only immediately processable or failed units, omitting
    # incomplete aggregate batches. Remaining downloads can finish the batch.
    for _ in range(100):
        gate.sample(pending=0, oldest_seconds=0)
    assert gate.limit == 128


def test_capacity_estimate_needs_saturated_work_and_accounts_for_elapsed_time():
    gate = DownloadAdmission(128)
    for _ in range(20):
        gate.sample(archived_per_second=2)
    assert gate.capacity_rate is None
    gate.sample(pending=100, archived_per_second=100)
    for _ in range(3):
        gate.sample(pending=100, archived_per_second=100, elapsed_seconds=2)
    assert gate.capacity_rate == 100
    # Constant queue with arrival equal to capacity has no required headroom.
    for _ in range(3):
        gate.sample(pending=100, archived_per_second=100)
    assert gate.limit < gate.ceiling
    before = gate.limit
    for _ in range(20):
        gate.sample(pending=100, archived_per_second=100)
    assert gate.limit <= before


def test_recovery_obeys_measured_headroom_and_stale_capacity_expires():
    gate = DownloadAdmission(128)
    gate.limit = 64
    pending = 10000
    gate.sample(pending=pending, archived_per_second=100)
    for _ in range(20):
        pending -= 40
        gate.sample(pending=pending, archived_per_second=100)
    before = gate.limit
    for _ in range(20):
        pending -= 40
        gate.sample(pending=pending, archived_per_second=100)
    assert gate.limit > before and gate.limit <= gate.ceiling
    for _ in range(40):
        gate.sample()
    assert gate.capacity_rate is None
    assert gate.ceiling == 128


def test_delayed_sample_measures_rate_per_second_and_monitor_loss_is_conservative():
    gate = DownloadAdmission(128)
    gate.sample(pending=100, archived_per_second=100, elapsed_seconds=2)
    gate.sample(pending=120, archived_per_second=100, elapsed_seconds=2)
    assert gate.arrival_rate == 105
    gate.sample(monitored=False, elapsed_seconds=3)
    assert gate.limit == 96 and gate.capacity_rate is None
    with pytest.raises(ValueError, match='时长'):
        gate.sample(elapsed_seconds=0)
