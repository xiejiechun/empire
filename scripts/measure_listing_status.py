"""Original 50000-event capacity protocol with owned guarded storage and cleanup."""
import asyncio
import hashlib
import json
import platform
import re
import sys
import time
import tracemalloc
from datetime import date, timedelta
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from uuid import uuid4

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_test_storage import PrivateStorage, read_server_uuid, test_settings
from source_verification import require
from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.data import make_envelope
from empire.core.config import default_config_path, load_config, project_root
from empire.core.preparation_release import source_digest
from empire.core.redaction import Redactor
from empire.features.listing_status import dataset as mapping
from empire.features.listing_status.contract import (
    COLUMNS,
    DATASET,
    JOB,
    bounds,
    digest,
    identity,
    validate_rows,
)
from empire.features.listing_status.query import ListingStatusDataPlugin
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.sql_lane import settle

CAPACITY_QUERIES = {
            'page': f'SELECT {",".join(COLUMNS[:-1])} FROM {mapping.TABLE} ORDER BY event_date,unified_code,event_type,record_key LIMIT 201',
            'security': f"SELECT {','.join(COLUMNS[:-1])} FROM {mapping.TABLE} WHERE unified_code='000001.SZ' ORDER BY event_date,unified_code,event_type,record_key LIMIT 201",
            'type': f"SELECT {','.join(COLUMNS[:-1])} FROM {mapping.TABLE} WHERE event_type='terminated' AND event_date BETWEEN '2000-01-01' AND '2009-12-31' ORDER BY event_date,unified_code,event_type,record_key LIMIT 201",
            'month': f"SELECT {','.join(COLUMNS)} FROM {mapping.TABLE} WHERE event_date BETWEEN '2000-01-01' AND '2000-01-31' ORDER BY event_date,unified_code,event_type,record_key LIMIT 5001",
        }


class ListingStatusCapacityStorage(PrivateStorage):
    def guard(self, conn, cursor, statement, parameters, context, executemany):
        approved = {'ANALYZE TABLE security_listing_event',
            *(prefix+q for prefix in ('EXPLAIN ', 'EXPLAIN ANALYZE ') for q in CAPACITY_QUERIES.values())}
        if statement in approved and not parameters:
            super().guard(conn, cursor, 'SELECT 1', (), context, False)
            return
        super().guard(conn, cursor, statement, parameters, context, executemany)


