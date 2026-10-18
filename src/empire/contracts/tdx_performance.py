"""Five independent source entities; typed SQL fields and lossless compact transport."""
import base64
import hashlib
import json
import re
import zlib
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

from empire.contracts.security import unified_code

CAPACITY = 10000
FIRST_YEAR = 1980
SCHEMA_VERSION = 1
KINDS = {
    'earnings_forecast': ('业绩预告', 'earnings_forecast', 'yjyg', '财务数据'),
    'earnings_quick': ('业绩快报', 'earnings_quick', 'yjkb', '财务数据'),
    'earnings_disclosure': ('业绩披露时间', 'earnings_disclosure', 'yjplsj', '财务数据'),
    'earnings_report': ('业绩报告', 'earnings_report', 'yjbg', '财务数据'),
    'holder_count': ('股东户数', 'shareholder_count', 'gdhs', '股东数据'),
}
UNIT_KINDS = {**KINDS, 'shareholder_changes':
    ('重要股东持股变动', 'shareholder_change', 'zygdcgbd', '股东数据')}
# (source column, SQL column, value type); raw presentation counters are not business facts.
FIELDS = {
    'shareholder_changes': (
        ('month', 'data_month', 'date'), ('T003', 'change_end', 'date'),
        ('T013', 'change_start', 'partial_date?'), ('T004', 'announcement_date', 'date?'),
        ('T005', 'actor', 'text512'), ('T006', 'price', 'decimal'),
        ('T007', 'shares_changed', 'decimal'), ('T008', 'shares_after', 'decimal'),
        ('T009', 'reason', 'text512'), ('T010', 'leader', 'text512'),
        ('T011', 'position', 'text512'), ('T012', 'relationship', 'text512'),
        ('occurrence', 'occurrence', 'integer?')),
    'earnings_forecast': (
        ('T003', 'report_date', 'date'), ('T002', 'announcement_date', 'date?'),
        ('T009', 'forecast_type', 'text100'), ('T005', 'forecast_text', 'text32768')),
    'earnings_quick': (
        ('T001', 'source_id', 'text100'), ('T004', 'report_date', 'date'),
        ('T002', 'announcement_date', 'date?'), ('rq', 'source_date', 'date?'),
        ('T006', 'profit_basis', 'text100'), ('T007', 'profit_scope', 'text100'),
        ('T005', 'roe_scope', 'text100'),
        ('T008', 'net_profit', 'decimal'), ('aoe', 'roe', 'decimal'), ('T016', 'eps', 'decimal'),
        ('T012', 'assets', 'decimal'), ('T014', 'equity', 'decimal'),
        ('T030', 'comparison_value', 'decimal'), ('pT008', 'previous_profit', 'decimal'),
        ('paoe', 'previous_roe', 'decimal'), ('jlyzzl', 'profit_change', 'decimal'),
        ('roezzl', 'roe_change', 'decimal')),
    'earnings_disclosure': (
        ('T002', 'report_date', 'date'), ('T003', 'first_scheduled', 'date?'),
        ('T004', 'changed_1', 'date?'), ('T005', 'changed_2', 'date?'),
        ('T006', 'changed_3', 'date?'), ('T007', 'actual_date', 'date?')),
    'earnings_report': (
        ('T003', 'report_date', 'date'), ('T007', 'announcement_date', 'date?'),
        ('roe', 'roe', 'decimal'), ('proe', 'previous_roe', 'decimal'),
        ('jly', 'net_profit', 'decimal'), ('pjly', 'previous_profit', 'decimal'),
        ('yysr', 'revenue', 'decimal'), ('pyysr', 'previous_revenue', 'decimal'),
        ('T084', 'operating_cashflow', 'decimal'), ('T006', 'eps', 'decimal')),
    'holder_count': (
        ('sT002', 'statistics_date', 'date'), ('T003', 'holders', 'integer?'),
        ('T004', 'average_float', 'decimal'), ('T005', 'holder_change_pct', 'decimal'),
        ('T008', 'top_float_shares', 'decimal'), ('T009', 'top_float_pct', 'decimal'),
        ('T010', 'top_shares', 'decimal'), ('T011', 'top_pct', 'decimal'),
        ('T012', 'holder_change', 'integer?')),
}
SOURCE_COLUMNS = {
    'shareholder_changes': ['T003', 'T004', 'T006', 'T005', 'T007', 'T008',
        'T010', 'T011', 'T012', 'T013', 'code', 'name', 'sc', 'T009'],
    'earnings_forecast': ['sc', 'code', 'name', 'T003', 'T009', 'T005', 'T002'],
    'earnings_quick': ['T001', 'sc', 'code', 'name', 'rq', 'T004', 'T008', 'aoe', 'T016',
        'T012', 'T014', 'T002', 'T030', 'T006', 'T007', 'pT008', 'paoe', 'T005', 'jlyzzl', 'roezzl'],
    'earnings_disclosure': ['cur', 'code', 'name', 'sc', 'T002', 'T003', 'T004', 'T005', 'T006', 'T007', 'days'],
    'earnings_report': ['code', 'name', 'sc', 'T007', 'T003', 'roe', 'proe', 'jly', 'pjly', 'yysr', 'pyysr', 'T084', 'T006'],
    'holder_count': ['code', 'name', 'sc', 'sT002', 'T003', 'T004', 'T005', 'T008', 'T009', 'T010', 'T011', 'T012'],
}
IDENTITIES = {
    'earnings_forecast': ('unified_code', 'report_date', 'announcement_date'),
    'earnings_quick': ('unified_code', 'source_id', 'report_date', 'announcement_date',
                       'profit_basis', 'profit_scope', 'roe_scope'),
    'earnings_disclosure': ('unified_code', 'report_date'),
    'earnings_report': ('unified_code', 'report_date'),
    'holder_count': ('unified_code', 'statistics_date'),
}


