"""Node-bound native requests and ordered publication on shared infrastructure."""
import asyncio
from datetime import date, datetime
from functools import partial
from uuid import uuid4

import httpx

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.request_retry import retry_delay
from empire.core.time import CHINA
from empire.features.yuanhang.availability import DeferredSecurity, resolve_empty
from empire.features.yuanhang.contract import (
    FINANCIAL_DATASET,
    FINANCIAL_JOB,
    FINANCIAL_PROJECT,
    PRICE_DATASET,
    PRICE_JOB,
    PRICE_PROJECT,
    SOURCE,
)
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.infra.routing import USE_PROXY
from empire.plugins.infra.sensitive_request import SensitiveRequestError
from empire.sources.yuanhang_auth import AuthenticationError
from empire.sources.yuanhang_client import fetch_history
from empire.sources.yuanhang_history import IncompleteFinancialHistory
from empire.sources.yuanhang_payload import (
    FINANCIAL_END,
    FIRST,
    daily_years,
    digest,
    financial_payload,
)
from empire.sources.yuanhang_range_payload import daily_ranges
from empire.sources.yuanhang_wire import EmptyHistoryResponse


class YuanhangCollector:
    def __init__(self, financial=False):
        self.financial = financial
        self.project_id = FINANCIAL_PROJECT if financial else PRICE_PROJECT
        self.job_key = FINANCIAL_JOB if financial else PRICE_JOB
        self.dataset = FINANCIAL_DATASET if financial else PRICE_DATASET
        capability = 'collector.yuanhang_financial' if financial else 'collector.yuanhang_prices'
        self.capability, self.source = capability, SOURCE
        self.manifest = PluginManifest(capability, '远航权息与股本' if financial else '远航完整历史日线',
            requires=('http.fetch', 'ingest.publish', 'yuanhang.history.query', 'yuanhang.identity',
                      'archive.confirmation', 'collection.records'), provides=(capability,),
            description='固定节点身份、完整原生响应、共享预取及统一归档')
        self.request_retries, self.selected_codes = 2, None
        self.stats = dict(status='stopped', collected=0)
        self.plans = {}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.identity = context.get('yuanhang.history.query'), context.get('yuanhang.identity')
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {self.capability: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    def result(self, cursor):
        # Rebuildable pool-wide plans live only in memory. Do not retain even
        # the current in-progress plan in the bounded operational run history.
        costs = ('logical_history_requests', 'response_bytes', 'decoded_bytes',
                 'planned_requests', 'skipped_units', 'full_units', 'range_units')
        return {**{k: v for k, v in cursor.items() if k != 'current_plan'},
                **{k: self.stats.get(k, 0) for k in costs}}

    async def fetch(self, unit, *, reservation=None):
        code, preferred, through = unit
        plan = self.plans.get(code, {})
        await wait_for_capacity(self.ingest, self.stats)
        excluded = set()
        for attempt in range(self.request_retries + 1):
            profiles = await self.identity.registry.load()
            nodes = sorted(n for n in self.identity.online_codes() - excluded
                           if n in profiles and profiles[n].provisioned)
            if not nodes:
                raise ValueError('远航版没有可重试的健康身份节点，保留当前断点')
            node = preferred if preferred in nodes else nodes[0]
            try:
                return await self.fetch_authenticated(node, code, through, plan, reservation)
            except (EmptyHistoryResponse, IncompleteFinancialHistory) as exc:
                if plan.get('mode') == 'range':
                    raise ValueError('远航区间含已知成交日仍返回空响应；保留断点，不转为成功或全历史') from exc
                return await resolve_empty(self, code, through, reservation=reservation, cause=exc)
            except (httpx.TransportError, SensitiveRequestError, TimeoutError) as exc:
                if (isinstance(exc, SensitiveRequestError) and not exc.retryable_transport
                        or attempt >= self.request_retries):
                    raise
                excluded.add(node)
                self.stats['node_transport_retries'] = self.stats.get('node_transport_retries', 0) + 1
                await asyncio.sleep(retry_delay(attempt + 1))

    async def fetch_authenticated(self, node, code, through, plan, reservation):
        session = await self.identity.login(node, project_id=self.project_id)
        for renewal in range(2):
            try:
                result = await fetch_history(self.http, session, unified_code=code,
                    dataset='financial' if self.financial else 'daily',
                    start=date.fromisoformat(plan['start']) if plan.get('start') else FIRST,
                    end=FINANCIAL_END if self.financial else date.fromisoformat(through),
                    max_retries=0, reservation=reservation, native_market=plan.get('native_market'))
                self.identity.sessions.confirm(node, session)
                return result
            except AuthenticationError as exc:
                if exc.stage != 'native-login' or exc.code is None:
                    raise
                if renewal:
                    self.identity.sessions.reject(node, session)
                    raise
                session = await self.identity.login(node, project_id=self.project_id, rejected=session)

    async def publish(self, state, cursor, history, observed):
        page = cursor['pages'] + 1
        cursor = {**cursor, 'pages': page, 'collected': cursor['collected']
                  + len(history.get('rows', [])) + len(history.get('actions', [])) + len(history.get('capital', []))}
        suffix = 'financial' if self.financial else str(history['year'])
        e = make_envelope(source=SOURCE, dataset=self.dataset,
            business_key=history['code'] + ':' + suffix, job_key=self.job_key,
            batch_id=cursor['batch_id'], run_id=cursor['batch_id'], payload=dict(page=page, history=history))
        e = e.model_copy(update=dict(observed_at=observed, available_at=None))
        state = await publish_with_capacity(self.ingest, self.stats, [e], job_key=self.job_key,
                                           expected_revision=state['revision'], cursor=cursor)
        return state, cursor

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'plan'
        try:
            self.stats.update(logical_history_requests=0, response_bytes=0, decoded_bytes=0)
            if not USE_PROXY.get():
                raise ValueError('远航节点身份要求代理，请在任务中启用代理；无法绑定本机直连身份')
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if state['revision'] > baseline_revision and cursor.get('phase') == 'complete' and not fresh:
                return self.result(cursor)
            codes, through = await self.query.collection_scope(self.selected_codes)
            scope = digest(codes)
            today = datetime.now(CHINA).date().isoformat()
            if (not fresh and cursor.get('phase') == 'complete' and cursor.get('scope_hash') == scope
                    and not cursor.get('deferred') and cursor.get('through') == through
                    and self.financial and cursor.get('run_date') == today):
                self.stats.update(status='complete', planned_requests=0, skipped_units=len(codes),
                                  completed_units=len(codes), total_units=len(codes))
                return self.result({**cursor, 'pages': 0, 'collected': 0})
            if cursor.get('phase') == 'complete' or (fresh and state['revision'] <= baseline_revision):
                cursor = {}
            if cursor and cursor.get('scope_hash') != scope:
                cursor = {}
            if 'plans' in cursor or 'work_codes' in cursor:
                raise ValueError('远航旧版整池计划断点需通过显式维护入口转换，保留原断点')
            if not cursor:
                cursor = dict(phase='collecting', scope_hash=scope, through=through,
                    next_index=0, next_year=1900, snapshot_hash='', pages=0, collected=0, batch_id=uuid4().hex,
                    run_date=today, force_full=fresh, skipped_units=0)
            # Positions always refer to the complete, scope-hashed stock pool.
            # SQL may have advanced after a crash; rebuild only the unstarted
            # suffix, pinning any partially published security to its old plan.
            self.plans = {}
            if cursor['phase'] == 'collecting':
                first = cursor['next_index'] + int(bool(cursor.get('current_plan')))
                remaining = codes[first:]
                if self.financial:
                    markets = await self.query.financial_markets()
                    self.plans = {c: dict(mode='financial', native_market=markets.get(c)) for c in remaining}
                elif remaining:
                    self.plans = await self.query.daily_plans(self.ingest.redis.prefix, remaining,
                        cursor['through'], force=cursor.get('force_full', False))
                if cursor.get('current_plan'):
                    self.plans[codes[cursor['next_index']]] = cursor['current_plan']
            positions = [i for i in range(cursor['next_index'], len(codes))
                         if self.plans.get(codes[i], {}).get('mode') != 'skip']
            self.stats.update(planned_requests=len(positions), skipped_units=cursor.get('skipped_units', 0)
                              + len(codes) - cursor['next_index'] - len(positions),
                full_units=sum(p['mode'] == 'full' for p in self.plans.values()),
                range_units=sum(p['mode'] == 'range' for p in self.plans.values()))
            cursor = {**cursor, 'deferred': cursor.get('deferred', {}),
                      'skipped_units': cursor.get('skipped_units', 0)}
            self.stats.update(status=cursor['phase'], total_units=len(codes),
                completed_units=cursor['next_index'], collected=cursor['collected'],
                deferred_units=len(cursor['deferred']), error='')
            if cursor['phase'] == 'collecting' and positions:
                profiles = await self.identity.registry.load()
                nodes = sorted(code for code in self.identity.online_codes()
                               if code in profiles and profiles[code].provisioned)
                if not nodes:
                    raise ValueError('没有已就绪且在线的远航节点身份，请查看身份管理')
                units = [(codes[i], nodes[n % len(nodes)], cursor['through']) for n, i in enumerate(positions)]
                async with prefetch_units(self, units, self.fetch, url='https://10jqka.com.cn/',
                        domains=('10jqka.com.cn',), profile='stocks', item_name='只股票') as reads:
                    async for n, read in reads:
                        i = positions[n]
                        stage = 'source_validation'
                        snapshot = await read.resolve()
                        self.stats['logical_history_requests'] += 1
                        self.stats['response_bytes'] += getattr(snapshot, 'response_bytes', 0)
                        self.stats['decoded_bytes'] += getattr(snapshot, 'decoded_bytes', 0)
                        code = codes[i]
                        if isinstance(snapshot, DeferredSecurity):
                            if snapshot.code != code or snapshot.through != cursor['through']:
                                raise ValueError('远航上市前范围证据身份或截止日不一致')
                            histories = []
                            cursor = {**cursor, 'deferred': {**cursor['deferred'], code: snapshot.evidence()}}
                        else:
                            plan = self.plans.get(code, {})
                            if plan.get('mode') == 'range':
                                histories = daily_ranges(snapshot, code=code, start=date.fromisoformat(plan['start']),
                                                         through=date.fromisoformat(cursor['through']))
                            else:
                                histories = ([financial_payload(snapshot, code=code)] if self.financial else
                                    daily_years(snapshot, code=code, through=date.fromisoformat(cursor['through'])))
                        checksum = digest(histories)
                        if cursor['snapshot_hash'] != checksum:
                            cursor = {**cursor, 'next_year': 1900, 'snapshot_hash': checksum}
                        self.stats['current_security'] = code
                        for history in histories:
                            year = history.get('year', 1900)
                            if year < cursor['next_year']:
                                continue
                            stage = 'queue_publish'
                            # The cursor advances only in the same Redis operation as this unit.
                            next_cursor = {**cursor, 'next_index': i, 'next_year': year + 1,
                                           'current_plan': self.plans[code],
                                           'skipped_units': cursor['skipped_units'] + i - cursor['next_index']}
                            state, cursor = await self.publish(state, next_cursor, history, snapshot.observed_at)
                        cursor = {**cursor, 'skipped_units': cursor['skipped_units'] + i - cursor['next_index'],
                                  'next_index': i + 1, 'next_year': 1900, 'snapshot_hash': ''}
                        cursor.pop('current_plan', None)
                        state = await self.ingest.advance_checkpoint(job_key=self.job_key,
                            expected_revision=state['revision'], cursor=cursor)
                        self.stats.update(completed_units=i + 1, collected=cursor['collected'], pages=cursor['pages'],
                                          deferred_units=len(cursor['deferred']))
            if cursor['phase'] == 'collecting':
                cursor = {**cursor, 'phase': 'awaiting_archive', 'next_index': len(codes),
                          'skipped_units': cursor['skipped_units'] + len(codes) - cursor['next_index']}
                state = await self.ingest.advance_checkpoint(job_key=self.job_key,
                    expected_revision=state['revision'], cursor=cursor)
                self.stats.update(completed_units=len(codes))
            stage = 'archive_confirmation'
            self.stats['status'] = 'awaiting_archive'
            if cursor['pages']:
                await wait_for_archive(partial(self.confirmation.page_status, SOURCE, self.job_key,
                    self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
            for code in cursor['deferred']:
                if await self.query.has_history(code, financial=self.financial):
                    raise ValueError(code + ': 延期证券出现已归档原生历史，需重新核实上市状态')
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return self.result(cursor)
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc, stage=stage,
                unavailable_message='远航错误记录暂不可用；已入队断点保留')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
