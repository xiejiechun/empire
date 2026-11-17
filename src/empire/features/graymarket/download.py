"""Source reads through the existing downloader and retained-unit byte budget."""

import hashlib
from datetime import UTC, datetime

from empire.core.time import CHINA
from empire.features.graymarket.contract import MAX_DAY_BYTES, PROJECT
from empire.features.graymarket.source import (
    DOMAINS,
    HEADERS,
    URL,
    DayAssembly,
    decode,
    params,
)
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity


class GraymarketDownload:
    """Mixin for the collector; does not own HTTP clients, queues or SQL."""

    async def read_page(self, stamp, page, *, reservation=None):
        await wait_for_capacity(self.ingest, self.stats)
        response = await self.http.request(
            "GET",
            URL,
            params=params(stamp, page),
            headers=HEADERS,
            allowed_domains=DOMAINS,
            project_id=PROJECT,
            policy=self.http.response_policy("generic"),
            max_retries=self.request_retries,
            reservation=reservation,
        )
        self.stats["requests"] = self.stats.get("requests", 0) + 1
        cost = response.extensions.get("download", {})
        self.stats["response_bytes"] = self.stats.get("response_bytes", 0) + cost.get("body_bytes", len(response.content))
        self.stats["wire_bytes"] = self.stats.get("wire_bytes", 0) + cost.get("wire_bytes", 0)
        try:
            try:
                return decode(
                    response.content,
                    page=page,
                    requested=stamp,
                    through=datetime.now(CHINA).date().isoformat(),
                )
            except (ValueError, TypeError, KeyError) as exc:
                raw = response.content
                exc.diagnostic_recorded = await record_error_safely(
                    self.records,
                    self.stats,
                    PROJECT,
                    exc,
                    stage="source_validation",
                    unavailable_message="资金榜诊断暂不可用",
                    fields=dict(
                        request_url=URL,
                        status_code=response.status_code,
                        raw_body=raw[:65536],
                        observed_bytes=len(raw),
                        body_sha256=hashlib.sha256(raw).hexdigest(),
                        metadata={"date": stamp, "page": page},
                    ),
                )
                raise
        finally:
            response.close()

    async def fetch_day(self, stamp, *, reservation=None, first=None):
        """Called under prefetch_units(retained_bytes=MAX_DAY_BYTES).

        Pages are read in order; the retained reservation belongs to the whole
        daily unit and is released by the shared prefetch owner on cancellation.
        No partial day escapes this function.
        """
        observed = datetime.now(UTC)
        if first is None:
            first = await self.read_page(stamp, 1, reservation=reservation)
        else:
            first, observed = first
            if first.date != stamp or first.number != 1:
                raise ValueError("资金榜复用第一页与目标日期不一致")
        assembly = DayAssembly(first)
        for page in range(2, first.pages + 1):
            assembly.add(await self.read_page(stamp, page, reservation=reservation))
        return assembly.finish(), observed

    def daily_reads(self, dates, *, discovered=None):
        """Independent dates; ordered publication and shared byte/exit bounds."""

        async def fetch(stamp, *, reservation):
            first = discovered if discovered and discovered[0].date == stamp else None
            return await self.fetch_day(stamp, reservation=reservation, first=first)

        return prefetch_units(
            self,
            dates,
            fetch,
            url=URL,
            domains=DOMAINS,
            independent=True,
            retained_bytes=MAX_DAY_BYTES,
            item_name="完整交易日",
        )
