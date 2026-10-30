"""Sort an already complete bounded Redis snapshot; never merge versions."""

from decimal import Decimal
from functools import cmp_to_key

from .contract import DECIMAL_FIELDS, INTEGER_FIELDS, MEMBER_FIELDS, TIME_FIELDS


def snapshot_page(rows, version, filters, order, after):
    fields = ('trade_date', 'pool_type', *MEMBER_FIELDS)
    if (not isinstance(order, dict) or set(order) != {'field', 'direction'}
            or order['field'] not in fields or order['direction'] not in ('asc', 'desc')):
        raise ValueError('盘中排序字段或方向无效')
    offset = 0
    if after is not None:
        if (not isinstance(after, dict) or set(after) != {'version', 'filters', 'order', 'offset'}
                or after['version'] != version or after['filters'] != list(filters)
                or after['order'] != order or type(after['offset']) is not int
                or not 0 <= after['offset'] <= 10000):
            raise ValueError('盘中排序游标不属于当前快照或筛选条件')
        offset = after['offset']
    numeric = (*DECIMAL_FIELDS, *INTEGER_FIELDS, *TIME_FIELDS, 'source_market_id')

    def compare(a, b):
        left, right = a.get(order['field']), b.get(order['field'])
        empty_a, empty_b = left in (None, ''), right in (None, '')
        if empty_a != empty_b:
            return 1 if empty_a else -1
        result = 0
        if not empty_a:
            left, right = ((Decimal(str(left)), Decimal(str(right))) if order['field'] in numeric
                           else (str(left), str(right)))
            result = (left > right) - (left < right)
        return (result * (1 if order['direction'] == 'asc' else -1)
                or (a['unified_code'] > b['unified_code']) - (a['unified_code'] < b['unified_code']))

    ordered = sorted(rows, key=cmp_to_key(compare))
    next_cursor = dict(version=version, filters=list(filters), order=order, offset=offset + 200)
    return ordered[offset:offset + 200], next_cursor if offset + 200 < len(rows) else None
