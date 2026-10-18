"""One catalogue request and one complete member request per index, ordered publication."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.download import ResponsePolicy
from empire.contracts.indices import BASE, JOB, MAX_RESPONSE_BYTES, PROJECT, members_url
from empire.contracts.plugin import PluginManifest
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.ths_index_source import parse_catalog, parse_members
from empire.plugins.collectors.ths_session import ThsDirectorySession


class ThsIndexCollector:
    manifest = PluginManifest('collector.ths_indices', '同花顺当前指数及成分',
        requires=('http.fetch', 'ingest.publish', 'indices.query', 'archive.confirmation', 'collection.records'),
        provides=('collector.ths_indices',), description='完整指数目录与当前成分；每指数独立单页归档')

    def __init__(self):
        self.source, self.project_id, self.job_key = 'ths', PROJECT, JOB
        self.request_retries = 2
        self.session = ThsDirectorySession()
        self.stats = {'status': 'stopped', 'collected': 0}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.ths_indices': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def fetch(self, url, parser, *, reservation=None, defer=False):
        await wait_for_capacity(self.ingest, self.stats)
        policy = self.http.response_policy('generic')
        policy = ResponsePolicy(max_body_bytes=min(policy.max_body_bytes, MAX_RESPONSE_BYTES),
                                max_wire_bytes=min(policy.max_wire_bytes, MAX_RESPONSE_BYTES))
        response = await self.http.request('GET', url, headers=self.session.headers(BASE),
            allowed_domains=('10jqka.com.cn',), project_id=self.project_id,
            policy=policy, max_retries=self.request_retries, reservation=reservation)
        async def consume():
            try:
                return parser(response.content.decode('gb18030'))
            except (ValueError, UnicodeError, TypeError, KeyError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, self.project_id,
                    exc, stage='source_validation', unavailable_message='指数错误样本暂未写入Redis',
                    fields={'request_url': url, 'status_code': response.status_code, 'raw_body': body[:65536],
                            'observed_bytes': len(body), 'body_sha256': hashlib.sha256(body).hexdigest()})
                raise
            finally:
                if not defer:
                    response.close()
        return DeferredResponse(response, consume) if defer else await consume()

    async def publish(self, state, cursor, dataset, identity, payload):
        envelope = make_envelope(source=self.source, dataset=dataset, business_key=identity,
            job_key=self.job_key, batch_id=cursor['batch_id'], run_id=cursor['batch_id'], payload=payload)
        envelope = envelope.model_copy(update={'observed_at': datetime.fromisoformat(cursor['observed_at']),
                                               'source_url': BASE if identity == 'catalog' else members_url(identity),
                                               'available_at': None})
        return await publish_with_capacity(self.ingest, self.stats, [envelope], job_key=self.job_key,
                                           expected_revision=state['revision'], cursor=cursor)

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'source_validation'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if state['revision'] > baseline_revision and cursor.get('phase') == 'complete' and not fresh:
                return cursor
            self.stats.update(status='collecting', error='')
            catalog = None
            if cursor.get('phase') not in ('collecting', 'awaiting_archive'):
                catalog = await self.fetch(BASE, parse_catalog)
                cursor = dict(phase='collecting', batch_id=uuid4().hex, observed_at=datetime.now(UTC).isoformat(),
                              codes=[r['code'] for r in catalog], next_index=0, pages=1, collected=0, unavailable=0)
                stage = 'queue_publish'
                state = await self.publish(state, cursor, 'index.catalog', 'catalog', {'page': 1, 'catalog': catalog})
            if catalog is None:
                catalog = [dict(code=code, name=code) for code in cursor['codes']]
            self.stats.update(total_units=len(catalog), completed_units=cursor['next_index'],
                              collected=cursor['collected'], unavailable=cursor['unavailable'])
            if cursor['phase'] != 'awaiting_archive':
                async def download(item, *, reservation):
                    return await self.fetch(members_url(item['code']), partial(parse_members, code=item['code']),
                                            reservation=reservation, defer=True)
                async with prefetch_units(self, catalog, download, url=BASE, domains=('10jqka.com.cn',),
                        first=cursor['next_index'], item_name='指数') as reads:
                    async for index, read in reads:
                        stage = 'source_validation'
                        self.stats.update(current_security=catalog[index]['name'])
                        result = await read.resolve()
                        cursor = {**cursor, 'next_index': index + 1, 'pages': index + 2,
                                  'collected': cursor['collected'] + len(result['members']),
                                  'unavailable': cursor['unavailable'] + int(not result['available'])}
                        if cursor['collected'] > 1000000:
                            raise ValueError('指数当前成员总量超过100万边界')
                        if index + 1 == len(catalog):
                            cursor['phase'] = 'awaiting_archive'
                        stage = 'queue_publish'
                        state = await self.publish(state, cursor, 'index.members', catalog[index]['code'],
                            dict(page=index + 2, code=catalog[index]['code'], **result))
                        self.stats.update(collected=cursor['collected'], completed_units=index + 1,
                                          pages=cursor['pages'], unavailable=cursor['unavailable'])
            stage = 'archive_confirmation'
            self.stats['status'] = 'awaiting_archive'
            await wait_for_archive(partial(self.confirmation.page_status, self.source, self.job_key,
                self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return {k: v for k, v in cursor.items() if k != 'codes'}
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc, stage=stage,
                                      unavailable_message='指数错误记录暂不可用；保留已入队进度')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
