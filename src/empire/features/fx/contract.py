"""Explicit page scope, non-equity identities and decimal/date contracts."""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal

SOURCE = 'ths'
LIVE_PROJECT = 'ths-fx-live'
DAILY_PROJECT = 'ths-fx-daily'
LIVE_JOB, DAILY_JOB = LIVE_PROJECT + '-v1', DAILY_PROJECT + '-v1'
DATASET = 'fx.price.year'
BASE = 'https://d.10jqka.com.cn/v4/'
FIELDS = ('open', 'high', 'low', 'close')
SYMBOLS = {
    'USDIND': ('美元指数', 'index', '指数点'),
    'USDCNY': ('美元/人民币', 'currency_pair', '人民币/美元'),
    'USDCNH': ('美元/人民币(离)', 'currency_pair', '离岸人民币/美元'),
    'XAUUSD': ('伦敦金', 'metal', '美元/金衡盎司'),
    'EURUSD': ('欧元/美元', 'currency_pair', '美元/欧元'),
    'GBPUSD': ('英镑/美元', 'currency_pair', '美元/英镑'),
    'USDCAD': ('美元/加元', 'currency_pair', '加元/美元'),
    'USDCHF': ('美元/瑞郎', 'currency_pair', '瑞郎/美元'),
    'USDHKD': ('美元/港币', 'currency_pair', '港币/美元'),
    'AUDUSD': ('澳元/美元', 'currency_pair', '美元/澳元'),
    'USDJPY': ('美元/日元', 'currency_pair', '日元/美元'),
    'USDSGD': ('美元/新元', 'currency_pair', '新加坡元/美元'),
}
TABLES = {
    'fx_daily_price': {'unified_code', 'trade_date', *FIELDS},
    'fx_price_year': {'unified_code', 'quote_year', 'source_count', 'row_count',
                      'first_date', 'last_date', 'content_hash', 'contract_version', 'version_observed_at'},
}
KEYS = {'fx_daily_price': ['unified_code', 'trade_date'],
        'fx_price_year': ['unified_code', 'quote_year']}


def symbol(value):
    if not isinstance(value, str) or value not in SYMBOLS:
        raise ValueError('汇率品种不属于已登记的十二品种')
    return value


def identity(value):
    return symbol(value) + '.FX'


def day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('汇率日期必须为YYYY-MM-DD')
    return value


def number(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d+)?', value):
        raise ValueError('汇率价格格式无效')
    n = Decimal(value)
    if not 0 < n < Decimal('10000000000') or n != n.quantize(Decimal('0.0000000001')):
        raise ValueError('汇率价格超出DECIMAL(20,10)精度范围')
    return format(n.normalize(), 'f')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_rows(rows, year=None):
    if not isinstance(rows, list) or not 1 <= len(rows) <= (366 if year else 1000):
        raise ValueError('汇率日线集合为空或超过完整单元上限')
    previous = ''
    for row in rows:
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError('汇率日线字段不完整')
        stamp = day(row[0])
        if stamp <= previous or year is not None and int(stamp[:4]) != year:
            raise ValueError('汇率日线重复、乱序或跨年')
        if any(number(v) != v for v in row[1:]):
            raise ValueError('汇率价格未规范化')
        previous = stamp
    return rows


def price_quality(row):
    op, high, low, close = map(Decimal, row)
    return low <= min(op, close) <= max(op, close) <= high


def url(code, unit='last'):
    symbol(code)
    if unit == 'live':
        return BASE + f'realhead/wh_{code}/last.js'
    if unit == 'today':
        return f'https://d.10jqka.com.cn/v6/line/wh_{code}/01/today.js'
    if unit != 'last' and (type(unit) is not int or not 1900 <= unit <= 2100):
        raise ValueError('汇率历史年份无效')
    return BASE + f'line/wh_{code}/01/{unit}.js'
