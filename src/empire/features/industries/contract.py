"""Current domestic-equity industry identifiers."""
import re

MEMBER_LIMIT = 1000


def name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise ValueError('行业或证券名称无效')
    return value.strip()


def market(code):
    if not isinstance(code, str) or not re.fullmatch(r'(?:[03468][0-9]{5}|92[0-9]{4})', code):
        raise ValueError('行业成分证券代码无效或不支持的市场')
    return 'SH' if code.startswith('6') else 'SZ' if code[0] in '03' else 'BJ'
