"""Current source plan versions; no quotation or inferred cancellation facts."""
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from empire.contracts.security import split_unified_code

PROJECT, JOB, DATASET = 'eastmoney-repurchases', 'eastmoney-repurchases-v1', 'repurchases.page'
URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
PAGE = 'https://data.eastmoney.com/gphg/hglist.html'
REPORT = 'RPTA_WEB_GETHGLIST_NEW'
PAGE_SIZE, MAX_ROWS = 500, 100000
PROGRESS = {'004': '实施中', '006': '回购完成'}
SOURCE_FIELDS = {
    'plan_id': 'REPURCODE', 'unified_code': 'SECUCODE', 'name': 'SECURITYSHORTNAME',
    'share_type': 'SHARETYPE', 'plan_date': 'DIM_DATE', 'updated_date': 'UPD',
    'progress_code': 'REPURPROGRESS', 'plan_updated_date': 'UPDATEDATE',
    'actual_through': 'DIM_DATE3', 'notice_date': 'NOTICEDATE',
    'start_date': 'REPURSTARTDATE', 'end_date': 'REPURENDDATE', 'finish_date': 'FINISHDATE',
    'shareholder_notice_date': 'SHMRSLTNOTICEDATE', 'advance_date': 'REPURADVANCEDATE',
    'plan_price_upper': 'REPURPRICECAP', 'plan_price_lower': 'REPURPRICELOWER',
    'plan_quantity_upper': 'REPURNUMCAP', 'plan_quantity_lower': 'REPURNUMLOWER',
    'plan_amount_upper': 'REPURAMOUNTLIMIT', 'plan_amount_lower': 'REPURAMOUNTLOWER',
    'actual_price_upper': 'REPURPRICECAP1', 'actual_price_lower': 'REPURPRICELOWER1',
    'actual_quantity': 'REPURNUM', 'actual_amount': 'REPURAMOUNT',
    'objective': 'REPUROBJECTIVE', 'remark': 'REMARK', 'progress_remark': 'REMARK2',
}
COLUMNS = tuple(SOURCE_FIELDS)
DATES = tuple(k for k in COLUMNS if k.endswith('_date') or k == 'actual_through')
NUMBERS = tuple(k for k in COLUMNS if k.startswith(('plan_price_', 'plan_quantity_',
                                                'plan_amount_', 'actual_price_'))
                or k in ('actual_quantity', 'actual_amount'))
TEXTS = ('objective', 'remark', 'progress_remark')


def number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('回购数值不能为布尔值')
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0 or n >= Decimal('1e20') or n != n.quantize(Decimal('0.00000001')):
            raise ValueError('回购数值超出DECIMAL(28,8)或精度增加')
        return format(n.normalize(), 'f') if n else '0'
    except InvalidOperation as exc:
        raise ValueError('回购数值无效') from exc


def day(value, required=False):
    if value is None and not required:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        value = value.isoformat()
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?: 00:00:00)?', value):
        raise ValueError('回购来源自然日格式无效')
    d = date.fromisoformat(value[:10])
    if not date(1990, 1, 1) <= d <= date(2100, 12, 31):
        raise ValueError('回购日期超界')
    return d.isoformat()


def validate(row):
    if not isinstance(row, dict) or set(row) != set(COLUMNS):
        raise ValueError('回购消息字段契约不符')
    r = dict(row)
    if not isinstance(r['plan_id'], str) or not re.fullmatch(r'[1-9][0-9]{0,19}', r['plan_id']):
        raise ValueError('回购方案编号无效')
    split_unified_code(r['unified_code'])
    for k in DATES:
        r[k] = day(r[k], k in ('plan_date', 'updated_date'))
    for k in NUMBERS:
        r[k] = number(r[k])
    for k, maximum in (('name', 100), ('share_type', 80), ('progress_code', 16)):
        if not isinstance(r[k], str) or not r[k] or len(r[k]) > maximum:
            raise ValueError('回购名称、股份类型或状态无效')
    # Unknown source status remains visible; never classify it as complete.
    for k in TEXTS:
        if r[k] is not None and (not isinstance(r[k], str) or len(r[k].encode()) > 65536):
            raise ValueError('回购说明超限或类型无效')
    for prefix in ('plan_price', 'plan_quantity', 'plan_amount', 'actual_price'):
        lo, hi = r[prefix + '_lower'], r[prefix + '_upper']
        if lo is not None and hi is not None and Decimal(lo) > Decimal(hi):
            raise ValueError('回购上下限倒置')
    return r


def normalize(row):
    if not isinstance(row, dict) or not set(SOURCE_FIELDS.values()) <= set(row):
        raise ValueError('回购来源缺少声明字段')
    return validate({k: row[v] for k, v in SOURCE_FIELDS.items()})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def extend_digest(previous, rows):
    for row in rows:
        previous = hashlib.sha256(bytes.fromhex(previous) +
            json.dumps([row['plan_id'], digest(row)], separators=(',', ':')).encode()).hexdigest()
    return previous


def parse(body, *, after='', remaining=None):
    result = body.get('result') if isinstance(body, dict) else None
    if not isinstance(body, dict) or body.get('success') is not True or not isinstance(result, dict):
        raise ValueError('东方财富回购业务状态异常')
    count, pages = result.get('count'), result.get('pages')
    if type(count) is not int or not 0 <= count <= MAX_ROWS or type(pages) is not int:
        raise ValueError('回购来源统计无效或超过容量')
    if remaining is not None and count != remaining:
        raise ValueError('回购来源集合在翻页间变化，断点未推进；从头核验建立新轮次')
    if pages != (count + PAGE_SIZE - 1) // PAGE_SIZE or not isinstance(result.get('data'), list):
        raise ValueError('回购来源页数无效')
    rows = [normalize(r) for r in result['data']]
    if len(rows) != min(PAGE_SIZE, count):
        raise ValueError('回购页长与剩余总数不符')
    keys = [after, *(r['plan_id'] for r in rows)]
    if any(a >= b for a, b in zip(keys, keys[1:])):
        raise ValueError('回购方案编号重复、乱序或游标不前进')
    return rows, count
