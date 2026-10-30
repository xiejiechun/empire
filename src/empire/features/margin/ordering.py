"""SQL counterparts of the formal financing/lending display formulas."""


def sort_fields():
    return {
        'financing_repaid': 'COALESCE(q.previous_financing,0)+q.financing_buy-q.financing_balance',
        'lending_repaid': 'COALESCE(q.previous_lending,0)+q.lending_sell-q.lending_balance',
        'first_source_row': '(q.previous_financing IS NULL)',
        'lending_amount': 'q.lending_balance*q.close_price',
        'margin_difference': 'q.financing_balance-q.lending_balance*q.close_price',
        'financing_buy_pct': 'CAST(CAST(q.financing_buy AS DECIMAL(65,30))/NULLIF(q.market_turnover,0)*100 AS DECIMAL(65,30))',
        'lending_sell_pct': 'CAST(CAST(q.lending_sell AS DECIMAL(65,30))/NULLIF(q.market_volume,0)*100 AS DECIMAL(65,30))',
    }
