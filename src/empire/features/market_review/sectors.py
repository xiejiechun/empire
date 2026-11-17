"""Current industry membership applied to the selected day's archived flows."""
import json
from decimal import Decimal

from empire.features.industries.api import STATE_DATASET, verify_current_snapshot
from empire.features.industries.contract import market


def empty_sectors():
    return dict(inflow=None, outflow=None, basis_observed_at=None, industry_count=0,
                complete_count=0, partial_count=0, uncovered_count=0, issue='')


def read_sectors(rows, day, namespace):
    result = empty_sectors()
    industries = rows('SELECT industry_code,name FROM industry ORDER BY industry_code LIMIT 501')
    members = rows('SELECT m.industry_code,m.unified_code,m.name,g.main_flow '
        'FROM industry_member m LEFT JOIN graymarket_daily g '
        'ON g.unified_code=m.unified_code AND g.trade_date=:day '
        'ORDER BY m.industry_code,m.unified_code LIMIT 15001', day=day)
    states = rows('SELECT source,dataset,payload FROM collection_state '
        'WHERE namespace=:namespace AND project_id=:project', namespace=namespace, project='ths-industries')
    try:
        if len(industries) > 500 or len(members) > 15000:
            raise ValueError('行业目录或成分超过复盘读取上限')
        snapshots = {r['industry_code']: dict(code=r['industry_code'], name=r['name'], members=[])
                     for r in industries}
        totals = {code: dict(industry_code=code, name=entry['name'], member_count=0,
                             covered_count=0, amount_yuan=None) for code, entry in snapshots.items()}
        for member in members:
            code, security = member['industry_code'], member['unified_code']
            if code not in snapshots or security != f'{security[:6]}.{market(security[:6])}':
                raise ValueError('行业成分关联或证券市场无效')
            snapshots[code]['members'].append([security[:6], member['name']])
            item = totals[code]
            item['member_count'] += 1
            if member['main_flow'] is not None:
                item['covered_count'] += 1
                item['amount_yuan'] = (item['amount_yuan'] or Decimal(0)) + member['main_flow']
        if not states or states[0]['source'] != 'ths' or states[0]['dataset'] != STATE_DATASET:
            raise ValueError('行业成分缺少当前命名空间的归档证明')
        state = states[0]['payload']
        state = json.loads(state) if isinstance(state, str) else state
        observed = verify_current_snapshot(list(snapshots.values()), state)
    except (ValueError, TypeError, KeyError) as error:
        result['issue'] = str(error)
        return result
    values = list(totals.values())
    result.update(basis_observed_at=observed, industry_count=len(values),
                  complete_count=sum(r['covered_count'] == r['member_count'] for r in values),
                  partial_count=sum(0 < r['covered_count'] < r['member_count'] for r in values),
                  uncovered_count=sum(r['covered_count'] == 0 for r in values))
    if not any(r['covered_count'] for r in values):
        result['issue'] = '所选日资金榜未覆盖当前行业成分'
        return result
    for key, sign in (('inflow', 1), ('outflow', -1)):
        candidates = [r for r in values if r['amount_yuan'] is not None and r['amount_yuan'] * sign > 0]
        result[key] = sorted(candidates, key=lambda r: (-r['amount_yuan'] * sign, r['industry_code']))[:5]
    return result
