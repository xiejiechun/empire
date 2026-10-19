"""Complete report-period responses assembled into existing full-security units."""
import json
from datetime import UTC, date, datetime

from empire.features.capital_actions.contract import digest, ordered, unit_key
from empire.features.capital_actions.dividend_parser import period_plan
from empire.plugins.collection.unit_prefetch import prefetch_units

MAX_ROWS = 100000
MAX_BYTES = 128 * 1024**2






async def report_periods(c, discovered=()):
    from empire.features.capital_actions.source_protocol import PAGE_URL
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
    from empire.features.capital_actions.source import complete_response
    from empire.features.capital_actions.source_protocol import PAGE_URL
    stocks = {unit_key(stock): stock for stock in await c.query.securities()}
    observed = datetime.now(UTC)
    marks = await c.query.dividend_history_proofs()
    unproven = {key: stock for key, stock in stocks.items() if force_history or key not in marks}
    discovered, required = set(), {}
    if unproven:
        from empire.features.capital_actions.dividend_discovery import discover
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
        from empire.features.capital_actions.contract import validate_rows
        validate_rows('dividends', key, units[key])
        if key in required and not required[key].issubset(row['record_key'] for row in units[key]):
            raise ValueError('分红报告期列表未覆盖历史目录方案，禁止发布不完整证券')
    return units, observed, digest([periods, stocks, units])