def project(kind):
    return 'tdx-' + kind.replace('_', '-')


def columns(kind):
    return ('unified_code', 'name', *(field[1] for field in FIELDS[kind]))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def identity(kind, row):
    if kind == 'shareholder_changes':
        return digest([row[key] for key in columns(kind) if key != 'name'])
    return digest([row[key] for key in IDENTITIES[kind]])


def day(value, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('来源日期类型无效')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or not '1900-01-01' <= value <= '2200-12-31':
        raise ValueError('来源日期范围或格式无效')
    return value


def convert(value, shape):
    if shape == 'partial_date?':
        if value is None:
            return None
        if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}', value):
            day(value + '-01')
            return value
        return day(value)
    if shape.startswith('date'):
        return day(value, shape.endswith('?'))
    if shape.startswith('text'):
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > int(shape[4:]) or '\ufffd' in value:
            raise ValueError('来源文本类型、长度或编码无效')
        return value
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError('来源数值类型无效')
    try:
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) >= Decimal('1e20'):
            raise ValueError('来源数值超出精度范围')
        if shape == 'integer?':
            if number != number.to_integral_value() or abs(number) >= 2**63:
                raise ValueError('来源户数须为BIGINT整数')
            return int(number)
        if number != number.quantize(Decimal('.00000001')):
            raise ValueError('来源数值超过8位小数，禁止无声舍入')
        return format(number.normalize(), 'f') if number else '0'
    except InvalidOperation as exc:
        raise ValueError('来源数值格式无效') from exc


def source_row(kind, raw):
    market = str(raw['sc'])
    if market not in ('0', '1', '2') or not isinstance(raw['code'], str):
        raise ValueError('来源证券市场无效')
    row = {'unified_code': unified_code({'0': 'SZ', '1': 'SH', '2': 'BJ'}[market], raw['code'].strip()),
           'name': convert(raw['name'], 'text100')}
    row.update({target: convert(raw[src], shape) for src, target, shape in FIELDS[kind]})
    if kind == 'shareholder_changes':
        if not row['actor'] or not row['name']:
            raise ValueError('重要股东持股变动必需字段缺失')
        if row['data_month'] != row['change_end'][:7] + '-01':
            raise ValueError('持股变动截止日期与指定数据月份不符')
        if row['change_start'] and row['change_start'] > row['change_end']:
            raise ValueError('持股变动开始日期晚于截止日期')
        if type(row['occurrence']) is not int or not 1 <= row['occurrence'] < CAPACITY:
            raise ValueError('持股变动来源重复序号无效')
        if row['shares_after'] is not None and Decimal(row['shares_after']) < 0:
            raise ValueError('变动后持股不能为负')
    if kind == 'earnings_quick' and not row['source_id']:
        raise ValueError('快报来源方案关联身份缺失')
    if kind == 'holder_count' and row['holders'] is not None and row['holders'] < 0:
        raise ValueError('股东户数不能为负')
    return row


