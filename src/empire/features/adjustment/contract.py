"""Bounded theoretical ex-rights factors from explicit business inputs."""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from empire.features.capital_actions.event_rules import ActionError, decimal, iso

ALGORITHM = 'empire-yuanhang-ex-rights-v3'
MAX_DAYS = 150 * 366
MAX_ROWS = 150 * 366


def share_change(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ActionError('送缩股比例格式无效') from None
    decimal(abs(result))
    if result <= -1:
        raise ActionError('缩股后股数必须为正')
    return result


def ex_reference(previous_close, cash, shares, rights, rights_price):
    with localcontext() as ctx:
        ctx.prec = 50
        p = decimal(previous_close, positive=True)
        d, r, a = (decimal(v) for v in (cash, rights, rights_price))
        s = share_change(shares)
        if s < 0 and any(v != 0 for v in (d, r, a)):
            raise ActionError('负送缩股比例只支持纯缩股事件')
        if d >= p:
            raise ActionError('现金分红不应达到或超过前收盘价，需要核实来源或特殊事件')
        return decimal((p - d + a * r) / (1 + s + r), positive=True)


def action_groups(events, lower, upper):
    if not isinstance(events, list) or len(events) > 2000:
        raise ActionError('远航版除权事件为空契约或超过上限')
    groups, seen = {}, set()
    for row in events:
        if not isinstance(row, list) or len(row) != 6:
            raise ActionError('远航版除权事件结构无效')
        day = iso(row[0])
        if day in seen:
            raise ActionError('同日多条除权事件无法裁定，需核实', day=day)
        seen.add(day)
        bonus = share_change(row[1])
        transfer, ratio, price, cash = map(decimal, row[2:])
        if bonus < 0 and any(v != 0 for v in (transfer, ratio, price, cash)):
            raise ActionError('负送缩股比例只支持纯缩股事件', day=day)
        if ratio > 0 and price <= 0:
            raise ActionError('配股价格必须为正', day=day)
        if lower < day <= upper:
            groups[day] = cash, bonus + transfer, ratio, price
    return groups


def calculate(prices, events):
    if not prices or len(prices) > MAX_ROWS:
        raise ActionError('原始行情为空或超过计算上限')
    days = [iso(p['date']) for p in prices]
    if days != sorted(set(days)):
        raise ActionError('原始行情日期重复或乱序')
    if (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days > MAX_DAYS:
        raise ActionError('计算日期范围超过150年')
    groups = action_groups(events, days[0], days[-1])
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
            group, used, reference = groups.get(day), [], None
            if group is not None:
                cash, shares, ratio, price = group
                try:
                    reference = ex_reference(prior, cash, shares, ratio, price)
                except ActionError as exc:
                    raise ActionError(str(exc), day=day) from None
                factor = decimal(factor * prior / reference, positive=True)
                used = [day]
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
