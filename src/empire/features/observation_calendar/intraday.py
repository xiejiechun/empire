"""Optional, bounded current-day FX snapshots; never a historical fallback."""
import asyncio
from datetime import datetime
from decimal import Decimal, localcontext

from empire.core.time import CHINA


def make_basis(history, option):
    mode, days = option.get('mode', 'value'), option.get('days', 5)
    count = 1 if mode == 'change' else days - 1 if mode == 'sum' else 0
    sample = history[-count:] if count else []
    ready = len(sample) == count and None not in sample
    with localcontext() as context:
        context.prec = 50
        total = sum(sample, Decimal(0)) if ready else Decimal(0)
    return dict(mode=mode, days=days, ready=ready, total=format(total, 'f'))


def calculate(metadata, basis):
    value = metadata['latest']
    with localcontext() as context:
        context.prec = 50
        total = Decimal(basis['total'])
        if basis['mode'] == 'change':
            value = (value / total - 1) * 100 if basis['ready'] and total > 0 else None
        elif basis['mode'] == 'sum':
            value = (value + total) / basis['days'] if basis['ready'] else None
    return value, dict(metadata, mode=basis['mode'], days=basis['days'])


async def read_live(registry, date, basis):
    now = datetime.now(CHINA)
    if date != now.date().isoformat():
        raise ValueError('盘中刷新日期已变化，请重新加载今天的月历')
    latest, warnings = await read_latest(registry, basis, now)
    values, sources = {}, {}
    for key, metadata in latest.items():
        values[key], sources[key] = calculate(metadata, basis[key])
    return dict(date=date, values=values, sources=sources, warnings=warnings, queried_at=now.isoformat())


async def read_latest(registry, keys, now):
    if not keys:
        return {}, []
    query = registry.optional('fx.latest.query')
    if query is None:
        return {}, ['汇率 Redis 盘中查询未启用，今日暂只显示已归档数据。']

    async def one(key):
        code = key.removeprefix('fx_')
        try:
            async with asyncio.timeout(3):
                result = await query.browse(code=code, limit=12)
            if result['next'] is not None or len(result['rows']) > 1:
                raise ValueError('快照身份异常')
            if not result['rows']:
                return key, None, f'{code} Redis 暂无盘中报价。'
            quote = result['rows'][0]
            if quote['symbol'] != code or quote['unified_code'] != code + '.FX':
                raise ValueError('快照身份异常')
            stamps = [datetime.fromisoformat(quote[k]) for k in ('source_time', 'source_update_time', 'observed_at')]
            if any(t.tzinfo is None or t.astimezone(CHINA).date() != now.date()
                   or (t - now).total_seconds() > 300 for t in stamps):
                return key, None, f'{code} Redis 快照时间不属于今天或异常，未填入今日。'
            latest = Decimal(str(quote['latest']))
            if not latest.is_finite() or latest <= 0:
                raise ValueError('报价异常')
            metadata = dict(source='redis', latest=latest,
                source_time=quote['source_time'], source_update_time=quote['source_update_time'],
                observed_at=quote['observed_at'], sampling_stale=(now - stamps[-1]).total_seconds() > 180)
            return key, metadata, None
        except Exception:
            # Provider errors may contain connection information: expose no raw exception.
            return key, None, f'{code} Redis 盘中读取失败，已保留归档结果，可刷新重试。'

    results = await asyncio.gather(*(one(key) for key in keys))
    return ({key: quote for key, quote, _ in results if quote is not None},
            [warning for _, _, warning in results if warning])
