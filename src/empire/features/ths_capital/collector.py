"""One ordered security response, one atomic publish; wait only after the round."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.features.ths_capital.contract import DATASET, JOB, PROJECT, TABLES, digest
from empire.features.ths_capital.source import parse
from empire.features.ths_capital.transport import SCHEMA, pack
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.ths_session import ThsSession


class CapitalPageCollector:
    def __init__(self):
        self.source, self.project_id, self.job_key = 'ths', PROJECT, JOB
        self.manifest = PluginManifest('collector.ths_capital', '公司资本运作（同花顺）',
            requires=('http.fetch', 'ingest.publish', 'ths_capital.query', 'archive.confirmation', 'collection.records'),
            provides=('collector.ths_capital',), description='一次响应采集全部栏目、展开详情及原事件/解除')
        self.stats, self.session, self.request_retries = dict(status='stopped', collected=0), None, 2

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.confirmation = context.get('ths_capital.query'), context.get('archive.confirmation')
        self.records = context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.ths_capital': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))['revision']

    async def fetch(self, stock, *, reservation=None, defer=False):
        await wait_for_capacity(self.ingest, self.stats)
        if self.session is None:
            self.session = ThsSession()
        url = f"https://basic.10jqka.com.cn/{stock['code']}/capital.html"
        observed = datetime.now(UTC)
        response = await self.http.request('GET', url, headers=self.session.headers(url),
            allowed_domains=('10jqka.com.cn',), project_id=PROJECT, policy=self.http.response_policy('generic'),
            max_retries=self.request_retries, reservation=reservation)
        async def consume():
            try:
                return parse(response.content, stock, observed.astimezone(CHINA).date()), observed, url
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, PROJECT, exc,
                    stage='source_validation', unavailable_message='资本运作错误样本暂不可用',
                    fields=dict(request_url=url, status_code=response.status_code, raw_body=body[:65536],
                                observed_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest()))
                raise
            finally:
                if not defer:
                    response.close()
        return DeferredResponse(response, consume) if defer else await consume()

    async def publish(self, state, cursor, unit, value, manifest, observed, url):
        self.stats.update(publication_unit=unit, publication_url=url, publication_bytes=None,
                          publication_limit=getattr(self.ingest, 'settings', {}).get('max_page_bytes', 524288))
        e = make_envelope(source='ths', dataset=DATASET, schema_version=SCHEMA, business_key=unit, job_key=JOB,
            batch_id=cursor['batch_id'], run_id=cursor['batch_id'],
            payload=dict(page=cursor['pages'], unit=unit, **{**value, 'rows': pack(value['rows'])}, manifest=manifest)).model_copy(
                update=dict(observed_at=observed, source_url=url, available_at=None))
        self.stats['publication_bytes'] = len(e.model_dump_json().encode())
        return await publish_with_capacity(self.ingest, self.stats, [e], job_key=JOB,
                                          expected_revision=state['revision'], cursor=cursor)

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(JOB)
            cursor = state['cursor']
            progressed = state['revision'] > baseline_revision
            if progressed and cursor.get('phase') == 'complete':
                return cursor
            if cursor.get('phase') != 'awaiting_archive':
                if (fresh and not progressed) or cursor.get('phase') == 'complete':
                    cursor = {}
                stocks = await self.query.securities()
                keys = [s['unified_code'] for s in stocks]
                if cursor and cursor.get('scope_hash') != digest(keys):
                    cursor = {}
                    self.stats['scope_changed'] = True
                if not cursor:
                    cursor = dict(phase='fetch', batch_id=uuid4().hex, index=0, pages=0, collected=0,
                                  units=len(keys), scope_hash=digest(keys), rolling=digest([]))
                selected = stocks[cursor['index']:]
                first = cursor['index']
                async def download(stock, *, reservation):
                    return await self.fetch(stock, reservation=reservation, defer=True)
                async with prefetch_units(self, selected, download, url='https://basic.10jqka.com.cn/',
                        domains=('10jqka.com.cn',), item_name='股票') as reads:
                    async for number, read in reads:
                        index = first + number
                        self.stats.update(status='collecting', current_security=keys[index], total_units=len(keys),
                                          processed_units=index, pages=cursor['pages'], collected=cursor['collected'])
                        stage = 'source_validation'
                        value, observed, url = await read.resolve()
                        count = sum(map(len, value['rows'].values()))
                        following = {**cursor, 'index': index + 1, 'pages': cursor['pages'] + 1,
                            'collected': cursor['collected'] + count,
                            'rolling': digest([cursor['rolling'], keys[index], digest(value), count])}
                        stage = 'queue_publish'
                        state = await self.publish(state, following, keys[index], value, None, observed, url)
                        cursor = state['cursor']
                following = {**cursor, 'phase': 'awaiting_archive', 'pages': cursor['pages'] + 1}
                manifest = dict(units=len(keys), count=cursor['collected'], securities=keys,
                                scope_hash=digest(keys), digest=cursor['rolling'])
                state = await self.publish(state, following, 'manifest', dict(rows={t: [] for t in TABLES},
                    availability={}), manifest, datetime.now(UTC), None)
                cursor = state['cursor']
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', pages=cursor['pages'], collected=cursor['collected'])
            await wait_for_archive(partial(self.confirmation.page_status, 'ths', JOB, PROJECT,
                                          cursor['batch_id'], cursor['pages']), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=JOB, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', completed_units=cursor['units'], error='')
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, PROJECT, exc, stage=stage,
                unavailable_message='资本运作失败位置已保留，错误记录暂不可用',
                fields=dict(request_url=self.stats.get('publication_url') or '', metadata={
                    k: self.stats[k] for k in ('publication_unit', 'publication_bytes', 'publication_limit')
                    if k in self.stats}) if stage == 'queue_publish' else None)
            raise

    async def stop(self):
        self.session = None
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
