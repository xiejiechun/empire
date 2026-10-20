"""Pure official BSE mapping validation contract."""
import re
from datetime import date

URL = 'https://www.bse.cn/service/code_mapping.html'
LIMIT = 1000


def validate(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= LIMIT:
        raise ValueError('北交所映射数量超限或为空')
    legacy, current = set(), set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'legacy_code', 'unified_code', 'name', 'listing_date'}:
            raise ValueError('北交所映射字段改变')
        old, new = row['legacy_code'], row['unified_code']
        if not isinstance(old, str) or not re.fullmatch('[48][0-9]{5}', old):
            raise ValueError('北交所旧代码无效')
        if not isinstance(new, str) or not re.fullmatch(r'920[0-9]{3}\.BJ', new):
            raise ValueError('北交所新代码无效')
        if old in legacy or new in current:
            raise ValueError('北交所映射业务集合重复或冲突')
        legacy.add(old)
        current.add(new)
        if not isinstance(row['name'], str) or not 1 <= len(row['name']) <= 100 or row['name'] != row['name'].strip():
            raise ValueError('北交所证券名称无效')
        listed = date.fromisoformat(row['listing_date'])
        if listed.isoformat() != row['listing_date'] or not date(2000, 1, 1) <= listed <= date(2024, 4, 21):
            raise ValueError('北交所存量换码上市日期无效')

