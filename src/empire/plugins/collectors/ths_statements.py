"""Three independently registered collectors sharing only their source lifecycle."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.datasets.financial_statements import KINDS, digest, parse
from empire.plugins.datasets.financial_wire import SCHEMA_VERSION, pack_rows


def chain(previous, unit, rows):
    return digest([previous, unit, digest(rows), len(rows)])


class ThsStatementCollector:
    def __init__(self, kind):
        self.kind, self.source = kind, 'ths'
        self.project_id = 'ths-' + kind
        self.job_key = self.project_id + '-v1'
        self.manifest = PluginManifest('collector.ths_' + kind, '同花顺' + KINDS[kind][0],
            requires=('http.fetch', 'ingest.publish', kind + '.query', 'archive.confirmation', 'collection.records'),
            provides=('collector.ths_' + kind,), description='单证券完整历史矩阵，整轮末等待归档')
        self.stats = {'status': 'stopped', 'collected': 0}
        self.request_retries = 2

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.confirmation = context.get(self.kind + '.query'), context.get('archive.confirmation')
        self.records = context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.ths_' + self.kind: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def fetch(self, stock, *, reservation=None, defer=False):
        await wait_for_capacity(self.ingest, self.stats)
        url = f"https://basic.10jqka.com.cn/api/stock/finance/{stock['code']}_{KINDS[self.kind][1]}.json"
        observed = datetime.now(UTC)
        response = await self.http.request('GET', url,
            headers={'User-Agent': 'Mozilla/5.0',
                     'Referer': f"https://basic.10jqka.com.cn/{stock['code']}/finance.html"},
            allowed_domains=('10jqka.com.cn',), project_id=self.project_id,
            policy=self.http.response_policy('generic'), max_retries=self.request_retries,
            reservation=reservation)
        async def consume():
            try:
                return parse(self.kind, response.json(), stock), observed, url
            except (ValueError, TypeError, KeyError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, self.project_id,
                    exc, stage='source_validation', unavailable_message='财报错误样本暂未写入 Redis',
                    fields={'request_url': url, 'status_code': response.status_code, 'raw_body': body[:65536],
                            'observed_bytes': len(body), 'body_sha256': hashlib.sha256(body).hexdigest()})
                raise
            finally:
                if not defer:
                    response.close()

        if defer:
            return DeferredResponse(response, consume)
        return await consume()

    async def publish(self, state, cursor, unit, rows, manifest, observed, url):
        envelope = make_envelope(source=self.source, dataset=self.kind + '.statement', business_key=unit,
            job_key=self.job_key, batch_id=cursor['batch_id'], run_id=cursor['batch_id'],
            schema_version=SCHEMA_VERSION,
            payload={'page': cursor['pages'], 'unit': unit, 'rows': pack_rows(rows), 'manifest': manifest})
        envelope = envelope.model_copy(update={'observed_at': observed, 'source_url': url, 'available_at': None})
        return await publish_with_capacity(self.ingest, self.stats, [envelope], job_key=self.job_key,
                                          expected_revision=state['revision'], cursor=cursor)

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            progressed = state['revision'] > baseline_revision
            if progressed and cursor.get('phase') == 'complete':
                return cursor
            if (fresh and not progressed) or cursor.get('phase') == 'complete':
                cursor = {}
            if cursor.get('phase') != 'awaiting_archive':
                stocks = sorted(await self.query.securities(), key=lambda s: (s['market'], s['code']))
                keys = [s['market'] + ':' + s['code'] for s in stocks]
                scope = digest(keys)
                if cursor and cursor.get('scope_hash') != scope:
                    # An index/rolling proof belongs to exactly one ordered pool.
                    # Keep old queued units; a new complete round rebuilds coverage.
                    self.stats.update(scope_changed=True, previous_units=cursor.get('units'))
                    cursor = {}
                if not cursor:
                    cursor = dict(phase='fetch', batch_id=uuid4().hex, index=0, pages=0, collected=0,
                                  units=len(keys), scope_hash=scope, rolling=digest([]))
                selected = list(enumerate(stocks))[cursor['index']:]
                async def download(item, *, reservation):
                    return await self.fetch(item[1], reservation=reservation, defer=True)
                async with prefetch_units(self, selected, download,
                        url='https://basic.10jqka.com.cn/', domains=('10jqka.com.cn',), item_name='证券') as reads:
                    async for number, read in reads:
                        index = selected[number][0]
                        stage = 'source_validation'
                        self.stats.update(status='collecting', current_security=keys[index],
                                          collected=cursor['collected'], pages=cursor['pages'], total_units=len(keys))
                        rows, observed, url = await read.resolve()
                        following = {**cursor, 'index': index + 1, 'pages': cursor['pages'] + 1,
                                     'collected': cursor['collected'] + len(rows),
                                     'rolling': chain(cursor['rolling'], keys[index], rows)}
                        stage = 'queue_publish'
                        state = await self.publish(state, following, keys[index], rows, None, observed, url)
                        cursor = state['cursor']
                manifest = dict(units=cursor['units'], count=cursor['collected'],
                                scope_hash=scope, digest=cursor['rolling'])
                following = {**cursor, 'phase': 'awaiting_archive', 'pages': cursor['pages'] + 1}
                state = await self.publish(state, following, 'manifest', [], manifest, datetime.now(UTC), None)
                cursor = state['cursor']
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'], pages=cursor['pages'])
            await wait_for_archive(partial(self.confirmation.page_status, self.source, self.job_key,
                                          self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc, stage=stage,
                                      unavailable_message='错误记录暂未写入 Redis；断点保留')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
