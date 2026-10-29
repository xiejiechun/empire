"""Explicit source identities, typed fields and bounded complete units."""
from datetime import date

SOURCE = 'ths_yuanhang'
DOMAIN = '10jqka.com.cn'
BASE_URL = 'http://dq.10jqka.com.cn/fuyao/pc_hevo_ztjj/focus_limit_up/v1/'
FILTER = 'HS,GEM2STAR'
POOLS = {
    'limit_up_pool': '涨停板',
    'sprint_limit_up': '涨停冲刺',
    'connect_broad_pool': '连板池',
    'open_limit_up_pool': '炸板池',
    'limit_down_pool': '跌停板',
}
PAGE_SIZE = 100
MAX_MEMBERS = 10000
MAX_UNIT_BYTES = 8 * 1024 * 1024
DECIMAL_FIELDS = ('change_rate', 'latest', 'turnover_rate', 'currency_value',
                  'sum_market_value', 'rise_rate', 'turnover', 'order_amount',
                  'order_volume', 'limit_up_suc_rate')
TIME_FIELDS = ('first_limit_up_time', 'last_limit_up_time',
               'first_limit_down_time', 'last_limit_down_time')
INTEGER_FIELDS = ('open_num', 'high_days_value', 'is_new', 'is_again_limit')
TEXT_LIMITS = {'name': 80, 'market_type': 32, 'reason_type': 4096,
               'limit_up_type': 128, 'limit_down_type': 128,
               'high_days': 80, 'change_tag': 80, '941948930': 1024}
REQUEST_FIELDS = ','.join((*DECIMAL_FIELDS, *TIME_FIELDS, 'open_num',
                           'name', 'reason_type', 'limit_up_type', 'limit_down_type',
                           'high_days', '941948930'))
MARKETS = {17: 'SH', 22: 'SH', 33: 'SZ', 151: 'BJ'}
BOARD_MARKETS = {'GEM': 'SZ', 'STAR': 'SH'}
MEMBER_FIELDS = ('unified_code', 'source_market_id', 'identity_basis', *DECIMAL_FIELDS, *INTEGER_FIELDS,
                 *(k if k != '941948930' else 'top_concept' for k in TEXT_LIMITS), *TIME_FIELDS)
POOL_FIELDS = ('trade_date', 'pool_type', 'source_total', 'filter_text',
               'key_sha256', 'content_sha256', 'contract_version', 'observed_at')
REASON_FIELDS = ('trade_date', 'unified_code', 'name', 'reason_text', 'reason_kind',
                 'availability', 'content_sha256', 'observed_at')
TABLE_COLUMNS = {'yuanhang_limit_pool': POOL_FIELDS,
                 'yuanhang_limit_member': ('trade_date', 'pool_type', *MEMBER_FIELDS),
                 'yuanhang_limit_reason': REASON_FIELDS}


def project(pool):
    if pool != 'reason':
        pool_value(pool)
    return 'ths-yuanhang-' + pool.replace('_', '-')


def job(pool):
    return project(pool) + '-v1'


def dataset(pool):
    if pool != 'reason':
        pool_value(pool)
    return 'yuanhang.limits.' + pool


def day_value(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('涨停分析日期须为YYYY-MM-DD')
    return value


def pool_value(value):
    if value not in POOLS:
        raise ValueError('未知远航涨停分析池')
    return value
