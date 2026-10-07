"""Prefetch unique issue IDs, validate in order, then assemble complete securities."""
from contextlib import asynccontextmanager

from empire.plugins.collection.unit_prefetch import UnitRead, prefetch_units
from empire.plugins.collectors.tdx_issue_detail import URL, attach_detail, fetch_detail


@asynccontextmanager
async def issue_units(c, keys, units, aliases, reusable, previous, observed, *, first):
    needed, planned = [], set()
    for unit in keys[first:]:
        for row in units[unit]:
            ident = row['data']['source_id']
            if ident not in reusable and ident not in planned:
                needed.append(row)
                planned.add(ident)

    async def download(row, *, reservation):
        c.stats['details_requested'] += 1
        return await fetch_detail(c, row, aliases[row['data']['source_id']],
                                  reservation=reservation, defer=True)

    async with prefetch_units(c, needed, download, url=URL, domains=('tdx.com.cn',), item_name='方案') as reads:
        cache = {}
        remaining = {}
        for unit in keys[first:]:
            for row in units[unit]:
                ident = row['data']['source_id']
                remaining[ident] = remaining.get(ident, 0) + 1

        async def results():
            for index in range(first, len(keys)):
                rows, error = [], None
                for row in units[keys[index]]:
                    ident = row['data']['source_id']
                    detail = reusable.get(ident)
                    if detail is not None:
                        c.stats['details_reused'] += 1
                    elif ident in cache:
                        detail = cache[ident]
                    else:
                        number, read = await anext(reads)
                        assert needed[number]['data']['source_id'] == ident
                        try:
                            detail = await read.resolve()
                        except Exception as exc:
                            detail = exc
                        finally:
                            read.close()
                        if remaining[ident] > 1:
                            cache[ident] = detail
                    remaining[ident] -= 1
                    if not remaining[ident]:
                        cache.pop(ident, None)
                    if isinstance(detail, Exception):
                        error = error or detail
                    else:
                        rows.append(attach_detail(c, row, detail, previous))
                yield index, UnitRead(value=(rows, observed), error=error)

        iterator = results()
        try:
            yield iterator
        finally:
            await iterator.aclose()
