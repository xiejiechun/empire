"""Bounded speculative reads; the consumer alone validates and commits in order."""
import asyncio
from contextlib import asynccontextmanager

from empire.contracts.download_settings import MAX_PARALLEL_DOWNLOADS


@asynccontextmanager
async def ordered_prefetch(first, last, fetch, capacity, *, budget, reservation_bytes, on_state=None):
    pending = {}
    next_submit = first
    width, phase, current = 1, "idle", first

    def successful(task):
        return (task.done() and not task.cancelled() and task.exception() is None
                and getattr(task.result(), "error", None) is None)

    def publish_state(_task=None):
        if on_state is not None:
            ready = sum(successful(task) for task, _ in pending.values())
            failed = sum(task.done() and not task.cancelled() and not successful(task)
                         for task, _ in pending.values())
            reason = phase
            if phase == "network" and ready:
                reason = "ordered"
            on_state({"download_window_limit": width,
                "download_buffer_capacity": budget.limit // reservation_bytes,
                "download_concurrency": min(width, budget.limit // reservation_bytes,
                                            max(0, last - current + 1)),
                "download_pending_pages": len(pending),
                "download_ready_pages": ready,
                "download_failed_pages": failed,
                "download_buffer_limited": (next_submit <= last and len(pending) < width
                    and budget.limit - budget.used < reservation_bytes),
                "download_wait_reason": reason})

    async def results():
        nonlocal next_submit, width, phase, current
        for number in range(first, last + 1):
            current = number
            width = max(1, min(MAX_PARALLEL_DOWNLOADS, await capacity()))
            phase = "network"
            while next_submit <= last and len(pending) < width:
                lease = budget.try_reserve(reservation_bytes)
                if lease is None:
                    if pending:
                        break  # Consume the earliest page before asking for more memory.
                    phase = "buffer"
                    publish_state()
                    lease = await budget.reserve(reservation_bytes)
                    phase = "network"
                task = asyncio.create_task(fetch(next_submit, lease))
                pending[next_submit] = (task, lease)
                task.add_done_callback(publish_state)
                next_submit += 1
            publish_state()
            task, lease = pending[number]
            # The owner cancels all child tasks exactly once in the drain path.
            # A second cancel of the consumer must not interrupt transport cleanup.
            result = await asyncio.shield(task)
            phase = "ordered"
            publish_state()
            try:
                yield number, result
            finally:
                try:
                    result.close()
                finally:
                    lease.release()
                    del pending[number]
                    publish_state()

    iterator = results()
    try:
        yield iterator
    finally:
        cleanup_error = None
        try:
            await iterator.aclose()
        except BaseException as exc:
            cleanup_error = exc
        for task, _ in pending.values():
            task.cancel()
        drain = asyncio.gather(*(task for task, _ in pending.values()), return_exceptions=True)
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError as exc:
                # Repeated cancellation must not abandon retained response bodies
                # or leases while a transport is still finishing its own cleanup.
                cleanup_error = cleanup_error or exc
        for task, lease in pending.values():
            try:
                if not task.cancelled() and task.exception() is None:
                    task.result().close()
            except BaseException as exc:
                cleanup_error = cleanup_error or exc
            finally:
                lease.release()
        pending.clear()
        current, phase = last + 1, "idle"
        publish_state()
        if cleanup_error is not None:
            raise cleanup_error
