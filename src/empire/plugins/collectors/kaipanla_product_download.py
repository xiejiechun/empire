"""One necessary response per day, ordered validation over shared bounded prefetch."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from empire.plugins.collection.prefetch import ordered_prefetch
from empire.plugins.collectors.kaipanla_products_source import consume, fetch
from empire.plugins.collectors.kaipanla_source import DOMAIN, URL, SourceError


@dataclass
class PartRead:
    response: object | None
    observed: object
    error: Exception | None = None

    def close(self):
        if self.response is not None:
            self.response.close()
        self.response = None


@asynccontextmanager
async def download_days(collector, stock, days):
    policy = collector.http.response_policy('generic')

    async def width():
        return await collector.http.parallelism(URL, (DOMAIN,))

    async def download(number, lease):
        observed = datetime.now(UTC)
        try:
            return PartRead(await fetch(collector, stock, days[number], lease, policy), observed)
        except Exception as exc:
            return PartRead(None, observed, exc)

    async def consume_days(reads):
        async for number, read in reads:
            if read.error:
                raise read.error
            try:
                row = await consume(collector, read.response, stock, days[number])
                yield number, days[number], row, read.observed, None
            except SourceError as exc:
                yield number, days[number], None, read.observed, exc

    async with ordered_prefetch(0, len(days) - 1, download, width,
            budget=collector.http.buffer_budget, reservation_bytes=policy.reservation_bytes,
            on_state=collector.stats.update) as reads:
        results = consume_days(reads)
        try:
            yield results
        finally:
            await results.aclose()
