"""One complete response per name category, before any queue checkpoint moves."""
import json
from collections import Counter
from datetime import date

from empire.contracts.name_changes import CAPACITY, KINDS, MARKETS, identity, validate_rows
from empire.contracts.security import unified_code

PAGE = 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_bfzl_bfzl.html'
URL = 'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_bfzl_bfzl'
COLUMN_SETS = {
    'company': ['code', 'lastname', 'prename', 'rq', 'sc', 'name', 'zjhhy', 'tdxhy'],
    'security': ['rq', 'lastname', 'code', 'prename', 'name', 'sc', 'zjhhy', 'tdxhy', 'zqlx'],
}


def parse(kind, body, through):
    if not isinstance(body, dict) or type(body.get('ErrorCode')) is not int or body['ErrorCode'] != 0:
        raise ValueError('通达信更名请求失败')
    sets = body.get('ResultSets')
    if not isinstance(sets, list) or len(sets) != 3:
        raise ValueError('通达信更名结果集缺失')
    contents = []
    for result, columns in zip(sets, [COLUMN_SETS[kind], ['page'], ['count']], strict=True):
        rows = result.get('Content')
        if (result.get('ColName') != columns or not isinstance(rows, list)
                or type(result.get('Count')) is not int or result['Count'] != len(rows)
                or any(not isinstance(r, list) or len(r) != len(columns) for r in rows)):
            raise ValueError('通达信更名列结构或结果计数不符')
        contents.append(rows)
    raw, pages, counts = contents
    if pages != [[1]] or len(counts) != 1 or type(counts[0][0]) is not int:
        raise ValueError('通达信更名分页或来源计数无效')
    if counts[0][0] != len(raw) or len(raw) >= CAPACITY:
        raise ValueError('通达信更名完整响应被截断或总数不符')
    groups = {market: Counter() for market in MARKETS}
    labels = {}
    for values in raw:
        row = dict(zip(COLUMN_SETS[kind], values, strict=True))
        if type(row['sc']) is not int or row['sc'] not in (0, 1, 2):
            raise ValueError('通达信更名市场无效')
        market = {0: 'SZ', 1: 'SH', 2: 'BJ'}[row['sc']]
        code = unified_code(market, row['code'].strip() if isinstance(row['code'], str) else row['code'])
        if kind == 'security' and row['zqlx'] != 'A股':
            raise ValueError('股票更名返回非A股，不能静默过滤')
        rq = str(row['rq'])
        if len(rq) != 8 or not rq.isascii() or not rq.isdigit():
            raise ValueError('通达信更名日期结构无效')
        day = date.fromisoformat(rq[:4] + '-' + rq[4:6] + '-' + rq[6:]).isoformat()
        if not '1990-01-01' <= day <= through:
            raise ValueError('通达信更名日期超出请求范围')
        key = (code, day, row['prename'], row['lastname'])
        industry = tuple(None if row[k] in (None, '无') else row[k] for k in ('zjhhy', 'tdxhy'))
        if key in labels and labels[key] != industry:
            raise ValueError('相同更名事件的行业冲突，不能静默合并')
        labels[key] = industry
        groups[market][key] += 1
    result = {}
    for market, group in groups.items():
        rows = sorted([list(key) + [count] + list(labels[key]) for key, count in group.items()], key=identity)
        validate_rows(kind, market, rows)
        result[market] = rows
    return result, len(raw)


def request_body(kind, through):
    return json.dumps({'Params': [KINDS[kind][2], '19900101', through.replace('-', ''),
                                  '1', '1', str(CAPACITY)]}, separators=(',', ':')).encode()
