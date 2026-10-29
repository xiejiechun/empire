"""Typed storage identities and lossless source conversions, before SQL writes."""
import struct
from datetime import UTC, datetime
from decimal import Decimal

from empire.contracts.security import split_unified_code
from empire.core.time import CHINA, mysql_time
from empire.features.themes.detail_model import DetailError, source_id
from empire.features.themes.history_model import decimal_text, digest, directory

LIST_PROJECT = 'kaipanla-themes'
DETAIL_PROJECT = 'kaipanla-theme-details'
LIST_JOB = LIST_PROJECT + '-v1'
DETAIL_JOB = DETAIL_PROJECT + '-v1'
LIST_DATASET = 'kaipanla.themes.day'
DETAIL_DATASET = 'kaipanla.themes.detail'
DAILY_FIELDS = ('theme_id', 'source_theme_id', 'concept_id', 'name', 'parent_id',
                'new_flag', 'rank_no', 'display_order', 'hot_score', 'change_rate', 'limit_up_count')
HEAD_FIELDS = ('theme_id', 'name', 'brief', 'introduction', 'source_created_at', 'source_updated_at')
CATEGORY_FIELDS = ('category_id', 'parent_id', 'name', 'order', 'plate_code',
                   'first_shelved_at', 'updated_at', 'is_new')
STOCK_FIELDS = ('source_stock_id', 'name', 'unified_code')
RELATION_FIELDS = ('relation_id', 'category_id', 'source_stock_id', 'reason',
                   'first_shelved_at', 'updated_at', 'is_new', 'is_hot', 'source_is_zz', 'occurrences')
TIME_FIELDS = frozenset(('source_created_at', 'source_updated_at', 'first_shelved_at', 'updated_at'))


def source_time(value):
    """Epoch seconds, not a date inferred from the device's local timezone."""
    if value is None:
        return None
    if type(value) is not int or value < 1:
        raise DetailError('来源时间须为正整数秒或未提供')
    try:
        result = datetime.fromtimestamp(value, CHINA).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError) as exc:
        raise DetailError('来源时间超出存储日期范围') from exc
    if result.year < 1000:
        raise DetailError('来源时间超出MySQL日期范围')
    return result


def epoch(value):
    return None if value is None else int(value.replace(tzinfo=CHINA).timestamp())


def binary32(value):
    """Canonical source binary32 stored exactly inside a MySQL DOUBLE."""
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]


def list_rows(rows):
    normalized = directory(rows)
    for row in normalized.values():
        score = row['hot_score']
        if score is not None and Decimal(score) != int(Decimal(score)):
            raise ValueError('来源热度必须为整数')
        exact = decimal_text(Decimal.from_float(binary32(row['change_rate'])), 149, 12)
        if exact != row['change_rate']:
            raise ValueError('涨跌幅不是来源binary32精确值')
    return [normalized[k] for k in sorted(normalized)]


def daily_record(row, day, observed):
    return {**row, 'business_date': day, 'hot_score': None if row['hot_score'] is None else int(row['hot_score']),
            'change_rate': binary32(row['change_rate']), 'observed_at': mysql_time(observed)}


def decode_daily(record):
    row = {k: record[k] for k in DAILY_FIELDS}
    row['hot_score'] = None if row['hot_score'] is None else str(row['hot_score'])
    row['change_rate'] = decimal_text(Decimal.from_float(binary32(row['change_rate'])), 149, 12)
    return row


def security_map(identities):
    """Use verified identities; ambiguity never becomes a prefix-based guess."""
    result = {}
    for identity in identities:
        _, code = split_unified_code(identity)
        if code in result and result[code] != identity:
            raise DetailError('六位来源证券代码对应多个市场，须核实')
        result[code] = identity
    return result


