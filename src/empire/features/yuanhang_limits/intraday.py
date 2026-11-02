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
    if mode == 'idle':
        collector.stats.update(status='complete', collected=0, requests=0, response_bytes=0,
            wire_bytes=0, queued_messages=0, queued_bytes=0, total_units=0, completed_units=0, notice='非采样时段或本日收盘维护已完成')
        return dict(phase='complete', storage='none', cutoff=day, collected=0, queued_messages=0)
    return await pool_maintenance(collector, now, fresh=fresh, baseline_revision=baseline_revision)


async def pool_maintenance(collector, now, *, fresh, baseline_revision):
    """Recent and close refresh have priority over one bounded missing-history batch."""
    state = await collector.ingest.checkpoint(collector.job_key)
    cursor = state['cursor']
    if (cursor.get('phase') in ('fetch', 'awaiting_archive') or
            cursor.get('phase') == 'complete' and state['revision'] > baseline_revision):
        scope = cursor.get('scope', 'recent')
    else:
        recent = await collector.query.collection_plan(collector.pool, force=fresh, scope='recent')
        if recent['units']:
            scope = 'recent'
        else:
            from empire.features.yuanhang_limits.close_refresh import refresh_slot
            slot = refresh_slot(now)
            if slot and await collector.live_store.close_slot(collector.pool) != slot:
                return await finish_today(collector, fresh, baseline_revision)
            scope = 'backfill'
            pending = await collector.query.collection_plan(collector.pool, scope=scope)
            if not pending['units']:
                collector.stats.update(status='complete', requests=0, collected=0,
                    response_bytes=0, wire_bytes=0, queued_messages=0, queued_bytes=0,
                    total_units=0, completed_units=0, notice='近期已核验且无历史缺口，当前无需请求')
                return dict(phase='complete', cutoff=recent['cutoff'], storage='none', queued_messages=0)
    if scope == 'today':
        return await finish_today(collector, fresh, baseline_revision)
    return await collector._execute(fresh=fresh, baseline_revision=baseline_revision,
                                    history_only=True, scope=scope)


async def finish_today(collector, fresh, baseline_revision):
    result = await collector._execute(fresh=fresh, baseline_revision=baseline_revision,
                                      history_only=True, scope='today')
    if result.get('close_slot'):
        await collector.live_store.mark_close_slot(collector.pool, result['close_slot'])
    return result


def live_store(context):
    return IntradayStore(context.get('redis.store'))
