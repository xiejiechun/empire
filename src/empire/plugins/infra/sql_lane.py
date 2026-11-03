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
        self.name = name
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self.slots = asyncio.Semaphore(workers)
        self.workers, self.limit = workers, workers + waiting
        self.pending = self.active = self.rejected = 0
        self.accepting = True
        self.idle = asyncio.Event()
        self.idle.set()
        self.available = asyncio.Event()
        self.available.set()
        self.admission_waiting = 0

    def reject_full(self):
        self.rejected += 1
        raise RuntimeError("数据库执行队列已满，请稍后重试；本次操作尚未执行"
                           f"（{self.name}，执行{self.active}，排队{self.pending - self.active}，容量{self.limit}）")

    async def admit(self, timeout):
        if self.accepting and self.pending >= self.limit and timeout:
            self.admission_waiting += 1
            try:
                async with asyncio.timeout(timeout):
                    while self.accepting and self.pending >= self.limit:
                        self.available.clear()
                        await self.available.wait()
            except TimeoutError:
                self.reject_full()
            finally:
                self.admission_waiting -= 1
        if not self.accepting:
            raise RuntimeError("数据库执行通道正在关闭")
        if self.pending >= self.limit:
            self.reject_full()
        self.pending += 1
        self.idle.clear()

    async def call(self, operation, *args, admission_timeout=0):
        # The deadline covers admission only, never a submitted SQL operation.
        await self.admit(admission_timeout)
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
            self.available.set()
            if not self.pending:
                self.idle.set()

    def begin_close(self):
        self.accepting = False
        self.available.set()

    async def close(self):
        self.begin_close()
        await self.idle.wait()
        # No worker is executing now; shutdown cannot wait on SQL I/O.
        self.executor.shutdown(wait=True)

    def health(self):
        return {"active": self.active, "waiting": self.pending - self.active,
                "workers": self.workers, "capacity": self.limit, "rejected": self.rejected,
                "admission_waiting": self.admission_waiting}
