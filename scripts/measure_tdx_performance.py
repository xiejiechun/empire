"""Five typed entities, 100000 rows each, on an independently owned test service."""
import argparse
import hashlib
import json
import platform
import re
import time
import tracemalloc
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, text

from empire.contracts.data import make_envelope
from empire.contracts.tdx_performance import KINDS, columns, digest, identity, source_row
from empire.core.config import load_config, project_root
from empire.core.time import mysql_time
from empire.plugins.datasets.tdx_performance import PerformanceDataset
from empire.plugins.infra.mysql_store import make_engine


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text('utf8'))
    production = load_config()['mysql']
    if (settings['host'], settings['port']) == (production['host'], production['port']):
        raise ValueError('容量验证必须独立MySQL服务，禁止生产放大数据')
    proof = json.loads((root / 'docs/evidence/tdx-performance-probe-2026-10-12.json').read_text('utf8'))
    sql = (root / 'sql/schema.sql').read_text('utf8')
    admin, engine = make_engine(settings), None
    database, created = 'empire_perf_' + uuid4().hex + '_test', False
    measured, ddl_scopes, seeds = {}, {}, {}
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4')
            created = True
        engine = make_engine({**settings, 'database': database})
        for kind, (_, table, suffix, _) in KINDS.items():
            source = next(v for v in proof['results'] if v['label'] == suffix + '_10000')
            raw = dict(zip(source['sets'][0]['columns'], source['sets'][0]['samples'][0], strict=True))
            seed = source_row(kind, raw)
            seeds[kind] = seed
            statement = re.search(r'CREATE TABLE IF NOT EXISTS ' + table + r'\s*\([\s\S]*?;', sql)[0]
            ddl_scopes[table] = hashlib.sha256(statement.encode()).hexdigest()
            with engine.begin() as conn:
                conn.exec_driver_sql(statement)
            names = ('record_key', *columns(kind), 'content_hash', 'version_observed_at')
            insert = text(f'INSERT INTO {table}({",".join(names)}) VALUES(' + ','.join(':' + k for k in names) + ')')
            stamp = datetime.now(UTC)
            sample_unit = []
            started = time.perf_counter()
            for block in range(20):
                period = f'{2020 + block // 4}-{("03-31", "06-30", "09-30", "12-31")[block % 4]}'
                values = []
                for security in range(5000):
                    row = {**seed, 'unified_code': f'{security:06d}.SH'}
                    field = 'statistics_date' if kind == 'holder_count' else 'report_date'
                    row[field] = period
                    if kind != 'holder_count' and 'announcement_date' in row:
                        row['announcement_date'] = (date.fromisoformat(period) + timedelta(days=60)).isoformat()
                    if kind == 'holder_count' and security == 0 or kind != 'holder_count' and block == 0:
                        sample_unit.append(row)
                    values.append({**row, 'record_key': identity(kind, row), 'content_hash': digest(row),
                                   'version_observed_at': mysql_time(stamp)})
                with engine.begin() as conn:
                    for offset in range(0, len(values), 500):
                        conn.execute(insert, values[offset:offset + 500])
            import_seconds = time.perf_counter() - started
            del values
            mapping = PerformanceDataset(kind)
            sample_unit.sort(key=lambda r: identity(kind, r))
            unit = '000000.SH' if kind == 'holder_count' else '2020-03-31|SH'
            envelope = make_envelope(source='tdx', dataset=kind + '.tdx_unit', job_key=mapping.JOB,
                business_key=unit, batch_id='capacity', run_id='capacity', payload={}).model_copy(update={'observed_at': stamp})
            data = dict(unit=unit, rows=sample_unit, row_count=len(sample_unit), archive_state={})
            dml = []
            def capture(conn, cursor, statement, parameters, context, executemany):
                if table in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                    dml.append(statement)
            event.listen(engine, 'before_cursor_execute', capture)
            with engine.begin() as conn:
                repeat = mapping.write(conn, envelope, data)
            assert not dml and repeat['written_count'] == 0
            repeat_dml = len(dml)
            changed = [{**r, 'name': '容量修订'} if index == 0 else r for index, r in enumerate(sample_unit)]
            with engine.begin() as conn:
                revision = mapping.write(conn, envelope, {**data, 'rows': changed})
            assert revision['written_count'] == 1
            event.remove(engine, 'before_cursor_execute', capture)
            field = 'statistics_date' if kind == 'holder_count' else 'report_date'
            queries = {
                'page': f'SELECT * FROM {table} ORDER BY {field} DESC,unified_code DESC,record_key DESC LIMIT 200',
                'security': f"SELECT * FROM {table} WHERE unified_code='000000.SH' ORDER BY {field} DESC,record_key DESC LIMIT 200",
                'detail': f"SELECT * FROM {table} WHERE record_key='{identity(kind, sample_unit[0])}'",
                'range': f"SELECT unified_code,{field} FROM {table} WHERE {field}>='2021-01-01' AND {field}<='2024-12-31' ORDER BY {field} DESC,unified_code DESC,record_key DESC LIMIT 200",
                'coverage': f'SELECT record_key,content_hash FROM {table} ORDER BY record_key LIMIT 100001',
            }
            unit_filter = "unified_code='000000.SH'" if kind == 'holder_count' else "report_date='2020-03-31' AND unified_code LIKE '%%.SH'"
            queries['unit'] = f'SELECT /*+ MAX_EXECUTION_TIME(15000) */ * FROM {table} WHERE {unit_filter} ORDER BY record_key LIMIT 80001'
            timings, plans, returns, peaks = {}, {}, {}, {}
            with engine.connect() as conn:
                conn.exec_driver_sql('ANALYZE TABLE ' + table)
                mysql_version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
                for label, query in queries.items():
                    times, peak_values = [], []
                    for trial in range(5):
                        tracemalloc.start()
                        start = time.perf_counter()
                        result = conn.execution_options(stream_results=True).exec_driver_sql(query)
                        count = 0
                        while values := result.fetchmany(200):
                            count += len(values)
                        elapsed = (time.perf_counter() - start) * 1000
                        peak_values.append(tracemalloc.get_traced_memory()[1])
                        tracemalloc.stop()
                        times.append(elapsed)
                    timings[label] = max(times)
                    returns[label] = count
                    peaks[label] = max(peak_values)
                    plans[label] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + query).mappings()]
                allocated = conn.execute(text('SELECT data_length+index_length FROM information_schema.tables '
                    'WHERE table_schema=:db AND table_name=:table'), {'db': database, 'table': table}).scalar_one()
                actual_rows = conn.exec_driver_sql('SELECT COUNT(*) FROM ' + table).scalar_one()
            measured[kind] = dict(rows=actual_rows, import_seconds=import_seconds, allocated_bytes=int(allocated),
                query_ms=timings, query_peak_bytes=peaks, returned=returns, explain=plans,
                repeated_business_dml=repeat_dml, repeated_rows=repeat['row_count'], revised_rows=revision['written_count'])
            print(json.dumps(dict(kind=kind, rows=actual_rows, queries=timings)), flush=True)
        paths = ['src/empire/contracts/tdx_performance.py', 'src/empire/plugins/datasets/tdx_performance.py',
                 'src/empire/plugins/data/tdx_performance.py', 'scripts/measure_tdx_performance.py']
        measurements = {kind + '_' + label + '_ms': value for kind, result in measured.items() for label, value in result['query_ms'].items()}
        measurements.update({kind + '_allocated_bytes': result['allocated_bytes'] for kind, result in measured.items()})
        measurements.update({kind + '_import_seconds': result['import_seconds'] for kind, result in measured.items()})
        measurements.update({kind + '_query_peak_bytes': max(result['query_peak_bytes'].values()) for kind, result in measured.items()})
        limits = {key: 2000 if key.endswith('_ms') else 512 * 1024**2 if key.endswith('_allocated_bytes') else
                  120 if key.endswith('_import_seconds') else 32 * 1024**2 for key in measurements}
        report = dict(checked_at=datetime.now(UTC).isoformat(),
            bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}, ddl_scopes=ddl_scopes,
            measurements=measurements, limits=limits,
            conditions=dict(platform=platform.platform(), mysql=mysql_version, independent_service=True,
                rows_per_table=100000, cache='first unforced, four warm; maximum conservatively bounds P95',
                source='one normalized live 10000-request row per entity; 5000 securities and 20 synthetic periods'),
            reviewed_tradeoffs='结构化列与证券/日期索引；前十大为汇总而非名单。预告正文随200条页读取，最大文本32768字符。'
                '覆盖以200条流式读取，32MiB预算是单查询Python受测分配。重复/修订测一个完整市场5000行或一个证券20统计日，非全表重复吞吐。'
                '放大实验不代表生产全市场历史覆盖，不能推断冷磁盘延迟或完整进程内存上限。',
            details=measured, representative_rows=seeds, cleanup='only UUID-owned private schema dropped')
        report['passed'] = all(measurements[key] <= maximum for key, maximum in limits.items())
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', 'utf8')
        return report
    finally:
        if engine:
            engine.dispose()
        if created:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{database}`')
        admin.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--output', default='docs/evidence/tdx-performance-capacity-2026-10-12.json')
    run(parser.parse_args())
