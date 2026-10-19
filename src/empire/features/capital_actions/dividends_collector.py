"""Independent TDX 分红送转 task and capability."""
from empire.contracts.plugin import PluginManifest
from empire.features.capital_actions.lifecycle import collect_units


class TdxDividendsCollector:
    manifest = PluginManifest('collector.tdx_dividends', '通达信分红送转',
        requires=('http.fetch', 'ingest.publish', 'dividends.query', 'archive.confirmation', 'collection.records'),
        provides=('collector.tdx_dividends',), description='完整来源集合核验、原子入队，整轮末确认归档')
    kind = 'dividends'

    def __init__(self):
        self.source, self.project_id, self.job_key = 'tdx', 'tdx-dividends', 'tdx-dividends-v1'
        self.http = self.ingest = self.query = self.confirmation = self.records = None
        self.request_retries = 2
        self.stats = {'status': 'stopped', 'collected': 0}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.confirmation = context.get('dividends.query'), context.get('archive.confirmation')
        self.records = context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.tdx_dividends': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def execute(self, *, fresh=False, baseline_revision=0):
        return await collect_units(self, fresh=fresh, baseline_revision=baseline_revision)

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
