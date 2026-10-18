"""Source facts and request groups are distinct identities for TDX unlocks."""
import base64
import binascii
import hashlib
import json
import re
import zlib
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

PROJECT, JOB, DATASET = 'tdx-unlocks', 'tdx-unlocks-v1', 'unlocks.tdx_month'
CAPACITY, CONTRACT = 10000000, 1
MARKETS = ('SH', 'SZ', 'BJ')
PARENT_COLUMNS = ('record_key', 'group_key', 'unified_code', 'unlock_date', 'reason_code',
                  'name', 'industry', 'reason', 'shares', 'total_shares', 'occurrence',
                  'detail_status', 'detail_count')
DETAIL_COLUMNS = ('record_key', 'group_key', 'unified_code', 'unlock_date', 'reason_code',
                  'holder', 'reason', 'shares', 'occurrence')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def text_value(value, limit, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ValueError('解禁来源文本字段无效')
    return value


def day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('解禁日期必须是YYYY-MM-DD')
    if not '1990-01-01' <= value <= '2200-12-31':
        raise ValueError('解禁日期超出声明范围')
    return value


def shares(value, *, source=False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('解禁数量无效')
    try:
        number = Decimal(str(value)) * (10000 if source else 1)
        if not number.is_finite() or not 0 <= number < Decimal('1e20') or number.as_tuple().exponent < -8:
            raise ValueError('解禁数量范围或精度无效')
        return format(number, 'f')
    except InvalidOperation as exc:
        raise ValueError('解禁数量不是十进制') from exc


def security(sc, code):
    if type(sc) is not int or sc not in (0, 1, 2) or not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
        raise ValueError('解禁证券关联无效')
    return code + '.' + ('SZ', 'SH', 'BJ')[sc]


def group_key(row):
    return digest([row[k] for k in ('unified_code', 'unlock_date', 'reason_code')])


def fact_key(row, detail=False):
    fields = ('group_key', 'holder', 'reason', 'shares', 'occurrence') if detail else (
        'group_key', 'reason', 'shares', 'occurrence')
    return digest([row[k] for k in fields])


def canonical_number(value):
    result = shares(value)
    return format(Decimal(result).normalize(), 'f') if result is not None else None


def pack(parents, details):
    matrix = [[[r[k] for k in PARENT_COLUMNS] for r in parents],
              [[r[k] for k in DETAIL_COLUMNS] for r in details]]
    raw = json.dumps(matrix, ensure_ascii=False, separators=(',', ':')).encode()
    if len(raw) > 8 * 1024**2:
        raise ValueError('解禁完整单元规范正文超过8MiB')
    return {'codec': 'zlib-json-v1', 'bytes': len(raw),
            'body': base64.b64encode(zlib.compress(raw)).decode('ascii')}


def unpack(value):
    if (not isinstance(value, dict) or set(value) != {'codec', 'bytes', 'body'}
            or value['codec'] != 'zlib-json-v1' or type(value['bytes']) is not int
            or not 0 <= value['bytes'] <= 8 * 1024**2 or not isinstance(value['body'], str)
            or len(value['body']) > 524288):
        raise ValueError('解禁规范消息无效')
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(base64.b64decode(value['body'], validate=True), value['bytes'] + 1)
    except (binascii.Error, zlib.error) as exc:
        raise ValueError('解禁消息编码无效') from exc
    if len(raw) != value['bytes'] or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('解禁消息解压边界无效')
    arrays = json.loads(raw)
    if not isinstance(arrays, list) or len(arrays) != 2:
        raise ValueError('解禁消息集合缺失')
    output = []
    for matrix, columns, limit in zip(arrays, (PARENT_COLUMNS, DETAIL_COLUMNS), (10000, 100000), strict=True):
        if not isinstance(matrix, list) or len(matrix) > limit or any(
                not isinstance(r, list) or len(r) != len(columns) for r in matrix):
            raise ValueError('解禁矩阵列数或容量错误')
        output.append([dict(zip(columns, r, strict=True)) for r in matrix])
    return output


def validate_unit(unit, parents, details):
    month, market = unit.split('|')
    day(month)
    if month[8:] != '01' or market not in MARKETS or len(parents) > 10000 or len(details) > 100000:
        raise ValueError('解禁月市场单元无效')
    groups = {}
    for detail, rows, columns in ((False, parents, PARENT_COLUMNS), (True, details, DETAIL_COLUMNS)):
        keys, facts, occurrence_sets = [], Counter(), {}
        for row in rows:
            if set(row) != set(columns):
                raise ValueError('解禁必需字段缺失')
            code = row['unified_code']
            if not isinstance(code, str) or not re.fullmatch(r'\d{6}\.' + market, code):
                raise ValueError('解禁市场关联错误')
            if day(row['unlock_date'])[:7] != month[:7]:
                raise ValueError('解禁月份越界')
            text_value(row['reason_code'], 128, True)
            text_value(row['reason'], 1024)
            if row['group_key'] != group_key(row):
                raise ValueError('解禁请求组被篡改')
            if type(row['occurrence']) is not int or not 1 <= row['occurrence'] <= 65535:
                raise ValueError('解禁来源出现次数无效')
            shares(row['shares'])
            if row['shares'] != canonical_number(row['shares']):
                raise ValueError('解禁数量非规范表示')
            if detail:
                text_value(row['holder'], 512, True)
            else:
                text_value(row['name'], 100)
                text_value(row['industry'], 200)
                shares(row['total_shares'])
                if row['total_shares'] != canonical_number(row['total_shares']):
                    raise ValueError('解禁总股本非规范表示')
                if row['detail_status'] not in ('present', 'source_empty') or type(row['detail_count']) is not int:
                    raise ValueError('解禁明细可用性状态无效')
                proof = (row['detail_status'], row['detail_count'])
                if row['group_key'] in groups and groups[row['group_key']] != proof:
                    raise ValueError('共享请求组证明冲突')
                groups[row['group_key']] = proof
            if row['record_key'] != fact_key(row, detail):
                raise ValueError('解禁来源事实身份错误')
            fact = tuple(row[k] for k in (('group_key', 'holder', 'reason', 'shares') if detail else
                                         ('group_key', 'reason', 'shares')))
            facts[fact] += 1
            occurrence_sets.setdefault(fact, set()).add(row['occurrence'])
            keys.append(row['record_key'])
        if keys != sorted(set(keys)):
            raise ValueError('解禁集合重复或顺序错误')
        for fact, count in facts.items():
            if occurrence_sets[fact] != set(range(1, count + 1)):
                raise ValueError('解禁同事实出现序号缺口')
    counts = Counter(r['group_key'] for r in details)
    if set(counts) - set(groups) or any((status == 'present') != (count > 0) or counts[key] != count
        for key, (status, count) in groups.items()):
        raise ValueError('解禁列表到明细集合关联不完整')


def monthly_plan(start, end):
    day(start)
    day(end)
    if start[8:] != '01' or end[8:] != '01' or start > end:
        raise ValueError('解禁范围须为月份第一天且起止有序')
    return [f'{n // 12:04d}-{n % 12 + 1:02d}-01'
            for n in range(int(start[:4]) * 12 + int(start[5:7]) - 1,
                           int(end[:4]) * 12 + int(end[5:7]))]


def valid_proof(proof):
    if not isinstance(proof, dict) or proof.get('contract') != CONTRACT:
        return False
    if any(type(proof.get(k)) is not int or not 0 <= proof[k] <= maximum
           for k, maximum in (('count', 10000), ('details', 100000), ('empty_groups', 10000))):
        return False
    if any(not isinstance(proof.get(k), str) or not re.fullmatch('[a-f0-9]{64}', proof[k])
           for k in ('digest', 'list_digest')):
        return False
    try:
        stamp = datetime.fromisoformat(proof['observed_at'])
        return stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0
    except (KeyError, TypeError, ValueError):
        return False


def source_day(value):
    if type(value) is not int or not 19900101 <= value <= 22001231:
        raise ValueError('解禁来源日期无效')
    return day(datetime.strptime(str(value), '%Y%m%d').date().isoformat())
