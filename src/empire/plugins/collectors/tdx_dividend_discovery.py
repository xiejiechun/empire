"""Discover otherwise unenumerable non-quarter report dates for unproven securities."""
import hashlib
import json

from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import record_error_safely
from empire.plugins.datasets.capital_actions import DIVIDEND_COLUMNS, ordered, source_row


def parse_directory(body, stock):
    from empire.plugins.collectors.tdx_capital_source import result_set
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


async def discover(c, stocks):
    from empire.plugins.collectors.tdx_capital_source import PAGE_URL
    async def download(key, *, reservation):
        response = await c.http.request('POST',
            'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_zfsp_zfsp',
            content=json.dumps({'Params': ['1', '1', '1', '', stocks[key]['code'], '1', '1', '1']}).encode(),
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'Referer': PAGE_URL},
            allowed_domains=('tdx.com.cn',), project_id=c.project_id,
            policy=c.http.response_policy('generic'), max_retries=c.request_retries, reservation=reservation)
        async def consume():
            try:
                return parse_directory(response.json(), stocks[key])
            except (ValueError, TypeError, KeyError) as exc:
                content = response.content
                exc.diagnostic_recorded = await record_error_safely(
                    c.records, c.stats, c.project_id, exc, stage='source_validation',
                    unavailable_message='错误样本暂未写入 Redis',
                    fields=dict(request_url='http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_zfsp_zfsp',
                        status_code=response.status_code, raw_body=content[:65536],
                        observed_bytes=len(content), body_sha256=hashlib.sha256(content).hexdigest(),
                        metadata={'kind': 'dividends', 'history_discovery_unit': key}))
                raise
        return DeferredResponse(response, consume)
    dates, keys, count = set(), {}, 0
    securities = sorted(stocks)
    async with prefetch_units(c, securities, download, url=PAGE_URL,
                              domains=('tdx.com.cn',), item_name='历史日期发现') as reads:
        async for index, read in reads:
            periods, identities = await read.resolve()
            count += len(identities)
            if count > 100000 or len(dates | periods) > 1000:
                raise ValueError('分红历史目录集合超过100000方案或1000期')
            dates.update(periods)
            keys[securities[index]] = identities
    return dates, keys
