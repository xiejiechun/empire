"""Bounded formal queries for native PC prices, actions and capital."""
import re
from datetime import datetime

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.yuanhang.contract import KEYS, TABLE_COLUMNS
from empire.features.yuanhang.repository import read_heads, read_rows
from empire.plugins.infra.query_order import column_fields, ordered_page
from empire.sources.yuanhang_coverage import audit_financial, audit_year
from empire.sources.yuanhang_history import price_quality, security_identity
from empire.sources.yuanhang_payload import CAPITAL_KINDS, action_key, day, digest


def _limit(limit):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('远航版查询每页须为1至500条')


class YuanhangDataPlugin:
    manifest = PluginManifest('data.yuanhang', '远航历史行情查询', requires=('mysql.store',),
        provides=('yuanhang.history.query',), description='不复权日线、权息及股本的有界正式查询')

    def __init__(self, namespace=None):
        self.namespace = namespace

    async def start(self, context):
        self.mysql = context.get('mysql.store')
        await self.mysql.require_schema({k: set(v) for k, v in TABLE_COLUMNS.items()}, KEYS)
        return {'yuanhang.history.query': self}

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if getattr(self, 'mysql', None) else 'stopped'}

    async def _read(self, operation):
        def read():
            with self.mysql.read_engine.connect() as conn:
                return operation(conn)
        return await self.mysql.read(read)

    async def prices(self, code, start='1900-01-01', end='2100-12-31', after=None, limit=500, order=None):
        security_identity(code)
        _limit(limit)
        if day(start) > day(end) or (order is None and after is not None and not start <= day(after).isoformat() <= end):
            raise ValueError('远航版日线查询日期范围无效')
        def read(conn):
            if order is not None:
                names = ('trade_date', 'open', 'high', 'low', 'close', 'volume_shares', 'amount_yuan')
                sort_fields = column_fields(names)
                sort_fields['quality_flags'] = 'NOT (q.low<=LEAST(q.open,q.close) AND GREATEST(q.open,q.close)<=q.high)'
                rows, cursor = ordered_page(
                    conn, 'SELECT trade_date,open,high,low,close,volume_shares,amount_yuan FROM yuanhang_daily_price WHERE unified_code=:code '
                    'AND trade_date BETWEEN :first AND :last', dict(code=code, first=start, last=end),
                    order=order, fields=sort_fields, identity=('trade_date',), after=after, limit=limit,
                )
                from empire.features.yuanhang.plan_query import coverage_summary
                for row in rows:
                    row['quality_flags'] = price_quality(*(row[k] for k in ('open', 'high', 'low', 'close')))
                return dict(rows=rows, next=cursor,
                            coverage=coverage_summary(conn, self.namespace, code) if self.namespace else {})
            rows = [dict(r) for r in conn.execute(text('SELECT trade_date,open,high,low,close,'
                'volume_shares,amount_yuan FROM yuanhang_daily_price WHERE unified_code=:code '
                'AND trade_date BETWEEN :first AND :last AND (:after IS NULL OR trade_date>:after) '
                'ORDER BY trade_date LIMIT :n'),
                dict(code=code, first=start, last=end, after=after, n=limit+1)).mappings()]
            for row in rows:
                row['quality_flags'] = price_quality(*(row[k] for k in ('open', 'high', 'low', 'close')))
            from empire.features.yuanhang.plan_query import coverage_summary
            return dict(rows=rows[:limit], next=rows[limit-1]['trade_date'].isoformat() if len(rows) > limit else None,
                        coverage=coverage_summary(conn, self.namespace, code) if self.namespace else {})
        return await self._read(read)

    async def price_day(self, trade_date, *, after='', limit=500):
        day(trade_date)
        _limit(limit)
        if after:
            security_identity(after)
        def read(conn):
            rows = [dict(r) for r in conn.execute(text('SELECT unified_code,trade_date,open,high,low,close,'
                'volume_shares,amount_yuan FROM yuanhang_daily_price WHERE trade_date=:day '
                'AND unified_code>:after ORDER BY unified_code LIMIT :n'),
                dict(day=trade_date, after=after, n=limit+1)).mappings()]
            for row in rows:
                row['quality_flags'] = price_quality(*(row[k] for k in ('open', 'high', 'low', 'close')))
            return dict(rows=rows[:limit], next=rows[limit-1]['unified_code'] if len(rows) > limit else None)
        return await self._read(read)

    async def price_quality(self, code):
        security_identity(code)
        def read(conn):
            condition = 'NOT(low<=LEAST(open,close) AND high>=GREATEST(open,close))'
            counts = conn.execute(text('SELECT COALESCE(SUM(' + condition + '),0) AS ohlc_anomalies,'
                'COALESCE(SUM(volume_shares IS NULL),0) AS missing_volume,'
                'COALESCE(SUM(amount_yuan IS NULL),0) AS missing_amount FROM yuanhang_daily_price '
                'WHERE unified_code=:code'), dict(code=code)).mappings().one()
            dates = conn.execute(text('SELECT trade_date FROM yuanhang_daily_price '
                'WHERE unified_code=:code AND ' + condition + ' ORDER BY trade_date LIMIT 10'), dict(code=code)).scalars()
            return {**{k: int(v) for k, v in counts.items()}, 'anomaly_dates': [d.isoformat() for d in dates]}
        return await self._read(read)

    async def actions(self, code, start='1900-01-01', end='2100-12-31', after=None, limit=500, order=None):
        security_identity(code)
        _limit(limit)
        after_date, after_key = None, ''
        if after is not None and order is None:
            if not isinstance(after, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}:[0-9a-f]{64}', after):
                raise ValueError('远航版权息游标必须含日期及事件身份')
            after_date, after_key = after.split(':', 1)
            day(after_date)
        if day(start) > day(end) or (after_date is not None and not start <= after_date <= end):
            raise ValueError('远航版权息查询日期范围无效')
        def read(conn):
            if order is not None:
                names = ('ex_date', 'event_key', 'bonus_ratio', 'transfer_ratio', 'rights_ratio', 'rights_price', 'cash_per_share')
                sort_fields = column_fields(names)
                rows, cursor = ordered_page(
                    conn, 'SELECT ex_date,event_key,bonus_ratio,transfer_ratio,rights_ratio,rights_price,cash_per_share FROM yuanhang_corporate_action WHERE unified_code=:code '
                    'AND ex_date BETWEEN :first AND :last', dict(code=code, first=start, last=end),
                    order=order, fields=sort_fields, identity=('ex_date', 'event_key'), after=after, limit=limit,
                )
                return dict(rows=rows, next=cursor)
            rows = [dict(r) for r in conn.execute(text('SELECT ex_date,event_key,bonus_ratio,transfer_ratio,rights_ratio,'
                'rights_price,cash_per_share FROM yuanhang_corporate_action WHERE unified_code=:code '
                'AND ex_date BETWEEN :first AND :last AND (:after_date IS NULL OR ex_date>:after_date '
                'OR (ex_date=:after_date AND event_key>:after_key)) ORDER BY ex_date,event_key LIMIT :n'),
                dict(code=code, first=start, last=end, after_date=after_date, after_key=after_key, n=limit+1)).mappings()]
            return dict(rows=rows[:limit], next=(rows[limit-1]['ex_date'].isoformat() + ':'
                + rows[limit-1]['event_key']) if len(rows) > limit else None)
        return await self._read(read)

    async def financial_quality(self, code):
        security_identity(code)
        def read(conn):
            missing = conn.execute(text('SELECT COUNT(*) FROM yuanhang_capital '
                'WHERE unified_code=:code AND shares IS NULL'), dict(code=code)).scalar_one()
            repeats = conn.execute(text('SELECT ex_date FROM yuanhang_corporate_action '
                'WHERE unified_code=:code GROUP BY ex_date HAVING COUNT(*)>1 ORDER BY ex_date LIMIT 10'),
                dict(code=code)).scalars()
            return dict(missing_circulating=int(missing), ambiguous_action_dates=[d.isoformat() for d in repeats])
        return await self._read(read)

    async def capital_as_of(self, code, kind, as_of):
        security_identity(code)
        day(as_of)
        if kind not in CAPITAL_KINDS:
            raise ValueError('远航版股本口径无效')
        return await self._read(lambda conn: (lambda r: dict(r) if r else None)(conn.execute(text(
            'SELECT effective_date,shares FROM yuanhang_capital WHERE unified_code=:code '
            'AND capital_kind=:kind AND effective_date<=:day ORDER BY effective_date DESC LIMIT 1'),
            dict(code=code, kind=kind, day=as_of)).mappings().first()))

    async def capital_points(self, code, kind, start='1900-01-01', end='2100-12-31', after=None, limit=500, order=None):
        security_identity(code)
        _limit(limit)
        if kind not in CAPITAL_KINDS or day(start) > day(end):
            raise ValueError('远航版股本查询范围无效')
        if order is None and after is not None and not start <= day(after).isoformat() <= end:
            raise ValueError('远航版股本分页日期无效')
        def read(conn):
            if order is not None:
                names = ('effective_date', 'shares')
                sort_fields = column_fields(names)
                rows, cursor = ordered_page(
                    conn, 'SELECT effective_date,shares FROM yuanhang_capital WHERE unified_code=:code '
                    'AND effective_date BETWEEN :first AND :last AND capital_kind=:kind', dict(code=code, first=start, last=end, kind=kind),
                    order=order, fields=sort_fields, identity=('effective_date',), after=after, limit=limit,
                )
                return dict(rows=rows, next=cursor)
            rows = [dict(r) for r in conn.execute(text('SELECT effective_date,shares FROM yuanhang_capital '
                'WHERE unified_code=:code AND capital_kind=:kind AND effective_date BETWEEN :first AND :last '
                'AND (:after IS NULL OR effective_date>:after) ORDER BY effective_date LIMIT :n'),
                dict(code=code, kind=kind, first=start, last=end, after=after, n=limit+1)).mappings()]
            return dict(rows=rows[:limit], next=rows[limit-1]['effective_date'].isoformat() if len(rows) > limit else None)
        return await self._read(read)

    async def year_heads(self, code):
        security_identity(code)
        def read(conn):
            rows = conn.execute(text('SELECT * FROM yuanhang_price_year WHERE unified_code=:code '
                                     'ORDER BY quote_year LIMIT 151'), dict(code=code)).mappings().all()
            if len(rows) > 150:
                raise ValueError('远航版年度证明超限')
            return {r['quote_year']: dict(r) for r in rows}
        return await self._read(read)

    async def has_history(self, code, *, financial=False):
        security_identity(code)
        tables = (('yuanhang_corporate_action', 'yuanhang_capital', 'yuanhang_series_proof')
                  if financial else ('yuanhang_daily_price', 'yuanhang_price_year'))
        return await self._read(lambda conn: any(conn.execute(text(
            f'SELECT EXISTS(SELECT 1 FROM {table} WHERE unified_code=:code)'), dict(code=code)).scalar_one()
            for table in tables))

    async def collection_scope(self, codes=None):
        if codes is not None:
            if not isinstance(codes, (list, tuple)) or not 1 <= len(codes) <= 15000 or len(set(codes)) != len(codes):
                raise ValueError('远航版指定证券集合无效')
            for code in codes:
                security_identity(code)
        def read(conn):
            rows = conn.execute(text('SELECT unified_code,name FROM stock ORDER BY unified_code LIMIT 15001')).mappings().all()
            if not rows or len(rows) > 15000:
                raise ValueError('远航版当前股票池为空或超限')
            catalog = {r['unified_code']: r['name'] for r in rows}
            if codes is not None and set(codes) - catalog.keys():
                raise ValueError('远航版指定证券不在当前股票池')
            selected = sorted(codes) if codes is not None else sorted(catalog)
            cutoff, message = read_trade_day_cutoff(conn, datetime.now(CHINA))
            if cutoff is None:
                raise ValueError('远航版日线截止日未准备：' + message)
            return selected, cutoff.date().isoformat()
        return await self._read(read)

    async def daily_plans(self, namespace, codes, through, *, force=False, scope='all'):
        from empire.features.yuanhang.plan_query import read_plans
        if not isinstance(codes, (list, tuple)) or len(codes) > 15000 or len(set(codes)) != len(codes):
            raise ValueError('远航版规划证券集合无效')
        for code in codes:
            security_identity(code)
        plans, calendar_cache = {}, {}
        work = 0
        for offset in range(0, len(codes), 64):
            batch = codes[offset:offset + 64]
            selected = await self._read(lambda conn: read_plans(conn, namespace, batch, through,
                force=force, scope=scope, calendar_cache=calendar_cache))
            plans.update(selected)
            work += sum(p['mode'] != 'skip' for p in selected.values())
            if scope == 'backfill' and work >= 64:
                break
        return plans

    async def financial_markets(self):
        def read(conn):
            rows = conn.execute(text("SELECT unified_code,native_market FROM yuanhang_series_proof "
                                     "WHERE series_kind='capital' ORDER BY unified_code LIMIT 15001")).all()
            if len(rows) > 15000:
                raise ValueError('远航金融证券数超限')
            return dict(rows)
        return await self._read(read)

    async def audit_price(self, payload):
        code, year = payload['code'], payload['year']
        security_identity(code)
        return await self._read(lambda conn: audit_year(payload,
            read_rows(conn, code, 'prices', year=year), read_heads(conn, code, year=year).get(year)))

    async def audit_financial(self, payload):
        code = payload['code']
        security_identity(code)
        return await self._read(lambda conn: audit_financial(payload, read_rows(conn, code, 'actions'),
            read_rows(conn, code, 'capital'), read_heads(conn, code)))

    async def audit_source_proofs(self, code, expected, *, financial=False):
        """Compare source digests with actual SQL keys/content, retaining no source body."""
        security_identity(code)
        if not isinstance(expected, dict) or not 1 <= len(expected) <= (2 if financial else 150):
            raise ValueError('远航版审计证明集合无效')
        def read(conn):
            problems = []
            heads = read_heads(conn, code) if financial else {}
            for unit, proof in expected.items():
                if financial:
                    rows = read_rows(conn, code, unit)
                    keys = [[r[0], action_key(r)] if unit == 'actions' else r[:2] for r in rows]
                    head = heads.get(unit)
                else:
                    rows = read_rows(conn, code, 'prices', year=unit)
                    keys = [r[0] for r in rows]
                    head = read_heads(conn, code, year=unit).get(unit)
                if head is None or any(head.get(k) != v for k, v in proof.items() if k != 'verified_through'):
                    problems.append(str(unit) + ':proof')
                if (len(rows) != proof['row_count'] or digest(rows) != proof['content_hash']
                        or digest(keys) != proof['key_hash']):
                    problems.append(str(unit) + ':content')
            return problems
        return await self._read(read)
