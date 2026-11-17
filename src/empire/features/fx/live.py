"""Independent Redis-only task: no SQL capability or durable checkpoint."""
from functools import partial

from empire.contracts.collector import CollectionSourceGap
from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.features.fx.contract import BASE, LIVE_JOB, LIVE_PROJECT, SYMBOLS
from empire.features.fx.latest import LatestStore
from empire.features.fx.source import QuoteUnavailable
from empire.features.fx.transport import Transport
from empire.plugins.collection.unit_prefetch import prefetch_units


class FxLatestQuery(LatestStore):
    manifest = PluginManifest('data.fx_latest', '汇率最新行情', requires=('redis.store',),
        provides=('fx.latest.query',))

    def __init__(self):
        self.redis = None

    async def start(self, context):
        super().__init__(context.get('redis.store'))
        return {'fx.latest.query': self}

    async def stop(self):
        self.redis = None

    def health(self):
        return {'status': 'ok' if self.redis else 'stopped'}


class FxLiveCollector(Transport):
    manifest = PluginManifest('collector.ths_fx_live', '同花顺汇率实时行情',
        requires=('http.fetch', 'ingest.publish', 'fx.latest.query', 'collection.records'),
        provides=('collector.ths_fx_live',))

    def __init__(self):
        self.source, self.project_id, self.job_key = 'ths', LIVE_PROJECT, LIVE_JOB
        self.selected_codes, self.request_retries = None, 2
        self.stats = {'status': 'stopped', 'collected': 0}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.store, self.records = context.get('fx.latest.query'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.ths_fx_live': self}

    async def checkpoint_revision(self):
        return 0

    @measured_run
    async def execute(self, *, fresh=False, baseline_revision=0):
        codes = self.codes()
        self.stats.update(status='collecting', collected=0, queued_messages=0, total_units=len(codes),
                          completed_units=0, unavailable_codes=[], source_gap_units=0,
                          storage='redis_only', notice='')
        async def download(code, *, reservation):
            return await self.fetch(code, 'live', reservation=reservation)
        try:
            async with prefetch_units(self, codes, download, url=BASE, domains=('10jqka.com.cn',), item_name='汇率品种') as reads:
                async for i, read in reads:
                    try:
                        quote = await read.resolve()
                    except QuoteUnavailable:
                        self.stats['unavailable_codes'].append(codes[i])
                        self.stats['source_gap_units'] += 1
                        self.stats['completed_units'] = i + 1
                        continue
                    await self.ingest.publish_volatile(self.project_id, partial(self.store.save, quote))
                    self.stats.update(collected=self.stats['collected'] + 1, completed_units=i + 1)
            if self.stats['unavailable_codes']:
                self.stats['notice'] = ('来源暂无报价：' + '、'.join(self.stats['unavailable_codes'])
                    + f"；本轮更新{self.stats['collected']}/{len(codes)}个品种，保留其余上次有效值，下轮重新采样")
                raise CollectionSourceGap(self.stats['notice'])
            self.stats['status'] = 'complete'
            return dict(phase='complete', storage='redis_only', collected=len(codes), queued_messages=0)
        except CollectionSourceGap:
            self.stats['status'] = 'source_gap'
            raise
        except BaseException:
            self.stats['status'] = 'paused'
            raise

    def codes(self):
        from empire.features.fx.contract import symbol
        codes = list(SYMBOLS) if self.selected_codes is None else list(self.selected_codes)
        if not codes or len(codes) > 12 or len(codes) != len(set(codes)):
            raise ValueError('汇率采集品种范围无效')
        return [symbol(code) for code in codes]

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
