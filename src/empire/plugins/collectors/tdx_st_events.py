"""Two independent collectors; one HTTP response and one atomic queue publication each."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.st_events import KINDS, MARKETS, SCHEMA_VERSION, pack_rows, project
from empire.core.time import CHINA
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.tdx_st_source import PAGE, URL, parse, request_body


class StEventCollector:
    def __init__(self, kind):
        self.kind, self.source = kind, 'tdx'
        self.project_id, self.job_key = project(kind), project(kind) + '-v1'
        capability = 'collector.tdx_st_' + kind
        self.manifest = PluginManifest(capability, KINDS[kind][0] + '采集',
            requires=('http.fetch', 'ingest.publish', 'st.' + kind + '.query',
                      'archive.confirmation', 'collection.records'), provides=(capability,),
            description='一次完整历史响应；全部市场入队后等待归档')
        self.stats = {'status': 'stopped', 'collected': 0, 'record_name': '条ST事件',
                      'unit_name': '次完整响应', 'total_units': 1, 'completed_units': 0}
        self.request_retries = 2

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {self.manifest.provides[0]: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def fetch(self, through, *, reservation=None, defer=False):
        await wait_for_capacity(self.ingest, self.stats)
        response = await self.http.request('POST', URL, content=request_body(self.kind, through),
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin': 'http://page2.tdx.com.cn:7615', 'Referer': PAGE},
            allowed_domains=('tdx.com.cn',), project_id=self.project_id,
            policy=self.http.response_policy('generic'), max_retries=self.request_retries,
            reservation=reservation)
        async def consume():
            try:
                return parse(self.kind, response.json(), through)
            except (ValueError, TypeError, KeyError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, self.project_id,
                    exc, stage='source_validation', unavailable_message='ST事件错误样本暂不可用',
                    fields=dict(request_url=URL, status_code=response.status_code, raw_body=body[:65536],
                                observed_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest()))
                raise
            finally:
                if not defer:
                    response.close()

        if defer:
            return DeferredResponse(response, consume)
        return await consume()

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'source_validation'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if (state['revision'] > baseline_revision and cursor.get('phase') == 'complete'
                    and cursor.get('contract') == SCHEMA_VERSION):
                return cursor
            if cursor.get('phase') == 'awaiting_archive' and cursor.get('contract') != SCHEMA_VERSION:
                raise ValueError('旧ST事件待归档断点必须先显式维护，不能跳过')
            if cursor.get('phase') != 'awaiting_archive':
                observed = datetime.now(UTC)
                through, batch = observed.astimezone(CHINA).date().isoformat(), uuid4().hex
                self.stats.update(status='collecting', collected=0, pages=0, error='', completed_units=0)
                async def download(day, *, reservation):
                    return await self.fetch(day, reservation=reservation, defer=True)
                async with prefetch_units(self, [through], download, url=URL,
                        domains=('tdx.com.cn',), item_name='响应') as reads:
                    async for _, read in reads:
                        groups, count = await read.resolve()
                envelopes = []
                for page, market in enumerate(MARKETS, 1):
                    rows = groups[market]
                    event = make_envelope(source='tdx', dataset='st.' + self.kind + '.market',
                        business_key=market, job_key=self.job_key, batch_id=batch, run_id=batch,
                        schema_version=SCHEMA_VERSION,
                        payload=dict(page=page, market=market, through=through, **pack_rows(rows),
                                     source_count=sum(r[4] for r in rows)))
                    envelopes.append(event.model_copy(update={'observed_at': observed,
                                                              'source_url': PAGE, 'available_at': None}))
                stage = 'queue_publish'
                cursor = dict(phase='awaiting_archive', batch_id=batch, pages=3, requests=1,
                              collected=sum(len(rows) for rows in groups.values()), source_count=count,
                              through=through, contract=SCHEMA_VERSION, record_name='条ST事件',
                              unit_name='次完整响应', total_units=1, completed_units=1)
                # All three markets fit or publication fails before any checkpoint/DML.
                state = await publish_with_capacity(self.ingest, self.stats, envelopes,
                    job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'],
                              source_count=cursor['source_count'], pages=3, completed_units=1)
            await wait_for_archive(partial(self.confirmation.page_status, 'tdx', self.job_key,
                self.project_id, cursor['batch_id'], 3), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=self.job_key,
                expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc, stage=stage,
                                    unavailable_message='ST事件错误记录暂不可用；断点未跳过失败')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
