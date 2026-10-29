"""Fail-closed source parsing; empty transport results are not historical coverage."""
import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from empire.contracts.security import split_unified_code, unified_code
from empire.core.time import CHINA
from empire.features.yuanhang_limits.contract import (
    BOARD_MARKETS,
    DECIMAL_FIELDS,
    INTEGER_FIELDS,
    MARKETS,
    MAX_MEMBERS,
    PAGE_SIZE,
    TEXT_LIMITS,
    TIME_FIELDS,
    day_value,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def decimal_value(value, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f'{field}: 非数值')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'{field}: 非数值') from exc
    if not result.is_finite() or abs(result) >= Decimal('1e22'):
        raise ValueError(f'{field}: 数值超界')
    with localcontext() as context:
        context.prec = 64
        if result != result.quantize(Decimal('1e-24')):
            raise ValueError(f'{field}: 超出24位小数精度')
    if field not in ('change_rate', 'rise_rate') and result < 0:
        raise ValueError(f'{field}: 不允许负数')
    if field == 'limit_up_suc_rate' and result > 1:
        raise ValueError('涨停成功率须为0～1的来源比例')
    if not result:
        return '0'
    rendered = format(result, 'f')
    return rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered


def member(row, day, *, identities=None):
    day_value(day)
    required = {'code', 'market_id', *DECIMAL_FIELDS, *TIME_FIELDS,
                *INTEGER_FIELDS, *TEXT_LIMITS}
    if not isinstance(row, dict) or not required <= row.keys():
        raise ValueError('涨停分析缺少契约字段，NULL不能替代字段缺失')
    market_id = row['market_id']
    board = BOARD_MARKETS.get(row['market_type'])
    if type(market_id) is int and market_id in MARKETS:
        market, basis = MARKETS[market_id], 'market_id'
        if board is not None and board != market:
            raise ValueError('来源市场与板块身份冲突')
    elif market_id is None and board is not None:
        market, basis = board, 'source_board'
    elif market_id is None and row['market_type'] == 'HS' and (identities or {}).get(row['code']):
        identity = identities[row['code']]
        symbol, basis = identity if isinstance(identity, tuple) else (identity, 'pool_history')
        market, code = split_unified_code(symbol)
        if code != row['code'] or market not in ('SH', 'SZ', 'BJ'):
            raise ValueError('历史池证券身份证据不匹配')
        if basis not in ('pool_history', 'sina_lookup'):
            raise ValueError('未登记的辅助身份来源')
    else:
        raise ValueError('涨停分析返回未验证的市场身份')
    result = {'unified_code': unified_code(market, row['code']),
              'source_market_id': market_id, 'identity_basis': basis}
    for key in DECIMAL_FIELDS:
        result[key] = decimal_value(row[key], key)
    for key in INTEGER_FIELDS:
        value = row[key]
        if value is not None and (type(value) is not int or not 0 <= value <= 4294967295):
            raise ValueError(f'{key}：非法整数')
        if key in ('is_new', 'is_again_limit') and value not in (None, 0, 1):
            raise ValueError(f'{key}：未知标记')
        result[key] = value
    for key, limit in TEXT_LIMITS.items():
        value = row[key]
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError(f'{key}：文本类型或长度错误')
        result['top_concept' if key == '941948930' else key] = value
    if not result['name'] or not result['market_type']:
        raise ValueError('成员缺少名称或市场类别')
    for key in TIME_FIELDS:
        value = row[key]
        if value is not None:
            if not isinstance(value, str) or not value.isascii() or not value.isdigit():
                raise ValueError(f'{key}：非法来源秒时间')
            value = int(value)
            stamp = datetime.fromtimestamp(value, CHINA)
            if value != 0 and stamp.date().isoformat() != day:
                raise ValueError(f'{key}：来源时刻跨出查询交易日')
        result[key] = value
    return result


def response_data(obj):
    if not isinstance(obj, dict) or type(obj.get('status_code')) is not int or obj['status_code'] != 0:
        error = ValueError('远航涨停分析业务响应失败')
        error.source_metadata = {'business_status': obj.get('status_code') if isinstance(obj, dict) else None}
        raise error
    if not isinstance(obj.get('data'), dict):
        raise ValueError('远航涨停分析响应结构错误')
    return obj['data']


def parse_page(obj, day, page, *, identities=None):
    data = response_data(obj)
    meta, rows = data.get('page'), data.get('data')
    if not isinstance(meta, dict) or not isinstance(rows, list):
        raise ValueError('涨停分析缺少分页或成员数组')
    if any(type(meta.get(k)) is not int for k in ('total', 'limit', 'count', 'page')):
        raise ValueError('涨停分析分页字段类型错误')
    total = meta['total']
    if not 0 <= total <= MAX_MEMBERS or meta['limit'] != PAGE_SIZE:
        raise ValueError('涨停分析总量或页容量错误')
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if total == 0:
        if rows or page != 1 or meta['page'] != 0 or meta['count'] != 0:
            raise ValueError('涨停分析空池元信息错误')
        return [], 0, 0
    if (meta['count'] != pages or meta['page'] != page or not 1 <= page <= pages
            or len(rows) != min(PAGE_SIZE, total - (page - 1) * PAGE_SIZE)):
        raise ValueError('涨停分析缺页、尾页或分页总量错误')
    values = [member(row, day, identities=identities) for row in rows]
    # The source code sort has unique keys in the declared equity universe.
    codes = [r['unified_code'].split('.')[0] for r in values]
    if any(a >= b for a, b in zip(codes, codes[1:])):
        raise ValueError('涨停分析代码排序重复或倒序')
    return values, total, pages


def parse_reason(obj, code, day):
    split_unified_code(code)
    day_value(day)
    data = response_data(obj)
    result = {'unified_code': code, 'trade_date': day}
    # Announcement 2025-028 (cninfo 1222544408): same listed entity,
    # 300114 became 302132 on 2025-02-17. The reason endpoint can label
    # pre-change history with its current code. Keep the requested old key.
    source_code = '302132.SZ' if code == '300114.SZ' and day < '2025-02-17' else code
    names = set()
    for source, target, limit in (('reasonrevealedList', 'reason_text', 65535),
                                   ('reasonKindList', 'reason_kind', 4096)):
        if source not in data:
            raise ValueError('原因详情缺少约定栏目')
        rows = data[source]
        # The source also uses an empty array for an unavailable column,
        # independently of a populated companion column.
        if rows is None or rows == []:
            result[target] = None
            continue
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError('原因详情单证券行数异常')
        values = rows[0].get('valueList')
        if (not isinstance(values, list) or len(values) != 3 or values[0] not in (code, source_code)
                or not isinstance(values[1], str) or not 1 <= len(values[1]) <= 80):
            raise ValueError('原因详情身份或日期槽不唯一')
        value = values[2]
        if value is not None and (not isinstance(value, str) or len(value.encode('utf8')) > limit):
            raise ValueError('原因正文类型或长度异常')
        names.add(values[1])
        result[target] = value
    if len(names) > 1:
        raise ValueError('原因详情两栏目证券名称冲突')
    result['name'] = next(iter(names), None)
    result['availability'] = 'no_content' if all(result[k] is None for k in ('reason_text', 'reason_kind')) else 'available'
    return result
