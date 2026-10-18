"""One rolling directory and independently downloadable complete months."""
import asyncio
import hashlib
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.unlock_industries import DATASET, JOB, PROJECT, basis, digest, month
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.tdx_unlock_industry_source import (
    DIRECTORY_URL,
    PAGE,
    URL,
    body,
    parse_directory,
    parse_month,
)


class UnlockIndustryCollector:
    project_id, job_key = PROJECT, JOB
    manifest = PluginManifest('collector.tdx_unlock_industries', '大小非解禁行业采集',
        requires=('http.fetch', 'ingest.publish', 'unlock_industries.tdx_query',
                  'archive.confirmation', 'collection.records'),
        provides=('collector.tdx_unlock_industries',), description='可得月行业完整集合与估值基准日')

    def __init__(self):
        self.request_retries = 2
        self.stats = dict(status='stopped', collected=0, requests=0, completed_units=0,
                          record_name='条行业汇总', unit_name='个月')

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.tdx_unlock_industries': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))['revision']

    async def fetch(self, unit=None, *, reservation=None):
        await wait_for_capacity(self.ingest, self.stats)
        params = ['dxfhy', '0'] if unit is None else [unit[:7].replace('-', ''), self.basis_date.replace('-', '')]
        url = DIRECTORY_URL if unit is None else URL
        response = await self.http.request('POST', url, content=body(params),
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'Referer': PAGE},
            allowed_domains=('tdx.com.cn',), project_id=PROJECT, policy=self.http.response_policy('generic'),
            max_retries=self.request_retries, reservation=reservation)
        self.stats['requests'] += 1
        async def consume():
            try:
                return parse_directory(response.json()) if unit is None else parse_month(response.json(), unit, self.basis_date)
            except (ValueError, TypeError, KeyError) as exc:
                raw = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, PROJECT, exc,
                    stage='source_validation', unavailable_message='解禁行业来源诊断暂不可用',
                    fields=dict(request_url=url, status_code=response.status_code, raw_body=raw[:65536],
                                observed_bytes=len(raw), body_sha256=hashlib.sha256(raw).hexdigest(),
                                metadata={'params': params}))
                raise
        return DeferredResponse(response, consume)

    def envelope(self, cursor, unit, rows, manifest=None):
        event = make_envelope(source='tdx', dataset=DATASET, business_key=unit, job_key=JOB,
            batch_id=cursor['batch_id'], run_id=cursor['batch_id'], schema_version=1,
            payload=dict(page=cursor['page'] + 1, unit=unit, basis_date=cursor['basis_date'], rows=rows, manifest=manifest))
        return event.model_copy(update={'source_url': PAGE, 'available_at': None})

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(JOB)
            cursor = state['cursor']
            progressed = state['revision'] > baseline_revision
            if progressed and cursor.get('phase') == 'complete':
                return cursor
            if cursor and cursor.get('contract') != 1:
                raise ValueError('解禁行业旧断点须显式维护')
            if cursor.get('phase') != 'awaiting_archive':
                if cursor.get('phase') == 'complete' or fresh and not progressed:
                    cursor = {}
                if not cursor:
                    response = await self.fetch()
                    try:
                        months, self.basis_date = await response.consume()
                    finally:
                        response.close()
                    cursor = dict(phase='fetch', contract=1, months=months, basis_date=self.basis_date,
                        index=0, page=0, collected=0, rolling='', batch_id=uuid4().hex)
                else:
                    if (not isinstance(cursor.get('months'), list) or not 1 <= len(cursor['months']) <= 120
                            or cursor['months'] != sorted(set(cursor['months']))
                            or not 0 <= cursor['index'] <= len(cursor['months'])):
                        raise ValueError('解禁行业断点目录错误')
                    for unit in cursor['months']:
                        month(unit)
                    self.basis_date = basis(cursor['basis_date'])
                self.stats.update(status='collecting', error='', collected=cursor['collected'],
                                  completed_units=cursor['index'], total_units=len(cursor['months']))
                stage = 'source_download'
                async with prefetch_units(self, cursor['months'][cursor['index']:], self.fetch,
                        url=URL, domains=('tdx.com.cn',), item_name='行业月份') as reads:
                    async for _, response in reads:
                        unit = cursor['months'][cursor['index']]
                        rows = await response.resolve()
                        event = self.envelope(cursor, unit, rows)
                        next_cursor = {**cursor, 'index': cursor['index'] + 1, 'page': cursor['page'] + 1,
                            'collected': cursor['collected'] + len(rows),
                            'rolling': digest([cursor['rolling'], unit, digest(rows), len(rows)])}
                        stage = 'queue_publish'
                        state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=JOB,
                            expected_revision=state['revision'], cursor=next_cursor)
                        cursor = next_cursor
                        self.stats.update(collected=cursor['collected'], completed_units=cursor['index'], pages=cursor['page'])
                manifest = dict(months=cursor['months'], count=cursor['collected'], digest=cursor['rolling'])
                event = self.envelope(cursor, 'manifest', [], manifest)
                cursor = {**cursor, 'phase': 'awaiting_archive', 'page': cursor['page'] + 1}
                state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=JOB,
                    expected_revision=state['revision'], cursor=cursor)
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'], pages=cursor['page'])
            await wait_for_archive(partial(self.confirmation.page_status, 'tdx', JOB, PROJECT,
                cursor['batch_id'], cursor['page']), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=JOB, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, PROJECT, exc, stage=stage,
                                    unavailable_message='解禁行业错误记录暂不可用')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
