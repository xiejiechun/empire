"""Two independent collectors; one HTTP response and one atomic queue publication each."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.name_changes import KINDS, MARKETS, project
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.tdx_name_source import PAGE, URL, parse, request_body


class NameChangeCollector:
    def __init__(self, kind):
        self.kind, self.source = kind, 'tdx'
        self.project_id, self.job_key = project(kind), project(kind) + '-v1'
        capability = 'collector.tdx_' + kind + '_renames'
        self.manifest = PluginManifest(capability, KINDS[kind][0] + '采集',
            requires=('http.fetch', 'ingest.publish', 'names.' + kind + '.query',
                      'archive.confirmation', 'collection.records'), provides=(capability,),
            description='一次完整历史响应；全部市场入队后等待归档')
        self.stats = {'status': 'stopped', 'collected': 0}
        self.request_retries = 2

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {self.manifest.provides[0]: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def fetch(self, through):
        await wait_for_capacity(self.ingest, self.stats)
        response = await self.http.request('POST', URL, content=request_body(self.kind, through),
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin': 'http://page2.tdx.com.cn:7615', 'Referer': PAGE},
            allowed_domains=('tdx.com.cn',), project_id=self.project_id,
            policy=self.http.response_policy('generic'), max_retries=self.request_retries)
        try:
            return parse(self.kind, response.json(), through)
        except (ValueError, TypeError, KeyError) as exc:
            body = response.content
            exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, self.project_id,
                exc, stage='source_validation', unavailable_message='更名错误样本暂不可用',
                fields=dict(request_url=URL, status_code=response.status_code, raw_body=body[:65536],
                            observed_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest()))
            raise
        finally:
            response.close()

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'source_validation'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if state['revision'] > baseline_revision and cursor.get('phase') == 'complete':
                return cursor
            if cursor.get('phase') != 'awaiting_archive':
                observed = datetime.now(UTC)
                through, batch = observed.astimezone(CHINA).date().isoformat(), uuid4().hex
                self.stats.update(status='collecting', collected=0, pages=0, error='')
                groups, count = await self.fetch(through)
                envelopes = []
                for page, market in enumerate(MARKETS, 1):
                    rows = groups[market]
                    event = make_envelope(source='tdx', dataset='names.' + self.kind + '.market',
                        business_key=market, job_key=self.job_key, batch_id=batch, run_id=batch,
                        payload=dict(page=page, market=market, through=through, rows=rows,
                                     source_count=sum(r[4] for r in rows)))
                    envelopes.append(event.model_copy(update={'observed_at': observed,
                                                              'source_url': PAGE, 'available_at': None}))
                stage = 'queue_publish'
                cursor = dict(phase='awaiting_archive', batch_id=batch, pages=3, requests=1,
                              collected=sum(len(rows) for rows in groups.values()), source_count=count,
                              through=through)
                # All three markets fit or publication fails before any checkpoint/DML.
                state = await publish_with_capacity(self.ingest, self.stats, envelopes,
                    job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'],
                              source_count=cursor['source_count'], pages=3)
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
                                    unavailable_message='更名错误记录暂不可用；断点未跳过失败')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