def validate_rows(kind, unit, rows):
    if not isinstance(rows, list) or len(rows) > (80000 if kind == 'earnings_quick' else CAPACITY):
        raise ValueError('完整单元行数超限')
    if kind == 'holder_count':
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', unit):
            raise ValueError('股东户数单元无效')
    else:
        parts = unit.split('|')
        if len(parts) != 2 or parts[1] not in ('SH', 'SZ', 'BJ'):
            raise ValueError('报告市场单元无效')
        day(parts[0])
    keys = []
    occurrences = Counter()
    names = {}
    occurrence_values = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(columns(kind)):
            raise ValueError('业务字段契约不符')
        rebuilt = source_row(kind, {**{src: row[target] for src, target, _ in FIELDS[kind]},
            'name': row['name'], 'code': row['unified_code'][:6],
            'sc': {'SZ': 0, 'SH': 1, 'BJ': 2}.get(row['unified_code'][-2:])})
        if rebuilt != row:
            raise ValueError('业务内容非规范值')
        if kind == 'holder_count':
            if row['unified_code'] != unit:
                raise ValueError('股东户数证券串用')
        elif row['data_month' if kind == 'shareholder_changes' else 'report_date'] != parts[0] or row['unified_code'][-2:] != parts[1]:
            raise ValueError('报告期或市场串用')
        keys.append(identity(kind, row))
        if kind == 'shareholder_changes':
            fact = digest([row[k] for k in columns(kind) if k not in ('name', 'occurrence')])
            occurrences[fact] += 1
            occurrence_values.setdefault(fact, set()).add(row['occurrence'])
            if fact in names and names[fact] != row['name']:
                raise ValueError('相同持股变动事实名称冲突')
            names[fact] = row['name']
    if kind == 'shareholder_changes':
        for fact, count in occurrences.items():
            if occurrence_values[fact] != set(range(1, count + 1)):
                raise ValueError('持股变动来源重复次数证明无效')
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise ValueError('业务键重复或单元顺序错误')


def pack(kind, rows):
    matrix = [[row[key] for key in columns(kind)] for row in rows]
    if kind not in ('earnings_quick', 'shareholder_changes'):
        return matrix
    raw = json.dumps(matrix, ensure_ascii=False, separators=(',', ':')).encode()
    if len(raw) > 8 * 1024**2:
        raise ValueError('快报规范矩阵超过8MiB解码上限')
    return {'codec': 'zlib-json-v1', 'bytes': len(raw), 'count': len(rows),
            'body': base64.b64encode(zlib.compress(raw)).decode('ascii')}


def unpack(kind, matrix):
    if kind in ('earnings_quick', 'shareholder_changes'):
        if (not isinstance(matrix, dict) or set(matrix) != {'codec', 'bytes', 'count', 'body'}
                or matrix['codec'] != 'zlib-json-v1' or type(matrix['bytes']) is not int
                or not 0 <= matrix['bytes'] <= 8 * 1024**2 or type(matrix['count']) is not int
                or not 0 <= matrix['count'] <= 80000 or not isinstance(matrix['body'], str)
                or len(matrix['body']) > 524288):
            raise ValueError('快报规范传输契约无效')
        try:
            decoder = zlib.decompressobj()
            raw = decoder.decompress(base64.b64decode(matrix['body'], validate=True), matrix['bytes'] + 1)
            if len(raw) != matrix['bytes'] or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('快报解码长度或压缩流无效')
            rows = json.loads(raw)
            if not isinstance(rows, list) or len(rows) != matrix['count']:
                raise ValueError('快报解码条数无效')
            matrix = rows
        except (zlib.error, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('快报传输解码失败') from exc
    if not isinstance(matrix, list) or any(not isinstance(r, list) or len(r) != len(columns(kind)) for r in matrix):
        raise ValueError('业务矩阵缺列')
    return [dict(zip(columns(kind), row, strict=True)) for row in matrix]


def quarterly_plan(latest):
    day(latest)
    values = [f'{year}-{suffix}' for year in range(FIRST_YEAR, int(latest[:4]) + 1)
              for suffix in ('03-31', '06-30', '09-30', '12-31') if f'{year}-{suffix}' <= latest]
    if not values or len(values) > 500:
        raise ValueError('报告期计划超过500期范围')
    return values


def monthly_plan(latest):
    day(latest)
    values = [f'{year}-{month:02d}-01' for year in range(1990, int(latest[:4]) + 1)
              for month in range(1, 13) if f'{year}-{month:02d}-01' <= latest]
    if not values or len(values) > 1000:
        raise ValueError('持股变动月份计划超过支持范围')
    return values
