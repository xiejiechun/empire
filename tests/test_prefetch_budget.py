"""Ordered publication keeps downloads bounded through consumption and cancellation."""
import asyncio

import pytest

from empire.plugins.collection.prefetch import ordered_prefetch
from empire.plugins.infra.resources import ByteBudget


class Response:
    def __init__(self, page, lease, *, fail_close=False):
        self.page, self.lease = page, lease
        self.close_count = 0
        self.fail_close = fail_close

    def close(self):
        self.close_count += 1
        if self.fail_close:
            raise OSError("simulated response close failure")


async def width():
    return 64


async def wait_until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


def assert_released(budget, responses, leases):
    assert budget.used == budget.waiting == 0
    assert all(response.close_count == 1 for response in responses)
    assert all(lease.released for lease in leases)


async def test_slow_first_page_holds_fast_following_body_inside_budget_without_fill_deadlock():
    budget = ByteBudget(20)
    first = asyncio.Event()
    responses, leases, starts, seen = [], [], [], []

    async def fetch(page, lease):
        leases.append(lease)
        starts.append(page)
        if page == 1:
            await first.wait()
        response = Response(page, lease)
        responses.append(response)
        return response

    async def consume():
        async with ordered_prefetch(1, 5, fetch, width, budget=budget, reservation_bytes=10) as reads:
            async for page, response in reads:
                assert not response.close_count and not response.lease.released
                seen.append(page)
                await asyncio.sleep(0)  # Simulated ordered validation/publication.

    task = asyncio.create_task(consume())
    try:
        await wait_until(lambda: any(response.page == 2 for response in responses))
        assert starts == [1, 2] and not seen
        assert budget.used == budget.peak == 20
        assert not responses[0].close_count
        first.set()
        await asyncio.wait_for(task, 2)
        assert seen == [1, 2, 3, 4, 5]
        assert_released(budget, responses, leases)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("mode", ["cancel_download", "break", "publish_error", "cancel_publish"])
async def test_all_exit_paths_close_completed_results_cancel_reads_and_release_budget(mode):
    budget = ByteBudget(30)
    gate, publishing = asyncio.Event(), asyncio.Event()
    responses, leases, active = [], [], set()

    async def fetch(page, lease):
        leases.append(lease)
        active.add(page)
        try:
            if page == 1 and mode == "cancel_download":
                await gate.wait()
            response = Response(page, lease)
            responses.append(response)
            return response
        finally:
            active.remove(page)

    async def consume():
        async with ordered_prefetch(1, 8, fetch, width, budget=budget, reservation_bytes=10) as reads:
            async for page, response in reads:
                assert page == response.page == 1
                assert not response.lease.released
                if mode == "break":
                    break
                if mode == "publish_error":
                    raise ValueError("publish failed")
                publishing.set()
                await gate.wait()

    task = asyncio.create_task(consume())
    try:
        if mode == "cancel_download":
            await wait_until(lambda: len(responses) == 2)
            task.cancel()
        elif mode == "cancel_publish":
            await asyncio.wait_for(publishing.wait(), 2)
            task.cancel()
        if mode.startswith("cancel"):
            with pytest.raises(asyncio.CancelledError):
                await task
        elif mode == "publish_error":
            with pytest.raises(ValueError, match="publish failed"):
                await asyncio.wait_for(task, 2)
        else:
            await asyncio.wait_for(task, 2)
        assert not active and budget.peak == 30
        assert_released(budget, responses, leases)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_fetch_error_releases_failed_lease_and_completed_later_pages():
    budget = ByteBudget(30)
    responses, leases = [], []

    async def fetch(page, lease):
        leases.append(lease)
        if page == 1:
            await asyncio.sleep(0)
            raise ValueError("download failed")
        response = Response(page, lease)
        responses.append(response)
        return response

    with pytest.raises(ValueError, match="download failed"):
        async with ordered_prefetch(1, 3, fetch, width, budget=budget, reservation_bytes=10) as reads:
            async for _ in reads:
                pytest.fail("Failed first page cannot publish later results")
    assert_released(budget, responses, leases)


async def test_competing_prefetch_tasks_share_one_budget_and_make_progress():
    budget = ByteBudget(20)
    gate = asyncio.Event()
    responses, leases, seen = [], [], {"a": [], "b": []}

    async def consume(owner):
        async def fetch(page, lease):
            leases.append(lease)
            if owner == "a" and page == 1:
                await gate.wait()
            response = Response((owner, page), lease)
            responses.append(response)
            return response

        async with ordered_prefetch(1, 4, fetch, width, budget=budget, reservation_bytes=10) as reads:
            async for page, response in reads:
                assert not response.lease.released
                seen[owner].append(page)
                await asyncio.sleep(0)

    first = asyncio.create_task(consume("a"))
    tasks = [first]
    try:
        await wait_until(lambda: budget.used == 20)
        tasks.append(asyncio.create_task(consume("b")))
        await wait_until(lambda: budget.waiting == 1)
        assert not seen["b"]
        gate.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 2)
        assert seen == {"a": [1, 2, 3, 4], "b": [1, 2, 3, 4]}
        assert budget.peak == 20
        assert_released(budget, responses, leases)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_cancel_while_waiting_for_first_reservation_does_not_release_other_owner():
    budget = ByteBudget(10)
    outside = await budget.reserve(10)
    started = []

    async def fetch(page, lease):
        started.append(page)
        return Response(page, lease)

    async def consume():
        async with ordered_prefetch(1, 3, fetch, width, budget=budget, reservation_bytes=10) as reads:
            async for _ in reads:
                pytest.fail("No memory was available")

    task = asyncio.create_task(consume())
    try:
        await wait_until(lambda: budget.waiting == 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not started and not outside.released
        assert budget.used == 10 and budget.waiting == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        outside.release()


async def test_close_failure_does_not_leak_any_prefetched_reservations():
    budget = ByteBudget(30)
    responses, leases = [], []

    async def fetch(page, lease):
        leases.append(lease)
        response = Response(page, lease, fail_close=page == 1)
        responses.append(response)
        return response

    with pytest.raises(OSError, match="close failure"):
        async with ordered_prefetch(1, 3, fetch, width, budget=budget, reservation_bytes=10) as reads:
            async for _ in reads:
                break
    assert_released(budget, responses, leases)
