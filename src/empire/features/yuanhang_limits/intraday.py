"""Clock/calendar boundary: volatile sampling before close, durable history after."""
from datetime import UTC, datetime, time
from functools import partial

from sqlalchemy import text

from empire.core.time import CHINA
from empire.features.yuanhang_limits.contract import BASE_URL, DOMAIN, MAX_UNIT_BYTES
from empire.features.yuanhang_limits.intraday_store import IntradayStore
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.collectors.support import wait_for_capacity


def session_phase(now, is_trade):
    if type(is_trade) is not int or is_trade not in (0, 1):
        raise ValueError('盘中采集需要正式日历，缺日不能推断休市')
    local = now.astimezone(CHINA).time().replace(tzinfo=None)
    if local >= time(15, 30):
        return 'daily'
    if is_trade and (time(9, 25) <= local <= time(11, 30) or time(13) <= local <= time(15, 5)):
        return 'live'
    return 'idle'


async def phase(query, now):
    day = now.astimezone(CHINA).date().isoformat()
    def read(conn):
        return conn.execute(text('SELECT is_trade FROM trade_calendar WHERE trade_date=:day'),
                            dict(day=day)).scalar_one_or_none()
    flag = await query.read(read)
    return session_phase(now, flag)


async def collect_live(collector, now):
    day = now.astimezone(CHINA).date().isoformat()
    collector.stats.update(status='collecting', error='', requests=0, response_bytes=0,
        wire_bytes=0, queued_messages=0, queued_bytes=0, collected=0, storage='redis_only',
        total_units=1, completed_units=0, unit_name='份盘中快照')
    # Retained full-pool memory is charged to the common prefetch reservation.
    async with prefetch_units(collector, [day], collector.fetch, url=BASE_URL,
            domains=(DOMAIN,), retained_bytes=MAX_UNIT_BYTES) as reads:
        async for _, read in reads:
            unit, started = await read.resolve()
            finished = datetime.now(UTC)
            await wait_for_capacity(collector.ingest, collector.stats)
            result = await collector.ingest.publish_volatile(collector.project_id,
                partial(collector.live_store.save, unit, started, finished))
    collector.stats.update(status='complete', completed_units=1, collected=len(unit['rows']),
        snapshot_changed=result['changed'], snapshot_stale=result['stale'],
        notice='仅Redis盘中采样完成；未归档MySQL')
    return dict(phase='complete', storage='redis_only', cutoff=day, collected=len(unit['rows']),
                changed=result['changed'], stale=result['stale'], queued_messages=0)


async def dispatch(collector, *, fresh, baseline_revision):
    now = datetime.now(CHINA)
    day = now.date().isoformat()
    mode = await phase(collector.query, now)
    if mode == 'live':
        return await collect_live(collector, now)
    if mode == 'idle' or (not fresh and await collector.live_store.maintenance_day(collector.pool) == day):
        collector.stats.update(status='complete', collected=0, requests=0, response_bytes=0,
            wire_bytes=0, queued_messages=0, queued_bytes=0, total_units=0, completed_units=0, notice='非采样时段或本日收盘维护已完成')
        return dict(phase='complete', storage='none', cutoff=day, collected=0, queued_messages=0)
    result = await collector._execute(fresh=fresh, baseline_revision=baseline_revision, history_only=True)
    # An older interrupted plan must finish first; do not suppress today's next round.
    target = await collector.query.collection_plan(collector.pool)
    if result['cutoff'] == target['cutoff'] and not target['units']:
        await collector.live_store.mark_maintenance(collector.pool, day)
    return result


def live_store(context):
    return IntradayStore(context.get('redis.store'))
