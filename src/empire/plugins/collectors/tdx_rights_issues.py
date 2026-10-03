"""Independent TDX 配股 task and capability."""
from empire.contracts.plugin import PluginManifest
from empire.plugins.collectors.capital_lifecycle import collect_units


class TdxRightsIssuesCollector:
    manifest = PluginManifest('collector.tdx_rights_issues', '通达信配股',
        requires=('http.fetch', 'ingest.publish', 'rights_issues.query', 'archive.confirmation', 'collection.records'),
        provides=('collector.tdx_rights_issues',), description='完整来源集合核验、原子入队，整轮末确认归档')
    kind = 'rights_issues'

    def __init__(self):
        self.source, self.project_id, self.job_key = 'tdx', 'tdx-rights-issues', 'tdx-rights-issues-v1'
        self.http = self.ingest = self.query = self.confirmation = self.records = None
        self.request_retries = 2
        self.stats = {'status': 'stopped', 'collected': 0}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.confirmation = context.get('rights_issues.query'), context.get('archive.confirmation')
        self.records = context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.tdx_rights_issues': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def execute(self, *, fresh=False, baseline_revision=0):
        return await collect_units(self, fresh=fresh, baseline_revision=baseline_revision)

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
