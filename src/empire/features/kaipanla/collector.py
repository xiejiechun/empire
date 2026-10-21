"""Current listed pool, SQL hole recovery and atomic independent security/day units."""
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.features.kaipanla.canonical import digest, identity
from empire.features.kaipanla.contract import PRODUCTS, capability, project
from empire.features.kaipanla.dates import lifecycle, required_days
from empire.features.kaipanla.download import download_days
from empire.features.kaipanla.listings_source import attach_listing_dates
from empire.features.kaipanla.normalization import point_count
from empire.features.kaipanla.refresh import review_days
from empire.features.kaipanla.source_protocol import URL, SourceError
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
)


class KaipanlaProductCollector:
    def __init__(self, kind):
        self.kind = kind
        self.source, self.project_id = 'kaipanla', project(kind)
        self.job_key = self.project_id + '-v1'
        self.dataset = 'kaipanla.' + kind + '.day'
        self.collector_capability = 'collector.kaipanla_' + kind
        self.manifest = PluginManifest(self.collector_capability, '开盘啦' + PRODUCTS[kind].title,
            requires=('http.fetch', 'ingest.publish', capability(kind),
                      'archive.confirmation', 'collection.records'),
            provides=(self.collector_capability,), description=PRODUCTS[kind].note)
        self.request_retries = 2
        self.stats = {'status': 'stopped', 'collected': 0, 'record_name': '点位', 'unit_name': '证券日',
                      'download_item_name': '个响应'}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.records = context.get(capability(self.kind)), context.get('collection.records')
        self.confirmation = context.get('archive.confirmation')
        self.stats['status'] = 'idle'
        return {self.collector_capability: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    def validate_request(self, request):
        if self.kind != 'quote':
            raise ValueError('当前仅历史盘口与日行情摘要支持显式有限采集范围')
        from empire.features.kaipanla.selection import validate_request
        return validate_request(request)

    async def execute(self, *, fresh=False, baseline_revision=0, request=None):
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if request is not None:
                request = self.validate_request(request)
            if cursor.get('phase') == 'awaiting_archive' and cursor.get('request') != request:
                raise ValueError('待归档断点属于另一采集范围，须先恢复原范围')
            if (state['revision'] > baseline_revision and cursor.get('phase') == 'complete'
                    and cursor.get('request') == request):
                return cursor
            if cursor.get('phase') == 'awaiting_archive':
                return await self.finish(state)
            stocks, days = await self.query.plan()
            if request is not None:
                from empire.features.kaipanla.selection import select_plan
                stocks, days = select_plan(request, stocks, days)
            self.aliases = {}  # Exchange identity proof is scoped to this download/resume round.
            if not days:
                raise ValueError('分时计划没有已结束交易日')
            stocks = await attach_listing_dates(self, stocks)
            exclusions = await self.query.suspension_plan(stocks, days[0], days[-1])
            plans = []
            checksum = hashlib.sha256(('weekly-review-v1:' + json.dumps([d.isoformat() for d in days])).encode())
            for stock in stocks:
                excluded = exclusions[stock['code'] + '.' + stock['market']]
                count = len(required_days(stock, days, excluded))
                plans.append((excluded, count))
                checksum.update(digest([stock['market'], stock['code'], lifecycle(stock),
                                       sorted(d.isoformat() for d in excluded)]).encode())
            scope = checksum.hexdigest()
            last_review = cursor.get('last_review')
            if (fresh or cursor.get('scope') != scope or cursor.get('phase') == 'complete'
                    or cursor.get('request') != request):
                cursor = {}
            if not cursor:
                token, review = review_days(days, last_review)
                cursor = dict(phase='collecting', scope=scope, batch_id=uuid4().hex,
                              index=0, pages=0, collected=0, started_at=datetime.now(UTC).isoformat(),
                              start_date=days[0].isoformat(), end_date=days[-1].isoformat(),
                              last_review=last_review, review_token=last_review if request else token,
                              review_days=review)
                if request is not None:
                    cursor['request'] = request
            total = sum(count for _, count in plans)
            first_gap, failed = None, 0
            cursor = {**cursor, 'first_gap': None, 'failed_units': 0,
                      'unlisted_without_date': self.stats.get('unlisted_without_date', 0)}
            self.stats.update(status='collecting', total_units=total, completed_units=cursor['index'],
                              failed_units=0, error='', failure_categories={})
            # Independent valid days continue after a source gap, while the
            # durable frontier stays at the first missing day. Never claim full
            # completion from later success; SQL recovers all later archived days.
            offset = 0
            for stock, (excluded, count) in zip(stocks, plans, strict=True):
                if offset + count <= cursor['index']:
                    offset += count
                    continue
                planned = required_days(stock, days, excluded)
                life = lifecycle(stock)
                covered = await self.query.covered_days(stock['market'], stock['code'], days[0], days[-1], life)
                todo = [(offset + di, day) for di, day in enumerate(planned)
                        if offset + di >= cursor['index'] and
                        (fresh or day not in covered or day.isoformat() in cursor['review_days'])]
                if not todo:
                    cursor = {**cursor, 'index': first_gap['index'] if first_gap else offset + len(planned)}
                async with download_days(self, stock, [day for _, day in todo]) as reads:
                    async for position, day, downloaded, observed, source_error in reads:
                        index = todo[position][0]
                        self.stats.update(current_security=stock['market'] + ':' + stock['code'] + ' / ' + day.isoformat(),
                                          current_date=day.isoformat(), completed_units=index - failed)
                        stage = 'source_validation'
                        if source_error:
                            failed += 1
                            categories = self.stats['failure_categories']
                            categories[source_error.category] = categories.get(source_error.category, 0) + 1
                            first_gap = first_gap or dict(index=index, market=stock['market'], code=stock['code'],
                                                         trade_date=day.isoformat(), error=str(source_error)[:256])
                            cursor = {**cursor, 'index': first_gap['index'], 'first_gap': first_gap,
                                      'failed_units': failed}
                            state = await self.ingest.advance_checkpoint(job_key=self.job_key,
                                expected_revision=state['revision'], cursor=cursor)
                            self.stats.update(failed_units=failed, first_gap=first_gap, error=str(source_error))
                            continue
                        row = {**downloaded, 'market': stock['market'], 'lifecycle': life}
                        page = cursor['pages'] + 1
                        envelope = make_envelope(source=self.source, dataset=self.dataset, business_key=identity(row),
                            job_key=self.job_key, run_id=cursor['batch_id'], batch_id=cursor['batch_id'],
                            payload=dict(page=page, rows=[row]))
                        envelope = envelope.model_copy(update={'source_url': URL, 'available_at': None, 'observed_at': observed})
                        next_cursor = {**cursor, 'index': first_gap['index'] if first_gap else index + 1, 'pages': page,
                                       'collected': cursor['collected'] + point_count(row)}
                        stage = 'queue_publish'
                        state = await publish_with_capacity(self.ingest, self.stats, [envelope], job_key=self.job_key,
                            expected_revision=state['revision'], cursor=next_cursor)
                        cursor = state['cursor']
                        self.stats.update(collected=cursor['collected'], pages=page, completed_units=index + 1 - failed)
                        if first_gap:
                            self.stats['error'] = '尚有来源缺口：' + first_gap['code'] + ' / ' + first_gap['trade_date']
                        # No page waits for SQL; only the end of the download round does.
                offset += len(planned)
            if not cursor['pages']:
                # A validated SQL-only recovery plan can finish without inventing
                # an archive progress message or entering the business queue.
                if first_gap:
                    raise SourceError('本轮仍有来源缺口：' + first_gap['code'] + ' / ' + first_gap['trade_date'])
                cursor = {**cursor, 'phase': 'complete', 'index': total, 'last_review': cursor['review_token']}
                await self.ingest.advance_checkpoint(job_key=self.job_key,
                    expected_revision=state['revision'], cursor=cursor)
                self.stats.update(status='complete', completed_units=total)
                return cursor
            cursor = {**cursor, 'phase': 'awaiting_archive', 'index': first_gap['index'] if first_gap else total}
            self.stats['completed_units'] = total - failed
            state = await self.ingest.advance_checkpoint(job_key=self.job_key,
                expected_revision=state['revision'], cursor=cursor)
            stage = 'archive_confirmation'
            return await self.finish(state)
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            self.stats.update(status='error', error=self.records.sanitize_text(exc))
            await record_error_safely(self.records, self.stats, self.project_id, exc,
                stage=stage, unavailable_message='开盘啦错误记录暂不可用；失败证券日未推进')
            raise

    async def finish(self, state):
        cursor = state['cursor']
        self.stats.update(status='awaiting_archive', collected=cursor['collected'])
        await wait_for_archive(partial(self.confirmation.page_status, self.source, self.job_key,
            self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
        if cursor.get('first_gap'):
            cursor = {**cursor, 'phase': 'collecting'}
            await self.ingest.advance_checkpoint(job_key=self.job_key,
                expected_revision=state['revision'], cursor=cursor)
            error = SourceError('本轮有效证券日已归档，仍有来源缺口：' + cursor['first_gap']['code']
                                + ' / ' + cursor['first_gap']['trade_date'])
            error.diagnostic_recorded = True  # Original precise source failures remain in bounded records.
            raise error
        cursor = {**cursor, 'phase': 'complete', 'last_review': cursor.get('review_token', cursor.get('last_review'))}
        await self.ingest.advance_checkpoint(job_key=self.job_key,
            expected_revision=state['revision'], cursor=cursor)
        self.stats.update(status='complete', error='')
        return cursor

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
