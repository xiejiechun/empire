"""Fixed arrival trials; scheduled waiting remains inside reported latency."""
import asyncio
import math
from collections import Counter, deque
from time import perf_counter
from uuid import uuid4

from archive_capacity_fixtures import fixture
from measure_capacity import process_resources


def quantiles(values):
    ordered = sorted(values)
    return {key: ordered[min(len(ordered) - 1, int(len(ordered) * q))] if ordered else None
            for key, q in (('p50', .5), ('p95', .95), ('p99', .99))}


async def timed_trial(args, trial, worker, ingest, storage, templates, publish, drained):
    count = math.ceil((args.warmup + args.seconds) * args.arrival_rate)
    # Source fixture parsing is outside the timed producer. It is separately
    # measured by the pure-compute/C experiments, never hidden in SQL capacity.
    values = []
    cache = {}
    proportions = Counter()
    for number in range(count):
        category = 'hot'
        if args.workload == 'B' and number % 10 in (8, 9):
            category = 'new' if number % 10 == 8 else 'revision'
            index = (64 + trial * math.ceil(count / 10) + number // 10
                     if category == 'new' else 32 + number // 10 % 32)
            revised = category == 'revision' and (trial * math.ceil(count / 10) + number // 10) // 32 % 2 == 0
            key = index, revised
            if key not in cache:
                cache[key] = fixture(args.dataset, index, revision=revised)
            value = cache[key]
        else:
            value = templates[number % (32 if args.workload == 'B' else len(templates))]
        proportions[category] += 1
        values.append(value)
    scheduled = {}
    latencies, lag, queries, status_queries, samples = [], [], [], [], []
    measured_completed = total_completed = 0
    stop = asyncio.Event()
    original_ack = worker.acknowledge
    began = perf_counter()
    measured, end = began + args.warmup, began + args.warmup + args.seconds

    async def acknowledge(ids):
        nonlocal measured_completed, total_completed
        times = []
        for ident in ids:
            batch = worker.queue.ids[ident].key[2]
            times.append(scheduled[batch].popleft())
            if not scheduled[batch]:
                del scheduled[batch]
        await original_ack(ids)
        finished = perf_counter()
        total_completed += len(ids)
        if measured <= finished < end:
            measured_completed += len(ids)
            latencies.extend((finished - planned) * 1000 for planned in times)

    async def monitor():
        last = began
        while not stop.is_set():
            expected = perf_counter() + .05
            await asyncio.sleep(.05)
            now = perf_counter()
            if measured <= now < end:
                lag.append(max(0, now - expected) * 1000)
            if now - last >= 1:
                started = perf_counter()
                await ingest.checkpoint(templates[0]['job_key'])
                if measured <= now < end:
                    queries.append((perf_counter() - started) * 1000)
                started = perf_counter()
                status = await args.control.workspace(section='tasks')
                assert len(status['jobs']) == len(args.control.definitions)
                if measured <= now < end:
                    status_queries.append((perf_counter() - started) * 1000)
                health = worker.health()
                redis_memory = await storage.client.info('memory')
                lane = getattr(worker.catalog, 'compute_lane', None)
                executor = lane.executor if lane else None
                # Benchmark introspection only: these are the exact workers
                # owned by our private runtime, never system-wide PID guesses.
                children = {str(pid): process_resources(pid)
                            for pid in (executor._processes if executor else ())}
                parent = process_resources()
                samples.append(dict(elapsed=now - began, **process_resources(),
                    compute_children=children,
                    total_rss_bytes=(parent['rss_bytes'] + sum(v['rss_bytes'] for v in children.values())
                                     if parent['rss_bytes'] is not None and
                                     all(v['rss_bytes'] is not None for v in children.values()) else None),
                    pending=await storage.client.xlen(worker.redis.stream),
                    redis_used_memory=redis_memory['used_memory'],
                    sql_lanes={name: getattr(worker.mysql, name).health()
                               for name in ('control_lane', 'read_lane', 'archive_lane')
                               if hasattr(worker.mysql, name)},
                    ready_pending=health.get('ready_pending'), ready_oldest_ms=health.get('ready_oldest_ms'),
                    staging_batches=health.get('staging_batches'),
                    compute=worker.catalog.health().get('compute'),
                    buffer=worker.catalog.compute_budget.health()
                        if getattr(worker.catalog, 'compute_budget', None) else None))
                last = now

    worker.acknowledge = acknowledge
    probe = asyncio.create_task(monitor())
    before = worker.stats['archived']
    failure = None
    pauses = []

    async def disrupt():
        await asyncio.sleep(args.warmup + args.pause_after)
        async with worker.lock:
            started = perf_counter()
            try:
                await asyncio.sleep(args.pause_seconds)
            finally:
                pauses.append(dict(start=started - began, end=perf_counter() - began))

    disruption = asyncio.create_task(disrupt()) if args.pause_seconds else None
    try:
        for offset in range(0, count, 16):
            selected = values[offset:offset + 16]
            times = [began + (offset + i) / args.arrival_rate for i in range(len(selected))]
            await asyncio.sleep(max(0, times[-1] - perf_counter()))
            if perf_counter() - times[0] > args.max_producer_lateness:
                raise RuntimeError('fixed arrival producer exceeded declared lateness limit; trial failed')
            batch = uuid4().hex
            scheduled[batch] = deque(times)
            await publish(selected, batch)
        await drained()
        assert worker.stats['archived'] - before == total_completed == count
        assert not scheduled
    except Exception as exc:
        failure = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        if disruption:
            disruption.cancel()
            await asyncio.gather(disruption, return_exceptions=True)
        stop.set()
        await probe
        worker.acknowledge = original_ack
        report = dict(round=trial, planned=count, messages=total_completed,
            measured_messages=measured_completed, seconds=args.seconds,
            messages_per_second=measured_completed / args.seconds,
            elapsed_seconds=perf_counter() - began, proportions=dict(proportions),
            latency_from_planned_ms=quantiles(latencies), event_loop_lag_ms=quantiles(lag),
            checkpoint_query_ms=quantiles(queries), query_samples=len(queries), resources=samples,
            status_query_ms=quantiles(status_queries), status_query_samples=len(status_queries),
            downstream_pauses=pauses,
            error=failure, unacknowledged_schedule=sum(map(len, scheduled.values())),
            rss_scope='parent plus exact owned compute workers; individual RSS includes shared pages')
        if failure:
            args.failed_trial = report
    return report
