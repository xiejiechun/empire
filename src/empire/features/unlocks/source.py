"""List capacity is large; responses and detail request groups remain bounded."""
import calendar
from collections import Counter

from empire.features.unlocks.contract import (
    CAPACITY,
    canonical_number,
    digest,
    fact_key,
    group_key,
    monthly_plan,
    security,
    shares,
    source_day,
    text_value,
)
from empire.sources.tdx_unlock import results

URL = 'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_cgbd_dxfgg'
LIST_COLUMNS = ['sc', 'T006', 'name', 'code', 'hyname', 'sT006', 'jjsl', 'T003', 'flag', 'T010']
DETAIL_SOURCE_COLUMNS = ['name', 'code', 'T007', 'sc', 'T006', 'jjsl']


def list_params(month):
    monthly_plan(month, month)
    year, number = int(month[:4]), int(month[5:7])
    return ['0', month.replace('-', ''), f'{year:04d}{number:02d}{calendar.monthrange(year, number)[1]:02d}',
            '', '1', '1', str(CAPACITY)]


def detail_params(parent):
    return ['1', parent['reason_code'], parent['unlock_date'].replace('-', ''),
            parent['unified_code'][:6], '1', '1', str(CAPACITY)]






def parse_list(value, month):
    raw, meta, counts = results(value, [LIST_COLUMNS, ['page', 'scode'], ['count']])
    if (meta != [[1, '']] or len(counts) != 1 or type(counts[0][0]) is not int
            or counts[0][0] < 0 or counts[0][0] > len(raw) or len(raw) > 10000):
        raise ValueError('大小非解禁完整月列表协议或容量错误')
    # The auxiliary count under-reports historical rows (1999-11: 1 vs 14).
    # Completeness uses the full month response, exact table Count and a
    # request capacity far above the accepted 10000-row business limit.
    # An auxiliary count above the returned set still proves truncation.
    output, seen = [], Counter()
    for values in raw:
        record = dict(zip(LIST_COLUMNS, values, strict=True))
        row = dict(unified_code=security(record['sc'], record['code']), unlock_date=source_day(record['T003']),
            reason_code=text_value(record['T006'], 128, True), name=text_value(record['name'], 100),
            industry=text_value(record['hyname'], 200), reason=text_value(record['sT006'], 1024),
            shares=canonical_number(shares(record['jjsl'], source=True)),
            total_shares=canonical_number(shares(record['T010'], source=True)))
        if row['unlock_date'][:7] != month[:7] or type(record['flag']) is not int or record['flag'] not in (0, 1):
            raise ValueError('大小非解禁列表日期或标记无效')
        row['group_key'] = group_key(row)
        output.append(row)
    # Assign occurrences deterministically even when mutable metadata differs
    # between otherwise identical facts and the source reorders its rows.
    for row in sorted(output, key=digest):
        fact = digest([row[k] for k in ('group_key', 'reason', 'shares')])
        seen[fact] += 1
        row['occurrence'] = seen[fact]
        row['record_key'] = fact_key(row)
    return sorted(output, key=lambda r: r['record_key'])


def parse_detail(value, parent):
    raw, meta = results(value, [DETAIL_SOURCE_COLUMNS, ['scode']])
    if meta != [[parent['unified_code'][:6]]] or len(raw) > 10000:
        raise ValueError('大小非解禁明细请求身份或容量错误')
    output, seen = [], Counter()
    for values in raw:
        r = dict(zip(DETAIL_SOURCE_COLUMNS, values, strict=True))
        if security(r['sc'], r['code']) != parent['unified_code']:
            raise ValueError('大小非解禁明细关联了其他证券')
        text_value(r['name'], 100)
        row = {k: parent[k] for k in ('group_key', 'unified_code', 'unlock_date', 'reason_code')}
        row.update(holder=text_value(r['T007'], 512, True), reason=text_value(r['T006'], 1024),
                   shares=canonical_number(shares(r['jjsl'], source=True)))
        fact = digest([row[k] for k in ('group_key', 'holder', 'reason', 'shares')])
        seen[fact] += 1
        row['occurrence'] = seen[fact]
        row['record_key'] = fact_key(row, True)
        output.append(row)
    return sorted(output, key=lambda r: r['record_key'])


