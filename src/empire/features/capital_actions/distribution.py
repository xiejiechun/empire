"""Read-only nominal cash distributions from proved, immutable security units."""
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, localcontext

from empire.contracts.preparation_scope import PreparationScope
from empire.features.capital_actions.contract import digest
from empire.features.capital_actions.event_rules import ActionError, actions
from empire.features.capital_actions.preparation import checked_units

VERSION = 'nominal-dividend-v1'
NOTICE = '名义每股含税派息，不是到账现金；各事件当期一股口径，不是期初一股收益。'
LIMITATIONS = (NOTICE, '当前来源修订版；缺稳定事件关联和逐次修订可用日，不用于历史信号。',
               '无持仓、支付日及税费；本项不计算现金收益或稀释。股息率另核验价格及股数基准，股数变化时名义金额不可当持仓收益。')


def amount_text(value):
    return format(value, 'f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else format(value, 'f')


def nominal_rows(records, start, end):
    groups = actions(records, [], start, end, include_lower=True, require_shares=False)
    by_key = {r['record_key']: r for r in records}
    rows, total = [], Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 60
        for day, group in sorted(groups.items()):
            key, values = group['dividends']
            row = by_key[key]
            cash = values[0]
            total += cash
            rows.append(dict(record_key=key, ex_date=day, report_date=row['data'].get('report_date'),
                record_date=row['data'].get('record_date'), cash_per_share=amount_text(cash),
                cash_per_ten=amount_text(cash * 10), status=row['data']['status']))
        return dict(rows=rows, cash_per_share=amount_text(total), cash_per_ten=amount_text(total * 10))


async def summarize_distribution(plugin, request):
    scope = PreparationScope.parse(request)
    if not scope.codes or len(scope.codes) > 20 or not scope.start or not scope.end:
        raise ValueError('名义派息汇总须指定1～20只证券及起止日期，不默认汇总全市场')
    checks, units = await checked_units(plugin, scope)
    return distribution_result(scope, checks, units)


def distribution_result(scope, checks, units):
    """Project already-proved immutable units; also used by multi-input snapshots."""
    result = dict(id='nominal_dividends', title='已实施名义每股派息', state='数据阻断',
        purpose=scope.purpose, scope=asdict(scope), checked_at=datetime.now(UTC).isoformat(),
        observed_at=min((c.observed_at for c in checks if c.observed_at), default=''),
        currency='CNY', unit='元/当期股（含税）', formula='Σ所选闭区间除息日的明确实施每股含税现金；每10股=每股×10',
        version=VERSION, checks=[asdict(c) for c in checks], securities=[], limitations=list(LIMITATIONS))
    blocking = [c for c in checks if c.blocking and c.status != 'pass']
    if blocking:
        result['state'] = '来源受限' if all(c.reason == 'source_limit' for c in blocking) else '数据阻断'
        result['problem'] = '；'.join(dict.fromkeys(c.measured for c in blocking))
        return result
    if len(units) != len(scope.codes) or {s[:6] for s in units} != set(scope.codes):
        result['problem'] = '完整证券单元身份缺失，不能把未证明空集当作零。'
        return result
    try:
        for security, records in units.items():
            result['securities'].append(dict(security=security,
                **nominal_rows(records, scope.start, scope.end),
                full_unit_count=len(records), unit_content_hash=digest(records)))
    except (ActionError, ValueError, KeyError, TypeError) as exc:
        result.update(problem=str(exc), identity=getattr(exc, 'identity', ''), securities=[])
        return result
    result.update(state='已计算', input_hash=digest([VERSION, asdict(scope), units]))
    return result
