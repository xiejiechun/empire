"""SQL is confined to the daily task and explicit daily browsing."""
from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.features.fx.contract import (
    FIELDS,
    KEYS,
    SYMBOLS,
    TABLES,
    day,
    identity,
    price_quality,
    symbol,
)
from empire.features.fx.dataset import sql_rows
from empire.plugins.infra.query_order import column_fields, ordered_page


class FxDailyQuery:
    manifest = PluginManifest('data.fx_daily', '汇率日线查询', requires=('mysql.store',),
        provides=('fx.daily.query',))

    async def start(self, context):
        self.mysql = context.get('mysql.store')
        await self.mysql.require_schema(TABLES, KEYS)
        return {'fx.daily.query': self}

    async def inventory(self, cutoff):
        day(cutoff)
        def read():
            with self.mysql.read_engine.connect() as conn:
                heads = conn.execute(text('SELECT * FROM fx_price_year ORDER BY unified_code,quote_year LIMIT 1801')).mappings().all()
                if len(heads) > 1800:
                    raise ValueError('汇率年份覆盖超过范围')
                result = {code: {} for code in SYMBOLS}
                for row in heads:
                    code = row['unified_code'].removesuffix('.FX')
                    symbol(code)
                    result[code][str(row['quote_year'])] = dict(row, last_date=row['last_date'].isoformat(), dates=[])
                dates = conn.execute(text('SELECT p.unified_code,p.trade_date FROM fx_daily_price p '
                    'JOIN (SELECT unified_code,MAX(last_date) AS latest FROM fx_price_year GROUP BY unified_code) h '
                    'ON h.unified_code=p.unified_code WHERE p.trade_date>=DATE_SUB(h.latest,INTERVAL 29 DAY) '
                    'ORDER BY p.unified_code,p.trade_date LIMIT 5001')).all()
                if len(dates) > 5000:
                    raise ValueError('汇率近期日期核验超限')
                for code, stamp in dates:
                    head = result[symbol(code.removesuffix('.FX'))].get(str(stamp.year))
                    if head:
                        head['dates'].append(stamp.isoformat())
                return result
        return await self.mysql.read(read)

    async def browse(self, code='', start='', end='', after=None, limit=50, order=None):
        if code:
            code = code.upper().removesuffix('.FX')
            symbol(code)
        for stamp in (start, end):
            if stamp:
                day(stamp)
        if start and end and start > end or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('汇率日线查询范围无效')
        params, conditions = {}, []
        for key, value, clause in [('code', identity(code) if code else '', 'unified_code=:code'),
                ('start', start, 'trade_date>=:start'), ('end', end, 'trade_date<=:end')]:
            if value:
                params[key] = value
                conditions.append(clause)
        labels = {}
        for field, index in [('name', 0), ('unit', 2)]:
            labels[field] = 'CASE unified_code ' + ' '.join(
                f"WHEN '{identity(s)}' THEN '{v[index]}'" for s, v in SYMBOLS.items()) + ' END AS ' + field
        relation = ('SELECT *, ' + ','.join(labels.values())
            + ', (low<=LEAST(open,close) AND high>=GREATEST(open,close) AND low<=high) AS price_relation_valid '
            + 'FROM fx_daily_price' + (' WHERE ' + ' AND '.join(conditions) if conditions else ''))
        def read():
            with self.mysql.read_engine.connect() as conn:
                rows, cursor = ordered_page(conn, relation, params,
                    order=order or dict(field='trade_date', direction='desc'),
                    fields=column_fields(TABLES['fx_daily_price'] | {'name', 'unit', 'price_relation_valid'}),
                    identity=('unified_code', 'trade_date'), after=after, limit=limit)
                for row in rows:
                    name = row['unified_code'].removesuffix('.FX')
                    row.update(name=SYMBOLS[name][0], unit=SYMBOLS[name][2],
                        price_relation_valid=price_quality([row[k] for k in FIELDS]))
                return dict(rows=rows, next=cursor)
        return await self.mysql.read(read)

    async def history(self, code, year):
        """One complete bounded source year for analysis and content audits."""
        symbol(code)
        if type(year) is not int or not 1900 <= year <= 2100:
            raise ValueError('汇率历史年份无效')
        def read():
            with self.mysql.read_engine.connect() as conn:
                return sql_rows(conn, code, year)
        return await self.mysql.read(read)

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
