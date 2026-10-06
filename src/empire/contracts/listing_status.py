"""Calendar listing-state events; a termination never means permanently delisted."""
import calendar
import hashlib
import json
import re
from datetime import date, timedelta

from empire.contracts.security import split_unified_code

PROJECT, JOB, DATASET = 'tdx-listing-status', 'tdx-listing-status-v1', 'listing_status.month'
FIRST = date(1990, 12, 19)
TYPES = {'suspended': '暂停上市', 'resumed': '恢复上市', 'terminated': '终止上市'}
SOURCE_TYPES = {label + '日': key for key, label in TYPES.items()}
COLUMNS = ('event_date', 'unified_code', 'event_type', 'record_key', 'name', 'description')
MAX_DAY, MAX_MONTH = 1000, 5000


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                                     sort_keys=True).encode()).hexdigest()


def identity(row):
    return digest([row[0], row[1], row[2], row[5]])


def bounds(month, through):
    if not isinstance(month, str) or not re.fullmatch(r'\d{4}-\d{2}', month):
        raise ValueError('上市状态月份格式无效')
    first = date.fromisoformat(month + '-01')
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    start, end = max(first, FIRST), min(last, through)
    if start > end or through < FIRST:
        raise ValueError('上市状态日期范围无效')
    return start, end


def months(through):
    result, day = [], FIRST
    while day <= through:
        month = day.strftime('%Y-%m')
        result.append(month)
        day = bounds(month, through)[1] + timedelta(days=1)
    return result


def validate_rows(rows, start, end):
    if not isinstance(rows, list) or len(rows) > MAX_MONTH:
        raise ValueError('上市状态月份超过事件上限')
    seen, clean = set(), []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(COLUMNS):
            raise ValueError('上市状态事件字段不符')
        day = date.fromisoformat(row[0])
        if day.isoformat() != row[0] or not start <= day <= end:
            raise ValueError('上市状态事件日期不在核验范围')
        market, code = split_unified_code(row[1])
        if not ((market == 'SH' and code.startswith('6')) or
                (market == 'SZ' and code.startswith(('0', '3')))):
            raise ValueError('上市状态事件不属于声明沪深A股范围')
        if row[2] not in TYPES or row[3] != identity(row):
            raise ValueError('上市状态事件类型或来源身份无效')
        if not isinstance(row[4], str) or not row[4].strip() or len(row[4]) > 100:
            raise ValueError('上市状态简称无效')
        if row[5] is not None and (not isinstance(row[5], str) or len(row[5]) > 2000):
            raise ValueError('上市状态说明无效或超限')
        key = tuple(row[:4])
        if key in seen:
            raise ValueError('上市状态来源业务身份重复，不能用等数量重复集合证明完整')
        seen.add(key)
        clean.append(list(row))
    return sorted(clean, key=lambda r: tuple(r[:4]))


def content(rows, counts):
    return dict(rows=rows, source_counts=counts)
