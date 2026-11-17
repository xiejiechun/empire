"""Single-day overview of archived facts with explicit sample scope and gaps."""
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import text

from empire.core.time import CHINA

from .reading import read_review
from .sectors import empty_sectors, read_sectors

INDICES = (('上证指数', ('1A0001',)), ('深证成指', ('399001',)),
           ('科创50', ('1B0688',)), ('创业板指', ('399006',)),
           ('沪深300', ('1B0300', '399300')), ('北证50', ('899050',)))
OVERSEAS = ('日经225', '韩国综合', '纳斯达克', 'SOX', '微软')


def read_market(conn, selected, *, now=None, namespace='empire'):
    day = date.fromisoformat(selected)
    now = (now or datetime.now(CHINA)).astimezone(CHINA)
    begin = date.fromordinal(max(1, day.toordinal() - 30))
    end = date.fromordinal(min(date.max.toordinal(), day.toordinal() + 370))

    def rows(sql, **params):
        sql = sql.replace('SELECT ', 'SELECT /*+ MAX_EXECUTION_TIME(8000) */ ', 1)
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]

    calendar = rows('SELECT trade_date,is_trade FROM trade_calendar '
                    'WHERE trade_date BETWEEN :start AND :end ORDER BY trade_date', start=begin, end=end)
    days = {r['trade_date']: bool(r['is_trade']) for r in calendar}
    previous, following = None, None
    for ordinal in range(day.toordinal() - 1, begin.toordinal() - 1, -1):
        candidate = date.fromordinal(ordinal)
        if candidate not in days:
            break
        if days[candidate]:
            previous = candidate
            break
    for ordinal in range(day.toordinal() + 1, end.toordinal() + 1):
        candidate = date.fromordinal(ordinal)
        if candidate not in days:
            break
        if days[candidate]:
            following = candidate
            break
    status = ('future' if day > now.date() else 'unknown' if day not in days else
              'rest' if not days[day] else 'pending' if day == now.date() and now.time() < time(15, 30) else 'closed')
    result = dict(date=selected, status=status, previous_date=previous, next_date=following,
                  queried_at=now.isoformat(), limit_up=None, limit_down=None, first_boards=None,
                  chain=None, amount_yuan=None, amount_change_yuan=None, price_count=0,
                  previous_price_count=0, main_flow_yuan=None, advance=None, decline=None,
                  flat=None, fund_count=0, issues=[],
                  capital=dict(visible_flow_yuan=None, dark_flow_yuan=None, inflow=None, outflow=None,
                               sectors=empty_sectors(), etf=None),
                  indices=[dict(name=name, code=None, close=None, change=None) for name, _ in INDICES],
                  overseas=[dict(name=name, close=None, change=None) for name in OVERSEAS])
    if status != 'closed':
        return result
    from .etf_flows import read_etf_flows
    result['capital']['etf'] = read_etf_flows(conn, day, previous, days, namespace)
    pools = rows('SELECT p.pool_type,p.source_total,p.filter_text,'
        '(SELECT COUNT(*) FROM yuanhang_limit_member m WHERE m.trade_date=p.trade_date '
        'AND m.pool_type=p.pool_type) AS actual FROM yuanhang_limit_pool p '
        "WHERE p.trade_date=:day AND p.pool_type IN ('limit_up_pool','limit_down_pool')", day=day)
    for pool in pools:
        key = 'limit_up' if pool['pool_type'] == 'limit_up_pool' else 'limit_down'
        if pool['actual'] == pool['source_total']:
            result[key] = pool['source_total']
        else:
            result['issues'].append('涨跌停池头与成员数量不一致，未显示受影响统计')
    if len([d for d in days if begin <= d <= day]) == 31:
        try:
            summary = read_review(conn, selected, selected, include_themes=False)['days'][0]
            result['chain'] = summary['chain']
            if result['limit_up'] is not None and summary['chain'] is not None:
                result['first_boards'] = result['limit_up'] - summary['chain']
        except ValueError as error:
            result['issues'].append(str(error))
    else:
        result['issues'].append('连板计算所需正式交易日历不足')
    prices = rows('SELECT trade_date,COUNT(*) AS n,COUNT(amount_yuan) AS known,'
        'SUM(amount_yuan) AS amount FROM yuanhang_daily_price '
        'WHERE trade_date=:day OR trade_date=:previous GROUP BY trade_date', day=day, previous=previous)
    by_date = {r['trade_date']: r for r in prices}
    current, prior = by_date.get(day), by_date.get(previous)
    if current:
        result['price_count'] = current['n']
        if current['n'] == current['known']:
            result['amount_yuan'] = current['amount']
        else:
            result['issues'].append('部分归档个股缺成交额，未计算合计')
    if prior:
        result['previous_price_count'] = prior['n']
        if result['amount_yuan'] is not None and prior['n'] == prior['known']:
            result['amount_change_yuan'] = result['amount_yuan'] - prior['amount']
    funds = rows('SELECT h.row_count,COUNT(g.unified_code) AS actual,'
        'SUM(g.main_flow) AS flow,SUM(g.visible_flow) AS visible,SUM(g.dark_flow) AS dark,'
        'SUM(g.change_ratio>0) AS advance,'
        'SUM(g.change_ratio<0) AS decline,SUM(g.change_ratio=0) AS flat '
        'FROM graymarket_day h LEFT JOIN graymarket_daily g ON g.trade_date=h.trade_date '
        'WHERE h.trade_date=:day GROUP BY h.row_count', day=day)
    if funds:
        fund = funds[0]
        if fund['row_count'] == fund['actual']:
            result.update(main_flow_yuan=fund['flow'], advance=int(fund['advance']),
                          decline=int(fund['decline']), flat=int(fund['flat']), fund_count=fund['actual'])
            capital = result['capital']
            capital.update(visible_flow_yuan=fund['visible'], dark_flow_yuan=fund['dark'])
            for key, sign, order in (('inflow', '>', 'DESC'), ('outflow', '<', 'ASC')):
                capital[key] = rows('SELECT unified_code,name,main_flow AS amount_yuan,change_ratio '
                    f'FROM graymarket_daily WHERE trade_date=:day AND main_flow{sign}0 '
                    f'ORDER BY main_flow {order},unified_code ASC LIMIT 5', day=day)
            capital['sectors'] = read_sectors(rows, day, namespace)
        else:
            result['issues'].append('资金榜头与成员数量不一致，未计算资金及涨跌家数')
    for item, (_, codes) in zip(result['indices'], INDICES, strict=True):
        for code in codes:
            quotes = rows('SELECT trade_date,close FROM yuanhang_index_daily_price '
                          'WHERE index_code=:code AND (trade_date=:day OR trade_date=:previous)',
                          code=code, day=day, previous=previous)
            quotes = {r['trade_date']: r['close'] for r in quotes}
            if day not in quotes or quotes[day] is None:
                continue
            item.update(code=code, close=quotes[day])
            if previous in quotes and quotes[previous] is not None and quotes[previous] > 0:
                item['change'] = (quotes[day] / quotes[previous] - 1) * Decimal(100)
            break
    return result
