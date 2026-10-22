"""Independent rational arithmetic on formal raw snapshot fields, no calculator import."""
import json
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
p=Path(__file__).parent
r=json.loads((p/'current.json').read_text('utf8'))
rows=[]
for raw in r['oracle_snapshot_dividends']:
    data=json.loads(raw['payload']) if isinstance(raw['payload'],str) else raw['payload']
    if data['status']=='实施方案' and data.get('ex_date') and '2026-01-01'<=data['ex_date']<='2026-10-20':
        assert data['tax_basis']=='含税'
        rows.append(dict(record_key=raw['record_key'],ex_date=data['ex_date'],cash=data['cash_per_share']))
assert len(rows)==2 and len({x['ex_date'] for x in rows})==2
cash=sum((Fraction(x['cash']) for x in rows),Fraction(0))
quote=r['oracle_quote'][0]
assert (quote['code'],quote['market'],quote['trade_date'])==('000001','SZ','2026-10-20')
price=Fraction(str(quote['data']['real']['last_px']))
percent=cash/price*100
actual=r['cases']['main']['yield_result']['securities'][0]
assert {x['record_key'] for x in actual['rows']}=={x['record_key'] for x in rows}
assert Fraction(actual['cash_per_share'])==cash
assert Fraction(actual['cash_per_ten'])==cash*10
with localcontext() as ctx:
    ctx.prec=60
    expected=Decimal(percent.numerator)/Decimal(percent.denominator)
    assert Decimal(actual['yield_percent'])==expected
out=dict(raw_events=rows,cash_fraction=str(cash),cash_per_ten=str(cash*10),price=str(price),denominator_date=quote['trade_date'],source_clock=quote['data']['real']['time'],price_heads=r['oracle_price_heads'],percent_fraction=str(percent),percent_decimal=str(expected),matches_current_product=True,
    boundary_results={k:r['cases'][k]['distribution']['securities'][0]['cash_per_share'] for k in ['2026-06-11','2026-06-12','2026-09-23','2026-09-24']})
assert list(out['boundary_results'].values())==['0','0.36','0.36','0.609']
(p/'independent-oracle.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(out,ensure_ascii=False))
