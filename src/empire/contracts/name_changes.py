"""TDX name-event identity and bounded canonical wire format."""
import hashlib
import json
from datetime import date

from empire.contracts.security import split_unified_code

KINDS = {'company': ('公司更名', 'company_renames', '0'),
         'security': ('股票更名', 'renames', '1')}
MARKETS = ('SH', 'SZ', 'BJ')
CAPACITY = 30000
COLUMNS = ('unified_code', 'event_date', 'old_name', 'new_name', 'source_occurrences')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identity(row):
    return digest(row[:4])


def project(kind):
    return 'tdx-' + kind + '-renames'


def validate_rows(kind, market, rows):
    if kind not in KINDS or market not in MARKETS or not isinstance(rows, list) or len(rows) >= CAPACITY:
        raise ValueError('更名类型、市场或集合上限无效')
    previous, source_count, dated = '', 0, set()
    for row in rows:
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError('更名事件字段无效')
        if split_unified_code(row[0])[0] != market:
            raise ValueError('更名事件市场不一致')
        if (not isinstance(row[1], str) or date.fromisoformat(row[1]).isoformat() != row[1]
                or not '1990-01-01' <= row[1] <= date.today().isoformat()):
            raise ValueError('更名日期无效')
        for value in row[2:4]:
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 200):
                raise ValueError('更名名称类型或长度无效')
        if type(row[4]) is not int or not 1 <= row[4] < CAPACITY:
            raise ValueError('更名来源出现次数无效')
        key = identity(row)
        if key <= previous:
            raise ValueError('更名事件重复或未按规范身份排序')
        previous = key
        source_count += row[4]
        dated_key = tuple(row[:2])
        if kind == 'security' and (dated_key in dated or row[4] != 1):
            raise ValueError('股票更名证券日期重复，不能用等数量重复集合代替完整集合')
        dated.add(dated_key)
    if source_count >= CAPACITY:
        raise ValueError('更名来源集合达到容量边界')
    return source_count
