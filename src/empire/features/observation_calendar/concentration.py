"""Rolling turnover concentration over explicitly labelled archived samples."""
from collections import deque
from decimal import ROUND_CEILING, Decimal, localcontext

from sqlalchemy import text


def concentration(days, daily, window, top):
    with localcontext() as context:
        context.prec = 50
        return _concentration(days, daily, window, top)


def _concentration(days, daily, window, top):
    history, totals, values, counts = deque(), {}, {}, []
    for day in days:
        if day['status'] == 'unknown':
            history.clear()
            totals.clear()
        if day['status'] != 'trade' or day['future']:
            continue
        sample = daily(day['date'])
        history.append(sample)
        for code, amount in (sample or {}).items():
            if amount is not None:
                totals[code] = totals.get(code, Decimal(0)) + amount
        if len(history) > window:
            removed = history.popleft()
            for code, amount in (removed or {}).items():
                if amount is not None:
                    totals[code] = totals.get(code, Decimal(0)) - amount
                    if totals[code] == 0:
                        del totals[code]
        valid = len(history) == window and all(s and all(v is not None for v in s.values()) for s in history)
        values[day['date']] = None
        if not valid:
            continue
        ranked = sorted((v for v in totals.values() if v > 0), reverse=True)
        if not ranked:
            continue
        n = int((Decimal(len(ranked)) * top / 100).to_integral_value(rounding=ROUND_CEILING))
        with localcontext() as context:
            context.prec = 50
            values[day['date']] = sum(ranked[:n]) / sum(ranked) * 100
        counts.append(len(ranked))
    return values, counts


async def read_concentration(registry, days, window, top):
    if type(window) is not int or not 1 <= window <= 60 or type(top) is not int or not 1 <= top <= 100:
        raise ValueError('Top窗口须为1～60个交易日，比例须为1～100%')
    mysql = registry.get('mysql.store')

    def read():
        with mysql.read_engine.connect() as conn:
            result = conn.execution_options(stream_results=True, max_row_buffer=1000).execute(text(
                'SELECT trade_date,unified_code,amount_yuan FROM yuanhang_daily_price '
                'WHERE trade_date BETWEEN :start AND :end '
                'ORDER BY trade_date,unified_code LIMIT 2500001'),
                dict(start=days[0]['date'], end=days[-1]['date']))
            iterator = iter(result)
            pending = next(iterator, None)
            seen = 0
            turnover, sample_counts = {}, []

            def daily(day):
                nonlocal pending, seen
                sample = {}
                while pending is not None and str(pending[0]) <= day:
                    seen += 1
                    if seen > 2500000:
                        raise ValueError('Top成交额查询超过250万行上限，拒绝截断统计')
                    if str(pending[0]) == day:
                        sample[pending[1]] = pending[2]
                    pending = next(iterator, None)
                if sample:
                    sample_counts.append(len(sample))
                with localcontext() as context:
                    context.prec = 50
                    turnover[day] = (sum(sample.values(), Decimal(0))
                                     if sample and all(v is not None for v in sample.values()) else None)
                return sample

            try:
                values, counts = concentration(days, daily, window, top)
            finally:
                result.close()
        count_text = f'{min(counts)}～{max(counts)}只' if counts else '暂无完整窗口'
        daily_count = f'{min(sample_counts)}～{max(sample_counts)}只' if sample_counts else '暂无已归档样本'
        return dict(values=values, turnover=turnover,
                    turnover_warning=f'沪深京成交额：已归档沪深京个股样本（{daily_count}）成交额合计，'
                    '不是官方全市场总额或全市场覆盖证明；未归档证券不计入，整日无记录或成交额缺值时不计算。',
                    warning=f'Top成交额占比：已归档个股样本（{count_text}），'
                    '不是全市场覆盖证明。按窗口累计成交额排名，取有成交股票前Top%（向上取整）；'
                    '窗口缺整日或成交额缺值时不计算，未归档证券不进入样本。')

    return await mysql.read(read)
