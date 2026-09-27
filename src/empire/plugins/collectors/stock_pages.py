"""Concurrent reads with per-page diagnostics and strictly ordered publication."""
from contextvars import ContextVar
from dataclasses import dataclass

from empire.contracts.stocks import normalize_sina_stock
from empire.plugins.collection.prefetch import ordered_prefetch


@dataclass
class PageRead:
    downloaded: object | None
    response: dict | None
    stage: str
    error: Exception | None = None

    def close(self):
        try:
            if self.downloaded is not None:
                self.downloaded.close()
        finally:
            self.downloaded = self.response = self.error = None


class StockPages:
    def init_diagnostics(self):
        self.response_context = ContextVar("stock_response", default=None)
        self.stage_context = ContextVar("stock_stage", default="collection")

    @property
    def _response(self):
        return self.response_context.get()

    @_response.setter
    def _response(self, value):
        self.response_context.set(value)

    @property
    def _stage(self):
        return self.stage_context.get()

    @_stage.setter
    def _stage(self, value):
        self.stage_context.set(value)

    async def collect_pages(self, state, data_url):
        cursor = state["cursor"]
        policy = self.http.response_policy("stocks")
        last = (cursor["expected_count"] + cursor["page_size"] - 1) // cursor["page_size"]

        async def width():
            return await self.http.parallelism(data_url, ("sina.com.cn",))

        async def fetch(page, lease):
            self._response = None
            try:
                response = await self._page_response(page, cursor["page_size"], reservation=lease, policy=policy)
                return PageRead(response, self._response, self._stage)
            except Exception as exc:
                return PageRead(None, self._response, self._stage, exc)

        try:
            async with ordered_prefetch(cursor["next_page"], last, fetch, width,
                    budget=self.http.buffer_budget, reservation_bytes=policy.reservation_bytes,
                    on_state=self.stats.update) as reads:
                async for page, read in reads:
                    self._response, self._stage = read.response, read.stage
                    if read.error:
                        raise read.error
                    self._capture_response(read.downloaded)
                    rows = self._decode_page(read.downloaded)
                    needed = min(cursor["page_size"], cursor["expected_count"] - cursor["collected"])
                    if len(rows) != needed or needed <= 0:
                        raise ValueError(f"第 {page} 页应有 {needed} 条，实际 {len(rows)} 条；未发布完整列表")
                    self._stage = "stock_validation"
                    normalized = [normalize_sina_stock(row) for row in rows]
                    symbols = [row["source_symbol"] for row in normalized]
                    if any(a <= b for a, b in zip(symbols, symbols[1:])) or (
                        cursor["last_symbol"] and cursor["last_symbol"] <= symbols[0]
                    ):
                        raise ValueError(f"第 {page} 页出现重复或排序边界变化，请重新采集")
                    updated = {**cursor, "next_page": page + 1,
                               "collected": cursor["collected"] + len(rows), "last_symbol": symbols[-1]}
                    if updated["collected"] == updated["expected_count"]:
                        updated["phase"] = "verify"
                    state = await self._publish("stock.universe.page", state, updated,
                                                {"page": page, "rows": normalized}, f"page:{page}")
                    cursor = state["cursor"]
                    del rows, normalized, symbols
        finally:
            self.stats["download_concurrency"] = 0
        return state
