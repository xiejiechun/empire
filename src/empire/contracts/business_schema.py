"""Allowlisted ownership for the explicit business-schema upgrade inventory."""
from types import MappingProxyType

from empire.contracts.market_storage import MARKET_TABLES, SERIES, dataset_tables
from empire.contracts.ths_capital import TABLES as CAPITAL_PAGE_TABLES

FIXED_SOURCES = MappingProxyType({
    **{table: 'ths' for table in CAPITAL_PAGE_TABLES},
    'restricted_share_unlock_industry': 'tdx', 'restricted_share_unlock': 'tdx', 'restricted_share_unlock_detail': 'tdx',
    'shareholder_change': 'tdx',
    'holder_report': 'ths', 'holder_member': 'ths',
    **{table: 'tdx' for table in ('earnings_forecast', 'earnings_quick', 'earnings_disclosure',
                                'earnings_report', 'shareholder_count')},
    'stock_repurchase_plan': 'eastmoney',
    'trading_rule_value': 'reviewed_rules', 'trading_rule_citation': 'reviewed_rules',
    'index_daily_price': 'ths', 'index_price_year': 'ths',
    'security_code_alias': 'bse',
    'stock_index': 'ths', 'stock_index_member': 'ths',
    'security_listing_event': 'tdx',
    'stock_listing': 'ths',
    **{table: 'kaipanla' for table in MARKET_TABLES},
    'stock': 'sina',
    'industry': 'ths', 'industry_member': 'ths',
    'security_name_change': 'tdx', 'security_st_event': 'tdx',
    'income_statement': 'ths', 'balance_statement': 'ths', 'cashflow_statement': 'ths',
    'dividend_plan': 'tdx', 'additional_issue': 'tdx', 'rights_issue': 'tdx',
    'suspension_event': 'tdx', 'stock_market_day': 'kaipanla', 'trade_calendar': 'cninfo',
})
TABLES = tuple(FIXED_SOURCES) + ('finance_news', 'collection_state', 'app_setting')

DATASET_TABLES = {
    'ths.capital.security': CAPITAL_PAGE_TABLES[0],
    'unlocks.tdx_industry_month': 'restricted_share_unlock_industry',
    'unlocks.tdx_month': 'restricted_share_unlock',
    'shareholder_changes.tdx_unit': 'shareholder_change',
    'holders.reports': 'holder_report',
    **{kind + '.tdx_unit': table for kind, table in (
        ('earnings_forecast', 'earnings_forecast'), ('earnings_quick', 'earnings_quick'),
        ('earnings_disclosure', 'earnings_disclosure'), ('earnings_report', 'earnings_report'),
        ('holder_count', 'shareholder_count'))},
    'repurchases.page': 'stock_repurchase_plan',
    **{'rules.' + k + '.complete': 'trading_rule_value' for k in ('limit_rules', 'settlement_rules', 'lot_rules', 'tick_rules', 'sessions', 'stamp_duty', 'transfer_fee')},
    'index.price.year': 'index_daily_price', 'index.price.status': 'index_daily_price',
    'bse.code_mapping.complete': 'security_code_alias',
    'index.catalog': 'stock_index', 'index.members': 'stock_index',
    'listing_status.month': 'security_listing_event',
    'listing.detail': 'stock_listing',
    'st.implementation.market': 'security_st_event', 'st.removal.market': 'security_st_event',
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

DATASET_TABLE_GROUPS = {dataset: CAPITAL_PAGE_TABLES if dataset == 'ths.capital.security' else ('restricted_share_unlock', 'restricted_share_unlock_detail') if dataset == 'unlocks.tdx_month' else ('holder_report', 'holder_member') if dataset == 'holders.reports' else ('trading_rule_value', 'trading_rule_citation') if dataset.startswith('rules.') else ('index_daily_price', 'index_price_year') if dataset.startswith('index.price.') else ('stock_index', 'stock_index_member') if dataset.startswith('index.') else dataset_tables(dataset.split('.')[1]) if dataset.startswith('kaipanla.') else ('industry', 'industry_member') if dataset == 'industry.snapshot' else ('suspension_event', 'suspension_source_date') if dataset == 'suspensions.period' else (table,)
                        for dataset, table in DATASET_TABLES.items()}

PRIMARY_KEYS = {
    **{table: ['record_key'] for table in CAPITAL_PAGE_TABLES},
    'restricted_share_unlock_industry': ['unlock_month', 'industry'],
    'restricted_share_unlock': ['record_key'], 'restricted_share_unlock_detail': ['group_key', 'record_key'],
    'shareholder_change': ['record_key'],
    'holder_report': ['report_key'], 'holder_member': ['report_key', 'member_group', 'seq'],
    **{table: ['record_key'] for table in ('earnings_forecast', 'earnings_quick', 'earnings_disclosure',
                                        'earnings_report', 'shareholder_count')},
    'stock_repurchase_plan': ['plan_id'],
    'trading_rule_value': ['record_key'], 'trading_rule_citation': ['citation_key'],
    'index_daily_price': ['index_code', 'trade_date'], 'index_price_year': ['index_code', 'quote_year'],
    'security_code_alias': ['legacy_code'],
    'stock_index': ['index_code'], 'stock_index_member': ['index_code', 'source_code'],
    'security_listing_event': ['event_date', 'unified_code', 'event_type', 'record_key'],
    'stock_listing': ['unified_code'],
    'security_name_change': ['name_kind', 'record_key'],
    'security_st_event': ['event_kind', 'record_key'],
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
    if table == 'stock' and source in ('sina', 'ths'):
        return
    expected = FIXED_SOURCES[table]
    if source != expected:
        raise ValueError(f'{table} 固定来源不匹配；正式归属为 {expected}')
