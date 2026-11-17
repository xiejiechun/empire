"""Reuse the current parent lease for dependent reads, without nested windows."""
import json
from contextlib import asynccontextmanager

from empire.plugins.collection.unit_prefetch import BorrowedReservation, UnitRead, prefetch_units


def retain_parent(read, value):
    owner = getattr(read.value, 'owner', None)
    retained = 3 * len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())
    if owner is not None and not owner.grow_to(max(owner.size, retained)):
        raise ValueError('规范父单元超出共享缓冲预算')
    read.close()
    return owner, retained


@asynccontextmanager
async def followup_reads(collector, units, fetch, owner, retained, **kwargs):
    if owner is None:
        async with prefetch_units(collector, units, fetch, **kwargs) as reads:
            yield reads
    else:
        async def sequential():
            for index, unit in enumerate(units):
                held = retained() if callable(retained) else retained
                minimum = collector.http.response_policy(kwargs.get('profile', 'generic')).reservation_bytes
                if not owner.grow_to(max(owner.size, held + minimum)):
                    raise ValueError('父单元及明细最小下载缓冲超出共享预算')
                reservation = BorrowedReservation(owner, max(0, owner.size - held))
                read = UnitRead(await fetch(unit, reservation=reservation))
                try:
                    yield index, read
                finally:
                    read.close()
        reads = sequential()
        try:
            yield reads
        finally:
            await reads.aclose()
