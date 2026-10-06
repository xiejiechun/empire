"""UUID-owned independent MySQL capacity experiment for formal listing-event queries."""
import argparse
import asyncio
import hashlib
import json
import platform
import re
import time
import tracemalloc
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.contracts.listing_status import COLUMNS, DATASET, JOB, bounds, identity, validate_rows
from empire.core.config import load_config, project_root
from empire.plugins.data.listing_status import ListingStatusDataPlugin
from empire.plugins.datasets import listing_status as mapping
from empire.plugins.infra.mysql_store import make_engine


async def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text('utf-8'))
    prod = load_config()['mysql']
    if (settings.get('host'), settings.get('port')) == (prod.get('host'), prod.get('port')):
        raise ValueError('容量实验必须使用独立MySQL服务')
    admin, engine, created = make_engine(settings), None, False
    database = 'empire_' + uuid4().hex + '_test'
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            created = True
        settings = {**settings, 'database': database}
        engine = make_engine(settings)
        ddl = (root/'sql/changes/2026-10-06-listing-status.sql').read_text('utf-8').strip()
        with engine.begin() as conn:
            conn.exec_driver_sql(ddl)
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
        sqls = {
            'page': f'SELECT {",".join(COLUMNS[:-1])} FROM {mapping.TABLE} ORDER BY event_date,unified_code,event_type,record_key LIMIT 201',
            'security': f"SELECT {','.join(COLUMNS[:-1])} FROM {mapping.TABLE} WHERE unified_code='000001.SZ' ORDER BY event_date,unified_code,event_type,record_key LIMIT 201",
            'type': f"SELECT {','.join(COLUMNS[:-1])} FROM {mapping.TABLE} WHERE event_type='terminated' AND event_date BETWEEN '2000-01-01' AND '2009-12-31' ORDER BY event_date,unified_code,event_type,record_key LIMIT 201",
            'month': f"SELECT {','.join(COLUMNS)} FROM {mapping.TABLE} WHERE event_date BETWEEN '2000-01-01' AND '2000-01-31' ORDER BY event_date,unified_code,event_type,record_key LIMIT 5001",
        }
        operations = dict(page=lambda: q.list_events(), security=lambda: q.list_events(code='000001'),
            page_after=lambda: q.list_events(after=after_row[:4]),
            type=lambda: q.list_events(event_type='terminated', start='2000-01-01', end='2009-12-31'),
            detail=lambda: q.detail(first_row[:4]))
        timings, first_ms, actual, explains, analyzed = {}, {}, {}, {}, {}
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
                first_ms[name], timings[name] = samples[0], sorted(samples)[18]
            samples = []
            for _ in range(20):
                started = time.perf_counter()
                mapping.read_month(conn, '2000-01-01', '2000-01-31')
                samples.append((time.perf_counter() - started) * 1000)
            timings['month'] = sorted(samples)[18]
            allocation = conn.execute(text('SELECT data_length+index_length FROM information_schema.tables '
                'WHERE table_schema=:db AND table_name=:table'), dict(db=database, table=mapping.TABLE)).scalar_one()
        bindings = ['src/empire/contracts/listing_status.py', 'src/empire/plugins/datasets/listing_status.py',
            'src/empire/plugins/data/listing_status.py', 'src/empire/plugins/data/listing_status_checks.py',
            'scripts/measure_listing_status.py', 'sql/changes/2026-10-06-listing-status.sql']
        declared = re.search(r'CREATE TABLE IF NOT EXISTS security_listing_event\s*\([\s\S]*?;', ddl).group()
        report = dict(bindings={p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in bindings},
            ddl_scopes={mapping.TABLE: hashlib.sha256(declared.encode()).hexdigest()},
            measurements={**{k + '_p95_ms': v for k, v in timings.items()}, 'import_seconds': import_seconds, 'allocated_bytes': int(allocation)},
            limits=dict(page_p95_ms=50, page_after_p95_ms=50, security_p95_ms=50, type_p95_ms=50, detail_p95_ms=50,
                        month_p95_ms=100, import_seconds=15, allocated_bytes=128*1024**2),
            conditions=dict(platform=platform.platform(), mysql=version, rows=50000, months=len(groups), synthetic=True,
                formal_queries=True, cache='unforced first; subsequent hot samples; no cold-cache reset', description_chars=[32,160,2000]),
            reviewed_tradeoffs='正式列表不投影正文；详情点查；单月覆盖最多5000行。5万事件为独立服务容量实验，不是生产实采范围。首读未强制冷缓存，磁盘冷启动和全设备吞吐不作承诺。',
            first_query_ms=first_ms, python_peak_bytes=peak, explain=explains, explain_analyze=analyzed, queries=actual,
            imported=initial, repeat=repeat, revision=revision, cleanup='UUID-owned test database dropped in finally')
        report['passed'] = all(report['measurements'][k] <= v for k,v in report['limits'].items())
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps(dict(passed=report['passed'], measurements=report['measurements'])))
        if not report['passed'] or repeat['written_count'] != 0 or revision['written_count'] != 1:
            raise RuntimeError('容量或重复/修订写入验收失败')
    finally:
        if engine:
            engine.dispose()
        if created:
            assert database.endswith('_test')
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{database}`')
        admin.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--output', default='docs/evidence/listing-status-capacity-2026-10-06.json')
    asyncio.run(run(parser.parse_args()))
