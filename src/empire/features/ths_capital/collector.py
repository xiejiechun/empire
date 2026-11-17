"""One ordered security response, one atomic publish; wait only after the round."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.core.time import CHINA
from empire.features.ths_capital.contract import DATASET, JOB, PROJECT, TABLES, digest
from empire.features.ths_capital.transport import SCHEMA, pack
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.ths_session import ThsSession
from empire.plugins.datasets.source_compute import MAX_SOURCE_RESULT
from empire.plugins.infra.ths_maintenance import due


class CapitalPageCollector:
    def __init__(self):
        self.source, self.project_id, self.job_key = 'ths', PROJECT, JOB
        self.manifest = PluginManifest('collector.ths_capital', '公司资本运作（同花顺）',
            requires=('http.fetch', 'ingest.publish', 'ths_capital.query', 'archive.confirmation',
                      'collection.records', 'dataset.catalog'),
            provides=('collector.ths_capital',), description='一次响应采集全部栏目、展开详情及原事件/解除')
        self.stats, self.session, self.request_retries = dict(status='stopped', collected=0), None, 2

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.confirmation = context.get('ths_capital.query'), context.get('archive.confirmation')
        self.records = context.get('collection.records')
        self.catalog = context.get('dataset.catalog')
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
            max_retries=self.request_retries, reservation=reservation, retry_empty_body=True)
        error, result = None, None
        async def consume():
            try:
                if error is not None:
                    raise error
                return result.value, observed, url
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, PROJECT, exc,
                    stage='source_validation', unavailable_message='资本运作错误样本暂不可用',
                    fields=dict(request_url=url, status_code=response.status_code, raw_body=body[:65536],
                                observed_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest()))
                raise
            finally:
                if not defer:
                    pending.close()
        pending = DeferredResponse(response, consume)
        try:
            result = await self.catalog.compute_source('ths.capital', response.content, stock,
                observed.astimezone(CHINA).date(), reservation=reservation)
            pending.retain(result)
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            # Pure parsing can finish out of order; only the ordered consumer
            # reports source failure and decides the publication frontier.
            error = exc
        except BaseException:
            pending.close()
            raise
        return pending if defer else await consume()

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

    @measured_run
    async def execute(self, *, fresh=False, baseline_revision=0):
        self.stats.update(completed_units=0, total_units=None, unit_name='只股票')
        self.stats['reused_units'] = 0
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(JOB)
            cursor = state['cursor']
            progressed = state['revision'] > baseline_revision
            force = bool((fresh and not progressed) or (cursor.get('phase') == 'fetch' and cursor.get('fresh')))
            if progressed and cursor.get('phase') == 'complete':
                self.stats.update(completed_units=cursor['index'], total_units=cursor['units'])
                return cursor
            if cursor.get('phase') != 'awaiting_archive':
                if (fresh and not progressed) or cursor.get('phase') == 'complete':
                    cursor = {}
                stocks = await self.query.securities()
                keys = [s['unified_code'] for s in stocks]
                if cursor and cursor.get('scope_hash') != digest(keys):
                    cursor = {}
                    self.stats['scope_changed'] = True
                units = await self.query.collection_units()
                now = datetime.now(UTC)
                if not cursor:
                    cursor = dict(phase='fetch', batch_id=uuid4().hex, index=0, pages=0, collected=0,
                                  units=len(keys), scope_hash=digest(keys), rolling=digest([]), fresh=force)
                self.stats.update(completed_units=cursor['index'], total_units=len(keys))
                selected = [(i, stocks[i]) for i in range(cursor['index'], len(keys))
                            if cursor.get('fresh', False) or keys[i] not in units or due(units[keys[i]]['stamp'], now)]
                def reuse_before(stop):
                    nonlocal cursor
                    self.stats['reused_units'] = self.stats.get('reused_units', 0) + stop - cursor['index']
                    for i in range(cursor['index'], stop):
                        proof = units[keys[i]]
                        cursor = {**cursor, 'index': i + 1,
                            'collected': cursor['collected'] + proof['count'],
                            'rolling': digest([cursor['rolling'], keys[i], proof['digest'], proof['count']])}
                async def download(item, *, reservation):
                    return await self.fetch(item[1], reservation=reservation, defer=True)
                retained = (MAX_SOURCE_RESULT if self.http.buffer_budget.limit >= 4 * MAX_SOURCE_RESULT else 0)
                async with prefetch_units(self, selected, download, url='https://basic.10jqka.com.cn/',
                        domains=('10jqka.com.cn',), item_name='股票', retained_bytes=retained) as reads:
                    async for number, read in reads:
                        index = selected[number][0]
                        reuse_before(index)
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
                        self.stats['completed_units'] = cursor['index']
                reuse_before(len(keys))
                following = {**cursor, 'phase': 'awaiting_archive', 'pages': cursor['pages'] + 1}
                manifest = dict(units=len(keys), count=cursor['collected'], securities=keys,
                                scope_hash=digest(keys), digest=cursor['rolling'])
                state = await self.publish(state, following, 'manifest', dict(rows={t: [] for t in TABLES},
                    availability={}), manifest, datetime.now(UTC), None)
                cursor = state['cursor']
            self.stats.update(completed_units=cursor['index'], total_units=cursor['units'])
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
