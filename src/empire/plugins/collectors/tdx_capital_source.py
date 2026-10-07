"""TDX-specific complete-response verification; transport remains the shared downloader."""
import hashlib
import json
from datetime import UTC, datetime

from empire.contracts.collection_integrity import require_complete_set
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.collectors.support import record_error_safely, wait_for_capacity
from empire.plugins.datasets.capital_actions import (
    DIVIDEND_COLUMNS,
    ISSUE_COLUMNS,
    RIGHTS_COLUMNS,
    TdxSourceError,
    digest,
    ordered,
    source_row,
)

PAGE_URL = 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_zfsp_zfsp.html'
DETAIL_URL = 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_zfsp_zfspmx.html'
ENTRIES = {'dividends': 'tdxsj_zfsp_zfsp', 'additional_issues': 'tdxsj_xgzx_zf',
           'rights_issues': 'tdxsj_xgzx_pg'}


def result_set(body, index, columns):
    if isinstance(body, dict) and type(body.get('ErrorCode')) is int and body['ErrorCode'] != 0:
        raise TdxSourceError(body['ErrorCode'], '通达信增发送配')
    if not isinstance(body, dict) or body.get('ErrorCode') != 0:
        raise ValueError('通达信增发送配请求失败')
    sets = body.get('ResultSets')
    if not isinstance(sets, list) or len(sets) != 3:
        raise ValueError('通达信增发送配结果集缺失')
    value = sets[index]
    if not isinstance(value, dict) or value.get('ColName') != columns or not isinstance(value.get('Content'), list):
        raise ValueError('通达信增发送配列结构不匹配')
    rows = value['Content']
    if type(value.get('Count')) is not int or value['Count'] != len(rows):
        raise ValueError('通达信增发送配结果条数不符')
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError('通达信增发送配行结构无效')
    return rows


def parse(kind, body, capacity, stock=None):
    columns = {'dividends': DIVIDEND_COLUMNS, 'additional_issues': ISSUE_COLUMNS,
               'rights_issues': RIGHTS_COLUMNS}[kind]
    values = result_set(body, 0, columns)
    total = result_set(body, 2, ['count'])
    if len(total) != 1 or type(total[0][0]) is not int or total[0][0] < 0:
        raise ValueError('来源总数无效')
    total = total[0][0]
    if kind == 'dividends':
        metadata = result_set(body, 1, ['page', 'nzt', 'nflag', 'strjzr'])
        if metadata != [[1, 1, 1, '1']] or total != 1 or len(values) > 2000:
            raise ValueError('分红详情查询对象/结构无效')
    else:
        columns_meta = ['ntype', 'page', 'cur'] if kind == 'additional_issues' else ['page', 'cur']
        metadata = result_set(body, 1, columns_meta)
        if len(metadata) != 1 or metadata[0][:-1] != ([0, 1] if kind == 'additional_issues' else [1]):
            raise ValueError('来源分页或栏目不匹配')
        from empire.plugins.datasets.capital_actions import day
        day(metadata[0][-1], True)
        if len(values) >= capacity or total > len(values):
            raise ValueError('完整响应被截断或来源总数不符；禁止偏移分页补凑')
    raw = [dict(zip(columns, value, strict=True)) for value in values]
    rows = ordered([source_row(kind, value, stock) for value in raw])
    require_complete_set(rows, len(rows), lambda row: row['record_key'])
    if kind == 'additional_issues':
        # A source issue can be joined to multiple historical security codes.
        groups = {}
        for row in rows:
            ident, data = row['data']['source_id'], row['data']
            if ident in groups and groups[ident] != data:
                raise ValueError('同一增发编号出现冲突业务内容')
            groups[ident] = data
        if len(groups) != total:
            raise ValueError('增发方案编号集合与来源总数不符')
    elif kind == 'rights_issues':
        # Count is source plans before the security-code alias join. Keep ALL aliases.
        if len({digest(row['data']) for row in rows}) != total:
            raise ValueError('配股方案与代码关联总数口径不符')
    return rows, total


async def complete_response(collector, kind, stock=None, *, reservation=None, defer=False):
    started = datetime.now(UTC)
    capacity = 1 if kind == 'dividends' else 10000
    await wait_for_capacity(collector.ingest, collector.stats)
    params = (['1', '1', '1', '', stock['code'], '1', '1', '1'] if kind == 'dividends'
              else ['0', '', '1', '1', str(capacity)] if kind == 'additional_issues'
              else ['', '1', '1', str(capacity)])
    response = await collector.http.request('POST',
        'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.' + ENTRIES[kind],
        content=json.dumps({'Params': params}, separators=(',', ':')).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                 'Origin': 'http://page2.tdx.com.cn:7615', 'Referer': PAGE_URL},
        allowed_domains=('tdx.com.cn',), project_id=collector.project_id,
        policy=collector.http.response_policy('generic'), max_retries=collector.request_retries,
        reservation=reservation)
    async def consume():
        try:
            rows, _ = parse(kind, response.json(), capacity, stock)
        except (ValueError, TypeError, KeyError) as exc:
            content = response.content
            exc.diagnostic_recorded = await record_error_safely(
                collector.records, collector.stats, collector.project_id, exc,
                stage='source_validation', unavailable_message='错误样本暂未写入 Redis',
                fields=dict(request_url='http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.' + ENTRIES[kind],
                    status_code=response.status_code, raw_body=content[:65536],
                    observed_bytes=len(content), body_sha256=hashlib.sha256(content).hexdigest(),
                    metadata={'kind': kind, 'security': stock, 'capacity': capacity}))
            raise
        finally:
            if not defer:
                response.close()
        return rows, started

    if defer:
        return DeferredResponse(response, consume)
    return await consume()
