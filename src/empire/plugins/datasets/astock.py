from __future__ import annotations

import hashlib
import json

from empire.contracts.data import Envelope, UnsupportedSchema, make_envelope
from empire.contracts.plugin import PluginContext, PluginManifest
from empire.plugins.datasets import news, stocks, trade_calendar


class DatasetPlugin:
    manifest = PluginManifest(
        "dataset.astock", "数据契约", provides=("dataset.catalog",),
        description="内部股票、财经新闻和交易日历数据契约、校验及业务表写入",
    )

    async def start(self, context: PluginContext) -> dict:
        return {"dataset.catalog": self}

    async def stop(self) -> None:
        pass

    def health(self) -> dict:
        return {"schemas": [f"{d}@1" for d in sorted(stocks.DATASETS | news.DATASETS | trade_calendar.DATASETS)]}

    def mapping(self, envelope):
        if envelope.schema_version == 1:
            if envelope.dataset in stocks.DATASETS:
                return stocks
            if envelope.dataset in news.DATASETS:
                return news
            if envelope.dataset in trade_calendar.DATASETS:
                return trade_calendar
        raise UnsupportedSchema(f"缺少数据映射 {envelope.dataset}@{envelope.schema_version}，消息保留在 Redis")

    def incremental(self, envelope):
        return self.mapping(envelope) in (news, trade_calendar)

    def observation_partition(self, envelope, normalized):
        """Full-month calendars have no source version; retain latest observation in Redis."""
        return normalized["month"] if self.mapping(envelope) is trade_calendar else None

    def normalize(self, envelope: Envelope) -> dict:
        mapping = self.mapping(envelope)
        payload = envelope.raw_payload
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()).hexdigest()
        if digest != envelope.content_hash:
            raise ValueError("Payload hash mismatch")
        identity = json.dumps([
            envelope.source, envelope.dataset, envelope.schema_version,
            envelope.business_key, envelope.content_hash,
        ], separators=(",", ":"))
        if hashlib.sha256(identity.encode()).hexdigest() != envelope.event_id:
            raise ValueError("Event identity mismatch")
        return mapping.normalize(envelope)

    def canonicalize(self, envelope: Envelope) -> Envelope:
        normalized = self.normalize(envelope)
        payload = self.mapping(envelope).canonical_payload(envelope, normalized)
        event = make_envelope(source=envelope.source, dataset=envelope.dataset,
                              business_key=envelope.business_key, job_key=envelope.job_key,
                              run_id=envelope.run_id, batch_id=envelope.batch_id, payload=payload)
        return event.model_copy(update={"observed_at": envelope.observed_at,
                                        "source_url": envelope.source_url,
                                        "available_at": envelope.available_at})

    def assemble(self, records: list[dict], *, include_rows: bool = True) -> dict | None:
        return stocks.assemble(records, include_rows=include_rows)

    def current(self, engine, source: str) -> dict | None:
        return stocks.current(engine, source)

    def write(self, connection, envelope: Envelope, normalized: dict) -> dict:
        return self.mapping(envelope).write(connection, envelope, normalized)
