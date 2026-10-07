"""Independent business units on the single ordered, byte-bounded prefetch path."""
from contextlib import asynccontextmanager
from dataclasses import dataclass

from empire.plugins.collection.prefetch import ordered_prefetch


class BorrowedReservation:
    """Closing a response cannot release the unit owner's retained-result budget."""
    def __init__(self, owner):
        self.owner = owner
        self.budget, self.size = owner.budget, owner.size

    @property
    def released(self):
        return self.owner.released

    def release(self):
        pass  # ordered_prefetch releases the owner after consumption/drain.


class DeferredResponse:
    """Keep source validation in the ordered consumer, with its diagnostic body."""
    def __init__(self, response, consume):
        self.response, self.consume = response, consume

    def close(self):
        if self.response is not None:
            self.response.close()
            self.response = None
        self.consume = None


@dataclass
class UnitRead:
    value: object = None
    error: Exception | None = None

    async def resolve(self):
        if self.error is not None:
            raise self.error
        if isinstance(self.value, DeferredResponse):
            return await self.value.consume()
        return self.value

    def close(self):
        if hasattr(self.value, 'close'):
            self.value.close()
        self.value = self.error = None


@asynccontextmanager
async def prefetch_units(collector, units, fetch, *, url, domains, profile='generic',
                         first=0, independent=True, item_name='单元'):
    """fetch(unit, reservation=...) may defer validation or return a bounded unit."""
    policy = collector.http.response_policy(profile)
    collector.stats['download_item_name'] = item_name
    if first < len(units):
        collector.stats['status'] = 'collecting'

    async def width():
        return await collector.http.parallelism(url, domains) if independent else 1

    async def download(index, lease):
        try:
            return UnitRead(await fetch(units[index], reservation=BorrowedReservation(lease)))
        except Exception as exc:
            return UnitRead(error=exc)

    async with ordered_prefetch(first, len(units) - 1, download, width,
            budget=collector.http.buffer_budget, reservation_bytes=policy.reservation_bytes,
            on_state=collector.stats.update) as reads:
        yield reads
