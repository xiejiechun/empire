"""Native index planning and coverage audits on the shared formal read service."""
import json
from datetime import datetime

from sqlalchemy import bindparam, text

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.contracts.preparation_scope import PreparationScope
from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.yuanhang_etf import price_dataset
from empire.features.yuanhang_etf.contract import PRICE_DATASET, PRICE_PROJECT
from empire.features.yuanhang_etf.price_audit import price_checks
from empire.features.yuanhang_etf.price_reads import PriceReads
from empire.features.yuanhang_etf.query import INTEGRATION, TESTS, CatalogQuery
from empire.plugins.infra.collection_state_unit import unit_path
from empire.sources.yuanhang_ranges import contiguous_through, versions_on


class PriceQuery(CatalogQuery, PriceReads):
    manifest = PluginManifest('data.yuanhang_etf_prices', '远航ETF日K查询',
        requires=('mysql.store', 'yuanhang.etfs.query'), provides=('yuanhang.etf.prices.query',))
    preparation = (PreparationContribution('etf_prices', 'yuanhang.etf.prices.query', '同花顺远航版', PRICE_PROJECT,
        PRICE_PROJECT + '-v1', PRICE_DATASET, 'collector.yuanhang_etf_prices', TESTS, INTEGRATION, scoped=True),)
    browse = PriceReads.browse

    async def start(self, context):
        self.context = context
        self.mysql, self.directory = context.get('mysql.store'), context.get('yuanhang.etfs.query')
        await self.mysql.require_schema(price_dataset.TABLES, price_dataset.KEYS)
        return {'yuanhang.etf.prices.query': self}

    async def catalog(self, codes=None):
        return await self.directory.catalog(codes)

    async def scope(self):
        def read(conn):
            through, message = read_trade_day_cutoff(conn, datetime.now(CHINA))
            if through is None:
                raise ValueError(message or 'ETF日K需要可信交易日历')
            through = through.date().isoformat()
            dates = [r[0].isoformat() for r in conn.execute(text('SELECT trade_date FROM trade_calendar '
                'WHERE is_trade=TRUE AND trade_date<=:through ORDER BY trade_date DESC LIMIT 10'), dict(through=through))]
            if not dates or dates[0] != through:
                raise ValueError('ETF日K近期交易日历缺失')
            return through, sorted(dates)
        return await self.read(read)

    async def plans(self, codes, through, trades, scope='recent', force=False):
        if not 1 <= len(codes) <= 64:
            raise ValueError('ETF规划每组最多64个')
        def read(conn):
            projections, params = [], dict(ns=self.namespace, project=PRICE_PROJECT)
            for i, code in enumerate(codes):
                params[f'p{i}'] = unit_path(code)
                projections.append(f'JSON_EXTRACT(payload,:p{i}) AS u{i}')
            raw = conn.execute(text('SELECT ' + ','.join(projections) + ' FROM collection_state '
                'WHERE namespace=:ns AND project_id=:project'), params).mappings().first()
            statement = text('SELECT unified_code,quote_year,last_date,contract_version,native_market,verified_through FROM yuanhang_etf_price_year '
                'WHERE unified_code IN :codes ORDER BY unified_code,quote_year LIMIT :n').bindparams(bindparam('codes', expanding=True))
            heads = {c: [] for c in codes}
            for row in conn.execute(statement, dict(codes=codes, n=len(codes)*151)).mappings():
                heads[row['unified_code']].append(row)
            result = {}
            for i, code in enumerate(codes):
                unit = raw[f'u{i}'] if raw else None
                unit = json.loads(unit) if isinstance(unit, str) else unit or {}
                head = heads[code]
                if len(head) > 150 or any(h['contract_version'] != 1 for h in head):
                    raise ValueError('ETF年度证明版本或数量无效')
                ranges = unit.get('price_ranges', {})
                by_year = {h['quote_year']: h for h in head}
                def trusted(year):
                    h = by_year.get(year)
                    return bool(h and h['native_market'] == unit.get('native_market')
                        and (h['verified_through'].isoformat() if h['verified_through'] else None)
                        == contiguous_through(ranges.get(str(year), []), year))
                start, full = None, False
                if force:
                    start, full = '1900-01-01', True
                elif scope == 'backfill':
                    if not unit.get('history_start'):
                        start, full = '1900-01-01', True
                    else:
                        years = range(int(unit['history_start'][:4]), int(through[:4]) + 1)
                        missing = [y for y in years if not trusted(y) or str(y) not in unit.get('full_years', {})
                            or (contiguous_through(ranges.get(str(y), []), y) or '') < min(f'{y}-12-31', through)]
                        if missing:
                            start, full = f'{min(missing)}-01-01', True
                else:
                    versions = {}
                    for y in {int(d[:4]) for d in trades}:
                        versions.update(versions_on(ranges.get(str(y), []), y, [d for d in trades if int(d[:4]) == y]))
                    complete = all(trusted(int(d[:4])) and d in versions
                        and datetime.fromisoformat(versions[d]).astimezone(CHINA).date().isoformat() >= through for d in trades)
                    if not complete:
                        start = trades[0]
                        known = max((h['last_date'].isoformat() for h in head if h['last_date']), default=None)
                        if known:
                            start = min(start, known)
                        year = int(start[:4])
                        if contiguous_through(ranges.get(str(year), []), year) is None:
                            start = f'{year}-01-01'
                result[code] = dict(start=start, through=through, full=full, history_start=unit.get('history_start'))
            return result
        return await self.read(read)

    async def preparation_check(self, request=None):
        return await price_checks(self, PreparationScope.parse(request))
