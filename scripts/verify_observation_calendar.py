"""Read-only live verification; never start Runtime, collectors or archive workers."""
import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from empire.core.config import load_config
from empire.desktop_bridge.preview import wire
from empire.features.calendar.query import CalendarDataPlugin
from empire.features.fx.query import FxDailyQuery
from empire.features.market_margin.query import MarketMarginDataPlugin
from empire.features.observation_calendar.query import ObservationQuery
from empire.features.yuanhang_indices.price_query import PriceQuery
from empire.features.yuanhang_indices.query import CatalogQuery
from empire.plugins.infra.mysql_store import MySQLPlugin


async def verify(config, month):
    mysql = MySQLPlugin(load_config(config)['mysql'])
    calendar, prices, margins = CalendarDataPlugin(), PriceQuery(), MarketMarginDataPlugin()
    directory = CatalogQuery(load_config(config)['redis']['namespace'])
    fx = FxDailyQuery()
    services = {'mysql.store': mysql, 'calendar.query': calendar,
                'yuanhang.indices.query': directory, 'index.prices.query': prices, 'market_margin.query': margins, 'fx.daily.query': fx}
    context = SimpleNamespace(get=services.__getitem__, optional=services.get)
    query = ObservationQuery()
    try:
        await mysql.start(context)
        for plugin in (calendar, directory, prices, margins, fx, query):
            await plugin.start(context)
        catalog = await query.catalog()
        if not catalog['indices']:
            raise ValueError('真实指数目录为空')
        index = next((r['code'] for r in catalog['indices'] if r['name'] == '上证指数'), catalog['indices'][0]['code'])
        fx_keys = [m['key'] for m in catalog['metrics'] if m['scope'] == 'fx']
        result = await query.month(month, index, '99', settings={'top_amount_share': {'window': 30, 'top': 5}, 'financing_repayment_ratio': {'market': '3', 'mode': 'value'}}, include_top=True, include_fx=fx_keys, include_turnover=True)
        assert 28 <= len(result['rows']) <= 42
        assert len({r['date'] for r in result['rows']}) == len(result['rows'])
        formal = await prices.browse(code=index, start=result['rows'][0]['date'],
                                     end=result['rows'][-1]['date'], limit=200)
        expected = {str(row['trade_date']): row for row in formal['rows']}
        for row in result['rows']:
            if row['status'] == 'trade' and not row['future']:
                assert row['values']['close'] == expected.get(row['date'], {}).get('close')
        def turnover():
            with mysql.read_engine.connect() as conn:
                rows = conn.execute(text('SELECT trade_date,SUM(amount_yuan) AS amount,'
                    'COUNT(*)-COUNT(amount_yuan) AS missing FROM yuanhang_daily_price '
                    'WHERE trade_date BETWEEN :start AND :end GROUP BY trade_date ORDER BY trade_date'),
                    dict(start=result['rows'][0]['date'], end=result['rows'][-1]['date'])).mappings()
                return {str(r['trade_date']): r['amount'] if not r['missing'] else None for r in rows}
        expected_turnover = await mysql.read(turnover)
        for row in result['rows']:
            assert row['values']['market_amount'] == (expected_turnover.get(row['date'])
                if row['status'] == 'trade' and not row['future'] else None)
        for key in fx_keys:
            formal_fx = await fx.browse(code=key[3:], start=result['rows'][0]['date'],
                                       end=result['rows'][-1]['date'], limit=500)
            assert formal_fx['next'] is None
            expected_fx = {str(r['trade_date']): r['close'] if r['price_relation_valid'] else None for r in formal_fx['rows']}
            for row in result['rows']:
                assert row['values'][key] == (None if row['future'] else expected_fx.get(row['date']))
        available = {m['key']: sum(r['in_month'] and r['values'][m['key']] is not None
                                   for r in result['rows']) for m in catalog['metrics']}
        return dict(month=month, index=index, market='99', indices=len(catalog['indices']),
                    cells=len(result['rows']), available_days=available,
                    unknown_calendar_days=sum(r['status'] == 'unknown' for r in result['rows']),
                    read_only=True, runtime_started=False, formal_price_values_equal=True,
                    formal_fx_values_equal=True,
                    archived_market_turnover_equal=True, full_market_coverage_proven=False,
                    queried_at=result['queried_at'], warnings=result.get('warnings', []),
                    derived_sample=[r for r in result['rows'] if r['in_month'] and not r['future']][-5:])
    finally:
        for plugin in (query, fx, margins, prices, directory, calendar, mysql):
            await plugin.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='dist/EmpireDesktop/config.toml')
    parser.add_argument('--month', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = asyncio.run(verify(args.config, args.month))
    Path(args.output).write_text(json.dumps(wire(result), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(wire(result), ensure_ascii=False))
