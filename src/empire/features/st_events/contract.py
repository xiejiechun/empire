"""TDX ST-event identity and bounded canonical wire format."""
import hashlib
import json
from datetime import date, datetime

from empire.contracts.security import split_unified_code
from empire.core.time import CHINA

KINDS = {'implementation': ('实施ST', 'st_implementation', '2'),
         'removal': ('撤销ST', 'st_removal', '3')}
MARKETS = ('SH', 'SZ', 'BJ')
CAPACITY = 30000
COLUMNS = ('unified_code', 'event_date', 'old_name', 'new_name', 'source_occurrences',
           'csrc_industry', 'tdx_industry', 'reason')
SCHEMA_VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identity(row):
    return digest(row[:4] + [row[7]])


def project(kind):
    return 'tdx-st-' + kind


def validate_rows(kind, market, rows):
    if kind not in KINDS or market not in MARKETS or not isinstance(rows, list) or len(rows) >= CAPACITY:
        raise ValueError('ST事件类型、市场或集合上限无效')
    previous, source_count, dated = '', 0, set()
    for row in rows:
        if not isinstance(row, list) or len(row) != 8:
            raise ValueError('ST事件字段无效')
        if split_unified_code(row[0])[0] != market:
            raise ValueError('ST事件市场不一致')
        if (not isinstance(row[1], str) or date.fromisoformat(row[1]).isoformat() != row[1]
                or not '1990-01-01' <= row[1] <= datetime.now(CHINA).date().isoformat()):
            raise ValueError('ST事件日期无效')
        for value in row[2:4] + row[5:7]:
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 200):
                raise ValueError('ST事件名称类型或长度无效')
        if type(row[4]) is not int or not 1 <= row[4] < CAPACITY:
            raise ValueError('ST事件来源出现次数无效')
        if row[7] is not None and (not isinstance(row[7], str) or not row[7].strip() or len(row[7]) > 2000):
            raise ValueError('ST事件原因类型或长度无效')
        key = identity(row)
        if key <= previous:
            raise ValueError('ST事件重复或未按规范身份排序')
        previous = key
        source_count += row[4]
        dated_key = tuple(row[:2])
        if dated_key in dated or row[4] != 1:
            raise ValueError('股票ST事件证券日期重复，不能用等数量重复集合代替完整集合')
        dated.add(dated_key)
    if source_count >= CAPACITY:
        raise ValueError('ST事件来源集合达到容量边界')
    return source_count


def pack_rows(rows):
    labels = sorted({tuple(r[5:8]) for r in rows}, key=digest)
    indexes = {label: i for i, label in enumerate(labels)}
    return dict(rows=[r[:4] + [indexes[tuple(r[5:8])]] for r in rows],
                industries=[list(label) for label in labels])


def unpack_rows(rows, industries):
    if (not isinstance(rows, list) or len(rows) >= CAPACITY or not isinstance(industries, list)
            or len(industries) > len(rows) or any(not isinstance(r, list) or len(r) != 3 for r in industries)):
        raise ValueError('ST事件标签字典结构无效')
    if [digest(r) for r in industries] != sorted({digest(r) for r in industries}):
        raise ValueError('ST事件标签字典重复或未排序')
    result, used = [], set()
    for row in rows:
        if (not isinstance(row, list) or len(row) != 5 or type(row[4]) is not int
                or not 0 <= row[4] < len(industries)):
            raise ValueError('ST事件标签字典索引无效')
        used.add(row[4])
        result.append(row[:4] + [1] + industries[row[4]])
    if used != set(range(len(industries))):
        raise ValueError('ST事件标签字典含未使用标签')
    return result
