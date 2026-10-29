"""Pure metrics with explicit gaps and left-censored streaks."""
from collections import defaultdict

UP = 'limit_up_pool'
OPEN = 'open_limit_up_pool'
DOWN = 'limit_down_pool'


def ratio(numerator, denominator):
    return 100 * numerator / denominator if denominator else None


def summarize(days, heads, members, themes, start):
    pools = {(r['trade_date'], r['pool_type']): r for r in heads}
    stocks = defaultdict(dict)
    for row in members:
        stocks[row['trade_date'], row['pool_type']][row['unified_code']] = row
    for key, values in stocks.items():
        if key not in pools or len(values) != pools[key]['source_total']:
            raise ValueError('池头与成员集合数量不一致，请核查归档完整性')
    for key, head in pools.items():
        if key[1] in (UP, OPEN) and len(stocks[key]) != head['source_total']:
            raise ValueError('池头缺少成员，请核查归档完整性')
    result, previous, previous_known = [], {}, False
    for day in days:
        up = stocks[day, UP]
        known = (day, UP) in pools
        streaks = {}
        if known:
            for code in up:
                if previous_known and code not in previous:
                    streaks[code] = 1
                elif previous_known and previous.get(code) is not None:
                    streaks[code] = previous[code] + 1
                else:
                    streaks[code] = None
        complete = known and all(v is not None for v in streaks.values())
        prior_complete = previous_known and all(v is not None for v in previous.values())
        first = {k for k, v in previous.items() if v == 1}
        chain = {k for k, v in previous.items() if v is not None and v >= 2}
        def count(pool):
            return pools.get((day, pool), {}).get('source_total')
        height = max(streaks.values(), default=0) if complete else None
        rows = [dict(**r, streak=streaks.get(code)) for code, r in up.items()]
        rows.sort(key=lambda r: (-(r['streak'] or 0), r['unified_code']))
        leaders = [r for r in rows if height and r['streak'] == height]
        result.append(dict(day=day, up=count(UP), opened=count(OPEN), down=count(DOWN),
            sealed=ratio(len(up), len(set(up) | set(stocks[day, OPEN])))
                if known and (day, OPEN) in pools else None,
            chain=sum(v >= 2 for v in streaks.values()) if complete else None,
            height=height, first_promotion=ratio(len(first & up.keys()), len(first))
                if known and prior_complete else None,
            promotion=ratio(len(chain & up.keys()), len(chain)) if known and prior_complete else None,
            rows=rows, leaders=leaders,
            note='缺涨停池' if not known else '连板起点待核实' if not complete else
                 '来源报告空涨停池' if not up else '已归档',
            observed=pools.get((day, UP), {}).get('observed_at')))
        previous, previous_known = streaks, known
    daily_themes = defaultdict(list)
    for row in themes:
        daily_themes[row['business_date']].append(row)
    return dict(days=[r for r in result if r['day'] >= start], themes=dict(daily_themes))


def theme_window(theme_days, days):
    """Only complete ten-trading-day windows produce an aggregate."""
    window = days[-10:]
    covered = [d for d in window if theme_days.get(d)]
    if len(window) < 10 or len(covered) != 10:
        return [], len(covered)
    totals, names, unknown = defaultdict(int), {}, set()
    for day in window:
        for row in theme_days[day]:
            if row['parent_id'] is not None:
                continue
            identity = row['theme_id']
            names[identity] = row['name']
            if row['hot_score'] is None:
                unknown.add(identity)
            else:
                totals[identity] += row['hot_score']
    return [dict(theme_id=k, name=names[k], heat=v) for k, v in
            sorted(totals.items(), key=lambda item: (-item[1], item[0])) if k not in unknown][:30], 10
