"""Fixed ownership and bounded typed SQL entities for native PC histories."""
from empire.sources.yuanhang_payload import ACTION_FIELDS, PRICE_FIELDS

SOURCE = 'ths_yuanhang'
PRICE_PROJECT = 'ths-yuanhang-prices'
FINANCIAL_PROJECT = 'ths-yuanhang-financial'
PRICE_JOB = PRICE_PROJECT + '-v1'
FINANCIAL_JOB = FINANCIAL_PROJECT + '-v1'
PRICE_DATASET = 'yuanhang.price.year'
FINANCIAL_DATASET = 'yuanhang.financial'
PROOF_FIELDS = ('native_market', 'source_count', 'row_count', 'first_date', 'last_date',
                'key_hash', 'content_hash', 'contract_version')
TABLE_COLUMNS = {
    'yuanhang_daily_price': ('unified_code', 'trade_date', *PRICE_FIELDS),
    'yuanhang_price_year': ('unified_code', 'quote_year', *PROOF_FIELDS,
                            'verified_through', 'version_observed_at'),
    'yuanhang_corporate_action': ('unified_code', 'ex_date', 'event_key', *ACTION_FIELDS),
    'yuanhang_capital': ('unified_code', 'capital_kind', 'effective_date', 'shares'),
    'yuanhang_series_proof': ('unified_code', 'series_kind', *PROOF_FIELDS, 'response_group',
                              'total_count', 'circulating_count', 'free_float_count',
                              'version_observed_at'),
}
KEYS = {table: list(columns[:n]) for table, columns, n in (
    ('yuanhang_daily_price', TABLE_COLUMNS['yuanhang_daily_price'], 2),
    ('yuanhang_price_year', TABLE_COLUMNS['yuanhang_price_year'], 2),
    ('yuanhang_corporate_action', TABLE_COLUMNS['yuanhang_corporate_action'], 3),
    ('yuanhang_capital', TABLE_COLUMNS['yuanhang_capital'], 3),
    ('yuanhang_series_proof', TABLE_COLUMNS['yuanhang_series_proof'], 2),
)}
