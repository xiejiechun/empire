"""One HTML download validates and publishes all three holder sections."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.collector import CollectionSourceGap
from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.features.holders.contract import KINDS, digest, project
from empire.features.holders.planning import choose, gap_notice, manifest_for
from empire.features.holders.source import parse
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.ths_session import ThsSession


class HolderCollector:
    def __init__(self):
        self.source, self.project_id = 'ths', project('top_holders')
        self.job_key = self.project_id + '-v1'
        self.manifest = PluginManifest('collector.ths_holders', '股东研究（同花顺）',
            requires=('http.fetch', 'ingest.publish', 'top_holders.query', 'float_holders.query',
                      'bond_holders.query', 'archive.confirmation', 'collection.records'),
            provides=('collector.ths_holders',), description='一次响应全部三栏；整轮末确认归档')
        self.stats, self.session, self.request_retries = {'status': 'stopped', 'collected': 0}, None, 2

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.confirmation = context.get('top_holders.query'), context.get('archive.confirmation')
        self.records = context.get('collection.records')
        self.stats['status'] = 'idle'
        return {self.manifest.provides[0]: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def fetch(self, stock, *, reservation=None, defer=False):
        await wait_for_capacity(self.ingest, self.stats)
        if self.session is None:
            self.session = ThsSession()
        url = f"https://basic.10jqka.com.cn/{stock['code']}/holder.html"
        observed = datetime.now(UTC)
        response = await self.http.request('GET', url, headers=self.session.headers(url),
            allowed_domains=('10jqka.com.cn',), project_id=self.project_id,
            policy=self.http.response_policy('generic'), max_retries=self.request_retries, reservation=reservation)
        async def consume():
            try:
                gaps = []
                reports = {kind: parse(response.content, kind, stock, observed.astimezone(CHINA).date(), gaps=gaps)
                           for kind in KINDS}
                return reports, observed, url, gaps
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, self.project_id,
                    exc, stage='source_validation', unavailable_message='持有人错误样本暂不可用',
                    fields=dict(request_url=url, status_code=response.status_code, raw_body=body[:65536],
                        metadata=getattr(exc, 'holder_metadata', {}),
                        observed_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest()))
                raise
            finally:
                if not defer:
                    response.close()
        return DeferredResponse(response, consume) if defer else await consume()

    async def publish(self, state, cursor, unit, reports, manifest, observed, url, gaps=None):
        envelope = make_envelope(source='ths', dataset='holders.reports', schema_version=5, business_key=unit,
            job_key=self.job_key, batch_id=cursor['batch_id'], run_id=cursor['batch_id'],
            payload=dict(page=cursor['pages'], unit=unit, reports=reports, manifest=manifest, gaps=gaps or []))
        envelope = envelope.model_copy(update={'observed_at': observed, 'source_url': url, 'available_at': None})
        return await publish_with_capacity(self.ingest, self.stats, [envelope], job_key=self.job_key,
                                          expected_revision=state['revision'], cursor=cursor)

    async def finish_round(self, state):
        cursor = state['cursor']
        self.stats.update(status='awaiting_archive', pages=cursor['pages'], collected=cursor['collected'])
        if cursor['pages']:
            await wait_for_archive(partial(self.confirmation.page_status, 'ths', self.job_key,
                self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
        phase = 'source_gap' if cursor.get('source_gap_units') else 'complete'
        cursor = {**cursor, 'phase': phase}
        await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
        self.stats.update(status=phase, failed_units=0, error='', processed_units=cursor['units'],
            total_units=cursor['units'], source_gap_units=cursor.get('source_gap_units', 0),
            source_identity_gaps=cursor.get('source_identity_gaps', 0), notice=cursor.get('notice', ''))
        if phase == 'source_gap':
            raise CollectionSourceGap(cursor['notice'])
        self.stats['completed_units'] = cursor['units']
        return cursor

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            previous = state['cursor']
            if previous and previous.get('format') != 2:
                raise ValueError('持有人旧续采游标须先运行 scripts/migrate_holder_checkpoint.py 显式维护')
            if previous.get('phase') == 'awaiting_archive':
                return await self.finish_round(state)
            progressed = state['revision'] > baseline_revision
            if progressed and previous.get('phase') == 'complete':
                return previous
            now = datetime.now(UTC)
            stocks = await self.query.securities()
            keys = [stock['unified_code'] for stock in stocks]
            key_set = set(keys)
            units = {key: value for key, value in (await self.query.collection_units(now)).items() if key in key_set}
            started = (datetime.fromisoformat(previous['started_at'])
                       if previous.get('phase') == 'fetch' and not (fresh and not progressed) else None)
            selected = choose(stocks, units, now, fresh=fresh and not progressed, started=started)
            cursor = dict(format=2, phase='fetch', batch_id=uuid4().hex, pages=0, index=0,
                collected=0, units=len(selected), scope_hash=digest(keys), scope_units=len(keys),
                started_at=(started or now).isoformat(timespec='microseconds'))
            if previous and previous.get('scope_hash') != cursor['scope_hash']:
                self.stats['scope_changed'] = True
            rejected, summaries = [], {}
            self.stats.pop('completed_units', None)
            self.stats.update(failed_units=0, source_gap_units=0, source_identity_gaps=0, notice='', error='',
                processed_units=0, completed_units=0, total_units=len(selected), continuous_collected=0, collected=0, pages=0)
            async def download(stock, *, reservation):
                return await self.fetch(stock, reservation=reservation, defer=True)
            async with prefetch_units(self, selected, download, url='https://basic.10jqka.com.cn/',
                    domains=('10jqka.com.cn',), item_name='股票') as reads:
                async for index, read in reads:
                    key = selected[index]['unified_code']
                    self.stats.update(status='collecting', current_security=key, processed_units=index)
                    stage = 'source_validation'
                    try:
                        reports, observed, url, gaps = await read.resolve()
                    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                        if not hasattr(exc, 'diagnostic_recorded'):
                            raise
                        rejected.append(key)
                        self.stats.update(failed_units=len(rejected), processed_units=index + 1)
                        continue
                    count = sum(map(len, reports.values()))
                    following = {**cursor, 'pages': cursor['pages'] + 1,
                        'collected': cursor['collected'] + count,
                        'index': cursor['index'] if rejected else index + 1}
                    stage = 'queue_publish'
                    state = await self.publish(state, following, key, reports, None, observed, url, gaps)
                    cursor = state['cursor']
                    units[key] = dict(stamp=observed, gap_count=len(gaps), count=count, digest=digest(reports))
                    summaries[key] = {**units[key], 'kinds': {
                        kind: dict(count=len(rows), digest=digest(rows)) for kind, rows in reports.items()}}
                    self.stats.update(collected=cursor['collected'], processed_units=index + 1, completed_units=index + 1 - len(rejected),
                        pages=cursor['pages'], continuous_collected=cursor['collected'] if not rejected else
                        self.stats['continuous_collected'])
            stage = 'archive_confirmation'
            if rejected:
                if cursor['pages']:
                    self.stats['status'] = 'awaiting_archive'
                    await wait_for_archive(partial(self.confirmation.page_status, 'ths', self.job_key,
                        self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
                error = ValueError(f'本轮已检查至末尾，{len(rejected)}只证券来源校验失败；'
                    '已入队有效报告已确认归档，下次只补查未确认证券：' + '、'.join(rejected[:5]))
                error.diagnostic_recorded = True
                raise error
            notice, gap_units, gap_count = gap_notice(units, len(selected))
            following = {**cursor, 'phase': 'awaiting_archive', 'notice': notice,
                         'source_gap_units': gap_units, 'source_identity_gaps': gap_count}
            # A partial maintenance pass cannot publish a whole-pool manifest.
            # Formal preparation already verifies each selected security proof.
            if keys and set(summaries) == set(keys) and not gap_units:
                following['pages'] += 1
                state = await self.publish(state, following, 'manifest', {kind: [] for kind in KINDS},
                    manifest_for(keys, summaries), now, None)
            else:
                state = await self.ingest.advance_checkpoint(job_key=self.job_key,
                    expected_revision=state['revision'], cursor=following)
            return await self.finish_round(state)
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except CollectionSourceGap:
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc, stage=stage,
                                      unavailable_message='持有人失败位置保留，错误记录暂不可用')
            raise

    async def stop(self):
        self.session = None
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