def map_detail(detail, identities):
    mapping = security_map(identities)
    stocks = []
    for stock in detail['stocks']:
        identity = mapping.get(stock['source_stock_id'])
        if identity is None:
            raise DetailError(f'来源证券代码缺少正式市场映射：{stock["source_stock_id"]}')
        stocks.append({**stock, 'unified_code': identity})
    return {**detail, 'stocks': sorted(stocks, key=lambda row: row['source_stock_id'])}


def validate_detail(value):
    """Validate the queue boundary independently of the downloader's parser."""
    if not isinstance(value, dict) or set(value) != {*HEAD_FIELDS, 'categories', 'stocks', 'relations'}:
        raise DetailError('正式详情字段错误')
    source_id(value['theme_id'])
    for key, cap in (('name', 128), ('brief', 65536), ('introduction', 1048576)):
        item = value[key]
        if (not isinstance(item, str) or len(item.encode()) > cap or '\x00' in item
                or key == 'name' and (not item.strip() or '***' in item)):
            raise DetailError('正式详情文本无效')
    for key in ('source_created_at', 'source_updated_at'):
        source_time(value[key])
    categories, stocks, relations = {}, {}, set()
    for name, limit in (('categories', 5000), ('stocks', 10000), ('relations', 50000)):
        if not isinstance(value[name], list) or len(value[name]) > limit:
            raise DetailError('正式详情集合超限')
    for row in value['categories']:
        if not isinstance(row, dict) or set(row) != set(CATEGORY_FIELDS):
            raise DetailError('正式分类字段错误')
        cid = source_id(row['category_id'])
        if cid in categories or type(row['order']) is not int or row['order'] != len(categories):
            raise DetailError('正式分类重复或顺序错误')
        if row['parent_id'] is not None and row['parent_id'] not in categories:
            raise DetailError('正式分类父节点缺失或循环')
        _child_values(row)
        categories[cid] = row
    for row in value['stocks']:
        if not isinstance(row, dict) or set(row) != set(STOCK_FIELDS):
            raise DetailError('正式股票字段错误')
        _, code = split_unified_code(row['unified_code'])
        if code != row['source_stock_id'] or code in stocks:
            raise DetailError('正式股票映射或身份重复')
        _child_values(row)
        stocks[code] = row
    count, associated = 0, set()
    for row in value['relations']:
        if not isinstance(row, dict) or set(row) != set(RELATION_FIELDS):
            raise DetailError('正式关联字段错误')
        content = {k: row[k] for k in RELATION_FIELDS if k not in ('relation_id', 'occurrences')}
        rid = digest(content)
        if (row['relation_id'] != rid or rid in relations or row['source_stock_id'] not in stocks
                or row['category_id'] is not None and row['category_id'] not in categories
                or type(row['occurrences']) is not int or not 1 <= row['occurrences'] <= 50000):
            raise DetailError('正式关联身份、次数或必需关联错误')
        _child_values(row)
        count += row['occurrences']
        relations.add(rid)
        associated.add(row['source_stock_id'])
    if count > 50000 or associated != stocks.keys():
        raise DetailError('正式证券集合与关联集合不一致或超限')
    return value


def _child_values(row):
    for key, value in row.items():
        if key in TIME_FIELDS:
            source_time(value)
        if key in ('is_new', 'is_hot', 'source_is_zz'):
            if type(value) is not int or not 0 <= value <= 999999999999:
                raise DetailError('正式来源标记无效')
        if key in ('name', 'reason', 'plate_code'):
            cap = {'name': 128, 'reason': 65536, 'plate_code': 32}[key]
            if (not isinstance(value, str) or len(value.encode()) > cap or '\x00' in value
                    or key == 'name' and not value.strip()
                    or key != 'plate_code' and '***' in value):
                raise DetailError('正式关联文本无效')


def detail_version(value, observed):
    stamp = source_time(value['source_updated_at'])
    source = stamp.replace(tzinfo=CHINA).astimezone(UTC) if stamp else datetime(1970, 1, 1, tzinfo=UTC)
    return [source.isoformat(timespec='microseconds'), observed.astimezone(UTC).isoformat(timespec='microseconds')]
