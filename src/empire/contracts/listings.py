"""Single-source first-listing details, exact decimal wire and bounded text."""
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from empire.contracts.security import split_unified_code, unified_code

PROJECT, JOB, DATASET = 'ths-listings', 'ths-listings-v1', 'listing.detail'
TABLE, CONTRACT = 'stock_listing', 2
HISTORY_MAX_BYTES = 256 * 1024
# Source directories can publish issuance details before the first trading day.
LISTING_LOOKAHEAD_DAYS = 31
MARKETS = {'SH': '17', 'SZ': '33', 'BJ': '151'}
NUMBERS = {'issuance_num': (24, 4), 'issuance_price': (24, 4),
           'first_day_open_price': (24, 4), 'estimated_raised': (24, 4),
           'actual_raised': (24, 4), 'issuance_pe': (20, 4), 'winning_rate': (20, 10)}
FIELDS = ('listing_date', 'establish_date', *NUMBERS, 'lead_underwriter', 'sponsor', 'history')
COLUMNS = ('unified_code', *FIELDS)
ROOT = 'https://basic.10jqka.com.cn'
REFERER = ROOT + '/astockpc/astockmain/index.html'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def url(stock):
    unified_code(stock['market'], stock['code'])
    return ROOT + '/fuyao/info/company/v1/issuance/detail?code=' + stock['code'] + '&market=' + MARKETS[stock['market']]


def number(value, field):
    if value is None or value in ('', '--'):
        return None
    if type(value) not in (str, int, float) or not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', str(value)):
        raise ValueError('发行数值格式无效：' + field)
    precision, scale = NUMBERS[field]
    try:
        d = Decimal(str(value))
        if (not d.is_finite() or abs(d) >= Decimal(10) ** (precision - scale)
                or d != d.quantize(Decimal(10) ** -scale)
                or (field != 'issuance_pe' and d < 0) or (field == 'winning_rate' and d > 100)):
            raise ValueError('发行数值范围或精度无效：' + field)
        return format(d.normalize(), 'f') if d else '0'
    except InvalidOperation:
        raise ValueError('发行数值范围或精度无效：' + field) from None


def validate(row, through):
    if is_unusable(row):
        split_unified_code(row['unified_code'])
        return dict(row)
    return _validate_detail(row, through)


def _validate_detail(row, through, *, require_listing=True):
    if not isinstance(row, dict) or set(row) != set(COLUMNS):
        raise ValueError('发行资料字段集合无效')
    split_unified_code(row['unified_code'])
    result = {'unified_code': row['unified_code']}
    for field in FIELDS:
        value = row[field]
        if value is None or value in ('', '--'):
            value = None
        if field in ('listing_date', 'establish_date'):
            if value is not None:
                upper = (date.fromisoformat(through) + timedelta(days=LISTING_LOOKAHEAD_DAYS)).isoformat() if field == 'listing_date' else through
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value or not '1900-01-01' <= value <= upper:
                    raise ValueError('发行日期无效：' + field)
            elif field == 'listing_date' and require_listing:
                raise ValueError('缺必需上市日期')
        elif field in NUMBERS:
            value = number(value, field)
        elif value is not None:
            bound = HISTORY_MAX_BYTES if field == 'history' else 2048
            if not isinstance(value, str) or '\x00' in value or (len(value.encode()) if field == 'history' else len(value)) > bound:
                raise ValueError('发行文本类型或上限无效：' + field)
        result[field] = value
    return result


def date_warning(row):
    return bool(row.get('establish_date') and row.get('listing_date')
                and row['establish_date'] > row['listing_date'])


def is_unavailable(row):
    return (isinstance(row, dict) and set(row) == {'unified_code', 'detail_status', 'source_status_code'}
            and row['detail_status'] == 'unavailable' and type(row['source_status_code']) is int
            and row['source_status_code'] == 10001)


def is_incomplete(row):
    return (isinstance(row, dict)
            and set(row) == {'unified_code', 'detail_status', 'source_status_code', 'missing_fields'}
            and row['detail_status'] == 'incomplete' and type(row['source_status_code']) is int
            and row['source_status_code'] == 0 and row['missing_fields'] == ['listing_date'])


def is_unusable(row):
    return is_unavailable(row) or is_incomplete(row)


def unusable_proof(proof):
    if not isinstance(proof, dict) or proof.get('availability_contract') != 1:
        return False
    if proof.get('availability') not in ('unavailable', 'incomplete'):
        return False
    row = dict(unified_code='', detail_status=proof.get('availability'),
               source_status_code=proof.get('source_status_code'))
    if proof.get('availability') == 'incomplete':
        row['missing_fields'] = proof.get('missing_fields')
    return is_unusable(row)


def parse(body, stock, through):
    if (isinstance(body, dict) and set(body) == {'status_code', 'data', 'status_msg'}
            and type(body['status_code']) is int and body['status_code'] == 10001
            and type(body['data']) is dict and not body['data'] and body['status_msg'] == 'result empty'):
        return dict(unified_code=unified_code(stock['market'], stock['code']),
                    detail_status='unavailable', source_status_code=10001)
    if not isinstance(body, dict) or type(body.get('status_code')) is not int or body['status_code'] != 0:
        raise ValueError('发行详情接口未成功')
    data = body.get('data')
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise ValueError('发行详情字段缺失或协议改变')
    row = _validate_detail(dict(unified_code=unified_code(stock['market'], stock['code']), **data),
                           through, require_listing=False)
    if row['listing_date'] is None:
        return dict(unified_code=row['unified_code'], detail_status='incomplete',
                    source_status_code=0, missing_fields=['listing_date'])
    return row


def decode(row):
    result = {k: row[k] for k in COLUMNS}
    for field in ('listing_date', 'establish_date'):
        if result[field] is not None:
            result[field] = result[field].isoformat()
    for field in NUMBERS:
        value = result[field]
        # SQL DECIMAL may stringify zero/small values as 0E-10 or 1E-10.
        # Its fixed-point value still follows the strict source/wire contract.
        value = format(value, 'f') if isinstance(value, Decimal) else str(value) if value is not None else None
        result[field] = number(value, field)
    return result
