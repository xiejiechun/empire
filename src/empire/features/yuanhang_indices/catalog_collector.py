"""Complete native D2-equivalent index catalogue, independently scheduled."""
import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.features.yuanhang_indices.collector_support import Publisher
from empire.features.yuanhang_indices.contract import CATALOG_DATASET
from empire.features.yuanhang_indices.native import fetch_catalog


class CatalogCollector(Publisher):
    capability, query_capability = 'collector.yuanhang_indices', 'yuanhang.indices.query'
    manifest = PluginManifest('collector.yuanhang_indices', '同花顺远航版 A股指数',
        requires=('http.fetch', 'ingest.publish', 'yuanhang.indices.query', 'yuanhang.identity', 'archive.confirmation', 'collection.records'),
        provides=('collector.yuanhang_indices',))

    def __init__(self):
        super().__init__(CATALOG_DATASET)

    @measured_run
    async def execute(self, *, fresh=False, baseline_revision=0):
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if cursor.get('phase') == 'complete' and state['revision'] > baseline_revision and not fresh:
                return cursor
            if cursor.get('phase') in ('collecting', 'awaiting_archive') and cursor['pages']:
                return await self.finish(state, cursor)
            self.stats.update(status='collecting', total_units=1, completed_units=0)
            async def fetch(session, **kwargs):
                return await fetch_catalog(self.http, session, project_id=self.project_id)
            rows = await self.authenticated(fetch)
            cursor = dict(phase='collecting', batch_id=uuid4().hex, observed_at=datetime.now(UTC).isoformat(), pages=0, collected=0)
            state, cursor = await self.publish(state, cursor, 'catalog', dict(catalog=rows), source_url='yuanhang://240/D2')
            result = await self.finish(state, cursor)
            self.stats['completed_units'] = 1
            return result
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            await self.report_failure(exc, 'catalog')
            raise
