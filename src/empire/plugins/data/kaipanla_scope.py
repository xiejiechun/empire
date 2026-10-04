"""Bounded SQL queries and coverage checks; Redis is not required for browsing."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

from empire.core.time import CHINA
from empire.plugins.data.preparation_checks import audit_stocks
from empire.plugins.data.trading_day_cutoff import read_trade_day_cutoff
from empire.plugins.infra.collection_state import read_state


class MarketDayScope:
    def __init__(self, namespace='empire'):
        self.source, self.mysql, self.namespace = 'kaipanla', None, namespace

    async def plan(self):
        return await self.mysql.read(self._plan)

    def _plan(self):
        with self.mysql.read_engine.begin() as conn:
            stocks = [dict(r) for r in conn.execute(text('SELECT RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code,name,unified_code,CONCAT(LOWER(RIGHT(unified_code,2)),LEFT(unified_code,6)) AS source_symbol FROM stock '
                'WHERE TRUE ORDER BY market,code'), {'source': 'sina'}).mappings()]
            keys = [(r['market'], r['code']) for r in stocks]
            if not keys or len(keys) > 15000 or len(set(keys)) != len(keys):
                raise ValueError('当前股票名单为空、重复或超过声明边界')
            now = datetime.now(CHINA)
            publication = read_state(conn, self.namespace, 'sina-stocks', 'sina')
            checks = audit_stocks(stocks, publication, now)
            if any(c.status != 'pass' for c in checks if c.criterion in ('fields', 'keys', 'coverage', 'temporal')):
                raise ValueError('当前股票名单与完整发布证明不匹配；先核实股票列表')
            cutoff, problem = read_trade_day_cutoff(conn, now)
            if cutoff is None:
                raise ValueError(problem)
            start, end = date(2021, 1, 1), cutoff.date()
            rows = conn.execute(text('SELECT trade_date,is_trade FROM trade_calendar WHERE '
                'trade_date BETWEEN :start AND :end ORDER BY trade_date'),
                dict(source='cninfo', start=start, end=end)).mappings().all()
            calendar = {r['trade_date']: r['is_trade'] for r in rows}
            expected = (end - start).days + 1
            if len(calendar) != expected or len(rows) != expected or any(v not in (0, 1) for v in calendar.values()):
                raise ValueError('2021 年以来正式交易日历缺日或标记异常，不能推断完整范围')
            days = sorted(d for d, flag in calendar.items() if flag == 1)
            return stocks, days

    async def covered_days(self, market, code, start, end, lifecycle=None):
        return await self.mysql.read(self._covered, market, code, start, end, lifecycle)

    async def suspended_days(self, market, code, start, end):
        """Only explicit bounded whole-day events can remove required request days."""
        def read():
            with self.mysql.read_engine.begin() as conn:
                events = conn.execute(text('SELECT suspended_at,resumed_at FROM suspension_event '
                    'WHERE unified_code=CONCAT(:code,CHAR(46),:market) AND suspension_type=:kind '
                    'AND suspended_at<:end AND resumed_at>:start ORDER BY suspended_at LIMIT 1001'),
                    dict(source='tdx', market=market, code=code, kind='full_day',
                         start=start, end=end + timedelta(days=1))).mappings().all()
                if len(events) > 1000:
                    raise ValueError('停牌生命周期证据超过有界查询上限')
                intervals = {}
                for event in events:
                    if not event['resumed_at'] or event['resumed_at'] <= event['suspended_at']:
                        continue
                    lower = event['suspended_at'].date()
                    if event['suspended_at'].time() > time(9, 30):
                        lower += timedelta(days=1)  # A suspension after opening cannot prove a whole day.
                    upper = event['resumed_at'].date()
                    intervals[lower] = min(intervals.get(lower, upper), upper)
                days = set()
                for lower, upper in intervals.items():
                    day = max(lower, start)
                    while day < upper and day <= end:
                        days.add(day)
                        day += timedelta(days=1)
                return days
        return await self.mysql.read(read)

    async def suspension_plan(self, stocks, start, end):
        """One bounded SQL snapshot, rather than one query per security at startup."""
        def read():
            wanted = {s['code'] + '.' + s['market'] for s in stocks}
            result = {key: set() for key in wanted}
            with self.mysql.read_engine.begin() as conn:
                rows = conn.execute(text('SELECT unified_code,suspended_at,resumed_at FROM suspension_event '
                    'WHERE suspension_type=:kind AND suspended_at<:end AND resumed_at>:start '
                    'ORDER BY unified_code,suspended_at LIMIT 100001'),
                    dict(kind='full_day', start=start, end=end + timedelta(days=1))).mappings().all()
                if len(rows) > 100000:
                    raise ValueError('停牌范围超过批量规划的有界上限')
                intervals, counts = {}, {}
                for row in rows:
                    key = row['unified_code']
                    if key not in wanted:
                        continue
                    counts[key] = counts.get(key, 0) + 1
                    if counts[key] > 1000:
                        raise ValueError('单证券停牌生命周期证据超过上限')
                    lower, upper = row['suspended_at'].date(), row['resumed_at'].date()
                    if row['resumed_at'] <= row['suspended_at']:
                        continue
                    if row['suspended_at'].time() > time(9, 30):
                        lower += timedelta(days=1)
                    pair = (key, lower)
                    intervals[pair] = min(intervals.get(pair, upper), upper)
                for (key, lower), upper in intervals.items():
                    day = max(lower, start)
                    while day < upper and day <= end:
                        result[key].add(day)
                        day += timedelta(days=1)
                return result
        return await self.mysql.read(read)

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
