"""Scheduled trading-session sampling and explicit manual off-hours sampling."""
import asyncio
from datetime import UTC, datetime
from functools import partial

from empire.contracts.collector import COLLECTION_ORIGIN
from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.core.time import CHINA
from empire.features.yuanhang_etf.collector_support import Publisher
from empire.features.yuanhang_etf.contract import CATALOG_DATASET, LATEST_PROJECT, MARKETS, digest
from empire.features.yuanhang_etf.native import fetch_latest
from empire.plugins.collection.unit_prefetch import prefetch_units


class LiveCollector(Publisher):
    capability = 'collector.yuanhang_etf_latest'
    manifest = PluginManifest('collector.yuanhang_etf_latest', '同花顺远航版 ETF最新行情',
        requires=('http.fetch', 'ingest.publish', 'collection.records', 'yuanhang.identity',
                  'yuanhang.etfs.query', 'yuanhang.etf.latest.query', 'calendar.query'), provides=(capability,))

    def __init__(self):
        super().__init__(CATALOG_DATASET)
        self.project_id, self.job_key = LATEST_PROJECT, LATEST_PROJECT + '-v1'

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.records, self.identity = context.get('collection.records'), context.get('yuanhang.identity')
        self.directory, self.store = context.get('yuanhang.etfs.query'), context.get('yuanhang.etf.latest.query')
        self.calendar = context.get('calendar.query')
        self.stats['status'] = 'idle'
        return {self.capability: self}

    async def checkpoint_revision(self):
        return 0

    async def should_sample(self, now):
        if COLLECTION_ORIGIN.get() != 'schedule':
            return True
        month = await self.calendar.month(now.strftime('%Y-%m'))
        if not month['complete']:
            raise ValueError('ETF定时采样需要完整的正式交易日历')
        trading = next((r['is_trade'] for r in month['rows'] if r['trade_date'] == now.date().isoformat()), None)
        if trading is None:
            raise ValueError('ETF定时采样缺少当日日历')
        clock = now.strftime('%H:%M')
        return trading and ('09:15' <= clock <= '11:30' or '13:00' <= clock <= '15:05')

    async def fetch(self, unit, *, reservation):
        market, codes = unit
        async def operation(session, **kwargs):
            return await fetch_latest(self.http, session, market, codes, project_id=self.project_id, **kwargs)
        return await self.authenticated(operation, reservation=reservation)

    @measured_run
    async def execute(self, *, fresh=False, baseline_revision=0):
        self.stats.update(status='collecting', collected=0, queued_messages=0, storage='redis_only')
        try:
            if not await self.should_sample(datetime.now(CHINA)):
                self.stats['status'] = 'complete'
                return dict(phase='complete', sampled=False, storage='redis_only', queued_messages=0,
                    notice='盘外或非交易日跳过定时采样；可手动采样一次，来源报价时间仍未知。')
            catalog = await self.directory.catalog(self.selected_codes)
            observed = datetime.now(UTC).isoformat()
            units = [(m, [r['code'] for r in catalog if r['native_market'] == m]) for m in MARKETS]
            units = [(m, codes) for m, codes in units if codes]
            rows = []
            async with prefetch_units(self, units, self.fetch, url='https://10jqka.com.cn/',
                    domains=('10jqka.com.cn',), item_name='个市场') as reads:
                async for _, read in reads:
                    rows.extend(await read.resolve())
            rows.sort(key=lambda r: r['code'])
            if [{k: r[k] for k in ('code', 'native_market', 'name')} for r in rows] != catalog:
                raise ValueError('ETF最新结果与本轮目录集合或名称不符，请先更新目录')
            saved = await self.ingest.publish_volatile(self.project_id, partial(self.store.save,
                dict(schema=1, catalog_hash=digest(catalog), observed_at=observed, rows=rows)))
            self.stats.update(status='complete', collected=len(rows))
            return dict(phase='complete', sampled=True, published=saved, collected=len(rows),
                storage='redis_only', queued_messages=0, source_time_unknown=True)
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            await self.report_failure(exc, 'etf_latest')
            raise
