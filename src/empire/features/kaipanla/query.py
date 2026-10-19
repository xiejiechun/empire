"""Typed browsing and bounded pages; coverage never downloads historical fact bodies."""
from collections.abc import Iterator
from datetime import date

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from empire.contracts.plugin import PluginManifest
from empire.contracts.preparation import PreparationContribution
from empire.contracts.security import unified_code
from empire.features.kaipanla.api import SecurityDay
from empire.features.kaipanla.codec import clock, decode, key_set
from empire.features.kaipanla.contract import PRODUCTS, capability, project
from empire.features.kaipanla.normalization import digest, validate
from empire.features.kaipanla.repository import head_record, read_day
from empire.features.kaipanla.schema import KEYS, TABLES
from empire.features.kaipanla.scope import MarketDayScope
from empire.features.kaipanla.storage_contract import (
    LAYOUT_VERSION,
    QUOTE_FIELDS,
    SERIES,
    dataset_tables,
    restore_values,
)

HEAD_PROJECTION = ('kind,unified_code,trade_date,listing_date,listing_source,market_start,'
                   'contract_version,point_count,key_set_hash,content_hash,version_observed_at')


class KaipanlaProductDataPlugin(MarketDayScope):
    def __init__(self, kind, namespace='empire'):
        super().__init__(namespace=namespace)
        self.kind, self.project_id = kind, project(kind)
        item = PRODUCTS[kind]
        self.manifest = PluginManifest('data.kaipanla_' + kind, '开盘啦' + item.title + '查询',
            requires=('mysql.store',), provides=(capability(kind),), description=item.note)
        self.preparation = (PreparationContribution(item.requirement, capability(kind), '开盘啦',
            self.project_id, self.project_id + '-v1', 'kaipanla.' + kind + '.day',
            'collector.kaipanla_' + kind,
            ('tests/test_kaipanla_products.py', 'tests/test_market_suspension_days.py'),
            ('tests/integration/test_kaipanla_products_archive.py',
             'tests/integration/test_kaipanla_suspension_scope.py'), scoped=True),)

    async def start(self, context):
        self.mysql = context.get('mysql.store')
        tables = dataset_tables(self.kind)
        await self.mysql.require_schema({t: TABLES[t] for t in tables}, {t: KEYS[t] for t in tables})
        return {capability(self.kind): self}

    def _heads(self, conn, market, code, start, end, full=False):
        return [dict(r) for r in conn.execute(text(
            f'SELECT {"*" if full else HEAD_PROJECTION} FROM stock_market_day '
            'WHERE kind=:kind AND unified_code=:security AND trade_date BETWEEN :start AND :end '
            'ORDER BY trade_date LIMIT 10001'), dict(kind=self.kind, security=unified_code(market, code),
                                                    start=start, end=end)).mappings()]

    def _records(self, conn, market, code, start, end):
        heads = self._heads(conn, market, code, start, end, full=True)
        if len(heads) > 10000:
            raise ValueError('证券日核验超限')
        for offset in range(0, len(heads), 16):
            batch = heads[offset:offset + 16]
            facts = {}
            for table in dataset_tables(self.kind)[1:]:
                order = 'block_seq' if self.kind == 'trades' else 'seq' if self.kind in SERIES else ('side,level' if table.endswith('_level') else 'unified_code')
                facts[table] = [dict(r) for r in conn.execute(text(f'SELECT * FROM {table} WHERE '
                    'unified_code=:security AND trade_date BETWEEN :start AND :end '
                    f'ORDER BY trade_date,{order}'), dict(security=code+'.'+market,
                    start=batch[0]['trade_date'], end=batch[-1]['trade_date'])).mappings()]
            for head in batch:
                try:
                    canonical = decode(head, {t: [r for r in rr if r['trade_date'] == head['trade_date']]
                                              for t, rr in facts.items()})
                    yield {**head, 'canonical': canonical}
                except ValueError as exc:
                    yield {**head, 'decode_error': str(exc)}

    def _decode(self, stored, market, code):
        if 'decode_error' in stored:
            raise ValueError(stored['decode_error'])
        row = stored['canonical']
        validate(row, self.kind)
        if ((row['market'], row['code']) != (market, code)
                or digest(row) != stored['content_hash'] or key_set(row) != stored['key_set_hash']
                or stored['contract_version'] != LAYOUT_VERSION):
            raise ValueError('证券日关联、摘要或校验契约错误')
        return row

    def iter_validated_days(self, conn: Connection, market: str, code: str,
                            start: date, end: date) -> Iterator[SecurityDay]:
        """Yield validated days within the caller's existing SQL snapshot.

        Does not open/close a connection, start a transaction, or schedule mysql.read.
        The caller must finish iteration before leaving its connection context.
        Uses the same 10000-head bound and 16-day fact batches as preparation.
        """
        for stored in self._records(conn, market, code, start, end):
            yield self._decode(stored, market, code)

    def _covered(self, market, code, start, end, lifecycle=None):
        with self.mysql.read_engine.begin() as conn:
            records = self._heads(conn, market, code, start, end)
        if len(records) > 10000:
            raise ValueError('证券日覆盖核验超限')
        covered = set()
        for head in records:
            life = {k: head[k] if k == 'listing_source' else head[k].isoformat()
                    for k in ('listing_date', 'listing_source', 'market_start')}
            count = head['point_count']
            expected = 1 if self.kind == 'quote' else 241 if self.kind not in ('auction', 'trades') else count
            if (head['contract_version'] == LAYOUT_VERSION and count == expected and count > 0
                    and head['listing_source'] == 'eastmoney'
                    and len(head['key_set_hash']) == 64 and len(head['content_hash']) == 64
                    and (lifecycle is None or lifecycle == life)):
                covered.add(head['trade_date'])
        return covered

    async def day(self, market, code, trade_date):
        security, day = unified_code(market, code), date.fromisoformat(trade_date)
        def read():
            with self.mysql.read_engine.begin() as conn:
                head = head_record(conn, self.kind, security, day)
                return dict(data=read_day(conn, head), observed_at=head['version_observed_at']) if head else None
        return await self.mysql.read(read)

    async def page(self, market, code, trade_date, cursor=None, limit=200, start_time=None, end_time=None):
        if self.kind not in SERIES or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('序列分页范围无效')
        security, day = unified_code(market, code), date.fromisoformat(trade_date)
        time_range = None
        if start_time is not None or end_time is not None:
            from datetime import time
            if self.kind != 'trades' or start_time is None or end_time is None:
                raise ValueError('时段查询仅支持分笔且需要起止时间')
            lower, upper = time.fromisoformat(start_time), time.fromisoformat(end_time)
            if (lower.isoformat() != start_time or upper.isoformat() != end_time
                    or lower.microsecond or upper.microsecond or lower.tzinfo or upper.tzinfo or lower > upper):
                raise ValueError('时段必须为无时区HH:MM:SS且起点不晚于终点')
            time_range = [start_time, end_time]
        table, columns = SERIES[self.kind]
        def read():
            with self.mysql.read_engine.begin() as conn:
                head = head_record(conn, self.kind, security, day)
                if not head:
                    return None
                after = -1
                if cursor:
                    if (set(cursor) != {'hash', 'seq', 'security', 'day', 'kind'} | ({'time_range'} if time_range else set())
                            or cursor.get('time_range') != time_range
                            or (cursor['hash'], cursor['security'], cursor['day'], cursor['kind']) !=
                            (head['content_hash'], security, trade_date, self.kind)
                            or type(cursor['seq']) is not int or cursor['seq'] < -1):
                        raise ValueError('分页版本已改变或游标无效，请重新查询')
                    after = cursor['seq']
                elif time_range:
                    # Start at the last block preceding the lower bound. Equal-time blocks
                    # are all retained; same-second observations may span block boundaries.
                    prior = conn.execute(text(f'SELECT first_seq FROM {table} WHERE unified_code=:security '
                        'AND trade_date=:day AND first_time<:lower ORDER BY first_time DESC,block_seq DESC LIMIT 1'),
                        dict(security=security, day=day, lower=start_time)).scalar_one_or_none()
                    after = prior-1 if prior is not None else -1
                if self.kind == 'trades':
                    from empire.features.kaipanla.trade_blocks import unpack
                    blocks = list(conn.execute(text(f'SELECT * FROM {table} WHERE unified_code=:security '
                        'AND trade_date=:day AND block_seq>=:first '
                        + ('AND first_time<=:upper ' if time_range else '') + 'ORDER BY block_seq LIMIT 3'),
                        dict(security=security, day=day, first=(after+1)//200, upper=end_time)).mappings())
                    if any(b['point_count'] != min(200, head['point_count']-b['first_seq']) for b in blocks):
                        raise ValueError('分笔块点数与证券日序号边界不一致')
                    rows = [dict(seq=b['first_seq']+i, point=p) for b in blocks
                            for i, p in enumerate(unpack(b)) if b['first_seq']+i > after
                            and (not time_range or start_time <= p[0] <= end_time)][:limit+1]
                    page = rows[:limit]
                    points = [r['point'] for r in page]
                else:
                    rows = list(conn.execute(text(f'SELECT * FROM {table} WHERE unified_code=:security '
                        'AND trade_date=:day AND seq>:after ORDER BY '+
                        ('seq' if self.kind == 'auction' else 'source_time')+' LIMIT :size'),
                        dict(security=security, day=day, after=after, size=limit+1)).mappings())
                    page = rows[:limit]
                    points = [[clock(r['source_time']),
                               *restore_values([r[c] for c in columns], r['float_mask'])] for r in page]
                token = dict(hash=head['content_hash'], seq=page[-1]['seq'], security=security,
                             day=trade_date, kind=self.kind) if len(rows) > limit and page else None
                if token and time_range:
                    token['time_range'] = time_range
                return dict(points=points, total=head['point_count'], start=after+1, next_cursor=token,
                            seqs=[r['seq'] for r in page],
                            content_hash=head['content_hash'], observed_at=head['version_observed_at'])
        return await self.mysql.read(read)

    async def archived_date(self, market, code, at='', direction=0):
        security = unified_code(market, code)
        if direction not in (-1, 0, 1) or direction and not at:
            raise ValueError('证券日导航方向或日期无效')
        if at:
            date.fromisoformat(at)
        def read():
            clause = ' AND trade_date' + ('<' if direction < 0 else '>') + ':at' if direction else ''
            with self.mysql.read_engine.connect() as conn:
                day = conn.execute(text('SELECT trade_date FROM stock_market_day WHERE kind=:kind '
                    'AND unified_code=:security' + clause + ' ORDER BY trade_date '
                    + ('ASC' if direction > 0 else 'DESC') + ' LIMIT 1'),
                    dict(kind=self.kind, security=security, at=at)).scalar_one_or_none()
                return day.isoformat() if day else None
        return await self.mysql.read(read)

    async def range(self, start, end, fields, securities=(), cursor=None, limit=200):
        if self.kind != 'quote' or not fields or set(fields) - set(QUOTE_FIELDS) or len(set(fields)) != len(fields):
            raise ValueError('日摘要查询字段无效')
        if type(limit) is not int or not 1 <= limit <= 1000 or len(securities) > 500:
            raise ValueError('查询范围超过上限')
        lower, upper = date.fromisoformat(start), date.fromisoformat(end)
        if lower > upper or (upper-lower).days > 366:
            raise ValueError('日期范围无效或超过366日')
        for security in securities:
            unified_code(security[-2:], security[:6])
        def read():
            where = 'trade_date BETWEEN :start AND :end'
            values = dict(start=lower, end=upper, size=limit+1)
            if securities:
                where += ' AND unified_code IN :securities'
                values['securities'] = list(securities)
            if cursor:
                where += ' AND (trade_date,unified_code)>(:after_day,:after_security)'
                values.update(after_day=date.fromisoformat(cursor['day']), after_security=cursor['security'])
            sql = text('SELECT unified_code,trade_date,'+','.join('`'+f+'`' for f in fields)+
                       ' FROM stock_daily_quote WHERE '+where+' ORDER BY trade_date,unified_code LIMIT :size')
            if securities:
                sql = sql.bindparams(bindparam('securities', expanding=True))
            with self.mysql.read_engine.begin() as conn:
                rows = [dict(r) for r in conn.execute(sql, values).mappings()]
            page = rows[:limit]
            return dict(rows=page, next_cursor=dict(day=page[-1]['trade_date'].isoformat(),
                security=page[-1]['unified_code']) if len(rows)>limit else None)
        return await self.mysql.read(read)

    async def preparation_check(self, request=None):
        from empire.features.kaipanla.audit import audit
        return await audit(self, request)
