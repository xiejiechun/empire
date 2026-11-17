"""Recent-first native index daily ranges and bounded historical initialization."""
import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.features.yuanhang_indices.collector_support import Publisher
from empire.features.yuanhang_indices.contract import PRICE_DATASET
from empire.features.yuanhang_indices.native import fetch_daily
from empire.plugins.collection.unit_prefetch import prefetch_units


class PriceCollector(Publisher):
    capability, query_capability = 'collector.yuanhang_index_prices', 'index.prices.query'
    manifest = PluginManifest('collector.yuanhang_index_prices', '同花顺远航版 指数日K',
        requires=('http.fetch', 'ingest.publish', 'index.prices.query', 'yuanhang.identity', 'archive.confirmation', 'collection.records'),
        provides=('collector.yuanhang_index_prices',))

    def __init__(self):
        super().__init__(PRICE_DATASET)
        self.plans = {}

    async def fetch(self, item, *, reservation):
        code, market = item
        plan = self.plans[code]
        async def fetch(session, **kwargs):
            return await fetch_daily(self.http, session, code, market, date.fromisoformat(plan['start']),
                date.fromisoformat(plan['through']), project_id=self.project_id, **kwargs)
        observed = datetime.now(UTC)
        return await self.authenticated(fetch, reservation=reservation), observed

    async def _round(self, scope, *, force=False):
        state = await self.ingest.checkpoint(self.job_key)
        cursor = state['cursor']
        through, trades = await self.query.scope()
        if cursor.get('phase') not in ('collecting', 'awaiting_archive'):
            catalog = await self.query.catalog(self.selected_codes)
            self.plans = {}
            for first in range(0, len(catalog), 64):
                self.plans.update(await self.query.plans([r['code'] for r in catalog[first:first+64]],
                    through, trades, scope=scope, force=force))
            work = [[r['code'], r['native_market']] for r in catalog if self.plans[r['code']]['start']]
            if scope == 'backfill' and not force:
                work = work[:64]
            cursor = dict(phase='collecting', batch_id=uuid4().hex, observed_at=datetime.now(UTC).isoformat(),
                through=through, trades=trades, scope=scope, force=force, work=work, next_index=0,
                next_year=1900, pages=0, collected=0)
            state = await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
        if cursor['phase'] == 'collecting':
            work, self.plans = cursor['work'], {}
            remaining = [c for c, _ in work[cursor['next_index']:]]
            for first in range(0, len(remaining), 64):
                self.plans.update(await self.query.plans(remaining[first:first+64], cursor['through'],
                    cursor['trades'], scope=cursor['scope'], force=cursor['force']))
            current = cursor.get('current_plan')
            if current:
                code = work[cursor['next_index']][0]
                self.plans[code] = current
                if cursor['next_year'] <= int(cursor['through'][:4]):
                    self.plans[code] = {**current, 'start': max(current['start'], f"{cursor['next_year']}-01-01")}
                else:
                    cursor = {**cursor, 'next_index': cursor['next_index'] + 1, 'next_year': 1900}
                    cursor.pop('current_plan', None)
            active = [i for i in range(cursor['next_index'], len(work)) if self.plans.get(work[i][0], {}).get('start')]
            units = [work[i] for i in active]
            self.stats.update(status='collecting', total_units=len(work), completed_units=cursor['next_index'],
                planned_requests=len(units), maintenance_scope=cursor['scope'])
            async with prefetch_units(self, units, self.fetch, url='https://10jqka.com.cn/',
                    domains=('10jqka.com.cn',), item_name='个指数') as reads:
                async for n, read in reads:
                    rows, observed = await read.resolve()
                    if not rows:
                        raise ValueError('指数日K空响应缺少身份/完整覆盖证明，不记为完成')
                    i = active[n]
                    code, market = work[i]
                    plan = self.plans[code]
                    first_year = int(plan['start'][:4])
                    if plan['full'] and not plan.get('history_start'):
                        first_year = max(first_year, int(rows[0][0][:4]))
                    history_start = min(plan.get('history_start') or rows[0][0], rows[0][0]) if plan['full'] else None
                    grouped = {}
                    for row in rows:
                        grouped.setdefault(int(row[0][:4]), []).append(row)
                    self.stats['current_security'] = code
                    for year in range(first_year, int(cursor['through'][:4])+1):
                        first = max(f'{year}-01-01', plan['start'])
                        last = min(f'{year}-12-31', cursor['through'])
                        next_cursor = {**cursor, 'next_index': i, 'next_year': year+1,
                            'current_plan': {**plan, 'history_start': history_start}}
                        state, cursor = await self.publish(state, next_cursor, code + ':' + str(year),
                            dict(code=code, native_market=market, start=first, through=last, rows=grouped.get(year, []),
                                 full=plan['full'], history_start=history_start), observed=observed,
                            source_url=f'yuanhang://210/{market}/{code}')
                    cursor = {**cursor, 'next_index': i+1, 'next_year': 1900}
                    cursor.pop('current_plan', None)
                    state = await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state['revision'], cursor=cursor)
                    self.stats['completed_units'] = i+1
        return await self.finish(state, cursor)

    @measured_run
    async def execute(self, *, fresh=False, baseline_revision=0):
        try:
            state = await self.ingest.checkpoint(self.job_key)
            if state['revision'] > baseline_revision and state['cursor'].get('phase') == 'complete' and not fresh:
                return self.result(state['cursor'])
            first = await self._round('backfill' if fresh else 'recent', force=fresh)
            if not fresh:
                if first['scope'] == 'backfill':
                    first = await self._round('recent')
                second = await self._round('backfill')
                return dict(recent=self.result(first), historical=self.result(second), status='complete')
            return self.result(first)
        except asyncio.CancelledError:
            self.stats['status'] = 'paused'
            raise
        except Exception as exc:
            await self.report_failure(exc, 'index_daily')
            raise

    @staticmethod
    def result(cursor):
        return {k: v for k, v in cursor.items() if k not in ('work', 'trades', 'current_plan')}
