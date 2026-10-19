"""Public pure fields extracted without business-rule changes."""
from datetime import date
from decimal import Decimal, InvalidOperation


class TdxSourceError(ValueError):
    """An explicit TDX business error must never be treated as a valid empty unit."""

    def __init__(self, code, operation):
        self.source_error_code = code
        info = '数据库执行失败' if code == -1005 else '源站业务错误'
        super().__init__(f'{operation}请求失败：通达信 ErrorCode={code}，{info}；数据未补齐')


def day(value, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('来源日期格式无效')
    if value < '1980-01-01':
        raise ValueError('来源日期超出支持范围')
    return value


def number(value, scale=1, *, required=False, signed=False):
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('来源数值无效')
    try:
        result = Decimal(str(value)) * Decimal(str(scale))
    except InvalidOperation:
        raise ValueError('来源数值无效') from None
    if not result.is_finite() or abs(result) > Decimal('1e18') or (result < 0 and not signed):
        raise ValueError('来源数值越界')
    return format(result.normalize(), 'f')
