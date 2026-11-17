"""Bounded shared review facts and canonical continuous-board calculation."""
from datetime import date, datetime, timedelta

from sqlalchemy import text

from empire.core.time import CHINA
from empire.features.market_review.model import summarize


def read_review(conn, start, end, *, include_themes=True):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if not 0 <= (last - first).days <= 119 or last > datetime.now(CHINA).date():
        raise ValueError('请选择不超过今天的1～120自然日范围')
    begin = first - timedelta(days=30)
    params = dict(start=begin, end=last)
    def read(sql):
        return [dict(r) for r in conn.execute(text(sql.replace('SELECT ',
            'SELECT /*+ MAX_EXECUTION_TIME(8000) */ ', 1)), params).mappings()]
    calendar = read('SELECT trade_date,is_trade FROM trade_calendar '
                    'WHERE trade_date BETWEEN :start AND :end ORDER BY trade_date')
    if len(calendar) != (last - begin).days + 1:
        raise ValueError('所选范围交易日历缺日，请先补齐正式日历')
    days = [r['trade_date'] for r in calendar if r['is_trade']]
    heads = read('SELECT trade_date,pool_type,source_total,observed_at FROM yuanhang_limit_pool '
                 'WHERE trade_date BETWEEN :start AND :end ORDER BY trade_date,pool_type LIMIT 751')
    members = read('SELECT trade_date,pool_type,unified_code,name,high_days,change_rate '
        'FROM yuanhang_limit_member WHERE trade_date BETWEEN :start AND :end '
        "AND pool_type IN ('limit_up_pool','open_limit_up_pool') "
        'ORDER BY trade_date,pool_type,unified_code LIMIT 100001')
    themes = read('SELECT business_date,theme_id,name,parent_id,rank_no,hot_score,change_rate,limit_up_count '
        'FROM theme_daily WHERE business_date BETWEEN :start AND :end '
        'ORDER BY business_date,theme_id LIMIT 300001') if include_themes else []
    if len(members) > 100000 or len(themes) > 300000:
        raise ValueError('查询范围超过复盘容量，请缩短日期范围')
    value = summarize(days, heads, members, themes, first)
    value['queried_at'] = datetime.now(CHINA).strftime('%Y-%m-%d %H:%M:%S')
    return value

