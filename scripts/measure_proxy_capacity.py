"""Real local HTTP proxy connections through shared routing and isolated Redis.

Virtual exits are synthetic; this never contacts a public source or RouterProxy.
One invocation is one retained round, not the complete paired/steady acceptance.
"""
import argparse
import asyncio
import gc
import hashlib
import json
import multiprocessing
import sys
from collections import Counter
from ipaddress import IPv4Address
from pathlib import Path
from time import perf_counter
from uuid import uuid4


def quantiles(values):
    ordered = sorted(values)
    return {name: ordered[min(len(ordered) - 1, int(len(ordered) * q))] if ordered else None
            for name, q in (('p50', .5), ('p95', .95), ('p99', .99))}


async def measure(args):
    from capacity_identity import environment, inputs
    frozen_inputs = inputs(args.source)
    import empire.core.config as config
    config.project_root = lambda: Path(__file__).resolve().parents[1]
    from measure_capacity import process_resources

    from empire.contracts.download import MiB
    from empire.plugins.infra.http import HttpService
    from empire.plugins.infra.proxy_pool import ProxyPool
    from empire.plugins.infra.redis_store import create_client
    from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_PERMIT, USE_PROXY
    assert ROUTE_PERMIT.endswith('return 0\n')
    audited_permit = ROUTE_PERMIT.removesuffix('return 0\n') + 'return {0, now}\n'

    client = create_client({'host': '127.0.0.1', 'port': args.redis_port})
    info = await client.info('server')
    prefix = 'empire:test:proxy-capacity:' + uuid4().hex
    mapping, directory = prefix + ':mapping', prefix + ':directory'
    response_body = b'x' * 32768
    pending = set()
    pending_changed = asyncio.Event()

    def completed(task):
        pending.discard(task)
        pending_changed.set()
    phase = 'prepare'
    gc_started, gc_pauses = {}, []

    def gc_event(action, info):
        generation = info['generation']
        if action == 'start':
            gc_started[generation] = perf_counter()
        elif generation in gc_started:
            gc_pauses.append((perf_counter() - gc_started.pop(generation)) * 1000)

    async def diagnose():
        while True:
            await asyncio.sleep(30)
            frames = []
            for task in list(asyncio.all_tasks())[:20]:
                frame = task.get_coro()
                chain = []
                for _ in range(12):
                    code = getattr(frame, 'cr_code', getattr(frame, 'gi_code', None))
                    if code:
                        chain.append(code.co_name)
                    frame = getattr(frame, 'cr_await', getattr(frame, 'gi_yieldfrom', None))
                    if frame is None:
                        break
                frames.append(chain)
            print(json.dumps(dict(phase=phase, pending=len(pending), completed=counts['completed'],
                active=service.global_active, waiters=pool.waiting, tasks=frames)), flush=True)
    counts = Counter()
    project_counts = Counter()
    errors, latency, lag, resources = Counter(), [], [], []
    permits = {}
    minimum_permit_ms = None
    original_eval = client.eval

    async def audited_eval(script, numkeys, *values):
        nonlocal minimum_permit_ms
        audit = args.audit_permits and script == ROUTE_PERMIT
        result = await original_eval(audited_permit if audit else script, numkeys, *values)
        if audit and isinstance(result, list):
            # Return-only instrumentation of the identical atomic decision.
            # Capture its existing Redis TIME without another round trip or
            # sampling source-arrival jitter as the permit grant timestamp.
            result, granted = result
            assert result == 0
            key = values[2]
            if key in permits:
                gap = granted - permits[key]
                minimum_permit_ms = gap if minimum_permit_ms is None else min(minimum_permit_ms, gap)
                if gap < 2000:
                    counts['permit_violations'] += 1
            permits[key] = granted
        return result

    client.eval = audited_eval
    started = measured = end = 0.0
    probe_stop = asyncio.Event()

    from proxy_capacity_server import run_server
    context = multiprocessing.get_context('spawn')
    parent_pipe, child_pipe = context.Pipe()
    fixture_process = context.Process(target=run_server, args=(child_pipe, args.latency))
    fixture_process.start()
    child_pipe.close()
    if not await asyncio.to_thread(parent_pipe.poll, 20):
        raise RuntimeError('owned proxy fixture did not start within 20 seconds')
    port = parent_pipe.recv()['port']
    pool = ProxyPool(client, mapping_key=mapping, directory_key=directory)
    groups = {f'site{i}': {'domains': [f'source{i}.test'], 'scaling_mode': 'auto',
        'max_concurrency': 0, 'proxy_interval_ms': 2000, 'min_interval_ms': 2000,
        'total_interval_ms': 1, 'max_rps': 0} for i in range(args.sites)}
    service = HttpService(client, prefix, groups, pool=pool,
        resources={'max_parallel_downloads': args.window, 'buffer_budget_bytes': args.buffer_mib * MiB})

    async def fetch(number, planned):
        try:
            site = number % args.sites
            project = f'project{number % args.projects}'
            response = await service.request('GET', f'http://source{site}.test/data',
                allowed_domains=(f'source{site}.test',), max_retries=0, total_timeout=30, project_id=project)
            try:
                assert response.content == response_body
            finally:
                response.close()
            finished = perf_counter()
            counts['completed'] += 1
            if measured <= finished < end:
                counts['measured_completed'] += 1
                project_counts[project] += 1
                latency.append((finished - planned) * 1000)
        except Exception as exc:
            errors['request:' + type(exc).__name__] += 1

    async def probe():
        last_sample = 0
        while not probe_stop.is_set():
            expected = perf_counter() + .05
            await asyncio.sleep(.05)
            now = perf_counter()
            if measured <= now < end:
                lag.append(max(0, now - expected) * 1000)
            if now - last_sample >= 1:
                resources.append({'elapsed': now - started, **process_resources(), 'pending': len(pending),
                                  'active': service.global_active, 'buffer': service.buffer_budget.used})
                last_sample = now

    proxy_flag, fallback_flag = USE_PROXY.set(True), PROXY_FALLBACK.set(False)
    monitor = diagnostic = None
    failure = None
    rate = min(args.exits * args.sites / max(2, args.latency), args.window / args.latency)
    offered_rate = args.arrival_rate or rate
    if offered_rate > rate:
        raise ValueError('offered rate must not exceed the legal theoretical ceiling')
    planned_count = int((args.warmup + args.seconds) * offered_rate)
    try:
        gc.callbacks.append(gc_event)
        if args.diagnostic:
            diagnostic = asyncio.create_task(diagnose())
        seconds, micros = await client.time()
        values = {f'n{i}': json.dumps({'code': f'n{i}',
            'proxy': f'http://n{i}:fixture@127.0.0.1:{port}',
            'exit_ip': str(IPv4Address(0x0A000001 + i))}) for i in range(args.exits)}
        await client.hset(mapping, mapping=values)
        await client.zadd(directory, {raw: seconds + micros / 1000000 + args.warmup + args.seconds
                                     + args.max_producer_lateness + 60
                                     for raw in values.values()})
        await pool.refresh()
        assert pool.healthy_count() == args.exits
        started = perf_counter()
        phase = 'produce'
        measured, end = started + args.warmup, started + args.warmup + args.seconds
        monitor = asyncio.create_task(probe())
        for number in range(planned_count):
            planned = started + number / offered_rate
            await asyncio.sleep(max(0, planned - perf_counter()))
            async with asyncio.timeout_at(planned + args.max_producer_lateness):
                while len(pending) >= 4096:
                    pending_changed.clear()
                    await pending_changed.wait()
            if perf_counter() - planned > args.max_producer_lateness:
                raise RuntimeError('fixed arrival producer exceeded declared lateness limit')
            task = asyncio.create_task(fetch(number, planned))
            pending.add(task)
            task.add_done_callback(completed)
        phase = 'drain'
        await asyncio.gather(*pending)
        elapsed = perf_counter() - started
    except Exception as exc:
        failure = type(exc).__name__ + ': ' + str(exc)
        errors['trial:' + type(exc).__name__] += 1
        elapsed = perf_counter() - started if started else 0
    finally:
        probe_stop.set()
        if monitor:
            await monitor
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        phase = 'http-close'
        await service.close()
        phase = 'proxy-close'
        await pool.close()
        phase = 'server-close'
        parent_pipe.send('stop')
        if not await asyncio.to_thread(parent_pipe.poll, 20):
            raise RuntimeError('owned proxy fixture did not finish within 20 seconds')
        fixture_result = parent_pipe.recv()
        await asyncio.to_thread(fixture_process.join, 10)
        assert fixture_process.exitcode == 0
        parent_pipe.close()
        counts.update(fixture_result['counters'])
        errors.update({'proxy:' + key: value for key, value in fixture_result['errors'].items()})
        PROXY_FALLBACK.reset(fallback_flag)
        USE_PROXY.reset(proxy_flag)
        keys = [key async for key in client.scan_iter(match=prefix + ':*')]
        if keys:
            assert all(key.startswith(prefix + ':') for key in keys)
            await client.delete(*keys)
        await client.aclose()
        gc.callbacks.remove(gc_event)
        if diagnostic:
            diagnostic.cancel()
            await asyncio.gather(diagnostic, return_exceptions=True)
    throughput = counts['measured_completed'] / args.seconds
    result = dict(kind='N-real-local-http-proxy', virtual_exits=args.exits, sites=args.sites,
        warmup_seconds=args.warmup, measured_seconds=args.seconds, elapsed_seconds=elapsed,
        window=args.window, buffer_mib=args.buffer_mib,
        theoretical_rps=rate, measured_rps=throughput, counters=dict(counts), errors=dict(errors),
        offered_rps=offered_rate,
        planned_requests=planned_count, max_producer_lateness_seconds=args.max_producer_lateness,
        error=failure,
        projects=args.projects, project_measured_completions=dict(project_counts),
        permit_audit_enabled=args.audit_permits, minimum_permit_gap_ms=minimum_permit_ms,
        permit_audit_mode='atomic Redis TIME; permit decision unchanged, successful return only instrumented',
        permit_audit_script_sha256=hashlib.sha256(audited_permit.encode()).hexdigest(),
        latency_from_planned_ms=quantiles(latency), event_loop_lag_ms=quantiles(lag),
        gc_pause_ms={**quantiles(gc_pauses), 'max': max(gc_pauses, default=0), 'count': len(gc_pauses)},
        resources=resources, fixture_process_resources=fixture_result['resources'],
        fixture_isolation='separate spawned process; client resources exclude fixture',
        remaining_buffer=service.buffer_budget.used,
        remaining_active=service.global_active, remaining_proxy_leases=sum(e.busy for e in pool.retired),
        directory_reads=pool.directory_reads, candidate_checks=pool.candidate_checks,
        index_operations={site: index.operations for site, index in pool.index.sites.items()}
            if hasattr(pool, 'index') else None,
        environment={**environment(),
                     'redis_run_id': info['run_id'],
                     'redis_port': args.redis_port}, source=str(args.source),
        input_hashes=frozen_inputs, input_unchanged=inputs(args.source) == frozen_inputs,
        correctness_passed=not errors and counts['completed'] == planned_count and not counts['permit_violations']
            and not counts['overlap_violations']
            and not counts['server_connections_not_closed_by_client']
            and service.global_active == service.buffer_budget.used == 0,
        formal_duration=args.warmup >= 60 and args.seconds >= 180)
    result['capacity_passed'] = throughput >= rate * .9 and (quantiles(lag)['p99'] or 0) <= 100
    result['fairness_passed'] = all(project_counts[f'project{i}'] >= offered_rate * args.seconds / args.projects * .8
                                  for i in range(args.projects))
    result['correctness_passed'] &= result['fairness_passed']
    result['correctness_passed'] &= result['input_unchanged']
    result['passed'] = result['correctness_passed'] and result['capacity_passed']
    # This invocation is one round. Paired runs, steady-state and runtime
    # isolation still belong to the acceptance matrix, even at full duration.
    result['full_acceptance'] = False
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'resources'}, indent=2))
    return result['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('src'))
    parser.add_argument('--redis-port', type=int, default=16379)
    parser.add_argument('--exits', type=int, choices=(100, 300, 1000, 3000), default=100)
    parser.add_argument('--sites', type=int, choices=(1, 2), default=1)
    parser.add_argument('--projects', type=int, choices=(1, 3), default=1)
    parser.add_argument('--window', type=int, default=1024)
    parser.add_argument('--buffer-mib', type=int, default=4096)
    parser.add_argument('--latency', type=float, default=.1)
    parser.add_argument('--audit-permits', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--diagnostic', action='store_true')
    parser.add_argument('--max-producer-lateness', type=int, default=30)
    parser.add_argument('--arrival-rate', type=float, help='explicit operating load; theoretical capacity target remains unchanged')
    parser.add_argument('--warmup', type=int, default=60)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (args.output.exists() or not 0 <= args.warmup <= 300 or not 1 <= args.seconds <= 1800
            or args.redis_port != 16379 or not .01 <= args.latency <= 3
            or not 1 <= args.window <= 4096 or not 512 <= args.buffer_mib <= 4096):
        parser.error('new output, owned port 16379 and bounded load required')
    if not 1 <= args.max_producer_lateness <= 120:
        parser.error('producer lateness must be 1..120 seconds; offered waiting remains measured')
    if args.arrival_rate is not None and not 1 <= args.arrival_rate <= 3000:
        parser.error('offered rate must be 1..3000 requests per second')
    sys.path.insert(0, str(args.source.resolve()))
    raise SystemExit(0 if asyncio.run(measure(args)) else 1)
