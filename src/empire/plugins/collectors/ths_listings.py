"""Sequential securities, independent archive, one request per necessary detail."""
import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.listings import (
    DATASET,
    JOB,
    PROJECT,
    REFERER,
    digest,
    is_unavailable,
    parse,
    url,
)
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.ths_session import ThsSession


class ThsListingCollector:
    manifest = PluginManifest('collector.ths_listings', '同花顺股票上市与发行资料',
        requires=('http.fetch', 'ingest.publish', 'listings.query', 'archive.confirmation', 'collection.records'),
        provides=('collector.ths_listings',), description='逐证券补缺，每七天回查全部当前股票池')

    def __init__(self):
        self.source, self.project_id, self.job_key = 'ths', PROJECT, JOB
        self.session, self.request_retries = None, 2
        self.stats = {'status': 'stopped', 'collected': 0}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.confirmation = context.get('listings.query'), context.get('archive.confirmation')
        self.records = context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.ths_listings': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))['revision']

    async def fetch(self, stock, *, reservation=None, defer=False):
        await wait_for_capacity(self.ingest, self.stats)
        if self.session is None:
            self.session = ThsSession()
        request_url, observed = url(stock), datetime.now(UTC)
        response = await self.http.request('GET', request_url, headers=self.session.headers(REFERER),
            allowed_domains=('10jqka.com.cn',), project_id=PROJECT,
            policy=self.http.response_policy('generic'), max_retries=self.request_retries,
            reservation=reservation)
        async def consume():
            try:
                return parse(response.json(), stock, observed.astimezone(CHINA).date().isoformat()), observed, request_url
            except (ValueError, TypeError, KeyError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, PROJECT,
                    exc, stage='source_validation', unavailable_message='发行错误样本暂不可用',
                    fields=dict(request_url=request_url, status_code=response.status_code, raw_body=body[:65536],
                        observed_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest()))
                raise
            finally:
                if not defer:
                    response.close()

        if defer:
            return DeferredResponse(response, consume)
        return await consume()

    async def publish(self, state, cursor, unit, row, manifest, observed, request_url):
        e = make_envelope(source='ths', dataset=DATASET, business_key=unit, job_key=JOB,
            batch_id=cursor['batch_id'], run_id=cursor['batch_id'],
            payload=dict(page=cursor['pages'], unit=unit, row=row, manifest=manifest))
        e = e.model_copy(update={'observed_at': observed, 'source_url': request_url, 'available_at': None})
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
                stocks, existing, proof = await self.query.plan()
                keys = [s['market'] + ':' + s['code'] for s in stocks]
                scope = digest(keys)
                if (fresh and not progressed) or cursor.get('phase') == 'complete':
                    cursor = {}
                if cursor and cursor.get('scope_hash') != scope:
                    raise ValueError('上市股票池集合已改变，请重新初始化；不混用旧断点')
                if not cursor:
                    now = datetime.now(UTC)
                    stamp = proof.get('refresh_started_at')
                    try:
                        age = now - datetime.fromisoformat(stamp)
                        full = fresh or not timedelta(0) <= age < timedelta(days=7)
                    except (ValueError, TypeError):
                        full = True
                    cursor = dict(phase='fetch', batch_id=uuid4().hex, index=0, pages=0, collected=0,
                        units=len(keys), scope_hash=scope, full_refresh=full,
                        refresh_started_at=now.isoformat() if full else stamp)
                selected = [(i, stocks[i]) for i in range(cursor['index'], len(stocks))
                         if cursor['full_refresh'] or keys[i] not in existing]
                async def download(item, *, reservation):
                    return await self.fetch(item[1], reservation=reservation, defer=True)
                async with prefetch_units(self, selected, download,
                        url='https://basic.10jqka.com.cn/', domains=('10jqka.com.cn',), item_name='证券') as reads:
                    async for number, read in reads:
                        index = selected[number][0]
                        self.stats.update(status='collecting', current_security=keys[index],
                            completed_units=index, total_units=len(keys), collected=cursor['collected'], pages=cursor['pages'])
                        stage = 'source_validation'
                        row, observed, request_url = await read.resolve()
                        following = {**cursor, 'index': index + 1, 'pages': cursor['pages'] + 1,
                                     'collected': cursor['collected'] + int(not is_unavailable(row)),
                                     'unavailable': cursor.get('unavailable', 0) + int(is_unavailable(row))}
                        stage = 'queue_publish'
                        state = await self.publish(state, following, keys[index], row, None, observed, request_url)
                        cursor = state['cursor']
                following = {**cursor, 'phase': 'awaiting_archive', 'index': len(keys), 'pages': cursor['pages'] + 1}
                manifest = {k: cursor[k] for k in ('scope_hash', 'units', 'refresh_started_at')}
                state = await self.publish(state, following, 'manifest', None, manifest, datetime.now(UTC), None)
                cursor = state['cursor']
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', pages=cursor['pages'], collected=cursor['collected'])
            await wait_for_archive(partial(self.confirmation.page_status, 'ths', JOB, PROJECT,
                cursor['batch_id'], cursor['pages']), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=JOB, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', completed_units=cursor['units'],
                              unavailable=cursor.get('unavailable', 0), error='')
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, PROJECT, exc, stage=stage,
                                      unavailable_message='发行采集错误暂不可用；失败位置未跳过')
            raise

    async def stop(self):
        self.session = None
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
