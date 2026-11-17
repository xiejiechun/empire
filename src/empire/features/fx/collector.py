"""Daily source candles; atomic enqueue, then whole-round archive confirmation."""
from functools import partial
from uuid import uuid4

from empire.contracts.collector import CollectionSourceGap
from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.features.fx.contract import BASE, DAILY_JOB, DAILY_PROJECT, DATASET, digest, url
from empire.features.fx.live import FxLiveCollector
from empire.features.fx.planning import full_years, tail
from empire.features.fx.source import DailyQuoteUnavailable
from empire.features.fx.verification import FxSourceConflict, verified_snapshot
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.collectors.support import publish_with_capacity, wait_for_archive


class FxDailyCollector(FxLiveCollector):
    manifest = PluginManifest('collector.ths_fx_daily', '同花顺汇率日线',
        requires=('http.fetch', 'ingest.publish', 'fx.daily.query', 'archive.confirmation', 'collection.records'),
        provides=('collector.ths_fx_daily',))

    def __init__(self):
        super().__init__()
        self.project_id, self.job_key = DAILY_PROJECT, DAILY_JOB

    async def start(self, context):
        self.http, self.ingest = context.get('http.fetch'), context.get('ingest.publish')
        self.query, self.confirmation = context.get('fx.daily.query'), context.get('archive.confirmation')
        self.records = context.get('collection.records')
        self.stats['status'] = 'idle'
        return {'collector.ths_fx_daily': self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))['revision']

    async def publish(self, state, cursor, code, payload, observed):
        page = cursor['pages'] + 1
        next_cursor = dict(cursor, pages=page, collected=cursor['collected'] + len(payload['rows']))
        envelope = make_envelope(source='ths', dataset=DATASET, business_key=f"{code}:{payload['year']}",
            job_key=self.job_key, batch_id=cursor['batch_id'], run_id=cursor['batch_id'],
            payload=dict(page=page, code=code, **payload)).model_copy(update=dict(
                observed_at=observed, source_url=url(code, payload['year']), available_at=None))
        result = await publish_with_capacity(self.ingest, self.stats, [envelope],
            job_key=self.job_key, expected_revision=state['revision'], cursor=next_cursor)
        return result, next_cursor

    @measured_run
    async def execute(self, *, fresh=False, baseline_revision=0):
        state = await self.ingest.checkpoint(self.job_key)
        cursor = state['cursor']
        if state['revision'] > baseline_revision and cursor.get('phase') == 'complete' and not fresh:
            return cursor
        if cursor.get('phase') not in ('collecting', 'awaiting_archive'):
            cursor = dict(phase='collecting', codes=self.codes(), next_index=0, next_year=1900,
                snapshot_hash='', pages=0, collected=0, batch_id=uuid4().hex, fresh=bool(fresh))
        self.stats.update(status=cursor['phase'], collected=cursor['collected'], total_units=len(cursor['codes']),
            completed_units=cursor['next_index'], unavailable_codes=[], empty_daily_codes=[],
            source_gap_units=0, notice='')
        try:
            if cursor['phase'] == 'collecting':
                from datetime import UTC, datetime

                from empire.features.fx.source import closed_through
                heads = await self.query.inventory(closed_through(datetime.now(UTC)))
                deferred = None
                for i in range(cursor['next_index'], len(cursor['codes'])):
                    code = cursor['codes'][i]
                    try:
                        snapshot, observed, verified = await verified_snapshot(self, code)
                    except (FxSourceConflict, DailyQuoteUnavailable) as exc:
                        self.stats['unavailable_codes'].append(code)
                        if isinstance(exc, DailyQuoteUnavailable):
                            self.stats['empty_daily_codes'].append(code)
                        self.stats['source_gap_units'] += 1
                        if deferred is None:
                            deferred = {k: cursor[k] for k in ('next_index', 'next_year', 'snapshot_hash')}
                        continue
                    # A new source snapshot invalidates only this symbol's
                    # resume position, while preserving all already queued pages.
                    checksum = digest({k: snapshot[k] for k in ('start', 'end', 'years', 'rows')})
                    next_year = cursor['next_year'] if deferred is None and checksum == cursor['snapshot_hash'] else 1900
                    if deferred is None and checksum != cursor['snapshot_hash']:
                        cursor = dict(cursor, next_year=1900, snapshot_hash=checksum)
                    years = [y for y in full_years(snapshot, heads[code], fresh=cursor['fresh'])
                             if y >= next_year]
                    async def download(year, *, reservation):
                        if year in verified:
                            return verified[year]
                        return await self.fetch(code, year, snapshot, reservation=reservation)
                    async with prefetch_units(self, years, download, url=BASE,
                            domains=('10jqka.com.cn',), item_name='汇率年份') as reads:
                        async for j, read in reads:
                            year = years[j]
                            rows = await read.resolve()
                            payload = dict(year=year, mode='full', source_count=snapshot['years'][str(year)],
                                start=snapshot['start'], end=snapshot['end'], rows=rows)
                            position = dict(cursor, next_year=year + 1) if deferred is None else cursor
                            state, cursor = await self.publish(state, position, code, payload, observed)
                            self.stats.update(collected=cursor['collected'], pages=cursor['pages'], current_date=str(year))
                    recent = tail(snapshot)
                    for year in sorted({r[0][:4] for r in recent}):
                        if heads[code].get(year, {}).get('last_date', '') > snapshot['end']:
                            continue
                        if int(year) in years or int(year) < next_year:
                            continue
                        rows = [r for r in recent if r[0][:4] == year]
                        state, cursor = await self.publish(state, cursor, code, dict(year=int(year), mode='recent',
                            source_count=snapshot['years'][year], start=snapshot['start'], end=snapshot['end'], rows=rows), observed)
                    cursor = dict(cursor, next_index=i + 1, next_year=1900, snapshot_hash='')
                    if deferred is not None:
                        cursor.update(deferred)
                    elif i + 1 == len(cursor['codes']):
                        cursor['phase'] = 'awaiting_archive'
                    state = await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
                    self.stats.update(completed_units=self.stats['completed_units'] + 1,
                                      collected=cursor['collected'], pages=cursor['pages'])
                if self.stats['unavailable_codes']:
                    # The first unresolved symbol remains the durable resume
                    # position even while later valid symbols are archived.
                    self.stats['status'] = 'awaiting_archive'
                    if cursor['pages']:
                        await wait_for_archive(partial(self.confirmation.page_status, 'ths', self.job_key,
                            self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
                    self.stats['notice'] = ('来源日线核验缺口：' + '、'.join(self.stats['unavailable_codes'])
                        + f"；已核验{self.stats['completed_units']}/{len(cursor['codes'])}个品种，"
                        + '有效入队数据已归档；保留缺口原数据和断点，下次继续核验')
                    if self.stats['empty_daily_codes']:
                        self.stats['notice'] += '；当日日线暂无报价：' + '、'.join(self.stats['empty_daily_codes'])
                    raise CollectionSourceGap(self.stats['notice'])
            self.stats['status'] = 'awaiting_archive'
            await wait_for_archive(partial(self.confirmation.page_status, 'ths', self.job_key,
                self.project_id, cursor['batch_id'], cursor['pages']), retry_seconds=1)
            cursor = dict(cursor, phase='complete')
            await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
            self.stats.update(status='complete', error='')
            return {k: v for k, v in cursor.items() if k != 'codes'}
        except CollectionSourceGap:
            self.stats['status'] = 'source_gap'
            raise
        except BaseException:
            self.stats['status'] = 'paused'
            raise
