"""ID-keyset recent/full refresh, streaming publication and final confirmation."""
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.features.repurchases.contract import (
    DATASET,
    JOB,
    PAGE,
    PAGE_SIZE,
    PROJECT,
    REPORT,
    SOURCE_FIELDS,
    URL,
    SourceSetChanged,
    extend_digest,
    parse,
)
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)


class RepurchaseCollector:
    manifest = PluginManifest('collector.eastmoney_repurchase', '东方财富股票回购采集',
        requires=('http.fetch', 'ingest.publish', 'repurchases.query', 'archive.confirmation',
                  'collection.records'), provides=('collector.eastmoney_repurchase',),
        description='唯一方案编号游标；近期增量与三日全历史核验')
    source, job_key, project_id = 'eastmoney', JOB, PROJECT

    def __init__(self):
        self.request_retries = 2
        self.stats = dict(status='stopped', collected=0, pages=0, record_name='条回购方案', unit_name='页')

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query = context.get('repurchases.query')
        self.confirmation, self.records = context.get('archive.confirmation'), context.get('collection.records')
        self.stats['status'] = 'idle'
        return {self.manifest.provides[0]: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))['revision']

    async def download(self, cursor, *, reservation):
        await wait_for_capacity(self.ingest, self.stats)
        params = dict(sortColumns='REPURCODE', sortTypes='1', pageSize=PAGE_SIZE, pageNumber=1,
                      reportName=REPORT, columns=','.join(SOURCE_FIELDS.values()), source='WEB')
        if cursor['after']:
            params['filter'] = f'(REPURCODE>"{cursor["after"]}")'
        if cursor.get('refresh'):
            params['filter'] = f"(UPD>='{cursor['refresh']['since']}')" + params.get('filter', '')
        response = await self.http.request('GET', URL, params=params, allowed_domains=('eastmoney.com',),
            headers={'Referer': PAGE}, project_id=PROJECT, policy=self.http.response_policy('generic'),
            max_retries=self.request_retries, reservation=reservation)
        async def consume():
            try:
                body = json.loads(response.content, parse_float=Decimal)
                # This exact source result was verified for a valid empty UPD filter.
                if (cursor.get('refresh') and not cursor['after'] and isinstance(body, dict) and body.get('success') is False
                        and body.get('result') is None and body.get('message') == '返回数据为空'):
                    return [], 0
                rows, count = parse(body, after=cursor['after'],
                                   remaining=None if cursor['total'] is None else cursor['total'] - cursor['collected'])
                if cursor.get('refresh') and any(r['updated_date'] < cursor['refresh']['since'] for r in rows):
                    raise ValueError('回购来源未遵守更新日期筛选')
                return rows, count
            except (ValueError, TypeError, KeyError) as exc:
                exc.diagnostic_recorded = await record_error_safely(self.records, self.stats, PROJECT,
                    exc, stage='source_validation', unavailable_message='回购错误样本暂不可用；断点保留',
                    fields=dict(raw_body=response.content, request_url=str(response.url), status_code=response.status_code))
                raise
        return DeferredResponse(response, consume)

    @measured_run
    async def execute(self, *, fresh=False, baseline_revision=0):
        self.stats.update(completed_units=0, total_units=None, source_rebases=0)
        rebased = False
        stage = 'checkpoint'
        try:
            state = await self.ingest.checkpoint(JOB)
            cursor = state['cursor']
            progressed = state['revision'] > baseline_revision
            if progressed and cursor.get('phase') == 'complete':
                self.stats.update(completed_units=cursor['collected'], total_units=cursor['total'])
                return cursor
            if cursor and cursor.get('contract') != 1:
                raise ValueError('回购旧断点契约需显式维护')
            if not cursor or cursor.get('phase') == 'complete' or (fresh and not progressed and cursor.get('phase') == 'fetch'):
                refresh = None if fresh else await self.query.refresh_plan(cursor)
                cursor = dict(phase='fetch', batch_id=uuid4().hex, pages=0, collected=0,
                              total=None, after='', digest='0'*64, contract=1, refresh=refresh)
            self.stats.update(completed_units=cursor['collected'], total_units=cursor['total'], unit_name='条回购方案')
            while cursor['phase'] == 'fetch':
                self.stats.update(status='collecting', error='')
                async with prefetch_units(self, [dict(cursor)], self.download, url=URL,
                        domains=('eastmoney.com',), independent=False, item_name='页') as reads:
                    async for _, read in reads:
                        stage = 'source_validation'
                        try:
                            rows, remaining = await read.resolve()
                        except SourceSetChanged:
                            if rebased:
                                raise
                            # A mutable complete catalogue has no snapshot token.
                            # Re-establish its proof once; no network/row failure
                            # takes this path. Already queued data stays owned by
                            # the archiver. Commit the new cursor only with data.
                            rebased = True
                            self.stats.update(source_rebases=1,
                                notice='回购来源集合已改变，本轮限一次从头核验；已归档方案保留')
                            cursor = dict(phase='fetch', batch_id=uuid4().hex, pages=0,
                                collected=0, total=None, after='', digest='0'*64, contract=1, refresh=cursor.get('refresh'))
                            break
                        total = remaining if cursor['total'] is None else cursor['total']
                        limit = getattr(self.ingest, 'settings', {}).get('max_page_bytes', 524288)
                        chunks, group, used = [], [], 4096
                        for row in rows:
                            size = len(json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode()) + 1
                            if size + 4096 > limit:
                                raise ValueError('单回购方案超过正式入队消息容量，断点未推进')
                            if used + size > limit and group:
                                chunks.append(group)
                                group, used = [], 4096
                            group.append(row)
                            used += size
                        chunks.append(group)
                        read.close()
                        for group in chunks:
                            collected, page = cursor['collected'] + len(group), cursor['pages'] + 1
                            summary = extend_digest(cursor['digest'], group)
                            finished = collected == total
                            updated = {**cursor, 'phase': 'awaiting_archive' if finished else 'fetch',
                                'total': total, 'collected': collected, 'pages': page, 'digest': summary,
                                'after': group[-1]['plan_id'] if group else cursor['after']}
                            envelope = make_envelope(source=self.source, dataset=DATASET, job_key=JOB,
                                business_key=f'{cursor["batch_id"]}:{page}', run_id=cursor['batch_id'],
                                batch_id=cursor['batch_id'], payload=dict(page=page, rows=group,
                                    total=total, collected=collected, digest=summary, finished=finished,
                                    **({'refresh': cursor['refresh']} if cursor.get('refresh') else {})))
                            envelope = envelope.model_copy(update={'source_url': PAGE, 'available_at': None})
                            if len(envelope.model_dump_json().encode()) > limit:
                                raise ValueError('回购消息超过公共容量，断点未推进')
                            stage = 'queue_publish'
                            state = await publish_with_capacity(self.ingest, self.stats, [envelope],
                                job_key=JOB, expected_revision=state['revision'], cursor=updated)
                            cursor = state['cursor']
                            self.stats.update(collected=collected, pages=page,
                                total_units=total, completed_units=collected, unit_name='条回购方案')
            stage = 'archive_confirmation'
            self.stats.update(status='awaiting_archive', collected=cursor['collected'], pages=cursor['pages'])
            await wait_for_archive(partial(self.confirmation.page_status, self.source, JOB,
                PROJECT, cursor['batch_id'], cursor['pages']), retry_seconds=1)
            if cursor.get('refresh') and not cursor.get('proof_published'):
                # All incremental messages are confirmed and drained first. This
                # digest describes SQL plus the dated full baseline, not a new
                # complete-source download.
                audit = await self.query.current_summary()
                if audit['invalid']:
                    raise ValueError('回购SQL内容摘要不一致，不能发布增量组合证明')
                page = cursor['pages'] + 1
                envelope = make_envelope(source=self.source, dataset=DATASET, job_key=JOB,
                    business_key=f'{cursor["batch_id"]}:{page}', run_id=cursor['batch_id'],
                    batch_id=cursor['batch_id'], payload=dict(page=page, rows=[], total=audit['count'],
                        collected=audit['count'], digest=audit['digest'], finished=True,
                        refresh=dict(cursor['refresh'], proof=True)))
                updated = dict(cursor, pages=page, proof_published=True,
                               coverage_count=audit['count'], coverage_digest=audit['digest'])
                state = await publish_with_capacity(self.ingest, self.stats, [envelope], job_key=JOB,
                    expected_revision=state['revision'], cursor=updated)
                cursor = state['cursor']
                await wait_for_archive(partial(self.confirmation.page_status, self.source, JOB,
                    PROJECT, cursor['batch_id'], cursor['pages']), retry_seconds=1)
            cursor = {**cursor, 'phase': 'complete', 'completed_at': datetime.now(UTC).isoformat(timespec='microseconds')}
            await self.ingest.advance_checkpoint(job_key=JOB, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return cursor
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, PROJECT, exc, stage=stage,
                                    unavailable_message='回购错误记录暂不可用；未跳过失败')
            raise

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