async def measure_inner(engine, database):
    root = project_root()
    groups, all_rows = {}, []
    for i in range(50000):
        month_i, day_i = divmod(i, 420)
        year, month = 2000 + month_i // 12, month_i % 12 + 1
        day = date(year, month, 1) + timedelta(days=day_i % 28)
        size = 2000 if i % 100 == 0 else 160 if i % 5 else 32
        row = [day.isoformat(), f'{i % 5000:06d}.SZ', ('suspended', 'resumed', 'terminated')[i % 3],
               '', '样本证券', '说明' * (size // 2)]
        row[3] = identity(row)
        groups.setdefault(day.strftime('%Y-%m'), []).append(row)
        all_rows.append(row)
    batch, initial, states = uuid4().hex, 0, {}
    tracemalloc.start()
    started = time.perf_counter()
    for month, rows in groups.items():
        a, b = bounds(month, date(2010, 12, 31))
        rows = validate_rows(rows, a, b)
        counts = [0] * ((b - a).days + 1)
        for row in rows:
            counts[(date.fromisoformat(row[0]) - a).days] += 1
        envelope = make_envelope(source='tdx', dataset=DATASET, job_key=JOB, run_id=batch, batch_id=batch,
            business_key=month, payload=dict(page=1, month=month, end=b.isoformat(), rows=rows, source_counts=counts))
        data = {**mapping.normalize(envelope), 'archive_state': states}
        with engine.begin() as conn:
            outcome = mapping.write(conn, envelope, data)
            initial += outcome['written_count']
        states = mapping.archive_state(envelope, data, outcome, states)
    import_seconds = time.perf_counter() - started
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    data['archive_state'] = states
    with engine.begin() as conn:
        repeat = mapping.write(conn, envelope, data)
        revised = [list(r) for r in data['rows']]
        revised[0][4] = '修订名称'
        revision = mapping.write(conn, envelope, {**data, 'rows': revised})
    q = ListingStatusDataPlugin()
    async def read(operation, *args):
        return operation(*args)
    q.mysql = SimpleNamespace(read_engine=engine, read=read)
    q.context = None
    first_row = all_rows[1]
    after_row = sorted(all_rows, key=lambda r: tuple(r[:4]))[40000]
    sqls = CAPACITY_QUERIES
    operations = dict(page=lambda: q.list_events(), security=lambda: q.list_events(code='000001'),
        page_after=lambda: q.list_events(after=after_row[:4]),
        type=lambda: q.list_events(event_type='terminated', start='2000-01-01', end='2009-12-31'),
        detail=lambda: q.detail(first_row[:4]))
    timings, first_ms, actual, explains, analyzed, raw_samples = {}, {}, {}, {}, {}, {}
    with engine.connect() as conn:
        version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
        conn.exec_driver_sql(f'ANALYZE TABLE {mapping.TABLE}')
        for name, sql in sqls.items():
            explains[name] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + sql).mappings()]
            analyzed[name] = conn.exec_driver_sql('EXPLAIN ANALYZE ' + sql).scalar_one()
            records = conn.exec_driver_sql(sql).all()
            actual[name] = dict(rows=len(records), read_bytes=len(json.dumps([list(r) for r in records], ensure_ascii=False, default=str).encode()))
        for name, operation in operations.items():
            samples = []
            for _ in range(20):
                started = time.perf_counter()
                await operation()
                samples.append((time.perf_counter() - started) * 1000)
            raw_samples[name] = samples
            first_ms[name], timings[name] = samples[0], sorted(samples)[18]
        samples = []
        for _ in range(20):
            started = time.perf_counter()
            mapping.read_month(conn, '2000-01-01', '2000-01-31')
            samples.append((time.perf_counter() - started) * 1000)
        raw_samples['month'] = samples
        timings['month'] = sorted(samples)[18]
        allocation = conn.execute(text('SELECT data_length+index_length FROM information_schema.tables '
            'WHERE table_schema=:db AND table_name=:object_name'), dict(db=database, object_name=mapping.TABLE)).scalar_one()
    bindings = ['src/empire/features/listing_status/contract.py', 'src/empire/features/listing_status/dataset.py',
        'src/empire/features/listing_status/query.py', 'src/empire/features/listing_status/audit.py',
        'scripts/measure_listing_status.py', 'scripts/source_test_storage.py', 'scripts/source_verification.py', 'sql/business-schema.json', 'src/empire/contracts/business_schema.py']
    declared = re.search(r'CREATE TABLE IF NOT EXISTS security_listing_event\s*\([\s\S]*?;', (root/'sql/schema.sql').read_text('utf-8')).group()
    report = dict(bindings={p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in bindings},
        ddl_scopes={mapping.TABLE: hashlib.sha256(declared.encode()).hexdigest()},
        measurements={**{k + '_p95_ms': v for k, v in timings.items()}, 'import_seconds': import_seconds, 'allocated_bytes': int(allocation)},
        limits=dict(page_p95_ms=50, page_after_p95_ms=50, security_p95_ms=50, type_p95_ms=50, detail_p95_ms=50,
                    month_p95_ms=100, import_seconds=15, allocated_bytes=128*1024**2),
        conditions=dict(platform=platform.platform(), mysql=version, rows=50000, audited=50000, months=len(groups), synthetic=True,
            formal_queries=True, cache='unforced first; subsequent hot samples; no cold-cache reset', description_chars=[32,160,2000]),
        reviewed_tradeoffs='正式列表不投影正文；详情点查；单月覆盖最多5000行。5万事件为独立服务容量实验，不是生产实采范围。首读未强制冷缓存，磁盘冷启动和全设备吞吐不作承诺。',
        first_query_ms=first_ms, python_peak_bytes=peak, explain=explains, explain_analyze=analyzed, queries=actual,
        imported=initial, repeat=repeat, revision=revision, samples=raw_samples, cleanup_protocol='shared finish; final durable report after independent cleanup')

    expected = {tuple(r[:4]): list(r) for r in all_rows}
    expected[tuple(revised[0][:4])] = revised[0]
    with engine.connect() as conn:
        records = conn.execute(text('SELECT '+','.join(COLUMNS)+' FROM security_listing_event '
            'ORDER BY event_date,unified_code,event_type,record_key LIMIT 50001')).all()
        observed = [[r[0].isoformat(), *r[1:]] for r in records]
    require(observed == sorted(expected.values(), key=lambda r: tuple(r[:4])), '50000事件完整集合内容不同')
    require(initial == 50000 and repeat['written_count'] == 0 and revision['written_count'] == 1,
            '初始导入/重复/修订写入数不同')
    report['correctness'] = dict(all_rows_equal=True, row_count=len(observed), content_digest=digest(observed))
    return report


