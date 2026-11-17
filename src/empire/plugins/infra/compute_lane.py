"""Bounded pure process execution; cancellation retains actual work ownership."""
import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from functools import partial

from empire.plugins.infra.sql_lane import settle

MAX_INPUT = 2 * 1024 * 1024
MAX_RESULT = 4 * 1024 * 1024
ITEM_BUDGET = 2 * MAX_INPUT + 2 * MAX_RESULT


class ComputeLane:
    def __init__(self, workers=4):
        self.workers = workers
        self.executor = None
        self.slots = asyncio.Semaphore(workers)
        self.pending = self.active = 0
        self.closed = False
        self.idle = asyncio.Event()
        self.idle.set()

    async def call(self, operation, *args):
        if self.closed:
            raise RuntimeError('计算执行通道已关闭')
        if self.pending >= self.workers * 16:
            raise RuntimeError('计算执行队列已满；本次单元未提交')
        self.pending += 1
        self.idle.clear()
        try:
            async with self.slots:
                if self.closed:
                    raise RuntimeError('计算执行通道已关闭')
                if self.executor is None:
                    self.executor = ProcessPoolExecutor(self.workers,
                        mp_context=multiprocessing.get_context('spawn'))
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
        self.closed = True
        await settle(asyncio.create_task(self._close()))

    async def _close(self):
        await self.idle.wait()
        if self.executor is not None:
            # Shutdown may join OS processes even when all user work is finished.
            shutdown = asyncio.create_task(asyncio.to_thread(self.executor.shutdown, wait=True))
            await settle(shutdown)
            self.executor = None

    def health(self):
        return dict(active=self.active, waiting=self.pending - self.active,
                    workers=self.workers, started=self.executor is not None)
