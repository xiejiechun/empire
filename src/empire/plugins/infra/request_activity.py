"""Bounded request-rate accounting and observable admission waits."""
import asyncio
from collections import deque
from time import monotonic


class RequestRate:
    """Ten seconds of 100ms buckets, independent of the number of requests."""
    def __init__(self):
        self.buckets = deque()

    def _expire(self, tick):
        while self.buckets and self.buckets[0][0] <= tick - 100:
            self.buckets.popleft()

    def add(self, now=None):
        tick = int((monotonic() if now is None else now) * 10)
        self._expire(tick)
        if self.buckets and self.buckets[-1][0] == tick:
            self.buckets[-1][1] += 1
        else:
            self.buckets.append([tick, 1])

    def rate(self, now=None):
        self._expire(int((monotonic() if now is None else now) * 10))
        return sum(count for _, count in self.buckets) / 10


async def wait_for_admission(service, stats, reason, delay=.05):
    waits = stats.setdefault("waiting_reasons", {})
    waits[reason] = waits.get(reason, 0) + 1
    stats["waiting"] += 1
    try:
        service.admission_changed.clear()
        try:
            await asyncio.wait_for(service.admission_changed.wait(), delay)
        except TimeoutError:
            pass
    finally:
        waits[reason] -= 1
        stats["waiting"] -= 1
