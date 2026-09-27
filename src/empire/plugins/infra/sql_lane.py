"""Bounded SQL execution, with ownership retained until real thread completion."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial


async def settle(future):
    """Repeated cancellation cannot abandon an in-flight SQL operation or shutdown."""
    cancelled = False
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        # Retrieve the outcome, even when the caller no longer wants the result.
        if not future.cancelled():
            future.exception()
        raise asyncio.CancelledError
    return future.result()


class SQLLane:
    def __init__(self, name, workers, waiting):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self.slots = asyncio.Semaphore(workers)
        self.workers, self.limit = workers, workers + waiting
        self.pending = self.active = self.rejected = 0
        self.accepting = True
        self.idle = asyncio.Event()
        self.idle.set()

    async def call(self, operation, *args):
        if not self.accepting:
            raise RuntimeError("数据库执行通道正在关闭")
        if self.pending >= self.limit:
            self.rejected += 1
            raise RuntimeError("数据库执行队列已满，请稍后重试；本次操作尚未执行")
        self.pending += 1
        self.idle.clear()
        try:
            async with self.slots:
                self.active += 1
                try:
                    future = asyncio.get_running_loop().run_in_executor(
                        self.executor, partial(operation, *args))
                    return await settle(future)
                finally:
                    self.active -= 1
        finally:
            self.pending -= 1
            if not self.pending:
                self.idle.set()

    async def close(self):
        self.accepting = False
        await self.idle.wait()
        # No worker is executing now; shutdown cannot wait on SQL I/O.
        self.executor.shutdown(wait=True)

    def health(self):
        return {"active": self.active, "waiting": self.pending - self.active,
                "workers": self.workers, "capacity": self.limit, "rejected": self.rejected}
