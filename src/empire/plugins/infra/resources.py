"""Loop-owned byte reservations; waiting never owns a network/egress permit."""
import asyncio


class Reservation:
    def __init__(self, budget, size):
        self.budget, self.size, self.released = budget, size, False

    def release(self):
        if not self.released:
            self.released = True
            self.budget.used -= self.size
            self.budget.changed.set()


class ByteBudget:
    def __init__(self, limit):
        if type(limit) is not int or limit <= 0:
            raise ValueError("下载缓冲预算必须为正整数")
        self.limit, self.used, self.peak, self.waiting = limit, 0, 0, 0
        self.changed = asyncio.Event()

    def try_reserve(self, size):
        if type(size) is not int or not 0 < size <= self.limit:
            raise ValueError("单响应预留额度超过全局缓冲预算")
        if self.used + size > self.limit:
            return None
        self.used += size
        self.peak = max(self.peak, self.used)
        return Reservation(self, size)

    async def reserve(self, size):
        self.waiting += 1
        try:
            while True:
                # No await between failed allocation and clear: no lost wake-up.
                lease = self.try_reserve(size)
                if lease:
                    return lease
                self.changed.clear()
                await self.changed.wait()
        finally:
            self.waiting -= 1

    def health(self):
        return {"limit_bytes": self.limit, "reserved_bytes": self.used,
                "peak_reserved_bytes": self.peak, "waiting": self.waiting}
