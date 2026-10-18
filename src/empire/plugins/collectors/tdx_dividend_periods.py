"""Complete report-period responses assembled into existing full-security units."""
import json
from datetime import UTC, date, datetime, timedelta

from empire.core.time import CHINA
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.datasets.capital_actions import (
    DIVIDEND_COLUMNS,
    TdxSourceError,
    digest,
    ordered,
    source_row,
    unit_key,
)

COLUMNS = ['T001', 'code', 'name', 'sc', 'aT013', 'aT014', 'szzs', 'aT015',
           'dT006', 'dT010', 'dT012', 'dT009', 'ygrq', 'gqdjr', 'cqcxr', 'fajd']
CAPACITY = 10000
MAX_ROWS = 100000
MAX_BYTES = 128 * 1024**2


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


async def report_periods(c, discovered=()):
    from empire.plugins.collectors.tdx_capital_source import PAGE_URL
    response = await c.http.request('POST',
        'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_zfsp_cache',
        content=json.dumps({'Params': ['fhszdate', '', '', '']}).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'Referer': PAGE_URL},
        allowed_domains=('tdx.com.cn',), project_id=c.project_id,
        policy=c.http.response_policy('generic'), max_retries=c.request_retries)
    try:
        body = response.json()
        if body.get('ErrorCode') != 0 or len(body.get('ResultSets', [])) != 1:
            raise ValueError('分红报告期目录响应无效')
        result = body['ResultSets'][0]
        values = result.get('Content')
        if (result.get('ColName') != ['T002', 'maxrq'] or not isinstance(values, list)
                or not values or result.get('Count') != len(values) or len(values) > 500
                or any(not isinstance(row, list) or len(row) != 2 for row in values)):
            raise ValueError('分红报告期目录结构无效')
        dates = [date.fromisoformat(row[0]).isoformat() for row in values]
        # maxrq is the website's default selected period, which can lag its
        # newest selectable quarter. It is not a maximum over T002.
        selected = {row[1] for row in values}
        if len(set(dates)) != len(dates) or len(selected) != 1 or not selected <= set(dates):
            raise ValueError('分红目录最新期或唯一集合不符')
        return period_plan(next(iter(selected)), set(dates) | set(await c.query.dividend_report_dates()) | set(discovered))
    finally:
        response.close()


async def collect_history(c, *, force_history=False):
    from empire.plugins.collectors.tdx_capital_source import PAGE_URL, complete_response
    stocks = {unit_key(stock): stock for stock in await c.query.securities()}
    observed = datetime.now(UTC)
    marks = await c.query.dividend_history_proofs()
    unproven = {key: stock for key, stock in stocks.items() if force_history or key not in marks}
    discovered, required = set(), {}
    if unproven:
        from empire.plugins.collectors.tdx_dividend_discovery import discover
        discovered, required = await discover(c, unproven)
        marks.update({key: observed.isoformat(timespec='microseconds') for key in unproven})
    c.history_discoveries = marks
    c.stats['history_discovery_securities'] = len(unproven)
    periods = await report_periods(c, discovered)
    units = {key: [] for key in stocks}
    size, count = 0, 0
    async def download(period, *, reservation):
        return await complete_response(c, 'dividends', period, reservation=reservation, defer=True)
    c.stats.update(total_report_periods=len(periods), downloaded_report_periods=0)
    async with prefetch_units(c, periods, download, url=PAGE_URL, domains=('tdx.com.cn',), item_name='报告期') as reads:
        async for index, read in reads:
            rows, _ = await read.resolve()
            size += len(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode())
            count += len(rows)
            if count > MAX_ROWS or size > MAX_BYTES:
                raise ValueError('分红历史完整集合超过100000条或128MiB规范内容预算')
            for row in rows:
                key = unit_key(row)
                if key in units:
                    row['name'] = stocks[key]['name']  # Same SQL stock-pool identity as the former detail path.
                    units[key].append(row)
            c.stats.update(downloaded_report_periods=index + 1, current_report_period=periods[index])
    for key in units:
        units[key] = ordered(units[key])
        from empire.plugins.datasets.capital_actions import validate_rows
        validate_rows('dividends', key, units[key])
        if key in required and not required[key].issubset(row['record_key'] for row in units[key]):
            raise ValueError('分红报告期列表未覆盖历史目录方案，禁止发布不完整证券')
    return units, observed, digest([periods, stocks, units])
