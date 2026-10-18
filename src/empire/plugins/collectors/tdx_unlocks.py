"""One collector discovers list facts and reads each shared detail group once."""
import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.unlocks import (
    CONTRACT,
    DATASET,
    JOB,
    MARKETS,
    PROJECT,
    digest,
    monthly_plan,
    pack,
    valid_proof,
    validate_unit,
)
from empire.core.time import CHINA
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.tdx_unlock_source import (
    PAGE,
    URL,
    body,
    detail_params,
    list_params,
    parse_detail,
    parse_list,
)
from empire.plugins.datasets.unlocks import list_digest


class UnlockCollector:
    project_id, job_key = PROJECT, JOB
    manifest = PluginManifest('collector.tdx_unlocks', '大小非解禁个股与明细采集',
        requires=('http.fetch', 'ingest.publish', 'unlocks.tdx_query', 'archive.confirmation', 'collection.records'),
        provides=('collector.tdx_unlocks',), description='列表10000000；月列表与共享股东明细一次完整校验')

    def __init__(self):
        self.request_retries = 2
        self.stats = dict(status='stopped', collected=0, record_name='条解禁列表事实',
                          unit_name='个月', completed_units=0, requests=0)

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.confirmation = context.get('unlocks.tdx_query'), context.get('archive.confirmation')
        self.records = context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.tdx_unlocks': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))['revision']

    async def fetch(self, requested, *, detail=False, reservation=None):
        await wait_for_capacity(self.ingest, self.stats)
        params = detail_params(requested) if detail else list_params(requested)
        response = await self.http.request('POST', URL, content=body(params),
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'Referer': PAGE},
            allowed_domains=('tdx.com.cn',), project_id=PROJECT,
            policy=self.http.response_policy('generic'), max_retries=self.request_retries, reservation=reservation)
        self.stats['requests'] += 1
        async def consume():
            try:
                return (parse_detail(response.json(), requested) if detail else parse_list(response.json(), requested))
            except (ValueError, TypeError, KeyError) as exc:
                raw = response.content
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, PROJECT, exc,
                    stage='source_validation', unavailable_message='解禁来源诊断暂不可用',
                    fields=dict(request_url=URL, status_code=response.status_code, raw_body=raw[:65536],
                                observed_bytes=len(raw), body_sha256=hashlib.sha256(raw).hexdigest(),
                                metadata={'mode': 'detail' if detail else 'list', 'params': params}))
                raise
        return DeferredResponse(response, consume)

    def envelope(self, unit, parents, details, cursor, observed, manifest=None):
        event = make_envelope(source='tdx', dataset=DATASET, business_key=unit, job_key=JOB,
            batch_id=cursor['batch_id'], run_id=cursor['batch_id'], schema_version=CONTRACT,
            payload=dict(page=cursor['page'] + 1, unit=unit,
                         data=None if manifest else pack(parents, details), manifest=manifest))
        return event.model_copy(update={'observed_at': observed, 'source_url': PAGE, 'available_at': None})

    async def execute(self, *, fresh=False, baseline_revision=0, start_month=None, end_month=None):
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(JOB)
            cursor = state['cursor']
            progressed = state['revision'] > baseline_revision
            if progressed and cursor.get('phase') == 'complete' and not (start_month or end_month):
                return cursor
            if cursor and cursor.get('contract') != CONTRACT:
                raise ValueError('解禁旧断点须显式维护')
            if cursor.get('phase') != 'awaiting_archive':
                active = cursor.get('phase') == 'fetch'
                start = start_month or (cursor.get('start') if active else None) or '1990-01-01'
                end = end_month or (cursor.get('end') if active else None) or f'{datetime.now(CHINA).year + 1}-12-01'
                months = monthly_plan(start, end)
                if len(months) > 2600:
                    raise ValueError('解禁范围超过有界月份计划')
                if cursor.get('phase') == 'fetch' and (start, end) != (cursor['start'], cursor['end']) and not fresh:
                    raise ValueError('解禁指定范围与断点冲突；须显式重新初始化')
                if fresh and not progressed or cursor.get('phase') == 'complete':
                    cursor = {}
                if not cursor:
                    cursor = dict(phase='fetch', start=start, end=end, index=0, market_index=0,
                        response_hash='', page=0, collected=0, details=0, rolling='', contract=CONTRACT,
                        batch_id=uuid4().hex, force=bool(fresh),
                        review_index=datetime.now(CHINA).date().toordinal() % len(months))
                stored = await self.query.state()
                proofs = stored.get('units', {}) if stored.get('contract_version') == CONTRACT else {}
                self.stats.update(status='collecting', error='', requests=0, total_units=len(months),
                                  completed_units=cursor['index'], collected=cursor['collected'])
                for index in range(cursor['index'], len(months)):
                    month, observed = months[index], datetime.now(UTC)
                    async with prefetch_units(self, [month], self.fetch, url=URL,
                            domains=('tdx.com.cn',), item_name='月列表') as reads:
                        async for _, read in reads:
                            parents = await read.resolve()
                    groups, skipped = {}, {}
                    for market in MARKETS:
                        unit = month + '|' + market
                        rows = [r for r in parents if r['unified_code'].endswith(market)]
                        proof = proofs.get(unit, {})
                        if (not cursor['force'] and not cursor['market_index'] and index != cursor['review_index']
                                and valid_proof(proof) and proof.get('count') == len(rows)
                                and proof.get('list_digest') == list_digest(rows) and not proof.get('empty_groups', 1)):
                            skipped[unit] = proof
                        else:
                            groups[unit] = rows
                    requests = {r['group_key']: r for rows in groups.values() for r in rows}
                    detail_rows = {}
                    async def download(parent, *, reservation):
                        return await self.fetch(parent, detail=True, reservation=reservation)
                    keys = sorted(requests)
                    async with prefetch_units(self, [requests[k] for k in keys], download, url=URL,
                            domains=('tdx.com.cn',), item_name='明细请求组') as reads:
                        async for offset, read in reads:
                            detail_rows[keys[offset]] = await read.resolve()
                    complete = {}
                    for unit, rows in groups.items():
                        headers = [{**r, 'detail_status': 'present' if detail_rows[r['group_key']] else 'source_empty',
                                    'detail_count': len(detail_rows[r['group_key']])} for r in rows]
                        children = sorted([r for key in {r['group_key'] for r in rows} for r in detail_rows[key]],
                                          key=lambda r: r['record_key'])
                        validate_unit(unit, headers, children)
                        complete[unit] = (headers, children)
                    source_hash = digest({month + '|' + market:
                        digest(list(complete[month + '|' + market])) if month + '|' + market in complete
                        else skipped[month + '|' + market]['digest'] for market in MARKETS})
                    if cursor['market_index'] and cursor['response_hash'] != source_hash:
                        raise ValueError('解禁中断月份来源已修订；须重新初始化，不混合旧新集合')
                    for unit, (headers, children) in complete.items():
                        probe = self.envelope(unit, headers, children, cursor, observed)
                        if len(probe.model_dump_json().encode()) > getattr(self.ingest, 'settings', {}).get('max_page_bytes', 524288):
                            raise ValueError('解禁完整月市场消息超限；不截断或推进断点')
                    for market_index, market in enumerate(MARKETS):
                        if market_index < cursor['market_index']:
                            continue
                        unit = month + '|' + market
                        if unit in complete:
                            headers, children = complete[unit]
                            content_hash, count, detail_count = digest([headers, children]), len(headers), len(children)
                        else:
                            proof = skipped[unit]
                            content_hash, count, detail_count = proof['digest'], proof['count'], proof['details']
                        next_cursor = {**cursor, 'market_index': market_index + 1, 'response_hash': source_hash,
                            'collected': cursor['collected'] + count, 'details': cursor['details'] + detail_count,
                            'rolling': digest([cursor['rolling'], unit, content_hash, count, detail_count])}
                        if market_index == 2:
                            next_cursor.update(index=index + 1, market_index=0, response_hash='')
                        stage = 'queue_publish'
                        if unit in complete:
                            event = self.envelope(unit, headers, children, cursor, observed)
                            next_cursor['page'] += 1
                            state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=JOB,
                                expected_revision=state['revision'], cursor=next_cursor)
                        else:
                            state = await self.ingest.advance_checkpoint(job_key=JOB,
                                expected_revision=state['revision'], cursor=next_cursor)
                        cursor = next_cursor
                    self.stats.update(collected=cursor['collected'], details=cursor['details'],
                                      completed_units=cursor['index'], pages=cursor['page'])
                m = dict(start=start, end=end, units=len(months) * 3, count=cursor['collected'],
                         details=cursor['details'], digest=cursor['rolling'])
                event = self.envelope('manifest', [], [], cursor, datetime.now(UTC), m)
                cursor = {**cursor, 'phase': 'awaiting_archive', 'page': cursor['page'] + 1}
                state = await publish_with_capacity(self.ingest, self.stats, [event], job_key=JOB,
                    expected_revision=state['revision'], cursor=cursor)
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'], pages=cursor['page'])
            await wait_for_archive(partial(self.confirmation.page_status, 'tdx', JOB, PROJECT,
                cursor['batch_id'], cursor['page']), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete'}
            await self.ingest.advance_checkpoint(job_key=JOB, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, PROJECT, exc, stage=stage,
                                    unavailable_message='解禁错误记录暂不可用；失败单元未跳过')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
