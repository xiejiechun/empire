"""One bounded complete calendar response per date, never offset-page merging."""
import json

from empire.contracts.listing_status import MAX_DAY, SOURCE_TYPES, identity, validate_rows
from empire.contracts.security import unified_code

API_URL = 'http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_tzrl_gsrl'
PAGE_URL = 'http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_tzrl_tzrl.html'


def request_body(day):
    return json.dumps({'Params': ['mrtbts', 'zthfss', day, '1', '1', str(MAX_DAY)]},
                      separators=(',', ':')).encode()


def parse(body, day):
    from datetime import date

    parsed_day = date.fromisoformat(day)
    if not isinstance(body, dict) or type(body.get('ErrorCode')) is not int or body['ErrorCode'] != 0:
        raise ValueError('上市状态来源请求失败')
    sets = body.get('ResultSets')
    columns = [['sc', 'code', 'name', 'sjcontent', 'sj'], ['page', 'sflag', 'sdate', 'stype'], ['count']]
    if not isinstance(sets, list) or len(sets) != 3:
        raise ValueError('上市状态结果集缺失')
    for item, cols in zip(sets, columns, strict=True):
        if (not isinstance(item, dict) or item.get('ColName') != cols
                or not isinstance(item.get('Content'), list)
                or type(item.get('Count')) is not int or item['Count'] != len(item['Content'])):
            raise ValueError('上市状态来源列或条数无效')
    if sets[1]['Content'] != [[1, 'mrtbts', day, 'zthfss']]:
        raise ValueError('上市状态日期、栏目或页码不符')
    totals = sets[2]['Content']
    if (len(totals) != 1 or not isinstance(totals[0], list) or len(totals[0]) != 1
            or type(totals[0][0]) is not int or not 0 <= totals[0][0] < MAX_DAY):
        raise ValueError('上市状态来源总数无效或达到完整响应上限')
    values, rows = sets[0]['Content'], []
    if len(values) >= MAX_DAY:
        raise ValueError('上市状态达到响应边界，拒绝不完整集合')
    if len(values) != totals[0][0]:
        raise ValueError('上市状态完整来源集合与来源总数不一致')
    for values_row in values:
        if not isinstance(values_row, list) or len(values_row) != 5:
            raise ValueError('上市状态来源行字段不符')
        sc, code, name, description, label = values_row
        market = {0: 'SZ', 1: 'SH', 2: 'BJ'}.get(sc) if type(sc) is int else None
        if market is None or not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ValueError('上市状态来源证券身份无效')
        if not ((market == 'SZ' and code.startswith(('0', '3'))) or (market == 'SH' and code.startswith('6'))):
            continue
        if not isinstance(label, str) or label not in SOURCE_TYPES:
            raise ValueError('上市状态来源出现未知事件类型')
        row = [day, unified_code(market, code), SOURCE_TYPES[label], '', name, description]
        row[3] = identity(row)
        rows.append(row)
    return validate_rows(rows, parsed_day, parsed_day), len(rows)
