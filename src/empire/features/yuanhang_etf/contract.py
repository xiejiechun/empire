"""ETF identities and bounded, lossless numeric contracts."""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

CATALOG_PROJECT = 'ths-yuanhang-etfs'
PRICE_PROJECT = 'ths-yuanhang-etf-prices'
LATEST_PROJECT = 'ths-yuanhang-etf-latest'
CATALOG_DATASET = 'yuanhang.etf.catalog'
PRICE_DATASET = 'yuanhang.etf.price.range'
PROJECTS = {CATALOG_DATASET: CATALOG_PROJECT, PRICE_DATASET: PRICE_PROJECT}
MARKETS = {'USHJ': 'SH', 'USZJ': 'SZ'}
ETF_LIMIT = 5000
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'amount')
LATEST_FIELDS = {6: 'previous_close', 7: 'open', 8: 'high', 9: 'low', 10: 'latest',
                 13: 'volume', 19: 'amount', 3397: 'net_value'}
LATEST_BYTES = 24 * 1024 * 1024
CONTRACT = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identity(code, market):
    if (not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}\.(SH|SZ)', code)
            or market not in MARKETS or code[-2:] != MARKETS[market]):
        raise ValueError('ETF统一代码与原生市场不符')
    return market + code[:6]


def security(code):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}\.(SH|SZ)', code):
        raise ValueError('ETF证券代码须为六位代码加.SH或.SZ')
    return code


def native_identity(value):
    if not isinstance(value, str) or len(value) != 10 or value[:4] not in MARKETS:
        raise ValueError('ETF响应原生身份无效')
    code = value[4:] + '.' + MARKETS[value[:4]]
    identity(code, value[:4])
    return code, value[:4]


def day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('ETF日期必须为YYYY-MM-DD')
    return value


def number(value):
    if value is None:
        return None
    if type(value) not in (str, int, float, Decimal):
        raise ValueError('ETF数值类型无效')
    try:
        n = Decimal(str(value))
        if not n.is_finite() or abs(n) >= Decimal(10) ** 18 or n != n.quantize(Decimal('0.0000000001')):
            raise ValueError('ETF数值超过DECIMAL(28,10)')
    except InvalidOperation:
        raise ValueError('ETF数值格式无效') from None
    return format(n.normalize(), 'f') if n else '0'


def validate_rows(rows, first, last):
    day(first)
    day(last)
    if first > last or first[:4] != last[:4] or not isinstance(rows, list) or len(rows) > 366:
        raise ValueError('ETF日K区间或数量无效')
    previous = ''
    for row in rows:
        if not isinstance(row, list) or len(row) != 7:
            raise ValueError('ETF日K字段无效')
        stamp = day(row[0])
        if not first <= stamp <= last or stamp <= previous or any(number(v) != v for v in row[1:]):
            raise ValueError('ETF日K日期、排序或规范数值无效')
        previous = stamp
