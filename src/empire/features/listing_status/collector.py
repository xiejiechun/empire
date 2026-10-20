"""Bounded independent day downloads; atomic month publication, independent archive advancement."""
import asyncio
import hashlib
from datetime import UTC, date, datetime, timedelta
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.features.listing_status.contract import DATASET, JOB, PROJECT, bounds, validate_rows
from empire.features.listing_status.source import (
    API_URL,
    PAGE_URL,
    parse,
    request_body,
)
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)


class TdxListingStatusCollector:
    manifest = PluginManifest('collector.tdx_listing_status', '暂停恢复终止上市（通达信）',
        requires=('http.fetch', 'ingest.publish', 'listing_status.query', 'archive.confirmation', 'collection.records'),
        provides=('collector.tdx_listing_status',), description='逐日完整校验；按月入队，整轮结束统一等归档')
    source, project_id, job_key = 'tdx', PROJECT, JOB

    def __init__(self, today=None):
        self.today = today or (lambda: datetime.now(CHINA).date())
        self.stats = dict(status='stopped', collected=0)
        self.request_retries = 2

    async def start(self, context):
        self.http, self.ingest, self.query = context.get('http.fetch'), context.get('ingest.publish'), context.get('listing_status.query')
        self.records, self.confirmation = context.get('collection.records'), context.get('archive.confirmation')
        self.stats['status'] = 'idle'
        return {'collector.tdx_listing_status': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))['revision']

    async def fetch(self, day, *, reservation=None, defer=False):
        await wait_for_capacity(self.ingest, self.stats)
        response = await self.http.request('POST', API_URL, content=request_body(day),
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin': 'http://page2.tdx.com.cn:7615', 'Referer': PAGE_URL},
            allowed_domains=('tdx.com.cn',), project_id=PROJECT,
            policy=self.http.response_policy('generic'), max_retries=self.request_retries,
            reservation=reservation)
        async def consume():
            try:
                return parse(response.json(), day)
            except (ValueError, TypeError, KeyError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, PROJECT, exc,
                    stage='source_validation', unavailable_message='上市状态错误样本暂不可用',
                    fields=dict(request_url=API_URL, raw_body=body[:65536], observed_bytes=len(body),
                                status_code=response.status_code, body_sha256=hashlib.sha256(body).hexdigest()))
                raise
            finally:
                if not defer:
                    response.close()

        if defer:
            return DeferredResponse(response, consume)
        return await consume()

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'planning'
        try:
            state = await self.ingest.checkpoint(JOB)
            cursor = state['cursor']
            if state['revision'] > baseline_revision and cursor.get('phase') == 'complete' and cursor.get('contract') == 1:
                return cursor
            active = cursor.get('phase') in ('fetch', 'awaiting_archive')
            if active and (cursor.get('contract') != 1 or (fresh and not cursor.get('fresh'))):
                raise ValueError('上市状态活跃断点与重新初始化范围冲突，请先继续原轮次')
            if not active:
                cursor = dict(phase='fetch', batch_id=uuid4().hex, through=self.today().isoformat(),
                    fresh=fresh, next_month='1990-12', pages=0, collected=0, dates_checked=0, contract=1)
                state = await self.ingest.advance_checkpoint(job_key=JOB, expected_revision=state['revision'], cursor=cursor)
            through = date.fromisoformat(cursor['through'])
            if cursor['phase'] == 'fetch':
                plan = [m for m in await self.query.plan(through, cursor['fresh']) if m >= cursor['next_month']]
                for month in plan:
                    start, end = bounds(month, through)
                    day, rows, counts = start, [], []
                    observed = datetime.now(UTC)
                    dates = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
                    async def download(day, *, reservation):
                        return await self.fetch(day, reservation=reservation, defer=True)
                    async with prefetch_units(self, dates, download, url=API_URL,
                            domains=('tdx.com.cn',), item_name='日') as reads:
                        async for index, read in reads:
                            day = date.fromisoformat(dates[index])
                            stage = 'source_validation'
                            self.stats.update(status='collecting', current_date=day.isoformat(), current_month=month,
                                              collected=cursor['collected'], pages=cursor['pages'], error='')
                            values, count = await read.resolve()
                            rows.extend(values)
                            counts.append(count)
                            if len(rows) > 5000:
                                raise ValueError('上市状态月份事件超限，断点保留')
                    rows = validate_rows(rows, start, end)
                    page = cursor['pages'] + 1
                    envelope = make_envelope(source='tdx', dataset=DATASET, job_key=JOB,
                        batch_id=cursor['batch_id'], run_id=cursor['batch_id'], business_key=month,
                        payload=dict(page=page, month=month, end=end.isoformat(), rows=rows, source_counts=counts))
                    envelope = envelope.model_copy(update={'observed_at': observed, 'source_url': PAGE_URL, 'available_at': None})
                    updated = {**cursor, 'pages': page, 'next_month': (end.replace(day=1) + timedelta(days=32)).strftime('%Y-%m'),
                        'collected': cursor['collected'] + len(rows), 'dates_checked': cursor['dates_checked'] + len(counts)}
                    stage = 'queue_publish'
                    state = await publish_with_capacity(self.ingest, self.stats, [envelope], job_key=JOB,
                        expected_revision=state['revision'], cursor=updated)
                    cursor = state['cursor']
                cursor = {**cursor, 'phase': 'awaiting_archive'}
                state = await self.ingest.advance_checkpoint(job_key=JOB, expected_revision=state['revision'], cursor=cursor)
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'], pages=cursor['pages'])
            if cursor['pages']:
                await wait_for_archive(partial(self.confirmation.page_status, 'tdx', JOB, PROJECT,
                                              cursor['batch_id'], cursor['pages']), retry_seconds=1)
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
                                    unavailable_message='上市状态错误记录暂不可用，断点保留')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
