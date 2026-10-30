"""Typed ordering of the existing bounded capital-action payload contract."""

from empire.plugins.infra.query_order import column_fields

NUMBERS = {
    'dividends': ('cash_per_share', 'bonus_per_share', 'transfer_per_share', 'total_bonus_per_share',
                  'earnings_per_share', 'net_assets_per_share', 'capital_reserve_per_share', 'retained_profit_per_share'),
    'additional_issues': ('issued_shares', 'issue_price', 'shares_before', 'shares_after', 'lock_months'),
    'rights_issues': ('rights_per_share', 'rights_price', 'issued_shares', 'shares_before', 'shares_after'),
}
TEXT = {
    'dividends': ('report_date', 'status', 'record_date', 'ex_date', 'announcement_date', 'tax_basis'),
    'additional_issues': ('issue_method', 'issue_date', 'listing_date', 'record_date', 'subscription_code',
                          'public_issue_date', 'private_issue_date', 'status'),
    'rights_issues': ('record_date', 'ex_date', 'payment_start', 'payment_end', 'listing_date', 'subscription_code', 'status'),
}


def sort_fields(kind):
    fields = column_fields(('record_key', 'unified_code', 'name', 'event_date', 'market', 'code'))
    for key in (*TEXT[kind], *NUMBERS[kind]):
        value = f"NULLIF(JSON_UNQUOTE(JSON_EXTRACT(q.payload,'$.{key}')),'null')"
        fields[key] = f'CAST({value} AS DECIMAL(65,30))' if key in NUMBERS[kind] else value
    return fields
