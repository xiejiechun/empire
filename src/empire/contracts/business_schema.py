"""Allowlisted ownership for the explicit business-schema upgrade inventory."""
from types import MappingProxyType

from empire.contracts.market_storage import MARKET_TABLES, SERIES, dataset_tables

FIXED_SOURCES = MappingProxyType({
    **{table: 'kaipanla' for table in MARKET_TABLES},
    'stock': 'sina',
    'industry': 'ths', 'industry_member': 'ths',
    'security_name_change': 'tdx',
    'income_statement': 'ths', 'balance_statement': 'ths', 'cashflow_statement': 'ths',
    'dividend_plan': 'tdx', 'additional_issue': 'tdx', 'rights_issue': 'tdx',
    'suspension_event': 'tdx', 'stock_market_day': 'kaipanla', 'trade_calendar': 'cninfo',
})
TABLES = tuple(FIXED_SOURCES) + ('finance_news', 'collection_state', 'app_setting')

DATASET_TABLES = {
    'names.company.market': 'security_name_change', 'names.security.market': 'security_name_change',
    **{'kaipanla.' + kind + '.day': 'stock_market_day' for kind in
       ('trend', 'auction', 'volume', 'trades', 'entrust', 'large_order', 'quote')},
    'stock.universe.start': 'stock', 'stock.universe.page': 'stock',
    'stock.universe.complete': 'stock', 'industry.snapshot': 'industry',
    'income.statement': 'income_statement', 'balance.statement': 'balance_statement',
    'cashflow.statement': 'cashflow_statement', 'dividends.unit': 'dividend_plan',
    'additional_issues.unit': 'additional_issue', 'rights_issues.unit': 'rights_issue',
    'calendar.month': 'trade_calendar',
    'suspensions.period': 'suspension_event',
    'news.flash.page': 'finance_news',
}

DATASET_TABLE_GROUPS = {dataset: dataset_tables(dataset.split('.')[1]) if dataset.startswith('kaipanla.') else ('industry', 'industry_member') if dataset == 'industry.snapshot' else ('suspension_event', 'suspension_source_date') if dataset == 'suspensions.period' else (table,)
                        for dataset, table in DATASET_TABLES.items()}

PRIMARY_KEYS = {
    'security_name_change': ['name_kind', 'record_key'],
    'stock': ['unified_code'], 'industry': ['industry_code'],
    'industry_member': ['industry_code', 'unified_code'],
    'trade_calendar': ['trade_date'],
    'suspension_event': ['unified_code', 'suspended_at', 'resume_key', 'record_key'],
    'suspension_source_date': ['source_date', 'unified_code', 'suspended_at', 'resume_key', 'record_key'],
    **{t: ['record_key'] for t in ('dividend_plan', 'additional_issue', 'rights_issue')},
    **{t: ['unified_code', 'report_date'] for t in
       ('income_statement', 'balance_statement', 'cashflow_statement')},
    'stock_market_day': ['kind', 'unified_code', 'trade_date'],
    **{table: ['unified_code', 'trade_date', 'block_seq' if kind == 'trades' else 'seq' if kind == 'auction' else 'source_time']
       for kind, (table, _) in SERIES.items()},
    'stock_daily_quote': ['unified_code', 'trade_date'],
    'stock_daily_quote_level': ['unified_code', 'trade_date', 'side', 'level'],
}


def require_dataset_source(dataset, source):
    table = DATASET_TABLES.get(dataset)
    if table and table in FIXED_SOURCES:
        require_fixed_source(table, source)


def schema_contract(table, *columns):
    required = set(PRIMARY_KEYS[table]) | set(columns)
    if table in ('dividend_plan', 'additional_issue', 'rights_issue'):
        required.add('unified_code')
    return {table: required}, {table: PRIMARY_KEYS[table]}


def require_fixed_source(table, source):
    expected = FIXED_SOURCES[table]
    if source != expected:
        raise ValueError(f'{table} 固定来源不匹配；正式归属为 {expected}')
