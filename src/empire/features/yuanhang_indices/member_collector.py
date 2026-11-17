"""Original THS webpage members over the native catalogue, one complete unit each."""
import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.contracts.security import index_code
from empire.features.yuanhang_indices.collector_support import Publisher
from empire.features.yuanhang_indices.contract import MEMBER_DATASET, digest
from empire.features.yuanhang_indices.members_source import parse_members
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity
from empire.plugins.collectors.ths_session import ThsDirectorySession

BASE = 'https://q.10jqka.com.cn/zs/'


def members_url(code):
    return BASE + f'detail/code/{index_code(code)}/field/code/order/asc/page/1/size/10000/ajax/1/'


class MemberCollector(Publisher):
    capability, query_capability = 'collector.yuanhang_index_members', 'indices.query'
    manifest = PluginManifest('collector.yuanhang_index_members', '同花顺 指数成分',
        requires=('http.fetch', 'ingest.publish', 'indices.query', 'archive.confirmation', 'collection.records'),
        provides=('collector.yuanhang_index_members',))

    def __init__(self):
        super().__init__(MEMBER_DATASET)
        self.session = ThsDirectorySession()

    async def fetch(self, item, *, reservation):
        code = item['code']
        await wait_for_capacity(self.ingest, self.stats)
        policy = self.http.response_policy('generic')
        policy = replace(policy, max_body_bytes=min(policy.max_body_bytes, 8*1024**2),
            max_wire_bytes=min(policy.max_wire_bytes, 8*1024**2))
        response = await self.http.request('GET', members_url(code), headers=self.session.headers(BASE),
            allowed_domains=('10jqka.com.cn',), project_id=self.project_id, policy=policy,
            max_retries=self.request_retries, reservation=reservation)
        async def consume():
            try:
                return parse_members(response.content.decode('gb18030'), code)
            except (ValueError, UnicodeError, TypeError, KeyError) as exc:
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, self.project_id, exc,
                    stage='source_validation', unavailable_message='成分错误样本暂不可用', fields=dict(request_url=members_url(code),
                        raw_body=response.content[:65536], observed_bytes=len(response.content),
                        body_sha256=hashlib.sha256(response.content).hexdigest()))
                raise
        return DeferredResponse(response, consume)

    @measured_run
    async def execute(self, *, fresh=False, baseline_revision=0):
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if cursor.get('phase') == 'complete' and state['revision'] > baseline_revision and not fresh:
                return {k: v for k, v in cursor.items() if k != 'codes'}
            if cursor.get('phase') not in ('collecting', 'awaiting_archive'):
                catalog = await self.query.catalog(self.selected_codes)
                cursor = dict(phase='collecting', batch_id=uuid4().hex, observed_at=datetime.now(UTC).isoformat(),
                    codes=[r['code'] for r in catalog], catalog_hash=digest(catalog), next_index=0, pages=0, collected=0, unavailable=0)
            self.stats.update(status='collecting', total_units=len(cursor['codes']), completed_units=cursor['next_index'])
            if cursor['phase'] != 'awaiting_archive':
                units = [dict(code=c) for c in cursor['codes']]
                async with prefetch_units(self, units, self.fetch, url=BASE, domains=('10jqka.com.cn',),
                        first=cursor['next_index'], item_name='个指数') as reads:
                    async for n, read in reads:
                        result = await read.resolve()
                        self.stats['current_security'] = units[n]['code']
                        cursor = {**cursor, 'next_index': n + 1, 'unavailable': cursor['unavailable'] + int(not result['available'])}
                        if cursor['collected'] + len(result['members']) > 1000000:
                            raise ValueError('当前成员关系超过100万边界')
                        state, cursor = await self.publish(state, cursor, units[n]['code'],
                            dict(code=units[n]['code'], **result), source_url=members_url(units[n]['code']))
                        self.stats.update(completed_units=n+1, unavailable=cursor['unavailable'])
            result = await self.finish(state, cursor)
            return {k: v for k, v in result.items() if k != 'codes'}
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            await self.report_failure(exc, 'members')
            raise
