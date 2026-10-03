"""Current listed pool, SQL hole recovery and atomic independent security/day units."""
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.plugins.collectors.kaipanla_scope import attach_listing_dates, lifecycle, required_days
from empire.plugins.collectors.kaipanla_source import URL, SourceError, fetch_day
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
)
from empire.plugins.datasets.intraday import JOB, PROJECT, digest, identity


class KaipanlaIntradayCollector:
    manifest = PluginManifest('collector.kaipanla_intraday', '开盘啦历史分时及竞价',
        requires=('http.fetch', 'ingest.publish', 'intraday.query', 'archive.confirmation', 'collection.records'),
        provides=('collector.kaipanla_intraday',), description='当前上市证券的历史逐日补采；不以源站错误证明空日')

    def __init__(self):
        self.source, self.project_id, self.job_key = 'kaipanla', PROJECT, JOB
        self.request_retries = 2
        self.stats = {'status': 'stopped', 'collected': 0, 'record_name': '点位', 'unit_name': '证券日'}

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.records = context.get('intraday.query'), context.get('collection.records')
        self.confirmation = context.get('archive.confirmation')
        self.stats['status'] = 'idle'
        return {'collector.kaipanla_intraday': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = 'plan'
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state['cursor']
            if state['revision'] > baseline_revision and cursor.get('phase') == 'complete':
                return cursor
            if cursor.get('phase') == 'awaiting_archive':
                return await self.finish(state)
            stocks, days = await self.query.plan()
            self.aliases = {}  # Exchange identity proof is scoped to this download/resume round.
            if not days:
                raise ValueError('分时计划没有已结束交易日')
            stocks = await attach_listing_dates(self, stocks)
            plans = []
            checksum = hashlib.sha256(json.dumps([d.isoformat() for d in days]).encode())
            for stock in stocks:
                excluded = await self.query.suspended_days(stock['market'], stock['code'], days[0], days[-1])
                count = len(required_days(stock, days, excluded))
                plans.append((excluded, count))
                checksum.update(digest([stock['market'], stock['code'], lifecycle(stock),
                                       sorted(d.isoformat() for d in excluded)]).encode())
            scope = checksum.hexdigest()
            if fresh or cursor.get('scope') != scope or cursor.get('phase') == 'complete':
                cursor = {}
            if not cursor:
                cursor = dict(phase='collecting', scope=scope, batch_id=uuid4().hex,
                              index=0, pages=0, collected=0, started_at=datetime.now(UTC).isoformat(),
                              start_date=days[0].isoformat(), end_date=days[-1].isoformat())
            total = sum(count for _, count in plans)
            first_gap, failed = None, 0
            cursor = {**cursor, 'first_gap': None, 'failed_units': 0}
            self.stats.update(status='collecting', total_units=total, completed_units=cursor['index'],
                              failed_units=0, error='')
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
                for di, day in enumerate(planned):
                    index = offset + di
                    if index < cursor['index']:
                        continue
                    self.stats.update(current_security=stock['market'] + ':' + stock['code'] + ' / ' + day.isoformat(),
                                      current_date=day.isoformat(), completed_units=index - failed)
                    # Missing/malformed SQL days always recollect. The newest five
                    # trading days are also refreshed for revisions each round.
                    if not fresh and day in covered and di < len(planned) - 5:
                        cursor = {**cursor, 'index': first_gap['index'] if first_gap else index + 1}
                        continue
                    stage = 'source_validation'
                    observed = datetime.now(UTC)
                    try:
                        row = {**await fetch_day(self, stock['code'], day, stock['market'], stock['listing_date']),
                               'market': stock['market'], 'lifecycle': life}
                    except SourceError as exc:
                        # A source error is not proof of an empty trading day.
                        # Keep only the first unresolved position in the cursor;
                        # bounded error records and actual SQL holes describe gaps.
                        failed += 1
                        first_gap = first_gap or dict(index=index, market=stock['market'], code=stock['code'],
                                                     trade_date=day.isoformat(), error=str(exc)[:256])
                        cursor = {**cursor, 'index': first_gap['index'], 'first_gap': first_gap,
                                  'failed_units': failed}
                        state = await self.ingest.advance_checkpoint(job_key=self.job_key,
                            expected_revision=state['revision'], cursor=cursor)
                        self.stats.update(failed_units=failed, first_gap=first_gap, error=str(exc))
                        continue
                    page = cursor['pages'] + 1
                    envelope = make_envelope(source=self.source, dataset='intraday.day', business_key=identity(row),
                        job_key=self.job_key, run_id=cursor['batch_id'], batch_id=cursor['batch_id'],
                        payload=dict(page=page, rows=[row]))
                    envelope = envelope.model_copy(update={'source_url': URL, 'available_at': None, 'observed_at': observed})
                    next_cursor = {**cursor, 'index': first_gap['index'] if first_gap else index + 1, 'pages': page,
                                   'collected': cursor['collected'] + len(row['trend']) + len(row['auction'])}
                    stage = 'queue_publish'
                    state = await publish_with_capacity(self.ingest, self.stats, [envelope], job_key=self.job_key,
                        expected_revision=state['revision'], cursor=next_cursor)
                    cursor = state['cursor']
                    self.stats.update(collected=cursor['collected'], pages=page, completed_units=index + 1 - failed)
                    # No page waits for SQL; only the end of the download round does.
                offset += len(planned)
            if not cursor['pages']:
                # A validated SQL-only recovery plan can finish without inventing
                # an archive progress message or entering the business queue.
                if first_gap:
                    raise SourceError('本轮仍有来源缺口：' + first_gap['code'] + ' / ' + first_gap['trade_date'])
                cursor = {**cursor, 'phase': 'complete', 'index': total}
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
        cursor = {**cursor, 'phase': 'complete'}
        await self.ingest.advance_checkpoint(job_key=self.job_key,
            expected_revision=state['revision'], cursor=cursor)
        self.stats.update(status='complete', error='')
        return cursor

    async def stop(self):
        self.stats['status'] = 'stopped'

    def health(self):
        return dict(self.stats)
