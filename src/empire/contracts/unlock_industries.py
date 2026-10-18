"""Monthly source industry summaries, with an explicit valuation basis."""
import re
from datetime import UTC, date, datetime
from decimal import Decimal

from empire.contracts.unlocks import canonical_number, digest, shares, text_value
from empire.core.time import CHINA

PROJECT = 'tdx-unlock-industries'
JOB = PROJECT + '-v1'
DATASET = 'unlocks.tdx_industry_month'
TABLE = 'restricted_share_unlock_industry'
NUMBERS = ('shares', 'unlock_value', 'market_cap', 'negotiable_cap', 'market_percent', 'float_percent')
COLUMNS = ('unlock_month', 'industry', 'basis_date', *NUMBERS)


def month(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-01', value):
        raise ValueError('解禁行业月份必须为YYYY-MM-01')
    date.fromisoformat(value)
    return value


def basis(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('解禁行业基准日错误')
    if date.fromisoformat(value) > datetime.now(CHINA).date():
        raise ValueError('解禁行业基准日超前')
    return value


def version(basis_date, observed):
    first = datetime.combine(date.fromisoformat(basis(basis_date)), datetime.min.time(), CHINA)
    return [first.astimezone(UTC).isoformat(timespec='microseconds'),
            observed.astimezone(UTC).isoformat(timespec='microseconds')]


def validate(unit, basis_date, rows):
    month(unit)
    basis(basis_date)
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError('解禁行业完整月容量错误')
    last = ''
    for row in rows:
        if (not isinstance(row, dict) or set(row) != set(COLUMNS) or row['unlock_month'] != unit
                or row['basis_date'] != basis_date or text_value(row['industry'], 200, True) != row['industry']
                or row['industry'] <= last):
            raise ValueError('解禁行业字段、关联、重复或顺序错误')
        last = row['industry']
        for key in NUMBERS:
            if canonical_number(shares(row[key])) != row[key]:
                raise ValueError('解禁行业数值未规范化')
            if row[key] is not None and Decimal(row[key]) < 0:
                raise ValueError('解禁行业数值为负')


__all__ = ['COLUMNS', 'DATASET', 'JOB', 'NUMBERS', 'PROJECT', 'TABLE', 'basis',
           'canonical_number', 'digest', 'month', 'validate', 'version']
