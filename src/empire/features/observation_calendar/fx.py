"""Archived FX quotes retain source dates independently of the A-share calendar."""
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

from empire.core.time import CHINA

from .intraday import calculate, make_basis, read_latest
from .reading import FX_METRICS, bounds


async def read_fx(registry, month, rows, keys, settings):
    known = {m[0] for m in FX_METRICS}
    if len(keys) != len(set(keys)) or set(keys) - known:
        raise ValueError('未知或重复的汇率观察指标')
    start, end, _ = bounds(month)
    today = next((date.fromisoformat(r['date']) - timedelta(days=1)
                  for r in rows if r['future']), end)
    upper = min(today, end)
    warnings = []
    pending = {}
    now = datetime.now(CHINA)
    for key in keys:
        option = settings.get(key, {})
        lower = start - timedelta(days=366) if option.get('mode', 'value') != 'value' else start
        if lower > upper:
            continue
        result = await registry.get('fx.daily.query').browse(
            code=key.removeprefix('fx_'), start=lower.isoformat(), end=upper.isoformat(), limit=500)
        if result['next'] is not None:
            raise ValueError('汇率观察返回超出日期范围，拒绝展示截断结果')
        quotes = sorted(result['rows'], key=lambda q: str(q['trade_date']))
        dates = [str(q['trade_date']) for q in quotes]
        if len(dates) != len(set(dates)) or any(not lower.isoformat() <= d <= upper.isoformat() for d in dates):
            raise ValueError('汇率观察日线重复或超出范围')
        values, history = {}, []
        invalid = False
        with localcontext() as context:
            context.prec = 50
            for stamp, quote in zip(dates, quotes, strict=True):
                valid = quote.get('price_relation_valid') is True or quote.get('price_relation_valid') == 1
                number = Decimal(str(quote['close'])) if valid else None
                invalid |= not valid
                value = number
                if option.get('mode') == 'change':
                    prior = history[-1] if history else None
                    value = (number / prior - 1) * 100 if number is not None and prior not in (None, 0) else None
                history.append(number)
                if option.get('mode') == 'sum':
                    count = option.get('days', 5)
                    sample = history[-count:]
                    value = sum(sample) / count if len(sample) == count and None not in sample else None
                values[stamp] = value
        for row in rows:
            row['values'][key] = values.get(row['date']) if not row['future'] else None
        if any(r['date'] == now.date().isoformat() and not r['future'] for r in rows) and now.date().isoformat() not in dates:
            pending[key] = make_basis(history, option)
        if invalid:
            name = next(m[1] for m in FX_METRICS if m[0] == key)
            warnings.append(f'{name}存在来源OHLC关系异常，该条及依赖它的计算显示缺值。')
    latest, notices = await read_latest(registry, pending, now)
    warnings.extend(notices)
    for row in rows:
        if row['date'] != now.date().isoformat() or row['future']:
            continue
        row['live_basis'] = pending
        for key, metadata in latest.items():
            value, source = calculate(metadata, pending[key])
            row['values'][key] = value
            row.setdefault('sources', {})[key] = source
    return warnings
