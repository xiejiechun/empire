"""Ordered sparse source reads without reserving buffers for reused proofs."""
from contextlib import asynccontextmanager

from empire.plugins.collection.unit_prefetch import prefetch_units


@asynccontextmanager
async def planned_reads(collector, units, fetch, reused, **kwargs):
    selected = [unit for unit in units if unit not in reused]
    async with prefetch_units(collector, selected, fetch, **kwargs) as reads:
        iterator = reads.__aiter__()

        async def ordered():
            for index, unit in enumerate(units):
                if unit in reused:
                    yield index, None
                else:
                    _, read = await anext(iterator)
                    yield index, read
        stream = ordered()
        try:
            yield stream
        finally:
            await stream.aclose()
