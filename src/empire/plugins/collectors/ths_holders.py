"""One HTML download validates and publishes all three holder sections."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.collector import CollectionSourceGap
from empire.contracts.data import make_envelope
from empire.contracts.holders import KINDS, digest, project
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.ths_holders_source import parse
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

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            progressed = state['revision'] > baseline_revision
            if progressed and cursor.get('phase') == 'complete':
                return cursor
            if cursor.get('phase') != 'awaiting_archive':
                if (fresh and not progressed) or cursor.get('phase') == 'complete':
                    cursor = {}
                stocks = await self.query.securities()
                keys = [s['unified_code'] for s in stocks]
                scope = digest(keys)
                if cursor and cursor.get('scope_hash') != scope:
                    self.stats['scope_changed'] = True
                    cursor = {}
                if cursor.get('source_gap'):
                    # A new attempt gets a bounded queue page sequence while
                    # retaining the verified prefix and its first missing index.
                    cursor = {k: v for k, v in cursor.items() if k != 'source_gap'}
                    cursor.update(batch_id=uuid4().hex, pages=0)
                if not cursor:
                    cursor = dict(phase='fetch', batch_id=uuid4().hex, index=0, pages=0,
                        collected=0, units=len(keys), scope_hash=scope, rolling=digest([]), unavailable=0,
                        kinds={kind: dict(count=0, digest=digest([])) for kind in KINDS})
                selected = list(enumerate(stocks))[cursor['index']:]
                failures, rejected, gap_securities = [], [], []
                queued = cursor['collected']
                self.stats.pop('completed_units', None)
                self.stats.update(failed_units=0, source_gap_units=0, source_identity_gaps=0, notice='', error='',
                                  processed_units=cursor['index'],
                                  continuous_collected=cursor['collected'])
                async def download(item, *, reservation):
                    return await self.fetch(item[1], reservation=reservation, defer=True)
                async with prefetch_units(self, selected, download, url='https://basic.10jqka.com.cn/',
                        domains=('10jqka.com.cn',), item_name='股票') as reads:
                    async for number, read in reads:
                        index = selected[number][0]
                        self.stats.update(status='collecting', current_security=keys[index],
                            processed_units=index, total_units=len(keys), pages=cursor['pages'], collected=queued)
                        stage = 'source_validation'
                        try:
                            reports, observed, url, gaps = await read.resolve()
                        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                            if not hasattr(exc, 'diagnostic_recorded'):
                                raise  # Local configuration/resource errors must still stop.
                            failures.append(keys[index])
                            rejected.append(keys[index])
                            self.stats.update(failed_units=len(rejected), processed_units=index + 1)
                            continue
                        if gaps:
                            failures.append(keys[index])
                            gap_securities.append(keys[index])
                            self.stats.update(source_gap_units=len(gap_securities),
                                source_identity_gaps=self.stats.get('source_identity_gaps', 0) + len(gaps))
                        following = {**cursor, 'index': index + 1, 'pages': cursor['pages'] + 1,
                            'collected': cursor['collected'] + sum(map(len, reports.values())),
                            'unavailable': cursor['unavailable'] + int(not reports['bond_holders']),
                            'rolling': digest([cursor['rolling'], keys[index], digest(reports), sum(map(len, reports.values()))]),
                            'kinds': {kind: dict(count=cursor['kinds'][kind]['count'] + len(rows),
                                digest=digest([cursor['kinds'][kind]['digest'], keys[index], digest(rows), len(rows)]))
                                for kind, rows in reports.items()}}
                        if failures:
                            # Queue valid independent securities, retaining the first
                            # failed security as the continuous restart frontier.
                            # Pages count queue messages, not verified securities.
                            following = {**cursor, 'pages': cursor['pages'] + 1,
                                         'source_gap': failures[0]}
                        stage = 'queue_publish'
                        state = await self.publish(state, following, keys[index], reports, None, observed, url, gaps)
                        cursor = state['cursor']
                        queued += sum(map(len, reports.values()))
                        self.stats.update(collected=queued, processed_units=index + 1, pages=cursor['pages'],
                                          continuous_collected=cursor['collected'])
                if failures:
                    stage = 'archive_confirmation'
                    if cursor['pages']:
                        self.stats['status'] = 'awaiting_archive'
                        await wait_for_archive(partial(self.confirmation.page_status, 'ths', self.job_key,
                            self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
                    if not rejected:
                        notice = (f"本轮已检查至末尾，可识别报告已确认归档；{len(gap_securities)}只证券共"
                            f"{self.stats['source_identity_gaps']}份债券报告名称为空，已登记来源缺口："
                            + '、'.join(gap_securities[:5]) + ('等' if len(gap_securities) > 5 else '')
                            + f"。连续断点保留在{failures[0]}，下次继续补采；债券缺口仍限制数据准备。")
                        self.stats.update(status='source_gap', notice=notice, error='')
                        raise CollectionSourceGap(notice)
                    error = ValueError(f"本轮已检查至末尾，{len(failures)}只证券来源校验失败；"
                        f"已入队有效报告已确认归档，连续断点保留在{failures[0]}，下次继续补采。失败证券："
                        + '、'.join(failures[:5]) + ('等' if len(failures) > 5 else '') +
                        ('；空名债券已隔离为来源缺口，可识别报告已保存，债券身份补齐后重采恢复。'
                         if self.stats.get('source_identity_gaps') else ''))
                    error.diagnostic_recorded = True
                    raise error
                following = {**cursor, 'phase': 'awaiting_archive', 'pages': cursor['pages'] + 1}
                manifest = dict(units=cursor['units'], count=cursor['collected'], scope_hash=scope,
                                digest=cursor['rolling'], securities=keys, kinds=cursor['kinds'])
                state = await self.publish(state, following, 'manifest', {kind: [] for kind in KINDS}, manifest, datetime.now(UTC), None)
                cursor = state['cursor']
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', pages=cursor['pages'], collected=cursor['collected'])
            await wait_for_archive(partial(self.confirmation.page_status, 'ths', self.job_key,
                self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', completed_units=cursor['units'], unavailable=cursor['unavailable'], error='')
            return cursor
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
