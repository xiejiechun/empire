"""Redis-only browsing with immutable snapshot pagination and explicit absence."""
import re
from datetime import datetime

from empire.core.time import CHINA
from empire.features.yuanhang_limits.contract import TIME_FIELDS, day_value, pool_value
from empire.features.yuanhang_limits.intraday_store import IntradayStore


async def browse_live(query, filters, after, order=None):
    mode, pool, _, day, _, at = filters
    pool_value(pool)
    day_value(day)
    store = query.context.optional('redis.store')
    if store is None:
        raise ValueError('Redis不可用，盘中回放不能用日终MySQL代替')
    live = IntradayStore(store)
    if mode == 4:
        result = await live.timeline(pool, day, before=after)
        rows = [dict(snapshot_id=version,
            started=datetime.fromtimestamp(int(version) / 1000000, CHINA).isoformat(timespec='microseconds'),
            finished=datetime.fromtimestamp(score / 1000000, CHINA).isoformat(timespec='microseconds'))
            for version, score in result['versions']]
        return dict(rows=rows, next=result['next'], message='Redis变化时刻（最新在前）；双击查看该次采样。最多72小时且受容量限制。')
    if at:
        if not isinstance(at, str) or not re.fullmatch(r'\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?', at):
            raise ValueError('回放时刻须为HH:MM:SS或HH:MM:SS.ffffff')
        try:
            parsed = datetime.fromisoformat(day + 'T' + at)
        except ValueError as exc:
            raise ValueError('回放时刻须为HH:MM:SS或HH:MM:SS.ffffff') from exc
        if parsed.tzinfo is not None or not 8 <= len(at) <= 15:
            raise ValueError('回放时刻使用北京时间，不附加时区')
    if order is None and after is not None and (not isinstance(after, (list, tuple)) or len(after) != 2):
        raise ValueError('盘中分页须绑定快照版本和证券代码')
    if order is not None and after is not None and (not isinstance(after, dict) or 'version' not in after):
        raise ValueError('盘中排序分页须绑定快照版本')
    version = (after['version'] if order is not None else after[0]) if after else None
    result = await live.read(pool, day, version=version, at=at or None)
    if result is None:
        if order is not None and after is not None:
            raise ValueError('本次分页绑定的盘中快照已失效，请返回第一页重新查询')
        return dict(rows=[], next=None, message='该时刻无保留快照：尚未采样、已过期/淘汰或Redis重启丢失；不推断空池。')
    unit = result['unit']
    if order is not None:
        from .snapshot_order import snapshot_page
        rows, following = snapshot_page(
            [dict(r, trade_date=day, pool_type=pool) for r in unit['rows']],
            result['version'], filters, order, after,
        )
    else:
        rows = [r for r in unit['rows'] if not after or r['unified_code'] > after[1]]
        following = (result['version'], rows[199]['unified_code']) if len(rows) > 200 else None
        rows = [dict(r, trade_date=day, pool_type=pool) for r in rows[:200]]
    for row in rows:
        for key in TIME_FIELDS:
            if row[key] is not None:
                row[key] = datetime.fromtimestamp(row[key], CHINA)
    start = datetime.fromisoformat(result['started']).astimezone(CHINA).isoformat(timespec='seconds')
    end = datetime.fromisoformat(result['finished']).astimezone(CHINA).isoformat(timespec='seconds')
    checked = datetime.fromtimestamp(int(result['meta']['checked']) / 1000000, CHINA).isoformat(timespec='seconds')
    retained = (datetime.fromtimestamp(result['retained_since'] / 1000000, CHINA).isoformat(timespec='seconds')
                if result['retained_since'] else '无')
    consistency = ('单响应采样' if result['consistency'] == 'single_response'
                   else '多页采样区间记录，非同一瞬间冻结完整池')
    return dict(rows=rows, next=following,
        message=f'Redis{consistency} {start} ～ {end}；{unit["source_total"]}条，未归档MySQL；'
                f'该池最近成功检查{checked}；保留自{retained}；累计淘汰{result["meta"].get("evicted", "0")}份；采样之间变化不可追溯。')
