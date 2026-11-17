"""Per-metric read scopes and transformations, with no writes or gap filling."""
from decimal import Decimal, localcontext

from .reading import METRICS, bounds, read_base


def transform(rows, key, option, percentage=False):
    mode, count = option.get('mode', 'value'), option.get('days', 5)
    history, values = [], {}
    for row in rows:
        value = row['values'].get(key)
        if row['status'] == 'unknown':
            history = []
        if row['status'] != 'trade' or row['future']:
            values[row['date']] = None
            continue
        with localcontext() as context:
            context.prec = 50
            number = Decimal(str(value)) if value is not None else None
            result = number
            if mode == 'change':
                prior = history[-1] if history else None
                result = ((number - prior) / abs(prior) * 100
                          if number is not None and prior not in (None, 0) else None)
            history.append(number)
            if mode == 'sum':
                sample = history[-count:]
                result = sum(sample) if len(sample) == count and None not in sample else None
                if result is not None and percentage:
                    result /= count
            values[row['date']] = result
    return values


async def configured_read(registry, month, index, market, settings, include_top, include_fx=(), include_turnover=False):
    known = {m[0] for m in METRICS}
    if set(settings) - known:
        raise ValueError('未知观察指标设置')
    markets = {market} | {o.get('market') for k, o in settings.items()
                          if o.get('market') and next(m[4] for m in METRICS if m[0] == k) == 'market'}
    results = {}
    for scope in sorted(markets):
        results[scope] = await read_base(registry, month, index, scope, extended=True)
    result = results[market]
    rows = result['rows']
    for row in rows:
        row['values']['index_daily_change'] = row['values']['change']
    warnings = []
    if include_top or include_turnover:
        from .concentration import read_concentration
        option = settings.get('top_amount_share', {})
        first = bounds(month)[0].isoformat()
        earlier = [i for i, r in enumerate(rows) if r['date'] < first and r['status'] == 'trade']
        amount_option = settings.get('market_amount', {})
        lookback = max(option.get('window', 30) + (option.get('days', 5) if option.get('mode') == 'sum' else 1)
                       if include_top else 0,
                       amount_option.get('days', 5) if amount_option.get('mode') == 'sum' else 1)
        first_index = earlier[-lookback] if len(earlier) >= lookback else 0
        top = await read_concentration(registry, rows[first_index:], option.get('window', 30), option.get('top', 5))
        for row in rows:
            if include_top:
                row['values']['top_amount_share'] = top['values'].get(row['date'])
            if include_turnover:
                row['values']['market_amount'] = top['turnover'].get(row['date'])
        if include_top:
            warnings.append(top['warning'])
        if include_turnover:
            warnings.append(top['turnover_warning'])
    # Compute before mutating rows: each metric uses the untransformed source.
    transformed = {}
    for key, option in settings.items():
        metric = next(m for m in METRICS if m[0] == key)
        if metric[4] == 'fx':
            continue
        source = results[option.get('market') or market]['rows'] if metric[4] == 'market' else rows
        if key == 'financing_repayment_ratio':
            for row, basis in zip(rows, source, strict=True):
                for field in ('financing_ratio_buy', 'financing_ratio_repayment'):
                    row['values'][field] = basis['values'].get(field)
        transformed[key] = transform(source, key, option, metric[3] == '%')
    for row in rows:
        for key, values in transformed.items():
            row['values'][key] = values[row['date']]
    start, end, _ = bounds(month)
    result['rows'] = [r for r in rows if start.isoformat() <= r['date'] <= end.isoformat()]
    if include_fx:
        from .fx import read_fx
        warnings.extend(await read_fx(registry, month, result['rows'], include_fx, settings))
    result['warnings'] = warnings
    return result
