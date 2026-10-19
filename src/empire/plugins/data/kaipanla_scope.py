"""Bounded SQL queries and coverage checks; Redis is not required for browsing."""
from datetime import date, datetime, timedelta

from sqlalchemy import bindparam, text

from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.stocks.api import current_directory
from empire.features.stocks.audit_rules import audit_stocks
from empire.features.suspensions.exclusions import excluded_days


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
            publication = current_directory(conn, self.namespace)
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
        plan = await self.suspension_plan([dict(market=market, code=code)], start, end)
        return plan[code + '.' + market]

    async def suspension_plan(self, stocks, start, end):
        """One bounded SQL snapshot, rather than one query per security at startup."""
        def read():
            wanted = {s['code'] + '.' + s['market'] for s in stocks}
            if not wanted:
                return {}
            with self.mysql.read_engine.begin() as conn:
                sql = text('SELECT unified_code,suspended_at,resumed_at,suspension_type,source_note '
                    'FROM suspension_event WHERE unified_code IN :securities AND suspended_at<:end '
                    'AND (resumed_at>:start OR (resumed_at IS NULL AND suspended_at>=:start)) '
                    'ORDER BY unified_code,suspended_at LIMIT 100001').bindparams(
                        bindparam('securities', expanding=True))
                rows = conn.execute(sql, dict(securities=sorted(wanted), start=start,
                    end=end + timedelta(days=1))).mappings().all()
                if len(rows) > 100000:
                    raise ValueError('停牌范围超过批量规划的有界上限')
                return excluded_days(rows, wanted, start, end)
        return await self.mysql.read(read)

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
