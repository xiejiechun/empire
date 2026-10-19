"""Current market/code identity; never infer aliases or permanent issuer identity."""
import re

MARKETS = frozenset(('SH', 'SZ', 'BJ'))


def unified_code(market, code):
    if not isinstance(market, str) or market not in MARKETS or not isinstance(code, str) or not re.fullmatch('[0-9]{6}', code):
        raise ValueError('证券身份须为 SH/SZ/BJ 市场及保留前导零的六位代码')
    return code + '.' + market


def split_unified_code(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)', value):
        raise ValueError('统一证券代码须为六位代码.市场')
    code, market = value.split('.')
    return market, code


def unit_identity(value):
    if not isinstance(value, str) or not re.fullmatch('(SH|SZ|BJ):[0-9]{6}', value):
        raise ValueError('证券单元须为市场:六位代码')
    market, code = value.split(':')
    return unified_code(market, code)


def index_code(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9A-Z]{6}', value):
        raise ValueError('指数来源编号无效')
    return value
