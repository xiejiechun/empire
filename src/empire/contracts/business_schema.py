"""Allowlisted ownership for the explicit business-schema upgrade inventory."""
from types import MappingProxyType

FIXED_SOURCES = MappingProxyType({
    'stock': 'sina',
    'industry': 'ths', 'industry_member': 'ths',
    'income_statement': 'ths', 'balance_statement': 'ths', 'cashflow_statement': 'ths',
    'dividend_plan': 'tdx', 'additional_issue': 'tdx', 'rights_issue': 'tdx',
    'suspension_event': 'tdx', 'stock_intraday': 'kaipanla', 'trade_calendar': 'cninfo',
})
TABLES = tuple(FIXED_SOURCES) + ('finance_news', 'collection_state', 'app_setting')

DATASET_TABLES = {
    'stock.universe.start': 'stock', 'stock.universe.page': 'stock',
    'stock.universe.complete': 'stock', 'industry.snapshot': 'industry',
    'income.statement': 'income_statement', 'balance.statement': 'balance_statement',
    'cashflow.statement': 'cashflow_statement', 'dividends.unit': 'dividend_plan',
    'additional_issues.unit': 'additional_issue', 'rights_issues.unit': 'rights_issue',
    'intraday.day': 'stock_intraday', 'calendar.month': 'trade_calendar',
    'suspensions.period': 'suspension_event',
}

PRIMARY_KEYS = {
    'stock': ['unified_code'], 'industry': ['industry_code'],
    'industry_member': ['industry_code', 'unified_code'],
    'trade_calendar': ['trade_date'],
    'suspension_event': ['unified_code', 'suspended_at', 'resume_key', 'record_key'],
    'suspension_source_date': ['source_date', 'unified_code', 'suspended_at', 'resume_key', 'record_key'],
    **{t: ['record_key'] for t in ('dividend_plan', 'additional_issue', 'rights_issue')},
    **{t: ['unified_code', 'report_date'] for t in
       ('income_statement', 'balance_statement', 'cashflow_statement')},
    'stock_intraday': ['unified_code', 'trade_date'],
}


def require_dataset_source(dataset, source):
    table = DATASET_TABLES.get(dataset)
    if table:
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
