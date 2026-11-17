"""Calendar-aware live sampling and bounded close/history maintenance."""
from datetime import UTC, datetime, time
from functools import partial

from empire.core.time import CHINA
from empire.plugins.collectors.support import wait_for_capacity


def session_phase(now, is_trade):
    if type(is_trade) is not int or is_trade not in (0, 1):
        raise ValueError("盘中采集需要完整正式日历")
    local = now.astimezone(CHINA).time().replace(tzinfo=None)
    if local >= time(15, 30):
        return "daily"
    if is_trade and (time(9, 25) <= local <= time(11, 30) or time(13) <= local <= time(15, 5)):
        return "live"
    return "idle"


def close_slot(now):
    local = now.astimezone(CHINA)
    minute = min(local.hour * 60 + local.minute, 21 * 60)
    return local.replace(hour=minute // 60, minute=minute % 60 // 30 * 30,
                         second=0, microsecond=0).isoformat(timespec="minutes")


async def collect_live(collector, now):
    stamp = now.astimezone(CHINA).date().isoformat()
    collector.stats.update(status="collecting", error="", storage="redis_only",
                           requests=0, response_bytes=0, wire_bytes=0, pages=0,
                           collected=0, queued_messages=0, queued_bytes=0,
                           total_units=1, completed_units=0)
    async with collector.daily_reads([stamp]) as reads:
        async for _, read in reads:
            rows, started = await read.resolve()
            finished = datetime.now(UTC)
            await wait_for_capacity(collector.ingest, collector.stats)
            result = await collector.ingest.publish_volatile(collector.project_id,
                partial(collector.live_store.save, stamp, rows, started, finished))
    collector.stats.update(status="complete", completed_units=1, collected=len(rows),
                           notice="Redis盘中采样完成；未归档MySQL", **result)
    return dict(phase="complete", storage="redis_only", collected=len(rows), queued_messages=0, **result)


def idle(collector, notice):
    collector.stats.update(status="complete", error="", storage="none", requests=0,
                           response_bytes=0, wire_bytes=0, pages=0, collected=0,
                           queued_messages=0, queued_bytes=0,
                           completed_units=0, total_units=0, notice=notice)
    return dict(phase="complete", storage="none", queued_messages=0)


async def dispatch(collector, *, fresh, baseline_revision):
    now = datetime.now(CHINA)
    stamp = now.date().isoformat()
    trading = await collector.query.trading_dates(stamp, stamp)
    mode = session_phase(now, int(stamp in trading))
    if mode == "live":
        return await collect_live(collector, now)
    if mode == "idle":
        return idle(collector, "非盘中采样或收盘维护时段")
    state = await collector.ingest.checkpoint(collector.job_key)
    cursor = state["cursor"]
    if cursor.get("phase") in ("fetch", "awaiting_archive"):
        # Old daily scopes had no explicit samples; preserve their exact scope.
        result = await collector._execute(fresh=False, baseline_revision=baseline_revision,
                                          **cursor.get("request_scope", {}))
        if result.get("maintenance_slot"):
            await collector.live_store.mark_maintenance(result["maintenance_slot"])
        return result
    if cursor.get("phase") == "complete" and cursor.get("maintenance_slot"):
        # Also repairs a failure after archive/checkpoint completion but before marking.
        await collector.live_store.mark_maintenance(cursor["maintenance_slot"])
    slot = close_slot(now)
    previous = await collector.live_store.maintenance()
    recent = 0
    if fresh or not previous or previous[:10] != stamp:
        recent = 3
    elif trading and previous != slot:
        recent = 1
    selected = await collector.query.maintenance_plan(stamp, recent=recent)
    if not selected:
        return idle(collector, "收盘复核已完成且无历史缺口")
    result = await collector._execute(fresh=True, baseline_revision=baseline_revision,
                                     sample_dates=selected, planned_dates=selected,
                                     maintenance_slot=slot if recent else None)
    if recent:
        await collector.live_store.mark_maintenance(slot)
    return result
