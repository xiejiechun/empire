"""Current-security request scope: listing metadata, not a second quotation source."""
import json
from datetime import date, datetime

from empire.core.time import CHINA
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import wait_for_capacity

LISTING_URL = 'https://datacenter.eastmoney.com/api/data/v1/get'
LISTING_COLUMNS = 'SECUCODE,SECURITY_CODE,LISTING_DATE,LISTING_STATE'
BSE_OPEN = date(2021, 11, 15)


def parse_listing_page(payload, page):
    if not isinstance(payload, dict) or payload.get('success') is not True:
        raise ValueError('当前证券上市日期目录请求未成功')
    result = payload.get('result')
    if (not isinstance(result, dict) or type(result.get('count')) is not int
            or not 1 <= result['count'] <= 30000 or type(result.get('pages')) is not int
            or result['pages'] != (result['count'] + 499) // 500):
        raise ValueError('上市日期目录分页数量无效')
    rows = result.get('data')
    expected = min(500, result['count'] - (page - 1) * 500)
    if not isinstance(rows, list) or len(rows) != expected or expected <= 0:
        raise ValueError('上市日期目录缺页或尾页不完整')
    clean = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(LISTING_COLUMNS.split(',')):
            raise ValueError('上市日期目录字段变更')
        symbol, code = row['SECUCODE'], row['SECURITY_CODE']
        if (not isinstance(symbol, str) or not isinstance(code, str) or not code.isdigit()
                or len(code) != 6 or symbol[:6] != code or row['LISTING_STATE'] != '0'):
            raise ValueError('上市日期证券身份或当前上市状态无效')
        listed = datetime.strptime(row['LISTING_DATE'], '%Y-%m-%d %H:%M:%S').date()
        if not date(1990, 1, 1) <= listed <= datetime.now(CHINA).date():
            raise ValueError('上市日期不可信')
        clean.append((symbol, listed))
    return result['count'], result['pages'], clean


async def download_listing_page(collector, page, *, reservation=None):
    await wait_for_capacity(collector.ingest, collector.stats)
    response = await collector.http.request('GET', LISTING_URL, allowed_domains=('eastmoney.com',),
        project_id=collector.project_id, policy=collector.http.response_policy('generic'),
        reservation=reservation, max_retries=collector.request_retries,
        params=dict(reportName='RPT_F10_ORG_BASICINFO', columns=LISTING_COLUMNS,
            filter='(LISTING_STATE="0")(SECURITY_TYPE_CODE="058001001")',
            pageSize='500', pageNumber=str(page), sortColumns='SECUCODE', sortTypes='1'))

    async def consume():
        return parse_listing_page(json.loads(response.content), page)

    return DeferredResponse(response, consume)


async def attach_listing_dates(collector, stocks):
    listings, previous = {}, ''
    first = await download_listing_page(collector, 1)
    try:
        total, pages, rows = await first.consume()
    finally:
        first.close()

    def append(values):
        nonlocal previous
        for symbol, listed in values:
            if symbol <= previous or symbol in listings:
                raise ValueError('上市日期目录存在重复、重排或同条数不同证券集合')
            previous = symbol
            listings[symbol] = listed

    append(rows)
    async def download(page, *, reservation):
        return await download_listing_page(collector, page, reservation=reservation)
    async with prefetch_units(collector, list(range(2, pages + 1)), download,
            url=LISTING_URL, domains=('eastmoney.com',), item_name='目录页') as reads:
        async for _, read in reads:
            count, reported_pages, rows = await read.resolve()
            if count != total or reported_pages != pages:
                raise ValueError('上市日期目录分页总数改变，保留断点')
            append(rows)
    if len(listings) != total:
        raise ValueError('上市日期目录集合不完整')
    result = []
    for stock in stocks:
        symbol = stock['code'] + '.' + stock['market']
        if symbol not in listings:
            raise ValueError(f'当前证券 {symbol} 缺少明确上市日期；不推断上市前空白')
        result.append({**stock, 'listing_date': listings[symbol].isoformat()})
    return result


def lifecycle(stock):
    return dict(listing_date=stock['listing_date'], listing_source='eastmoney',
                market_start=BSE_OPEN.isoformat() if stock['market'] == 'BJ' else stock['listing_date'])


def required_days(stock, calendar, excluded):
    start = max(date.fromisoformat(stock['listing_date']),
                BSE_OPEN if stock['market'] == 'BJ' else date(2021, 1, 1))
    return [day for day in calendar if day >= start and day not in excluded]
