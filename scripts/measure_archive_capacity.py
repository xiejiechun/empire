"""Formal archive/ingest/query smoke capacity with owned real SQL and Redis.

Bounded message-count trials are diagnostics, not the 60/180s acceptance runs.
Every SQL statement retains the independent-server/session identity guard.
"""
import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter
from uuid import uuid4


async def measure(args):
    from capacity_identity import environment, inputs
    frozen_inputs = inputs(args.source)
    import empire.core.config as config
    config.project_root = lambda: Path(__file__).resolve().parents[1]
    from archive_capacity_fixtures import fixture
    from source_test_storage import PrivateStorage, read_server_uuid, test_settings

    from empire.bootstrap import build_manager
    from empire.contracts.data import make_envelope
    from empire.core.config import load_config

    cfg = load_config()
    production_uuid = read_server_uuid(cfg['mysql'])
    private = test_settings(json.loads(args.mysql_settings.read_text(encoding='utf-8')))
    storage = PrivateStorage(private, {'host': '127.0.0.1', 'port': 16379},
                             uuid4().hex, uuid4().hex + uuid4().hex, production_uuid)
    manager, trials = None, []
    clean = dict(sql=False, redis=False)
    result = dict(kind='formal-ingest-archive-real-private-sql',
        formal_duration=args.warmup >= 60 and args.seconds >= 180,
        dataset=args.dataset, workload=args.workload, source=str(args.source),
        guard='every-SQL actual server_uuid/DATABASE verification retained; extra round-trip included',
        environment=environment(), input_hashes=frozen_inputs,
        error=None)
    try:
        await asyncio.to_thread(storage.create_sql)
        await storage.create_redis()
        await asyncio.to_thread(storage.seed, [], [])
        cfg['mysql'] = storage.settings
        cfg['redis'] = {**storage.redis, 'namespace': storage.namespace}
        cfg['archive'] = {**cfg.get('archive', {}), 'unit_batch_size': args.batch_size}
        cfg['archive']['interval_seconds'] = 60
        manager = build_manager(cfg)
        await manager.start('pipeline.ingest')
        worker, ingest = manager.registry.get('archive.worker'), manager.registry.get('ingest.publish')
        mysql = manager.registry.get('mysql.store')
        # All policies belong to this owned database. Start the real status
        # service with every collector disabled; no public-source work is run.
        from empire.plugins.infra.settings import SettingsStore
        control = manager.entries['collection.control'].plugin
        settings = SettingsStore(mysql, worker.redis.prefix)
        for spec in control.definitions.values():
            await settings.save('task', spec.id, dict(enabled=False, mode='manual',
                interval_seconds=spec.interval_seconds, daily_time='18:00', request_retries=2))
        await manager.start('collection.control')
        assert all(not job['policy']['enabled'] for job in control.state['jobs'].values())
        args.control = control
        # Experiments only, before the first owned publication. No live user
        # resource is replaced and every trial still calls the formal methods.
        if hasattr(worker, 'metrics'):
            worker.metrics.timing_enabled = args.timings
        if getattr(worker.catalog, 'compute_lane', None):
            from empire.plugins.infra.compute_lane import ComputeLane
            await worker.catalog.compute_lane.close()
            worker.catalog.compute_lane = ComputeLane(args.compute_workers) if args.compute_workers else None
        if hasattr(mysql, 'archive_lane') and args.sql_workers != mysql.archive_lane.workers:
            from empire.plugins.infra.mysql_store import make_engine
            from empire.plugins.infra.sql_lane import SQLLane
            async with worker.lock:
                assert mysql.archive_lane.pending == mysql.archive_lane.active == 0
                await mysql.archive_lane.close()
                await asyncio.to_thread(mysql.archive_engine.dispose)
                mysql.archive_engine = make_engine(mysql.settings, pool_size=args.sql_workers)
                mysql.archive_lane = SQLLane('capacity-owned-archive', args.sql_workers, 16)
        templates = [fixture(args.dataset, i, large=args.workload == 'C') for i in range(64)]
        source_inputs = ({template['business_key']: fixture(args.dataset, i, large=True, source_only=True)
                          for i, template in enumerate(templates)} if args.include_source else None)
        result['timed_source_parsing'] = args.include_source
        revisions = Counter()
        expected_units = {}

        async def publish(values, batch):
            if source_inputs:
                from archive_capacity_sources import parsed_sources
                async with parsed_sources(worker.catalog, values, source_inputs) as parsed:
                    await publish_values(parsed, batch)
            else:
                await publish_values(values, batch)

        async def publish_values(values, batch):
            groups = {}
            for value in values:
                groups.setdefault(value['job_key'], []).append(value)
            for selected in groups.values():
                await publish_project(selected, batch)
            expected_units.update(((value['dataset'], value['business_key']), value) for value in values)

        async def publish_project(values, batch):
            key = values[0]['job_key']

            async def admit_page():
                # A benchmark window bounds admitted work. Its waiting remains
                # inside planned-to-ACK latency, including unsent offered work.
                if args.producer_queue_window:
                    while await storage.client.xlen(worker.redis.stream) >= args.producer_queue_window:
                        if worker.health().get('status') == 'degraded':
                            raise RuntimeError(worker.health().get('error', 'archive degraded'))
                        await asyncio.sleep(.01)

            envelopes = []
            for page, template in enumerate(values, 1):
                envelope = make_envelope(**{**template, 'payload': {**template['payload'], 'page': page}},
                    run_id=batch, batch_id=batch)
                envelopes.append(envelope)
            pending, size = [], 0
            for envelope in envelopes:
                wire_size = len(envelope.model_dump_json().encode())
                if pending and size + wire_size > cfg['ingest'].get('max_page_bytes', 524288):
                    await admit_page()
                    await ingest.publish_page(pending, job_key=key, expected_revision=revisions[key],
                                              cursor={'capacity_page': revisions[key] + 1})
                    revisions[key] += 1
                    pending, size = [], 0
                pending.append(envelope)
                size += wire_size
            if pending:
                await admit_page()
                await ingest.publish_page(pending, job_key=key, expected_revision=revisions[key],
                                          cursor={'capacity_page': revisions[key] + 1})
                revisions[key] += 1

        async def drained():
            async with asyncio.timeout(180):
                while await storage.client.xlen(worker.redis.stream):
                    if worker.health().get('status') == 'degraded':
                        raise RuntimeError(worker.health().get('error', 'archive degraded'))
                    await asyncio.sleep(.005)

        # Seed proofs by the formal writer, not by manufacturing cache hashes.
        for offset in range(0, len(templates), 16):
            await publish(templates[offset:offset + 16], uuid4().hex)
        await drained()
        from sqlalchemy import event
        sql_calls, sql_write_tables = Counter(), Counter()
        import re

        def lock_snapshot():
            storage.verify_sql_owner()
            return {key: int(value) for key, value in storage.conn.exec_driver_sql(
                "SHOW GLOBAL STATUS WHERE Variable_name IN "
                "('Innodb_row_lock_waits','Innodb_row_lock_time','Innodb_deadlocks')")}

        lock_before = await asyncio.to_thread(lock_snapshot)

        def capture(conn, cursor, statement, parameters, context, executemany):
            sql_calls[statement.split(None, 1)[0].upper()] += 1
            match = re.match(r'\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+`?(\w+)', statement, re.I)
            if match:
                sql_write_tables[match[1]] += 1

        engines = [mysql.engine, mysql.read_engine]
        if hasattr(mysql, 'archive_engine'):
            engines.append(mysql.archive_engine)
        for engine in engines:
            event.listen(engine, 'before_cursor_execute', capture)
        try:
            for trial in range(args.rounds):
                sql_calls.clear()
                if args.seconds:
                    from archive_capacity_trial import timed_trial
                    result_trial = await timed_trial(args, trial, worker, ingest, storage,
                                                      templates, publish, drained)
                    result_trial.update(sql_statements=sum(sql_calls.values()),
                        sql_dml=sum(sql_calls[x] for x in ('INSERT', 'UPDATE', 'DELETE')))
                    trials.append(result_trial)
                    if args.workload in ('A', 'C'):
                        assert not sql_calls, 'trusted proofs accessed SQL'
                    continue
                before = worker.stats['archived']
                began = perf_counter()
                for offset in range(0, args.messages, 16):
                    values = []
                    for number in range(offset, min(args.messages, offset + 16)):
                        if args.workload == 'B' and number % 10 in (8, 9):
                            index = (64 + trial * args.messages // 10 + number // 10 if number % 10 == 8
                                     else 32 + number // 10 % 32)
                            revised = (number % 10 == 9
                                       and (trial * args.messages // 10 + number // 10) // 32 % 2 == 0)
                            values.append(fixture(args.dataset, index, revision=revised))
                        else:
                            values.append(templates[number % (32 if args.workload == 'B' else 64)])
                    await publish(values, uuid4().hex)
                await drained()
                seconds = perf_counter() - began
                archived = worker.stats['archived'] - before
                assert archived == args.messages
                if args.workload in ('A', 'C'):
                    assert not sql_calls, 'trusted proofs accessed SQL'
                trials.append(dict(round=trial, messages=archived, seconds=seconds,
                    messages_per_second=archived / seconds,
                    sql_statements=sum(sql_calls.values()), sql_dml=sum(sql_calls[x] for x in ('INSERT', 'UPDATE', 'DELETE'))))
        finally:
            for engine in engines:
                event.remove(engine, 'before_cursor_execute', capture)
        lock_after = await asyncio.to_thread(lock_snapshot)
        from empire.contracts.business_schema import DATASET_TABLE_GROUPS
        declared = {table for template in templates for table in DATASET_TABLE_GROUPS[template['dataset']]}
        declared.add('collection_state')
        assert not (sql_write_tables.keys() - declared), 'writer escaped declared table domain'
        from archive_capacity_queries import verify_queries
        verified = await verify_queries(args, manager, worker, expected_units)
        result.update(trials=trials, identity=storage.identity(), batch_size=args.batch_size,
            experiment=dict(sql_workers=args.sql_workers, compute_workers=args.compute_workers, timings=args.timings),
            archive_metrics=worker.metrics.snapshot(worker.catalog.project_id(
                make_envelope(**templates[0], run_id='metrics', batch_id='metrics'))) if hasattr(worker, 'metrics') else None,
            compute=worker.catalog.health().get('compute'),
            fixture_sha256=hashlib.sha256(json.dumps(templates, sort_keys=True).encode()).hexdigest(),
            fixture_wire_bytes=[len(json.dumps(t['payload'], ensure_ascii=False, separators=(',', ':')).encode()) for t in templates[:1]],
            sql_write_tables=dict(sql_write_tables), declared_write_tables=sorted(declared),
            sql_lock_counters={key: lock_after[key] - value for key, value in lock_before.items()},
            query_verified=True, query_verification=verified, pending=await storage.client.xlen(worker.redis.stream))
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        if hasattr(args, 'failed_trial'):
            result['failed_trial'] = args.failed_trial
    finally:
        cleanup_errors = []

        async def cleanup_step(name, operation):
            try:
                await operation()
                return True
            except Exception as exc:
                cleanup_errors.append(name + ': ' + type(exc).__name__ + ': ' + str(exc))
                return False

        stopped = not manager or await cleanup_step('shutdown', manager.shutdown)
        # Never delete storage while a producer/transaction may still own it.
        if stopped:
            if await cleanup_step('redis', storage.cleanup_redis):
                clean['redis'] = not storage.redis_owned
            if await cleanup_step('sql', lambda: asyncio.to_thread(storage.cleanup_sql)):
                clean['sql'] = not storage.created
        storage.remove_guard()
        await cleanup_step('sql-release', lambda: asyncio.to_thread(storage.release_sql))
        if storage.client:
            await cleanup_step('redis-close', storage.client.aclose)
        result['cleanup'] = clean
        result['cleanup_errors'] = cleanup_errors
        result['input_unchanged'] = inputs(args.source) == frozen_inputs
        result['correctness_passed'] = (result['error'] is None and all(clean.values())
                                         and not cleanup_errors and result['input_unchanged'])
        threshold = {'A': 500, 'B': 100}.get(args.workload)
        result['capacity_passed'] = (all(t['messages_per_second'] >= threshold
            and (t.get('event_loop_lag_ms', {}).get('p99') or 0) <= 100
            and (t.get('status_query_ms', {}).get('p95') or 0) <= 1000
            and (t.get('checkpoint_query_ms', {}).get('p95') or 0) <= 1000 for t in trials)
                                     if threshold is not None and trials else None)
        result['full_acceptance'] = False
        result['passed'] = result['correctness_passed'] and result['capacity_passed'] is True
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    return result['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('src'))
    parser.add_argument('--mysql-settings', type=Path, required=True)
    parser.add_argument('--dataset', choices=('financial', 'capital', 'calendar', 'mixed'), required=True)
    parser.add_argument('--workload', choices=('A', 'B', 'C'), required=True)
    parser.add_argument('--batch-size', type=int, choices=(1, 8, 16, 32), default=16)
    parser.add_argument('--sql-workers', type=int, choices=(1, 2, 4, 8), default=1)
    parser.add_argument('--compute-workers', type=int, choices=(0, 2, 4, 8), default=4)
    parser.add_argument('--timings', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--messages', type=int, default=320)
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--warmup', type=int, default=0)
    parser.add_argument('--seconds', type=int, default=0)
    parser.add_argument('--arrival-rate', type=float, default=500)
    parser.add_argument('--max-producer-lateness', type=int, default=30)
    parser.add_argument('--producer-queue-window', type=int, default=0)
    parser.add_argument('--pause-after', type=int, default=60)
    parser.add_argument('--pause-seconds', type=int, default=0)
    parser.add_argument('--include-source', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not 16 <= args.messages <= 4096 or not 1 <= args.rounds <= 8:
        parser.error('new output and bounded message/round count required')
    if args.workload == 'B' and args.messages % 10:
        parser.error('B requires a multiple of ten messages for exact 80/10/10 proportions')
    if (not 0 <= args.warmup <= 300 or not 0 <= args.seconds <= 1800
            or not 1 <= args.arrival_rate <= 2000
            or not 30 <= args.max_producer_lateness <= 1800
            or not 0 <= args.producer_queue_window <= 4096
            or not 0 <= args.pause_seconds <= 30 or not 0 <= args.pause_after <= 1500
            or args.workload == 'B' and (args.warmup + args.seconds) * args.arrival_rate > 90000):
        parser.error('bounded time/rate and B cache cardinality required')
    if args.seconds and args.workload == 'B' and args.dataset == 'calendar':
        parser.error('calendar has a finite historical month set; sustained 10% new months is not representative')
    if args.include_source and (args.workload != 'C' or args.dataset not in ('financial', 'capital')):
        parser.error('source timing requires a financial or capital C fixture')
    sys.path[:0] = [str(args.source.resolve()), str(Path(__file__).resolve().parents[1])]
    raise SystemExit(0 if asyncio.run(measure(args)) else 1)
