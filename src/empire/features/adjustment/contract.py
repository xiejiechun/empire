"""Bounded theoretical ex-rights factors from explicit business inputs."""
from datetime import date
from decimal import Decimal, localcontext

from empire.features.capital_actions.event_rules import ActionError, actions, decimal, iso

ALGORITHM = 'empire-ex-rights-v1'
MAX_DAYS = 3660
MAX_ROWS = 10000


def ex_reference(previous_close, cash, shares, rights, rights_price):
    with localcontext() as ctx:
        ctx.prec = 50
        p = decimal(previous_close, positive=True)
        d, s, r, a = (decimal(v) for v in (cash, shares, rights, rights_price))
        if d >= p:
            raise ActionError('含税现金分红不应达到或超过前收盘价，需要核实来源或特殊事件')
        return decimal((p - d + a * r) / (1 + s + r), positive=True)


def calculate(prices, dividends, rights):
    if not prices or len(prices) > MAX_ROWS:
        raise ActionError('原始行情为空或超过计算上限')
    days = [iso(p['date']) for p in prices]
    if days != sorted(set(days)):
        raise ActionError('原始行情日期重复或乱序')
    if (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days > MAX_DAYS:
        raise ActionError('计算日期范围超过3660日')
    groups = actions(dividends, rights, days[0], days[-1])
    missing = sorted(set(groups) - set(days))
    if missing:
        raise ActionError('除权日缺少收盘后行情或处于停牌区间，本版本不推断参考价', day=missing[0])
    result, factor, prior = [], Decimal(1), None
    with localcontext() as ctx:
        ctx.prec = 50
        for item, day in zip(prices, days, strict=True):
            values = {k: decimal(item[k], positive=True) for k in ('open', 'high', 'low', 'close')}
            if not values['low'] <= min(values['open'], values['close']) <= max(values['open'], values['close']) <= values['high']:
                raise ActionError('原始行情开收盘不在日高低价区间', day=day)
            group, used, reference = groups.get(day, {}), [], None
            if group:
                cash, shares = group.get('dividends', ('', [Decimal(0), Decimal(0)]))[1]
                ratio, price = group.get('rights', ('', [Decimal(0), Decimal(0)]))[1]
                try:
                    reference = ex_reference(prior, cash, shares, ratio, price)
                except ActionError as exc:
                    raise ActionError(str(exc), day=day) from None
                factor = decimal(factor * prior / reference, positive=True)
                used = [v[0] for v in group.values()]
            result.append(dict(date=day, factor=factor, **values, events=used, reference=reference))
            prior = values['close']
        last = result[-1]['factor']
        for row in result:
            row['forward_multiplier'], row['backward_multiplier'] = row['factor'] / last, row['factor']
            for key in ('open', 'high', 'low', 'close'):
                row['forward_' + key] = row[key] * row['forward_multiplier']
                row['backward_' + key] = row[key] * row['backward_multiplier']
            for key, value in list(row.items()):
                if isinstance(value, Decimal):
                    row[key] = format(value, 'f')
        return result
