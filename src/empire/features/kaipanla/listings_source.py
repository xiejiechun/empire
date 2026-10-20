"""Current-security request scope: listing metadata, not a second quotation source."""
import json
from datetime import date, datetime, timedelta

from empire.contracts.security import split_unified_code
from empire.core.time import CHINA
from empire.features.listings.contract import LISTING_LOOKAHEAD_DAYS
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import wait_for_capacity

LISTING_URL = 'https://datacenter.eastmoney.com/api/data/v1/get'


LISTING_COLUMNS = 'SECUCODE,SECURITY_CODE,LISTING_DATE,LISTING_STATE'


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
                or len(code) != 6 or symbol[:6] != code or row['LISTING_STATE'] not in ('0', '9')):
            raise ValueError('上市日期证券身份或当前上市状态无效')
        split_unified_code(symbol)
        if row['LISTING_STATE'] == '9' and row['LISTING_DATE'] is None:
            # State 9 explicitly proves that trading has not begun. Preserve the
            # unknown announcement date; do not manufacture a historical start.
            clean.append((symbol, None))
            continue
        if not isinstance(row['LISTING_DATE'], str):
            raise ValueError('上市日期缺失或格式无效')
        listed = datetime.strptime(row['LISTING_DATE'], '%Y-%m-%d %H:%M:%S').date()
        today = datetime.now(CHINA).date()
        if (row['LISTING_STATE'] == '0' and not date(1990, 1, 1) <= listed <= today
                or row['LISTING_STATE'] == '9' and not today <= listed <= today + timedelta(days=LISTING_LOOKAHEAD_DAYS)):
            raise ValueError('上市日期不可信')
        clean.append((symbol, listed))
    return result['count'], result['pages'], clean


async def download_listing_page(collector, page, *, reservation=None, supplemental_symbol=None):
    await wait_for_capacity(collector.ingest, collector.stats)
    response = await collector.http.request('GET', LISTING_URL, allowed_domains=('eastmoney.com',),
        project_id=collector.project_id, policy=collector.http.response_policy('generic'),
        reservation=reservation, max_retries=collector.request_retries,
        params=dict(reportName='RPT_F10_ORG_BASICINFO', columns=LISTING_COLUMNS,
            filter=(f'(SECUCODE="{supplemental_symbol}")' if supplemental_symbol
                    else '(LISTING_STATE="0")(SECURITY_TYPE_CODE="058001001")'),
            pageSize='500', pageNumber=str(page), sortColumns='SECUCODE', sortTypes='1'))

    async def consume():
        payload = json.loads(response.content)
        parsed = parse_listing_page(payload, page)
        if not supplemental_symbol and any(row['LISTING_STATE'] != '0' for row in payload['result']['data']):
            raise ValueError('已上市目录返回了其他状态')
        if supplemental_symbol and (parsed[:2] != (1, 1) or len(parsed[2]) != 1
                or parsed[2][0][0] != supplemental_symbol):
            raise ValueError('补充上市资料缺少精确身份及来源状态证明')
        return parsed

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
    missing = [s['code'] + '.' + s['market'] for s in stocks
               if s['code'] + '.' + s['market'] not in listings]
    # Only a current-pool mismatch needs one extra identity-specific source response.
    # Never infer a listing date or treat an absent security as an empty history.
    for symbol in missing:
        split_unified_code(symbol)
    async def supplement(symbol, *, reservation):
        return await download_listing_page(collector, 1, reservation=reservation, supplemental_symbol=symbol)
    async with prefetch_units(collector, missing, supplement,
            url=LISTING_URL, domains=('eastmoney.com',), item_name='补充证券') as reads:
        async for _, read in reads:
            _, _, rows = await read.resolve()
            listings.update(rows)
    result = []
    collector.stats['unlisted_without_date'] = sum(value is None for value in listings.values())
    for stock in stocks:
        symbol = stock['code'] + '.' + stock['market']
        if symbol not in listings:
            raise ValueError(f'当前证券 {symbol} 缺少明确上市日期；不推断上市前空白')
        if listings[symbol] is None:
            continue
        result.append({**stock, 'listing_date': listings[symbol].isoformat()})
    return result
