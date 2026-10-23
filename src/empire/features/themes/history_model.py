"""Validated full directories and lossless field deltas, independent of storage."""
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from empire.core.time import CHINA

BEIJING = CHINA
FIELDS = {'theme_id', 'name', 'parent_id', 'rank_no', 'display_order',
          'hot_score', 'change_rate', 'limit_up_count', 'source_theme_id', 'concept_id', 'new_flag'}
IDENTITY = re.compile(r'[0-9]{1,32}(?:_[0-9]{1,32})?\Z')
SOURCE_ID = re.compile(r'[0-9]{1,32}\Z')


class HistoryError(ValueError):
    """Invalid, incomplete or out-of-order input cannot mutate history."""


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def digest(rows):
    return hashlib.sha256(dumps(rows).encode('utf-8')).hexdigest()


def instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise HistoryError('采样时刻必须包含时区')
    return value.astimezone(UTC)


def expiry(day):
    return int(datetime.combine(day + timedelta(days=7), datetime.min.time(), BEIJING).timestamp())


def decimal_text(value, scale, integral):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise HistoryError('数值须为无损十进制文本/整数，不接受float或bool')
    try:
        with localcontext() as context:
            context.prec = 200
            number = Decimal(value)
            if not number.is_finite() or abs(number) >= Decimal(10) ** integral:
                raise HistoryError('非有限数或数值超界')
            if number != number.quantize(Decimal(10) ** -scale):
                raise HistoryError('数值精度超界，不允许舍入')
    except InvalidOperation as exc:
        raise HistoryError('非法十进制数') from exc
    if number == 0:
        return '0'
    formatted = format(number, 'f')
    return formatted.rstrip('0').rstrip('.') if '.' in formatted else formatted


def directory(rows, max_rows=2000):
    if not isinstance(rows, list) or not 1 <= len(rows) <= max_rows:
        raise HistoryError('目录为空或超过题材数量上限')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise HistoryError('目录字段不符合现行契约')
        row = dict(row)
        key = row['theme_id']
        if not isinstance(key, str) or not IDENTITY.fullmatch(key) or key in result:
            raise HistoryError('题材身份非法或重复')
        if not isinstance(row['name'], str) or not row['name'].strip() or len(row['name']) > 128:
            raise HistoryError('题材名称缺失或超长')
        parent = row['parent_id']
        if parent is not None and (not isinstance(parent, str) or not IDENTITY.fullmatch(parent)):
            raise HistoryError('父题材身份非法')
        source, concept = row['source_theme_id'], row['concept_id']
        if not isinstance(source, str) or not SOURCE_ID.fullmatch(source):
            raise HistoryError('来源主题材ID非法')
        if type(row['new_flag']) is not int or not 0 <= row['new_flag'] <= 0xFFFFFFFF:
            raise HistoryError('来源新题材标记非法')
        if parent is None:
            if concept is not None or key != source or row['hot_score'] is None:
                raise HistoryError('主题材身份或热度缺失')
        elif (not isinstance(concept, str) or not SOURCE_ID.fullmatch(concept)
              or parent != source or key != f'{source}_{concept}'
              or row['hot_score'] is not None or row['rank_no'] is not None):
            raise HistoryError('子题材须使用父ID与CID身份，且无独立热度和排名')
        for field in ('display_order', 'limit_up_count', 'rank_no'):
            value = row[field]
            if field == 'rank_no' and value is None and (parent is not None or row['new_flag']):
                continue
            if type(value) is not int or not 0 <= value <= 2147483647:
                raise HistoryError(f'{field}缺失或非法')
        if row['hot_score'] is not None:
            row['hot_score'] = decimal_text(row['hot_score'], 6, 18)
            if Decimal(row['hot_score']) < 0:
                raise HistoryError('热度不得为负')
        # Source ratio is binary32. Its exact decimal expansion may have 149 places.
        row['change_rate'] = decimal_text(row['change_rate'], 149, 12)
        result[key] = row
    for key in result:
        seen = {key}
        parent = result[key]['parent_id']
        while parent is not None:
            if parent not in result or parent in seen:
                raise HistoryError('父题材缺失或层级循环')
            seen.add(parent)
            parent = result[parent]['parent_id']
    return result


def delta(before, after):
    return {'added': {k: after[k] for k in sorted(after.keys() - before.keys())},
            'removed': sorted(before.keys() - after.keys()),
            'changed': {k: {f: v for f, v in after[k].items() if before[k][f] != v}
                        for k in sorted(before.keys() & after.keys()) if before[k] != after[k]}}


def apply_delta(before, change, max_rows=2000):
    if not isinstance(change, dict) or set(change) != {'added', 'removed', 'changed'}:
        raise HistoryError('差异结构损坏')
    added, removed, changed = change['added'], change['removed'], change['changed']
    if (not isinstance(added, dict) or not isinstance(removed, list) or not isinstance(changed, dict)
            or any(not isinstance(k, str) for k in removed) or len(set(removed)) != len(removed)):
        raise HistoryError('差异身份损坏')
    if (set(added) & set(before) or not set(removed) <= set(before)
            or not set(changed) <= set(before) or set(changed) & set(removed)):
        raise HistoryError('差异不属于前一状态')
    after = {k: dict(v) for k, v in before.items() if k not in removed}
    after.update(added)
    for key, fields in changed.items():
        if not isinstance(fields, dict) or not fields or set(fields) - (FIELDS - {'theme_id'}):
            raise HistoryError('差异包含非法字段')
        after[key].update(fields)
    checked = directory(list(after.values()), max_rows)
    if checked != after:
        raise HistoryError('历史包含非规范内容或键身份不符')
    return checked
