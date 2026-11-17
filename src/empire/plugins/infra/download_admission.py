"""Disposable fair request admission and conservative downstream feedback.

The saved limit never changes. A reduced window admits at least one request so
an unfinished complete business unit can still obtain its remaining pages.
"""
import asyncio
import math
from collections import OrderedDict, deque


class DownloadAdmission:
    def __init__(self, limit):
        self.ceiling = self.limit = limit
        self.active = 0
        self.waiting = OrderedDict()
        self.high = self.low = 0
        self.previous_pending = None
        self.archive_rate = self.arrival_rate = 0
        self.samples = deque()
        self.sample_seconds = 0
        self.capacity_rate = None
        self.capacity_idle_seconds = 0
        self.reason = ''
        self.closed = False

    def _drain(self):
        while self.waiting and self.active < self.limit and not self.closed:
            key, queue = self.waiting.popitem(last=False)
            future = queue.popleft()
            if queue:
                self.waiting[key] = queue
            if future.done():
                continue
            self.active += 1
            future.set_result(None)

    async def acquire(self, site, project):
        if self.closed:
            raise RuntimeError('下载准入已关闭')
        key = (site, project)
        future = asyncio.get_running_loop().create_future()
        queue = self.waiting.setdefault(key, deque())
        queue.append(future)
        self._drain()
        try:
            # Shield distinguishes cancellation after grant from an ungranted
            # waiter. The owner returns exactly the slot it actually received.
            await asyncio.shield(future)
        except BaseException:
            if future.done() and not future.cancelled() and future.exception() is None:
                self.release()
            else:
                future.cancel()
                if future in queue:
                    queue.remove(future)
                if not queue:
                    self.waiting.pop(key, None)
                self._drain()
            raise

    def release(self):
        if self.active <= 0:
            raise RuntimeError('下载准入额度重复释放')
        self.active -= 1
        self._drain()

    def sample(self, *, pending=0, oldest_seconds=0, buffer_ratio=0, lag_ms=0,
               archive_failed=False, archived_per_second=0, monitored=True, elapsed_seconds=1):
        if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0:
            raise ValueError('反馈采样时长必须为正数')
        growth = self.previous_pending is not None and pending > self.previous_pending
        self.archive_rate = max(0, archived_per_second)
        previous = pending if self.previous_pending is None else self.previous_pending
        arrival = max(0, self.archive_rate + (pending - previous) / elapsed_seconds)
        # Only ACKs while ready work existed at both ends can estimate saturated
        # service capacity. Idle throughput must never be mistaken for capacity.
        busy = (self.previous_pending is not None and monitored and not archive_failed
                and min(previous, pending) > 0)
        if not monitored or archive_failed:
            self.samples.clear()
            self.sample_seconds = 0
            self.capacity_rate = None
            self.arrival_rate = 0
        else:
            self.samples.append((elapsed_seconds, self.archive_rate, arrival, busy))
            self.sample_seconds += elapsed_seconds
            while self.sample_seconds > 10:
                seconds, ack, incoming, saturated = self.samples.popleft()
                trim = min(seconds, self.sample_seconds - 10)
                self.sample_seconds -= trim
                if trim < seconds:
                    self.samples.appendleft((seconds - trim, ack, incoming, saturated))
            self.arrival_rate = sum(s * rate for s, _, rate, _ in self.samples) / self.sample_seconds
            busy_seconds = sum(s for s, _, _, saturated in self.samples if saturated)
            if busy_seconds >= 5:
                self.capacity_rate = sum(s * ack for s, ack, _, saturated in self.samples
                                         if saturated) / busy_seconds
        self.capacity_idle_seconds = 0 if busy else self.capacity_idle_seconds + elapsed_seconds
        if self.capacity_idle_seconds >= 30:
            # Allow bounded recovery probes after an old bottleneck disappears.
            self.capacity_rate = None
        self.previous_pending = pending
        reason = ('归档监测暂不可用' if not monitored else
                  '归档暂不可用' if archive_failed and pending else
                  '归档积压' if pending and (oldest_seconds > 30 or growth) else
                  '归档处理余量不足' if self.capacity_rate is not None
                    and self.arrival_rate > self.capacity_rate / 1.25 else
                  '缓冲使用率偏高' if buffer_ratio >= .85 else
                  '事件循环延迟偏高' if lag_ms > 100 else '')
        if reason:
            self.high += elapsed_seconds
            self.low = 0
            if self.high >= 3:
                self.limit = max(1, self.limit * 3 // 4)
                self.reason = reason
                self.high = 0
        elif oldest_seconds < 10 and buffer_ratio < .6 and lag_ms <= 50:
            self.high = 0
            self.low += elapsed_seconds
            if self.low >= 10:
                candidate = min(self.ceiling, self.limit + max(1, self.limit // 16))
                predicted = self.arrival_rate * candidate / self.limit
                if self.capacity_rate is None or predicted <= self.capacity_rate / 1.25:
                    self.limit = candidate
                self.low = 0
                if self.limit == self.ceiling:
                    self.reason = ''
        else:
            self.high = self.low = 0
        self._drain()

    def snapshot(self):
        return dict(effective_download_window=self.limit, download_admission_active=self.active,
                    download_admission_waiting=sum(map(len, self.waiting.values())),
                    archive_messages_per_second=self.archive_rate,
                    estimated_ready_arrival_per_second=self.arrival_rate,
                    estimated_archive_capacity_per_second=self.capacity_rate,
                    download_feedback_reason=self.reason)

    def close(self):
        self.closed = True
        for queue in self.waiting.values():
            for future in queue:
                if not future.done():
                    future.set_exception(RuntimeError('下载准入已关闭'))
        self.waiting.clear()
