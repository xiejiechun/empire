"""Bounded SQL browsing; optional cache evidence is used only by collection planning."""
import json
from datetime import datetime

from sqlalchemy import text

from empire.contracts.plugin import PluginManifest
from empire.contracts.security import split_unified_code
from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.yuanhang_limits.contract import (
    SOURCE,
    TABLE_COLUMNS,
    day_value,
    pool_value,
    project,
)
from empire.features.yuanhang_limits.dataset import LimitDataset
from empire.features.yuanhang_limits.planning import calendar_dates, plan_pool
from empire.features.yuanhang_limits.preparation import CONTRIBUTIONS, check
from empire.features.yuanhang_limits.repository import read_members, read_pool_head, read_reason
from empire.features.yuanhang_limits.storage import pool_payload, pool_proof
from empire.plugins.infra.query_order import column_fields, ordered_page
from empire.plugins.infra.schema_manifest import schema_contract
from empire.plugins.pipeline.fingerprints import FingerprintCache


def page_limit(value, maximum=200):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('涨停分析查询条数超界')


class LimitQuery:
    preparation = CONTRIBUTIONS
    manifest = PluginManifest('data.yuanhang_limits', '远航涨停分析查询',
        requires=('mysql.store',), provides=('yuanhang.limits.query',))

    def __init__(self, namespace, archive_settings=None):
        self.namespace, self.archive_settings = namespace, archive_settings or {}
        self.mysql = None

    async def start(self, context):
        self.mysql, self.context = context.get('mysql.store'), context
        await self.mysql.require_schema(*schema_contract(TABLE_COLUMNS))
        return {'yuanhang.limits.query': self}

    async def cache_proofs(self, pool, identities):
        from redis.exceptions import RedisError
        store = self.context.optional('redis.store')
        if store is None:
            return {}
        cache = FingerprintCache(store, self.archive_settings, lambda _: LimitDataset.FINGERPRINT_VERSION)
        try:
            return await cache.peek(LimitDataset(pool).FINGERPRINT_NAMESPACE, SOURCE, identities)
        except RedisError:
            return {}  # Optional freshness supplement; SQL remains authoritative.

    async def read(self, operation):
        def execute():
            with self.mysql.read_engine.connect() as conn:
                return operation(conn)
        return await self.mysql.read(execute)

    async def resolve_identities(self, codes):
        """Use only explicit identities already archived from this source's pools."""
        if not 1 <= len(codes) <= 100:
            raise ValueError('历史池身份查询数量超界')
        from sqlalchemy import bindparam
        candidates = []
        for code in sorted(codes):
            for market in ('SH', 'SZ', 'BJ'):
                value = f'{code}.{market}'
                split_unified_code(value)
                candidates.append(value)
        def operation(conn):
            statement = text('SELECT DISTINCT unified_code FROM yuanhang_limit_member '
                "WHERE unified_code IN :codes AND identity_basis IN ('market_id','source_board','sina_lookup')").bindparams(
                    bindparam('codes', expanding=True))
            known = list(conn.execute(statement, dict(codes=candidates)).scalars())
            if any(sum(value[:6] == code for value in known) > 1 for code in codes):
                raise ValueError('已归档证券市场身份冲突，不能用辅助查询覆盖')
            return {code: matches[0] for code in codes
                    if len(matches := [value for value in known if value[:6] == code]) == 1}
        return await self.read(operation)

    async def members(self, day, pool, *, after='', limit=200, order=None):
        day_value(day)
        pool_value(pool)
        page_limit(limit)
        if after and order is None:
            split_unified_code(after)
        def operation(conn):
            if order is not None:
                from empire.features.yuanhang_limits.contract import TABLE_COLUMNS
                rows, cursor = ordered_page(
                    conn, 'SELECT * FROM yuanhang_limit_member WHERE trade_date=:day AND pool_type=:pool',
                    dict(day=day, pool=pool), order=order,
                    fields=column_fields(TABLE_COLUMNS['yuanhang_limit_member']),
                    identity=('unified_code',), after=after or None, limit=limit,
                )
                head = read_pool_head(conn, day, pool)
                return dict(head=dict(head) if head else None, rows=rows, next=cursor)
            # Decimal values remain Decimal in SQL browsing; no lossy float cast.
            rows = [dict(r) for r in conn.execute(text('SELECT * FROM yuanhang_limit_member '
                'WHERE trade_date=:day AND pool_type=:pool AND unified_code>:after '
                'ORDER BY unified_code LIMIT :n'), dict(day=day, pool=pool, after=after, n=limit + 1)).mappings()]
            head = read_pool_head(conn, day, pool)
            return dict(head=dict(head) if head else None, rows=rows[:limit],
                        next=rows[limit - 1]['unified_code'] if len(rows) > limit else None)
        return await self.read(operation)

    async def history(self, code, start, end, *, after=None, limit=500):
        split_unified_code(code)
        day_value(start)
        day_value(end)
        page_limit(limit, 500)
        if start > end:
            raise ValueError('证券历史日期范围倒序')
        marker_day, marker_pool = ('1900-01-01', '') if after is None else after
        day_value(marker_day)
        if marker_pool:
            pool_value(marker_pool)
        def operation(conn):
            rows = [dict(r) for r in conn.execute(text('SELECT * FROM yuanhang_limit_member '
                'WHERE unified_code=:code AND trade_date BETWEEN :first AND :last '
                'AND (trade_date>:d OR (trade_date=:d AND pool_type>:p)) '
                'ORDER BY trade_date,pool_type LIMIT :n'), dict(code=code, first=start, last=end,
                    d=marker_day, p=marker_pool, n=limit + 1)).mappings()]
            return dict(rows=rows[:limit], next=(rows[limit - 1]['trade_date'].isoformat(),
                rows[limit - 1]['pool_type']) if len(rows) > limit else None)
        return await self.read(operation)

    async def reason(self, day, code):
        day_value(day)
        split_unified_code(code)
        def operation(conn):
            result = read_reason(conn, day, code)
            return dict(result) if result else None
        return await self.read(operation)

    async def browse(self, filters, after=None, order=None):
        if not isinstance(filters, (tuple, list)) or len(filters) != 6:
            raise ValueError('涨停分析查询条件错误')
        mode, pool, code, start, end, _ = filters
        if mode in (3, 4):
            from empire.features.yuanhang_limits.intraday_query import browse_live
            return await browse_live(self, filters, after, order=order)
        if mode == 0:
            result = await self.members(start, pool, after=after or '')
            head = result['head']
            message = ('未采集该日期池' if head is None else '来源报告空集合；不推定历史边界'
                       if head['source_total'] == 0 else f"来源池共{head['source_total']}条，本页{len(result['rows'])}条")
        elif mode == 1:
            result = await self.history(code, start, end, after=after, limit=200)
            message = f"证券历史本页{len(result['rows'])}条；无记录不代表范围已采齐"
        elif mode == 2:
            record = await self.reason(start, code)
            result = dict(rows=[record] if record else [], next=None)
            message = '未采集该证券日原因' if record is None else '来源未提供正文' if record['availability'] == 'no_content' else '来源原因；无可靠历史公布时刻'
        else:
            raise ValueError('未知涨停分析查询方式')
        return dict(result, message=message)

    async def check_limit_up_pool(self, request=None):
        return await check(self, 'limit_up_pool', request)

    async def check_sprint_limit_up(self, request=None):
        return await check(self, 'sprint_limit_up', request)

    async def check_connect_broad_pool(self, request=None):
        return await check(self, 'connect_broad_pool', request)

    async def check_open_limit_up_pool(self, request=None):
        return await check(self, 'open_limit_up_pool', request)

    async def check_limit_down_pool(self, request=None):
        return await check(self, 'limit_down_pool', request)

    async def check_reason(self, request=None):
        return await check(self, 'reason', request)

    async def audit_pool(self, day, pool):
        day_value(day)
        pool_value(pool)
        def operation(conn):
            head = read_pool_head(conn, day, pool)
            if head is None:
                return dict(complete=False, reason='未归档日期池')
            unit = dict(trade_date=day, pool_type=pool, filter=head['filter_text'],
                        source_total=head['source_total'], rows=read_members(conn, day, pool))
            proof = pool_proof(pool_payload(unit))
            valid = len(unit['rows']) == head['source_total'] and all(head[k] == v for k, v in proof.items())
            return dict(complete=valid, reason='来源报告空集合；不推定来源历史边界' if not unit['rows'] else '',
                        count=len(unit['rows']))
        return await self.read(operation)

    async def collection_plan(self, pool, *, force=False, exclude=(), through=None, scan_after=None):
        if pool == 'reason':
            # Reason planning has a different ownership/grain; implemented in its
            # own module rather than embedding cross-pool SQL in the collector.
            from empire.features.yuanhang_limits.reason_planning import reason_plan
            return await reason_plan(self, force=force, exclude=exclude, through=through, scan_after=scan_after)
        pool_value(pool)
        now = datetime.now(CHINA)
        def operation(conn):
            cutoff, message = read_trade_day_cutoff(conn, now)
            if cutoff is None:
                raise ValueError(message)
            endpoint = min(cutoff.date().isoformat(), through) if through else cutoff.date().isoformat()
            days = [(r[0].isoformat(), r[1]) for r in conn.execute(text('SELECT trade_date,is_trade '
                'FROM trade_calendar WHERE trade_date BETWEEN :first AND :last ORDER BY trade_date'),
                dict(first='1990-12-19', last=endpoint))]
            if not days or days[0][0] != '1990-12-19':
                raise ValueError('全历史规划缺少正式日历起点')
            trades = calendar_dates(days, endpoint)
            heads = [dict(r) for r in conn.execute(text('SELECT trade_date,contract_version,content_sha256 '
                'FROM yuanhang_limit_pool WHERE pool_type=:pool AND trade_date<=:last ORDER BY trade_date LIMIT 36601'),
                dict(pool=pool, last=endpoint)).mappings()]
            if len(heads) > 36600:
                raise ValueError('日期池历史头超限')
            state = conn.execute(text("SELECT JSON_EXTRACT(payload,'$.versions') FROM collection_state "
                'WHERE namespace=:namespace AND project_id=:project AND source=:source'),
                dict(namespace=self.namespace, project=project(pool), source=SOURCE)).scalar_one_or_none()
            versions = json.loads(state) if isinstance(state, str) else state or {}
            return endpoint, trades, heads, versions
        cutoff, trades, heads, versions = await self.read(operation)
        coverage = {r['trade_date'].isoformat(): r for r in heads if r['contract_version'] == 1}
        verified = {d: datetime.fromisoformat(v).astimezone(CHINA).date().isoformat()
                    for d, v in versions.items() if d in coverage}
        identities = [d + ':' + pool for d in coverage]
        proofs = {}
        for offset in range(0, len(identities), 256):
            proofs.update(await self.cache_proofs(pool, identities[offset:offset + 256]))
        for key, proof in proofs.items():
            day = key[:10]
            if proof['hash'] == coverage[day]['content_sha256']:
                observed = datetime.fromisoformat(proof['version'][0]).astimezone(CHINA).date().isoformat()
                if observed <= now.date().isoformat():
                    verified[day] = max(verified.get(day, ''), min(observed, cutoff))
        if any(v > now.date().isoformat() for v in verified.values()):
            raise ValueError('SQL核验版本超前，不能据此跳过历史')
        verified = {d: min(v, cutoff) for d, v in verified.items()}
        planned = plan_pool(trades, coverage, verified, cutoff=cutoff, force=force, exclude=exclude)
        return dict(units=list(planned.days), cutoff=cutoff, remaining=planned.remaining)

    async def stop(self):
        self.mysql = None

    def health(self):
        return {'status': 'ok' if self.mysql else 'stopped'}
