"""Validated complete 10000-plan lists, including quick-report comparison joins."""
import json
from collections import Counter
from datetime import datetime

from empire.features.performance.contract import (
    CAPACITY,
    SOURCE_COLUMNS,
    day,
    identity,
    source_row,
    validate_rows,
)
from empire.features.performance.contract import (
    UNIT_KINDS as KINDS,
)

PAGE = 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_cbjd_cbjd.html'
CHANGES_PAGE = 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_cgbd_cgbd.html'
BASE = 'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.'


def entry(kind):
    if kind == 'shareholder_changes':
        return 'tdxsj_cgbd_zygdcgbd'
    return 'tdxsj_cbjd_' + ('yjpl' if kind == 'earnings_disclosure' else KINDS[kind][2])


def params(kind, period=None, security=''):
    if kind == 'shareholder_changes':
        day(period)
        if period[8:] != '01':
            raise ValueError('持股变动数据日期须为月份第一天')
        return ['0', 'asc', period[:7].replace('-', ''), '', '1', '1', str(CAPACITY)]
    if kind == 'holder_count':
        return ['0', security[:6], '1', '1', str(CAPACITY)]
    values = ['0', day(period), '', '1', '1', str(CAPACITY)]
    return values[1:] if kind == 'earnings_quick' else values


def result_sets(body, columns):
    if not isinstance(body, dict) or type(body.get('ErrorCode')) is not int or body['ErrorCode'] != 0:
        raise ValueError('通达信财报解读请求失败')
    values = body.get('ResultSets')
    if not isinstance(values, list) or len(values) != len(columns):
        raise ValueError('通达信财报解读完整结果集缺失')
    output = []
    for result, expected in zip(values, columns, strict=True):
        rows = result.get('Content')
        if (result.get('ColName') != expected or not isinstance(rows, list)
                or type(result.get('Count')) is not int or result['Count'] != len(rows)
                or any(not isinstance(r, list) or len(r) != len(expected) for r in rows)):
            raise ValueError('通达信财报解读列结构或计数不符')
        output.append(rows)
    return output


def parse_directory(kind, body):
    label = KINDS[kind][2]
    rows, metadata = result_sets(body, [['bgq', 'rq'] if kind == 'earnings_forecast' else ['bgq'],
                                      ['stype', 'param1']])
    if metadata != [[label, '']] or not 1 <= len(rows) <= 100:
        raise ValueError('报告期目录身份或范围无效')
    dates = [day(row[0]) for row in rows]
    if dates != sorted(set(dates), reverse=True):
        raise ValueError('报告期目录重复或乱序')
    for row in rows:
        if len(row) == 2:
            day(row[1])
    return dates


def parse(kind, body, period=None, security=''):
    if kind == 'shareholder_changes':
        return parse_changes(body, period)
    meta_columns = (['stype', 'bgq', 'page'] if kind == 'earnings_forecast' else
                    ['sbgq', 'page'] if kind == 'earnings_quick' else
                    ['page', 'nflag'] if kind == 'holder_count' else ['sbgq', 'page', 'nflag'])
    raw, metadata, counts = result_sets(body, [SOURCE_COLUMNS[kind], meta_columns, ['count']])
    expected = ([['0', period, 1]] if kind == 'earnings_forecast' else
                [[period, 1]] if kind == 'earnings_quick' else
                [[1, 0]] if kind == 'holder_count' else [[period, 1, 0]])
    if metadata != expected or len(counts) != 1 or type(counts[0][0]) is not int or counts[0][0] < 0:
        raise ValueError('通达信分页、报告期或总数无效')
    total = counts[0][0]
    if total >= CAPACITY or len(raw) > (80000 if kind == 'earnings_quick' else CAPACITY - 1):
        raise ValueError('来源10000容量边界无法证明完整，禁止偏移分页凑数')
    records = [dict(zip(SOURCE_COLUMNS[kind], row, strict=True)) for row in raw]
    actual = len({r['T001'] for r in records}) if kind == 'earnings_quick' else len(records)
    if actual != total:
        raise ValueError('来源方案集合与独立总数不符')
    rows = sorted([source_row(kind, row) for row in records], key=lambda r: identity(kind, r))
    if len({identity(kind, row) for row in rows}) != len(rows):
        raise ValueError('重复业务键，不能用去重掩盖遗漏')
    if kind == 'holder_count':
        if security:
            validate_rows(kind, security, rows)
        elif len({r['unified_code'] for r in rows}) != total:
            raise ValueError('最新股东户数证券目录重复')
    else:
        for market in ('SH', 'SZ', 'BJ'):
            validate_rows(kind, period + '|' + market, [r for r in rows if r['unified_code'].endswith(market)])
    return rows, total


def request_body(kind, period=None, security=''):
    return json.dumps({'Params': params(kind, period, security)}, separators=(',', ':')).encode()


def parse_changes(body, period):
    day(period)
    raw, metadata, counts = result_sets(body, [SOURCE_COLUMNS['shareholder_changes'],
        ['nflag', 'stype', 'page'], ['count']])
    if metadata != [[0, 'asc', 1]] or len(counts) != 1 or type(counts[0][0]) is not int:
        raise ValueError('持股变动分页或来源总数无效')
    total = counts[0][0]
    if total != len(raw) or not 0 <= total < CAPACITY:
        raise ValueError('持股变动完整月份被截断或来源总数不符')
    rows, occurrences = [], Counter()
    from empire.features.performance.contract import columns, digest
    for values in raw:
        record = dict(zip(SOURCE_COLUMNS['shareholder_changes'], values, strict=True))
        for field in ('T003', 'T004', 'T013'):
            value = record[field]
            if value is not None:
                if field == 'T013' and type(value) is int and 190001 <= value <= 220012:
                    record[field] = datetime.strptime(str(value), '%Y%m').strftime('%Y-%m')
                    continue
                if type(value) is not int or not 19000101 <= value <= 22001231:
                    raise ValueError('持股变动日期协议无效')
                record[field] = datetime.strptime(str(value), '%Y%m%d').date().isoformat()
        row = source_row('shareholder_changes', {**record, 'month': period, 'occurrence': 1})
        fact = digest([row[k] for k in columns('shareholder_changes') if k not in ('name', 'occurrence')])
        occurrences[fact] += 1
        rows.append({**row, 'occurrence': occurrences[fact]})
    rows.sort(key=lambda r: identity('shareholder_changes', r))
    for market in ('SH', 'SZ', 'BJ'):
        validate_rows('shareholder_changes', period + '|' + market,
            [r for r in rows if r['unified_code'].endswith(market)])
    return rows, total
