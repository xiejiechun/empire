"""Bounded SQL queries and coverage checks; Redis is not required for browsing."""
import json
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.core.time import CHINA
from empire.plugins.data.preparation_checks import audit_stocks
from empire.plugins.data.trading_day_cutoff import read_trade_day_cutoff
from empire.plugins.datasets.intraday import KEYS, TABLES, digest, validate
from empire.plugins.infra.collection_state import read_state


class IntradayDataPlugin:
    preparation = (PreparationContribution('intraday', 'intraday.query', '开盘啦',
        'kaipanla-intraday', 'kaipanla-intraday-v1', 'intraday.day', 'collector.kaipanla_intraday',
        ('tests/test_kaipanla_source.py', 'tests/test_kaipanla_intraday.py'),
        ('tests/integration/test_intraday_archive.py',), scoped=True),)
    manifest = PluginManifest('data.intraday', '开盘啦分时查询', requires=('mysql.store',),
        provides=('intraday.query',), description='查询无损分时与竞价，按证券日核对内容和历史缺口')

    def __init__(self, source='kaipanla', namespace='empire'):
        self.source, self.mysql, self.namespace = source, None, namespace

    async def start(self, context):
        self.mysql = context.get('mysql.store')
        await self.mysql.require_schema(TABLES, KEYS)
        return {'intraday.query': self}

    async def plan(self):
        return await self.mysql.read(self._plan)

    def _plan(self):
        with self.mysql.read_engine.begin() as conn:
            stocks = [dict(r) for r in conn.execute(text('SELECT market,code,name,unified_code,source_symbol FROM stock '
                'WHERE source=:source ORDER BY market,code'), {'source': 'sina'}).mappings()]
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
                'source=:source AND trade_date BETWEEN :start AND :end ORDER BY trade_date'),
                dict(source='cninfo', start=start, end=end)).mappings().all()
            calendar = {r['trade_date']: r['is_trade'] for r in rows}
            expected = (end - start).days + 1
            if len(calendar) != expected or len(rows) != expected or any(v not in (0, 1) for v in calendar.values()):
                raise ValueError('2021 年以来正式交易日历缺日或标记异常，不能推断完整范围')
            days = sorted(d for d, flag in calendar.items() if flag == 1)
            return stocks, days

    async def covered_days(self, market, code, start, end, lifecycle=None):
        return await self.mysql.read(self._covered, market, code, start, end, lifecycle)

    def _covered(self, market, code, start, end, lifecycle=None):
        with self.mysql.read_engine.begin() as conn:
            rows = conn.execute(text('SELECT trade_date,payload,content_hash FROM stock_intraday '
                'WHERE source=:source AND market=:market AND code=:code AND trade_date BETWEEN '
                ':start AND :end ORDER BY trade_date'),
                dict(source=self.source, market=market, code=code, start=start, end=end)).mappings()
            covered = set()
            for stored in rows:
                value = json.loads(stored['payload']) if isinstance(stored['payload'], str) else stored['payload']
                try:
                    validate(value)
                    if (value['market'], value['code'], value['trade_date']) != (market, code, stored['trade_date'].isoformat()):
                        continue
                    if digest(value) != stored['content_hash']:
                        continue
                    if lifecycle is not None and value['lifecycle'] != lifecycle:
                        continue
                except (ValueError, TypeError, KeyError):
                    continue  # Old/malformed records need source recollection, not a false coverage proof.
                covered.add(stored['trade_date'])
            return covered

    async def suspended_days(self, market, code, start, end):
        """Only explicit bounded whole-day events can remove required request days."""
        def read():
            with self.mysql.read_engine.begin() as conn:
                events = conn.execute(text('SELECT suspended_at,resumed_at FROM suspension_event '
                    'WHERE source=:source AND market=:market AND code=:code AND suspension_type=:kind '
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

    async def day(self, market, code, trade_date):
        if market not in ('SH', 'SZ', 'BJ') or not isinstance(code, str) or not code.isdigit() or len(code) != 6:
            raise ValueError('请选择有效市场及六位证券代码')
        day = date.fromisoformat(trade_date)
        def read():
            with self.mysql.read_engine.connect() as conn:
                row = conn.execute(text('SELECT payload,content_hash,version_observed_at FROM stock_intraday '
                    'WHERE source=:source AND market=:market AND code=:code AND trade_date=:day'),
                    dict(source=self.source, market=market, code=code, day=day)).mappings().first()
                if not row:
                    return None
                payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
                validate(payload)
                if digest(payload) != row['content_hash'] or (payload['market'], payload['code'], payload['trade_date']) != (market, code, day.isoformat()):
                    raise ValueError('已归档分时摘要或证券日关联异常，需要补采')
                return dict(data=payload, observed_at=row['version_observed_at'])
        return await self.mysql.read(read)

    async def coverage(self, market, code, start='2021-01-01', end=None):
        # A calendar trading day without a response remains unclassified, including
        # pre-listing, changed-code and suspended days. Never fabricate an empty day.
        start = date.fromisoformat(start)
        end = date.fromisoformat(end) if end else datetime.now(CHINA).date() - timedelta(days=1)
        if start < date(2021, 1, 1) or end < start or (end - start).days > 10000:
            raise ValueError('分时核查范围无效')
        covered = await self.covered_days(market, code, start, end)
        return dict(archived_days=len(covered), first=min(covered).isoformat() if covered else None,
                    last=max(covered).isoformat() if covered else None,
                    note='仅成功响应日；上市前、停牌与代码变更尚无来源生命周期证明，不能宣称逐日完整')

    async def stop(self):
        self.mysql = None

    async def preparation_check(self, request=None):
        from empire.plugins.data.intraday_preparation import audit
        return await audit(self, request)

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
