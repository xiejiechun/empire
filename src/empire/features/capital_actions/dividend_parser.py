"""Public pure dividend parser extracted without business-rule changes."""
from datetime import date, datetime, timedelta

from empire.core.time import CHINA
from empire.features.capital_actions.contract import DIVIDEND_COLUMNS, ordered, source_row
from empire.features.capital_actions.fields import TdxSourceError

COLUMNS = ['T001', 'code', 'name', 'sc', 'aT013', 'aT014', 'szzs', 'aT015',
           'dT006', 'dT010', 'dT012', 'dT009', 'ygrq', 'gqdjr', 'cqcxr', 'fajd']


CAPACITY = 10000


def period_plan(latest, historical=()):
    today = datetime.now(CHINA).date().isoformat()
    known = set(historical)
    for value in known:
        if date.fromisoformat(value).isoformat() != value or not '1980-01-01' <= value <= today:
            raise ValueError('已有分红报告期超出支持范围，不能跳过历史')
    latest_day = date.fromisoformat(max({latest, *known}))
    if not '1980-01-01' <= latest <= today:
        raise ValueError('分红最新报告期超出支持范围')
    periods = {date(year, month, day).isoformat()
               for year in range(1980, latest_day.year + 1)
               for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))
               if date(year, month, day) <= latest_day}
    periods.update(known)
    # The website's selector can lag the latest non-quarter corporate actions.
    # Scan only the open interval after its newest quarter, not all historical days.
    day = date.fromisoformat(latest) + timedelta(days=1)
    while day.isoformat() <= today:
        periods.add(day.isoformat())
        day += timedelta(days=1)
    if not periods or len(periods) > 1000:
        raise ValueError('分红报告期计划为空或超过1000期')
    return sorted(periods)


def parse_period(body, period, capacity=CAPACITY):
    if isinstance(body, dict) and type(body.get('ErrorCode')) is int and body['ErrorCode'] != 0:
        raise TdxSourceError(body['ErrorCode'], '通达信分红列表')
    if not isinstance(body, dict) or type(body.get('ErrorCode')) is not int or body['ErrorCode'] != 0:
        raise ValueError('分红报告期响应无效')
    if date.fromisoformat(period).isoformat() != period or period < '1980-01-01':
        raise ValueError('分红报告期无效')
    sets = body.get('ResultSets')
    if not isinstance(sets, list) or len(sets) not in (2, 3):
        raise ValueError('分红列表结果集缺失')
    expected = [COLUMNS, ['page', 'nzt', 'nflag', 'strjzr'], ['count']]
    contents = []
    for result, columns in zip(sets, expected):
        if not isinstance(result, dict):
            raise ValueError('分红列表结果集结构无效')
        values = result.get('Content')
        if (result.get('ColName') != columns or not isinstance(values, list)
                or type(result.get('Count')) is not int or result['Count'] != len(values)
                or any(not isinstance(row, list) or len(row) != len(columns) for row in values)):
            raise ValueError('分红列表列结构或结果条数不符')
        contents.append(values)
    raw, metadata = contents[:2]
    if metadata != [[1, 0, 0, period]]:
        raise ValueError('分红列表报告期、筛选或页码不符')
    if len(raw) >= capacity:
        raise ValueError('分红完整报告期响应达到容量，禁止截断或偏移补凑')
    rows = []
    # The list response contains all securities for the requested period, not a
    # single-security object whose count happens to be one.
    for values in raw:
        row = dict(zip(COLUMNS, values, strict=True))
        if type(row['sc']) is not int or row['sc'] not in (0, 1, 2):
            raise ValueError('分红列表证券市场无效')
        if not isinstance(row['T001'], str) or not 1 <= len(row['T001']) <= 100:
            raise ValueError('分红来源证券身份无效')
        source = {'fhbgq': period, **{k: row[k] for k in ('szzs', 'ygrq', 'gqdjr', 'cqcxr', 'fajd')}}
        source.update({k: row['a' + k] for k in ('T013', 'T014', 'T015')})
        source.update({k: row['d' + k] for k in ('T006', 'T010', 'T012', 'T009')})
        assert set(source) == set(DIVIDEND_COLUMNS)
        stock = dict(market={0: 'SZ', 1: 'SH', 2: 'BJ'}[row['sc']], code=row['code'], name=row['name'])
        rows.append(source_row('dividends', source, stock))
    if len({row['record_key'] for row in rows}) != len(rows):
        raise ValueError('分红报告期业务键重复，不能以去重凑齐')
    if len(contents) == 3 and (contents[2] != [[len(raw)]] or type(contents[2][0][0]) is not int):
        raise ValueError('分红报告期来源总数不符')
    return ordered(rows), len(raw)


def parse_directory(body, stock):
    from empire.features.capital_actions.source_protocol import result_set
    values = result_set(body, 0, DIVIDEND_COLUMNS)
    metadata = result_set(body, 1, ['page', 'nzt', 'nflag', 'strjzr'])
    total = result_set(body, 2, ['count'])
    if metadata != [[1, 1, 1, '1']] or total != [[1]] or len(values) > 2000:
        raise ValueError('分红历史目录证券对象或完整响应无效')
    rows = ordered([source_row('dividends', dict(zip(DIVIDEND_COLUMNS, row, strict=True)), stock)
                    for row in values])
    if len({row['record_key'] for row in rows}) != len(rows):
        raise ValueError('分红历史目录业务键重复')
    return {row['data']['report_date'] for row in rows}, {row['record_key'] for row in rows}
