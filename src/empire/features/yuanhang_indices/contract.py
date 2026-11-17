"""Explicit independent projects and bounded source identities."""
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from empire.contracts.security import index_code

CATALOG_PROJECT = 'ths-yuanhang-indices'
MEMBER_PROJECT = 'ths-yuanhang-index-members'
PRICE_PROJECT = 'ths-yuanhang-index-prices'
CATALOG_DATASET = 'yuanhang.index.catalog'
MEMBER_DATASET = 'ths.index.members'
PRICE_DATASET = 'yuanhang.index.price.range'
PROJECTS = {CATALOG_DATASET: CATALOG_PROJECT, MEMBER_DATASET: MEMBER_PROJECT, PRICE_DATASET: PRICE_PROJECT}
SOURCES = {CATALOG_DATASET: 'ths_yuanhang', MEMBER_DATASET: 'ths', PRICE_DATASET: 'ths_yuanhang'}
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'amount')
MARKETS = {'USHI': 'Market_16_16', 'USZI': 'Market_32_32', 'USTI': 'Market_144_144'}
INDEX_LIMIT = 1000
MEMBER_LIMIT = 10000
CONTRACT = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identity(code, market):
    index_code(code)
    if market not in MARKETS:
        raise ValueError('指数原生市场不受支持')
    return market + code


def day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('指数日期必须为YYYY-MM-DD')
    return value


def number(value):
    if value is None:
        return None
    if type(value) not in (str, int, float, Decimal):
        raise ValueError('指数数值类型无效')
    try:
        n = Decimal(str(value))
        if not n.is_finite() or abs(n) >= Decimal(10) ** 18 or n != n.quantize(Decimal('0.0000000001')):
            raise ValueError('指数数值超过DECIMAL(28,10)')
    except InvalidOperation:
        raise ValueError('指数数值格式无效') from None
    return format(n.normalize(), 'f') if n else '0'


def validate_rows(rows, first, last):
    day(first)
    day(last)
    if first > last or first[:4] != last[:4] or not isinstance(rows, list) or len(rows) > 366:
        raise ValueError('指数日K区间或数量无效')
    previous = ''
    for row in rows:
        if not isinstance(row, list) or len(row) != 7:
            raise ValueError('指数日K字段无效')
        stamp = day(row[0])
        if not first <= stamp <= last or stamp <= previous or any(number(v) != v for v in row[1:]):
            raise ValueError('指数日K日期、排序或规范数值无效')
        previous = stamp