def measure(storage):
    engine = make_engine(storage.settings)
    try:
        return asyncio.run(measure_inner(engine, storage.database))
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        engine.dispose()


async def verify(args):
    output, report = verification.initial_report(args)
    storage = lock = None
    redactor = Redactor()
    try:
        require(type(args.timeout) is int and 1 <= args.timeout <= 7200, 'timeout须为1～7200秒')
        require(args.random_count == 0 and args.seed is None and not args.codes, '合成容量不能声明实采随机样本')
        paths = [Path(args.pool_config or default_config_path()).resolve(), Path(args.test_mysql_settings).resolve()]
        report['input_files'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        cfg, raw = load_config(paths[0]), json.loads(paths[1].read_text('utf-8'))
        require(isinstance(raw, dict), '测试连接须为JSON对象')
        redactor = Redactor([cfg['mysql'].get('password'), cfg['redis'].get('password'), raw.get('password')])
        settings = test_settings(raw)
        lock = acquire_instance_lock()
        source_uuid = read_server_uuid(cfg['mysql'])
        report.update(subject='listing_status_capacity', source_sha256=source_digest(project_root()),
                      source_server_uuid=source_uuid, acceptance_complete=False, sample_30_applicable=False,
                      sample_30_reason='50000事件合成容量；不请求来源，不替代完整月份代理实采')
        storage = ListingStatusCapacityStorage(settings, cfg['redis'], report['run_id'], token_hex(32), source_uuid)
        redactor = Redactor([*redactor.secrets, storage.owner])
        ownership = output.with_name(output.name+'.ownership.json')
        verification.write_ownership(ownership, storage, str(paths[1]))
        storage.create_sql(before_create=lambda: verification.write_ownership(ownership, storage, str(paths[1])))
        report['storage'] = storage.identity()
        report['environment'] = dict(storage.conn.exec_driver_sql(
            'SELECT VERSION() AS version,@@port AS port,@@datadir AS datadir,'
            '@@innodb_flush_log_at_trx_commit AS innodb_flush_log_at_trx_commit,'
            '@@sync_binlog AS sync_binlog,@@log_bin AS log_bin').mappings().one())
        await storage.create_redis()
        storage.seed([], [])
        async with asyncio.timeout(args.timeout):
            # Cancellation waits for the SQL worker before owned cleanup, never drops an active writer's database.
            measured = await settle(asyncio.create_task(asyncio.to_thread(measure, storage)))
        report.update(measured)
        report['input_files'].update({str(project_root()/p): sha for p, sha in measured['bindings'].items()})
        require(measured['conditions']['audited'] == 50000, '容量详细审计集合不完整')
        require(all(measured['measurements'][k] <= limit for k, limit in measured['limits'].items()), '容量超出冻结预算')
        require(await storage.client.get(storage.owner_key) == storage.owner, 'Redis归属变化')
        report.update(pipeline_verified=True, acceptance_complete=True)
    except BaseException as exc:
        report['errors'].append(dict(stage='capacity', message=redactor.text(exc, 2048), type=type(exc).__name__))
    finally:
        passed = await verification.complete(output, report, redactor, None, storage, lock, False)
    return passed


def main(argv=None):
    parser = verification.parser(__doc__)
    parser.set_defaults(random_count=0, timeout=900)
    args = parser.parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verify(args))
    print(('CLEANUP COMPLETE' if args.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
