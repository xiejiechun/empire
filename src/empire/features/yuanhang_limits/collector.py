"""Bounded ordered units; ingestion and archive progress independently."""
import asyncio
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.features.yuanhang_limits.contract import (
    BASE_URL,
    DOMAIN,
    MAX_UNIT_BYTES,
    SOURCE,
    dataset,
    job,
    project,
)
from empire.features.yuanhang_limits.source import fetch_pool, fetch_reason
from empire.features.yuanhang_limits.storage import pool_payload, reason_payload
from empire.features.yuanhang_limits.wire import encode
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)


class LimitCollector:
    def __init__(self, pool, *, intraday=False, scope='all'):
        self.pool = pool
        self.intraday = intraday
        if scope not in ('all', 'recent', 'backfill', 'today') or scope == 'today' and pool == 'reason':
            raise ValueError('涨停分析任务范围无效')
        self.scope = scope
        self.project_id, self.job_key, self.dataset = project(pool), job(pool), dataset(pool)
        self.capability = 'collector.yuanhang_limits_' + pool
        self.manifest = PluginManifest(self.capability, '远航涨停分析 ' + pool,
            requires=('http.fetch', 'ingest.publish', 'archive.confirmation', 'collection.records', 'yuanhang.limits.query'),
            provides=(self.capability,))
        self.stats = dict(status='stopped', collected=0, requests=0, response_bytes=0,
                          record_name='条成员', unit_name='个单元')
        self.request_retries = 1

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.records = context.get('yuanhang.limits.query'), context.get('collection.records')
        self.confirmation = context.get('archive.confirmation')
        if self.intraday:
            from empire.features.yuanhang_limits.intraday import live_store
            self.live_store = live_store(context)
        self.stats['status'] = 'idle'
        return {self.capability: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def fetch(self, key, *, reservation=None):
        await wait_for_capacity(self.ingest, self.stats)
        started = datetime.now(UTC)
        if self.pool == 'reason':
            day, code = key
            result = await fetch_reason(self.http, code, day, project_id=self.project_id,
                                         max_retries=self.request_retries, reservation=reservation)
        else:
            result = await fetch_pool(self.http, self.pool, key, project_id=self.project_id,
                max_retries=self.request_retries, reservation=reservation,
                identity_resolver=getattr(self.query, 'resolve_identities', None),
                retry_earlier_time=self.stats.get('storage') == 'redis_only')
        self.stats['requests'] += result.pop('requests')
        self.stats['response_bytes'] += result.pop('response_bytes')
        wire = result.pop('wire_bytes')
        self.stats['wire_bytes'] = self.stats.get('wire_bytes', 0) + wire if wire is not None and self.stats.get('wire_bytes', 0) is not None else None
        # Observation belongs to request start, not asynchronous completion order.
        return result, started

    def envelope(self, cursor, unit, observed):
        validator = reason_payload if self.pool == 'reason' else pool_payload
        unit = validator(unit)
        identity = unit['trade_date'] + ':' + (unit['unified_code'] if self.pool == 'reason' else self.pool)
        event = make_envelope(source=SOURCE, dataset=self.dataset, business_key=identity,
            job_key=self.job_key, batch_id=cursor['batch_id'], run_id=cursor['batch_id'],
            payload={'page': cursor['page'] + 1, 'unit_zlib': encode(unit)})
        return event.model_copy(update={'observed_at': observed, 'available_at': None, 'source_url': BASE_URL})

    async def execute(self, *, fresh=False, baseline_revision=0, history_only=False, maintenance_scope=None):
        self.stats.update(completed_units=0, total_units=None)
        try:
            result = await self._execute(fresh=fresh, baseline_revision=baseline_revision,
                                         history_only=history_only, scope=maintenance_scope)
            carried = {}
            if (self.pool == 'reason' and self.scope == 'recent' and not fresh
                    and not history_only and maintenance_scope is None):
                current = await self.query.collection_plan('reason', scope='recent')
                if result['cutoff'] < current['cutoff']:
                    carried = {key: self.stats.get(key, 0) for key in ('requests', 'response_bytes',
                        'wire_bytes', 'queued_messages', 'queued_bytes', 'collected')}
                    result = await self._execute(baseline_revision=await self.checkpoint_revision(),
                                                  history_only=True, scope='recent')
            if (self.pool == 'reason' and not fresh and not history_only and maintenance_scope is None
                    and result.get('scope') == 'recent'):
                costs = {key: self.stats.get(key, 0) for key in ('requests', 'response_bytes',
                    'wire_bytes', 'queued_messages', 'queued_bytes', 'collected')}
                result = await self._execute(baseline_revision=await self.checkpoint_revision(),
                                              history_only=True, scope='backfill')
                for key, value in costs.items():
                    self.stats[key] = None if value is None or self.stats.get(key) is None else self.stats[key] + value
            for key, value in carried.items():
                self.stats[key] = None if value is None or self.stats.get(key) is None else self.stats[key] + value
            return result
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc,
                stage='yuanhang_limits', unavailable_message='涨停分析错误记录暂不可用',
                fields=getattr(exc, 'source_diagnostic', None))
            raise

    async def _execute(self, *, fresh=False, baseline_revision=0, history_only=False, scope=None):
        if self.intraday and not history_only:
            from empire.features.yuanhang_limits.intraday import dispatch
            return await dispatch(self, fresh=fresh, baseline_revision=baseline_revision)
        state = await self.ingest.checkpoint(self.job_key)
        cursor = state['cursor']
        scope = cursor.get('scope', self.scope) if cursor.get('phase') in ('fetch', 'awaiting_archive') else scope or self.scope
        if cursor and cursor.get('contract') != 2:
            raise ValueError('涨停分析断点契约不符，须显式维护')
        if state['revision'] > baseline_revision and cursor.get('phase') == 'complete':
            self._progress(cursor, finished=True)
            return cursor
        self.stats.update(status='collecting', error='', collected=0, requests=0, response_bytes=0,
                          wire_bytes=0, queued_bytes=0, queued_messages=0, storage='mysql_archive', notice='')
        if scope != 'all':
            self.stats['notice'] = ('本轮仅补历史缺口；本批归档后返回近期调度' if scope == 'backfill'
                                    else '本轮仅核验最近10个交易日；历史缺口另轮补齐')
        if scope == 'today':
            self.stats['notice'] = '本轮仅复核当天完整池；每30分钟至21:00'
        pending = None
        if cursor.get('phase') not in ('fetch', 'awaiting_archive'):
            planned = await self.query.collection_plan(self.pool, force=fresh, **self.plan_options(scope))
            if self.pool == 'reason' and scope == 'recent' and not planned['units'] and not fresh:
                scope = 'backfill'
                planned = await self.query.collection_plan(self.pool, scope=scope)
                self.stats['notice'] = '近期已核验；本轮仅补最多256个历史证券日'
            pending = planned.get('pending')
            cursor = dict(contract=2, phase='fetch', batch_id=uuid4().hex, page=0, index=0,
                          plan=planned['units'], cutoff=planned['cutoff'], remaining=planned['remaining'],
                          force=fresh, scope=scope, scan_after=planned.get('scan_after'))
            if scope == 'today':
                cursor['close_slot'] = planned['close_slot']
        if cursor.get('replan_recent'):
            planned = await self.query.collection_plan(self.pool, scope='recent')
            cursor = {**cursor, 'plan': planned['units'], 'index': 0,
                      'cutoff': planned['cutoff'], 'remaining': planned['remaining'],
                      'scan_after': planned.get('scan_after'), 'scope': 'recent'}
            cursor.pop('replan_recent')
            pending = planned.get('pending')
            state = await self.ingest.advance_checkpoint(job_key=self.job_key,
                expected_revision=state['revision'], cursor=cursor)
        # Whole-run page numbers bind every message to one confirmation.
        # Only the current bounded plan is persisted. After process/Redis
        # loss SQL restores archived units; unconfirmed work may be reread.
        visited = set()
        while cursor['phase'] == 'fetch':
            self._progress(cursor)
            plan = cursor['plan']
            index = cursor.get('index', cursor['page'])
            if (not isinstance(plan, list) or len(plan) > 256 or type(index) is not int
                    or not 0 <= index <= len(plan) or type(cursor['page']) is not int
                    or not 0 <= cursor['page'] <= 10000000):
                raise ValueError('涨停分析断点计划超限或损坏')
            visited.update(tuple(k) if isinstance(k, list) else k for k in plan[:index])
            async with prefetch_units(self, plan, self.fetch, first=index,
                    url=BASE_URL, domains=(DOMAIN,), item_name='涨停分析完整单元',
                    retained_bytes=MAX_UNIT_BYTES if self.pool != 'reason' else 65536) as reads:
                async for position, response in reads:
                    unit, observed = await response.resolve()
                    event = self.envelope(cursor, unit, observed)
                    cursor = {**cursor, 'page': cursor['page'] + 1, 'index': position + 1}
                    if cursor['index'] == len(plan) and (cursor['remaining'] == 0 or scope == 'backfill'):
                        cursor['phase'] = 'awaiting_archive'
                    state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=self.job_key,
                        expected_revision=state['revision'], cursor=cursor)
                    key = plan[position]
                    visited.add(tuple(key) if isinstance(key, list) else key)
                    self.stats['queued_bytes'] += len(event.model_dump_json().encode())
                    self.stats['queued_messages'] += 1
                    self._progress(cursor)
                    self.stats.update(
                                      collected=self.stats['collected'] + (1 if self.pool == 'reason' else len(unit['rows'])))
            if cursor['phase'] == 'awaiting_archive' or cursor['remaining'] == 0 or scope == 'backfill':
                break
            if pending is not None:
                planned = dict(units=pending[:64], remaining=max(0, len(pending) - 64))
                pending = pending[64:]
            else:
                planned = await self.query.collection_plan(self.pool, force=cursor.get('force', False),
                    exclude=visited, through=cursor['cutoff'], scan_after=cursor.get('scan_after'), **self.plan_options(scope))
                pending = planned.get('pending')
            if self.pool == 'reason':
                visited.clear()  # The durable key cursor already excludes prior reason pages.
            cursor = {**cursor, 'plan': planned['units'], 'index': 0, 'remaining': planned['remaining'],
                      'scan_after': planned.get('scan_after')}
            if not cursor['plan']:
                cursor['phase'] = 'awaiting_archive'
        self._progress(cursor, finished=True)
        if cursor['page']:
            self.stats['status'] = 'awaiting_archive'
            await wait_for_archive(partial(self.confirmation.page_status, SOURCE, self.job_key,
                self.project_id, cursor['batch_id'], cursor['page']), retry_seconds=1)
        cursor = {**cursor, 'phase': 'complete'}
        await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
        self.stats.update(status='complete', remaining_units=cursor['remaining'])
        return cursor

    def plan_options(self, scope=None):
        selected = scope or self.scope
        return {'scope': selected} if selected != 'all' else {}

    def _progress(self, cursor, *, finished=False):
        index = cursor.get('index', cursor['page'])
        remaining = cursor['remaining']
        if finished:
            done = total = cursor['page']
            unit = '个完整单元'
        elif remaining is None:
            done, total = index, len(cursor['plan'])
            unit = '个单元（当前批）'
        else:
            done = cursor['page']
            total = done + len(cursor['plan']) - index + remaining
            unit = '个完整单元'
        if cursor.get('scope', self.scope) == 'backfill':
            done, total = index, len(cursor['plan'])
            unit = '个历史证券日' if self.pool == 'reason' else '个历史日期池'
            self.stats['remaining_units'] = remaining
        self.stats.update(completed_units=done, total_units=total, unit_name=unit)

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
