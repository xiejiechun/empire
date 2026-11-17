"""Source-owned ETF validation over shared authenticated native transport."""
import struct
from datetime import date

from empire.features.yuanhang_etf.contract import (
    ETF_LIMIT,
    LATEST_FIELDS,
    identity,
    native_identity,
    number,
)
from empire.sources.yuanhang_history import DAILY_FIELDS, _same_grid, day_number
from empire.sources.yuanhang_transport import request
from empire.sources.yuanhang_wire import decode_response, decode_table, validate_history_tables


def snapshot(body, request_id, limit, reserve=None):
    if not 21 <= len(body) <= limit:
        raise ValueError('ETF快照帧长度无效')
    if struct.unpack_from('<HiIHiB', body) != (17, 1, request_id, 1, len(body) - 17, 1):
        raise ValueError('ETF快照帧身份或完整性无效')
    if struct.unpack_from('<I', body, 17)[0] != len(body) - 21:
        raise ValueError('ETF快照块边界无效')
    table = decode_table(body[21:], limit, reserve, text_encodings={55: 'utf8'})
    if not 1 <= table['row_count'] <= ETF_LIMIT:
        raise ValueError('ETF快照数量无效')
    return table


def catalog(body, limit, reserve=None):
    table = snapshot(body, 7, limit, reserve)
    if ({f for f, *_ in table['fields']} != {5, 55}
            or type(table['extra'].get(34056)) is not int
            or table['extra'][34056] != table['row_count']):
        raise ValueError('ETF完整目录字段或来源总数不符')
    rows = []
    for row in table['rows']:
        code, market = native_identity(row[5])
        name = row[55]
        if not isinstance(name, str) or not name.strip() or name != name.strip() or len(name) > 100:
            raise ValueError('ETF名称无效')
        rows.append(dict(code=code, native_market=market, name=name))
    if len(rows) != len({r['code'] for r in rows}):
        raise ValueError('ETF完整目录证券集合重复')
    return sorted(rows, key=lambda r: r['code'])


def latest(body, market, codes, limit, reserve=None):
    table = snapshot(body, 200, limit, reserve)
    if {f for f, *_ in table['fields']} != {5, 55, 56, *LATEST_FIELDS}:
        raise ValueError('ETF最新行情字段不符')
    rows = []
    for row in table['rows']:
        code, actual_market = native_identity(row[5])
        if market != actual_market or not isinstance(row[55], str) or not row[55].strip() or len(row[55]) > 100:
            raise ValueError('ETF最新行情市场或名称不符')
        # Field 56 is explicitly NULL in verified ETF responses. Until its date
        # semantics are established, a non-NULL value needs source review.
        if row[56] is not None:
            raise ValueError('ETF来源时间字段出现尚未验证的值')
        rows.append(dict(code=code, native_market=market, name=row[55], quote_at=None, net_value_date=None,
            **{name: number(row[field]) for field, name in LATEST_FIELDS.items()}))
    if len(rows) != len(set(codes)) or {r['code'] for r in rows} != set(codes):
        raise ValueError('ETF最新行情缺码、额外代码或重复')
    return sorted(rows, key=lambda r: r['code'])


def daily(tables, code, market, start, end):
    validate_history_tables(tables, security=identity(code, market), required_fields=set(DAILY_FIELDS),
        start=day_number(start), end=day_number(end), identical_fields=DAILY_FIELDS)
    rows = []
    for row in _same_grid(tables, DAILY_FIELDS):
        stamp = str(row[1])
        rows.append([date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:])).isoformat()]
            + [number(row[f]) for f in (7, 8, 9, 11, 13, 19)])
    return rows


async def fetch_catalog(http, session, *, project_id):
    # Complete one-response set; sorting by name avoids duplicated field 5 in
    # the source table. Source total 34056 must equal the complete row count.
    query = (f'id=7&blockid=CFF3&reqflag=blockserver&sortbegin=0&sortcount={ETF_LIMIT+1}'
             '&sortid=55&sortorder=A&zipversion=2&instance=1').encode('ascii')
    return await request(http, session, query, catalog, project_id=project_id, service='block')


async def fetch_latest(http, session, market, codes, *, project_id, reservation=None):
    if not 1 <= len(codes) <= ETF_LIMIT or len(codes) != len(set(codes)):
        raise ValueError('ETF批量行情目标数量无效')
    for code in codes:
        identity(code, market)
    query = (f'id=200&market={market}&codelist={",".join(c[:6] for c in codes)}'
             f'&datatype=5,55,56,{",".join(map(str, LATEST_FIELDS))}&zipversion=2&instance=1').encode('ascii')
    return await request(http, session, query, lambda b, n, r: latest(b, market, codes, n, r),
        project_id=project_id, reservation=reservation, service='16' if market == 'USHJ' else '32')


async def fetch_daily(http, session, code, market, start, end, *, project_id, reservation=None):
    identity(code, market)
    query = (f'id=210&market={market}&code={code[:6]}&start={day_number(start)}&end={day_number(end)}'
             '&period=16384&datatype=1,7,8,9,11,13,19&zipversion=2&instance=1').encode('ascii')
    return await request(http, session, query,
        lambda b, n, r: daily(decode_response(b, instance=1, request_id=210, limit=n, reserve=r), code, market, start, end),
        project_id=project_id, reservation=reservation, service='16' if market == 'USHJ' else '32')
