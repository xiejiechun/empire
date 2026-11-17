"""Shared proxy/download resources; no independent clients or SQL writes."""

import hashlib
from datetime import UTC, datetime

from empire.features.etf_fundamentals import source
from empire.features.etf_fundamentals.contract import MAX_BYTES
from empire.features.etf_fundamentals.xlsx import szse_workbook
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity


class Downloads:
    async def read(self, url, params, parser, reservation):
        await wait_for_capacity(self.ingest, self.stats)
        response = await self.http.request(
            "GET",
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0", "Referer": self.referer},
            allowed_domains=self.domains,
            project_id=self.project_id,
            policy=self.http.response_policy("generic"),
            max_retries=self.request_retries,
            reservation=reservation,
        )
        self.stats["requests"] += 1
        cost = response.extensions.get("download", {})
        self.stats["response_bytes"] += cost.get("body_bytes", len(response.content))
        self.stats["wire_bytes"] += cost.get("wire_bytes", 0)
        try:
            try:
                return parser(response.content)
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                raw = response.content
                exc.diagnostic_recorded = await record_error_safely(
                    self.records,
                    self.stats,
                    self.project_id,
                    exc,
                    stage="source_validation",
                    unavailable_message="ETF来源错误记录暂不可用",
                    fields=dict(
                        request_url=url,
                        status_code=response.status_code,
                        raw_body=raw[:65536],
                        observed_bytes=len(raw),
                        body_sha256=hashlib.sha256(raw).hexdigest(),
                        metadata={"params": params},
                    ),
                )
                raise
        finally:
            response.close()

    async def fetch_unit(self, unit, *, reservation):
        observed = datetime.now(UTC)
        if self.source == "sse":
            rows, count = [], 0
            for group in source.SQL_IDS:
                total, pages, first = await self.read(
                    source.SSE_URL,
                    source.sse_params(unit["date"], group),
                    lambda raw: source.sse_page(raw, unit["date"], group, 1),
                    reservation,
                )
                rows.extend(first)
                for page in range(2, pages + 1):
                    t, p, values = await self.read(
                        source.SSE_URL,
                        source.sse_params(unit["date"], group, page),
                        lambda raw, n=page: source.sse_page(raw, unit["date"], group, n),
                        reservation,
                    )
                    if (t, p) != (total, pages):
                        raise ValueError("上交所ETF跨页集合变化，拒绝发布")
                    rows.extend(values)
                count += total
            return source.finish_shares(rows, self.source, count), observed
        if self.source == "szse":
            stamp = unit["date"]
            total, first = await self.read(
                source.SZSE_URL + "/data",
                source.szse_params(stamp),
                lambda raw: source.szse_head(raw, stamp),
                reservation,
            )
            rows = await self.read(
                source.SZSE_URL,
                source.szse_params(stamp, "xlsx"),
                lambda raw: szse_workbook(raw, stamp, total, first),
                reservation,
            )
            return rows, observed
        code, first, last = unit["code"], unit["start"], unit["through"]
        params = dict(fundCode=code[:6], pageIndex=1, pageSize=20, startDate=first, endDate=last)
        total, signature, rows = await self.read(
            source.NAV_URL,
            params,
            lambda raw: source.nav_page(raw, code, first, last, 1),
            reservation,
        )
        retained = sum(len(str(r)) for r in rows)
        for page in range(2, (total + 19) // 20 + 1):
            count, metadata, values = await self.read(
                source.NAV_URL,
                {**params, "pageIndex": page},
                lambda raw, n=page: source.nav_page(raw, code, first, last, n),
                reservation,
            )
            if (
                count != total
                or metadata != signature
                or values
                and rows
                and values[0][0] >= rows[-1][0]
            ):
                raise ValueError("天天基金跨页重排或元数据变化，拒绝发布")
            rows.extend(values)
            retained += sum(len(str(r)) for r in values)
            if retained > 8 * 1024 * 1024:
                raise ValueError("ETF证券历史规范正文超过8MiB")
        return source.finish_nav(rows, first, last, total), observed

    def reads(self, units):
        return prefetch_units(
            self,
            units,
            self.fetch_unit,
            url=self.url,
            domains=self.domains,
            independent=True,
            retained_bytes=8 * 1024 * 1024 if self.source == "ttjj" else MAX_BYTES,
            item_name="ETF完整来源单元",
        )
