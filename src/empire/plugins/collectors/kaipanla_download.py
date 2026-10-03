"""Use the shared bounded prefetcher; validate source parts and emit days in order."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

from empire.plugins.collection.prefetch import ordered_prefetch
from empire.plugins.collectors.kaipanla_source import (
    DOMAIN,
    URL,
    SourceError,
    combine_day,
    consume_part,
    request_options,
)
from empire.plugins.collectors.support import wait_for_capacity


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

    async def fetch(number, lease):
        day, kind = days[number // 2], 'auction' if number % 2 else 'trend'
        observed = datetime.now(UTC)
        try:
            await wait_for_capacity(collector.ingest, collector.stats)
            response = await collector.http.request('POST', URL,
                attempt_options=partial(request_options, stock['code'], day, kind), max_redirects=0,
                allowed_domains=(DOMAIN,), project_id=collector.project_id,
                policy=policy, reservation=lease, max_retries=collector.request_retries)
            return PartRead(response, observed)
        except Exception as exc:
            return PartRead(None, observed, exc)

    async def consume(reads):
        trend = error = observed = None
        async for number, read in reads:
            index, kind = number // 2, 'auction' if number % 2 else 'trend'
            day = days[index]
            if not number % 2:
                trend, error, observed = None, None, read.observed
            if read.error:
                raise read.error  # Infrastructure failures retain the ordered frontier.
            try:
                part = None if error else await consume_part(collector, read.response,
                    stock['code'], day, kind, stock['market'], stock['listing_date'])
                if not number % 2:
                    trend = part
            except SourceError as exc:
                error = error or exc
            if number % 2:
                try:
                    row = None if error else combine_day(trend, part)
                except SourceError as exc:
                    row, error = None, exc
                yield index, day, row, observed, error

    async with ordered_prefetch(0, 2 * len(days) - 1, fetch, width,
            budget=collector.http.buffer_budget, reservation_bytes=policy.reservation_bytes,
            on_state=collector.stats.update) as reads:
        results = consume(reads)
        try:
            yield results
        finally:
            await results.aclose()
