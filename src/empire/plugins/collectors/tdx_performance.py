"""Five separately registered collectors sharing validated source and lifecycle helpers."""
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.tdx_performance import (
    SCHEMA_VERSION,
    day,
    digest,
    identity,
    monthly_plan,
    pack,
    project,
    quarterly_plan,
)
from empire.contracts.tdx_performance import (
    UNIT_KINDS as KINDS,
)
from empire.core.time import CHINA
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.tdx_performance_source import (
    BASE,
    CHANGES_PAGE,
    PAGE,
    entry,
    parse,
    parse_directory,
    request_body,
)


class PerformanceCollector:
    def __init__(self, kind):
        self.kind, self.source = kind, 'tdx'
        self.project_id, self.job_key = project(kind), project(kind) + '-v1'
        capability = 'collector.tdx_' + kind
        self.manifest = PluginManifest(capability, KINDS[kind][0] + '采集',
            requires=('http.fetch', 'ingest.publish', kind + '.tdx_query', 'archive.confirmation', 'collection.records'),
            provides=(capability,), description='每页10000、完整来源单元、全部入队后等待归档')
        self.request_retries = 2
        self.stats = {'status': 'stopped', 'collected': 0, 'record_name': '条来源记录',
                      'unit_name': '个完整响应', 'completed_units': 0}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query = context.get(self.kind + '.tdx_query')
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {self.manifest.provides[0]: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def fetch(self, unit=None, *, directory=False, reservation=None, defer=False):
        await wait_for_capacity(self.ingest, self.stats)
        url = BASE + ('tdxsj_cbjd_cache' if directory else entry(self.kind))
        content = (json.dumps({'Params': [KINDS[self.kind][2], '', '', '']}).encode()
                   if directory else request_body(self.kind, unit if self.kind != 'holder_count' else None,
                                                  unit if self.kind == 'holder_count' and unit else ''))
        response = await self.http.request('POST', url, content=content,
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                     'Referer': CHANGES_PAGE if self.kind == 'shareholder_changes' else PAGE},
            allowed_domains=('tdx.com.cn',), project_id=self.project_id,
            policy=self.http.response_policy('generic'), max_retries=self.request_retries, reservation=reservation)
        self.stats['requests'] = self.stats.get('requests', 0) + 1
        async def consume():
            try:
                return (parse_directory(self.kind, response.json()) if directory else
                        parse(self.kind, response.json(), unit if self.kind != 'holder_count' else None,
                              unit if self.kind == 'holder_count' and unit else ''))
            except (ValueError, TypeError, KeyError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, self.project_id,
                    exc, stage='source_validation', unavailable_message='财报解读错误样本暂不可用',
                    fields=dict(request_url=url, status_code=response.status_code, raw_body=body[:65536],
                                observed_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest(),
                                metadata={'unit': unit, 'capacity': 10000}))
                raise
            finally:
                if not defer:
                    response.close()
        if defer:
            return DeferredResponse(response, consume)
        return await consume()

    async def execute(self, *, fresh=False, baseline_revision=0, start_month=None, end_month=None):
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            progressed = state['revision'] > baseline_revision
            if progressed and cursor.get('phase') == 'complete':
                return cursor
            if cursor and cursor.get('contract') != SCHEMA_VERSION:
                raise ValueError('旧财报解读断点须显式维护，不能跳过')
            if cursor.get('phase') != 'awaiting_archive':
                self.stats.update(status='collecting', requests=0, error='')
                if self.kind == 'holder_count':
                    latest_rows, _ = await self.fetch()
                    latest_by_code = {row['unified_code']: row for row in latest_rows}
                    if not latest_by_code:
                        raise ValueError('股东户数最新证券目录为空，不能确认全池历史')
                    stored = await self.query.state()
                    downloads = sorted(set(latest_by_code) | set(stored.get('units', {})))
                    latest = max(row['statistics_date'] for row in latest_rows)
                    units = downloads
                elif self.kind == 'shareholder_changes':
                    latest = datetime.now(CHINA).date().replace(day=1).isoformat()
                    if end_month is not None:
                        day(end_month)
                        if end_month[8:] != '01':
                            raise ValueError('指定持股变动日期须为月份第一天YYYY-MM-01')
                        if end_month > latest:
                            raise ValueError('指定持股变动月份超过当前月份')
                        latest = end_month
                    downloads = monthly_plan(latest)
                    if start_month is not None:
                        if start_month not in downloads:
                            raise ValueError('指定持股变动起始月份不在支持范围')
                        downloads = [unit for unit in downloads if unit >= start_month]
                    units = [period + '|' + market for period in downloads for market in ('SH', 'SZ', 'BJ')]
                    latest_by_code = {}
                else:
                    directory = await self.fetch(directory=True)
                    latest = directory[0]
                    if int(latest[:4]) > datetime.now(CHINA).year + 1:
                        raise ValueError('来源报告期异常超前')
                    downloads = quarterly_plan(latest)
                    units = [period + '|' + market for period in downloads for market in ('SH', 'SZ', 'BJ')]
                    latest_by_code = {}
                scope_hash = digest(units)
                if (self.kind == 'shareholder_changes' and cursor.get('phase') == 'fetch'
                        and cursor.get('scope_hash') != scope_hash and not fresh):
                    raise ValueError('持股变动断点与指定范围冲突；显式重新初始化才能变更范围')
                if (fresh and not progressed or cursor.get('phase') == 'complete'
                        or cursor.get('scope_hash') != scope_hash):
                    cursor = {}
                if not cursor:
                    cursor = dict(phase='fetch', batch_id=uuid4().hex, index=0, market_index=0, response_hash='', page=0, collected=0,
                        rolling='', scope_hash=scope_hash, units=len(units), latest=latest,
                        started_at=datetime.now(UTC).isoformat(), contract=SCHEMA_VERSION)
                observed = datetime.fromisoformat(cursor['started_at'])
                self.stats.update(total_units=len(downloads), completed_units=cursor['index'],
                                  collected=cursor['collected'])
                async def download(unit, *, reservation):
                    return await self.fetch(unit, reservation=reservation, defer=True)
                remaining = downloads[cursor['index']:]
                async with prefetch_units(self, remaining, download,
                        url=BASE + entry(self.kind), domains=('tdx.com.cn',), item_name='完整响应') as reads:
                    async for offset, read in reads:
                        requested = remaining[offset]
                        stage = 'source_validation'
                        rows, _ = await read.resolve()
                        observed = datetime.now(UTC)
                        if self.kind == 'holder_count':
                            current = latest_by_code.get(requested)
                            if current:
                                matches = [r for r in rows if identity(self.kind, r) == identity(self.kind, current)]
                                if matches and matches != [current]:
                                    raise ValueError('股东户数最新列表与历史同键内容冲突，不能确认本轮')
                                if not matches:
                                    rows = sorted([*rows, current], key=lambda r: identity(self.kind, r))
                            groups = [(requested, rows)]
                        else:
                            groups = [(requested + '|' + market, [r for r in rows if r['unified_code'].endswith(market)])
                                      for market in ('SH', 'SZ', 'BJ')]
                        source_hash = digest(groups)
                        if cursor.get('market_index') and cursor['response_hash'] != source_hash:
                            raise ValueError('中断单期的来源内容已变化；请重新采集以重建完整范围，旧数据保留')
                        for unit, values in groups:
                            probe = self.envelope(unit, values, cursor['page'] + 1, cursor['batch_id'], observed)
                            if len(probe.model_dump_json().encode()) > getattr(self.ingest, 'settings', {}).get('max_page_bytes', 524288):
                                raise ValueError('完整报告市场超过单消息容量；未入队本期，禁止截断')
                        # Validate whole source and every message budget before publishing any market.
                        for group_index, (unit, values) in enumerate(groups):
                            if group_index < cursor.get('market_index', 0):
                                continue
                            stage = 'queue_publish'
                            page = cursor['page'] + 1
                            event = self.envelope(unit, values, page, cursor['batch_id'], observed)
                            next_cursor = {**cursor, 'page': page, 'market_index': group_index + 1, 'response_hash': source_hash,
                                'collected': cursor['collected'] + len(values),
                                'rolling': digest([cursor['rolling'], unit, digest(values), len(values)])}
                            if unit == groups[-1][0]:
                                next_cursor['index'] += 1
                                next_cursor.update(market_index=0, response_hash='')
                            state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=self.job_key,
                                expected_revision=state['revision'], cursor=next_cursor)
                            cursor = next_cursor
                        self.stats.update(collected=cursor['collected'], completed_units=cursor['index'], pages=cursor['page'])
                manifest = dict(units=len(units), count=cursor['collected'], scope_hash=scope_hash,
                                digest=cursor['rolling'], latest=latest)
                if self.kind == 'shareholder_changes':
                    manifest['start'] = downloads[0]
                page = cursor['page'] + 1
                event = self.envelope('manifest', [], page, cursor['batch_id'], datetime.now(UTC), manifest)
                cursor = {**cursor, 'phase': 'awaiting_archive', 'page': page}
                state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=self.job_key,
                    expected_revision=state['revision'], cursor=cursor)
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'], pages=cursor['page'])
            await wait_for_archive(partial(self.confirmation.page_status, 'tdx', self.job_key,
                self.project_id, cursor['batch_id'], cursor['page']), retry_seconds=1)
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
                                    unavailable_message='错误记录暂不可用；未跳过失败单元')
            raise

    def envelope(self, unit, rows, page, batch, observed, manifest=None):
        event = make_envelope(source='tdx', dataset=self.kind + '.tdx_unit', business_key=unit,
            job_key=self.job_key, batch_id=batch, run_id=batch, schema_version=SCHEMA_VERSION,
            payload=dict(page=page, unit=unit, rows=[] if manifest is not None else pack(self.kind, rows), manifest=manifest))
        return event.model_copy(update={'observed_at': observed,
            'source_url': CHANGES_PAGE if self.kind == 'shareholder_changes' else PAGE, 'available_at': None})

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
