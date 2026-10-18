"""Owned test database capacity and formal SQL access-pattern measurement."""
import argparse
import hashlib
import json
import platform
import re
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, text

from empire.contracts.unlocks import digest, fact_key, group_key
from empire.core.config import load_config, project_root
from empire.core.time import mysql_time
from empire.plugins.collectors.tdx_unlocks import UnlockCollector
from empire.plugins.datasets.unlocks import TABLE_COLUMNS, UnlockDataset
from empire.plugins.infra.mysql_store import make_engine


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text('utf-8-sig'))
    production = load_config()['mysql']
    if (settings['host'], settings['port']) == (production['host'], production['port']):
        raise ValueError('容量放大必须独立测试服务')
    sample = json.loads(Path(args.sample).read_text('utf8'))
    if not sample['passed']:
        raise ValueError('真实样本尚未核验')
    seed, member = sample['representative_parent'], sample['representative_detail']
    admin, engine = make_engine(settings), None
    database, created = 'empire_unlock_' + uuid4().hex + '_test', False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4')
            created = True
        engine = make_engine({**settings, 'database': database})
        schema = (root / 'sql/schema.sql').read_text('utf8')
        ddls = {t: re.search(r'CREATE TABLE IF NOT EXISTS ' + t + r'\s*\([\s\S]*?;', schema)[0] for t in TABLE_COLUMNS}
        with engine.begin() as conn:
            for statement in ddls.values():
                conn.exec_driver_sql(statement)
        stamp, unit_p, unit_d = datetime.now(UTC), [], []
        started = time.perf_counter()
        for month in range(100):
            period = f'{2010 + month // 12}-{month % 12 + 1:02d}-15'
            parents, details = [], []
            for security in range(1000):
                p = {**seed, 'unified_code': f'{security:06d}.SH', 'unlock_date': period,
                     'occurrence': 1, 'detail_status': 'present', 'detail_count': 2}
                p['group_key'] = group_key(p)
                p['record_key'] = fact_key(p)
                parents.append(p)
                for holder in range(2):
                    d = {**member, **{k: p[k] for k in ('group_key', 'unified_code', 'unlock_date', 'reason_code')},
                         'holder': member['holder'] + str(holder), 'occurrence': 1}
                    d['record_key'] = fact_key(d, True)
                    details.append(d)
            with engine.begin() as conn:
                for (table, columns), values in zip(TABLE_COLUMNS.items(), (parents, details), strict=True):
                    names = (*columns, 'content_hash', 'version_observed_at')
                    insert = text(f'INSERT INTO {table}({",".join(names)}) VALUES(' + ','.join(':' + k for k in names) + ')')
                    for offset in range(0, len(values), 300):
                        conn.execute(insert, [{**r, 'content_hash': digest(r), 'version_observed_at': mysql_time(stamp)}
                                              for r in values[offset:offset + 300]])
            if month == 0:
                unit_p, unit_d = parents, details
        imported = time.perf_counter() - started
        unit_p.sort(key=lambda r: r['record_key'])
        unit_d.sort(key=lambda r: r['record_key'])
        envelope = UnlockCollector().envelope('2010-01-01|SH', unit_p, unit_d, dict(page=0, batch_id='capacity'), stamp)
        message_bytes = len(envelope.model_dump_json().encode())
        mapping, dml = UnlockDataset(), []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if 'restricted_share_unlock' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                dml.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        data = dict(unit='2010-01-01|SH', parents=unit_p, details=unit_d, row_count=3000, archive_state={})
        started = time.perf_counter()
        with engine.begin() as conn:
            repeat = mapping.write(conn, envelope, data)
        repeated = time.perf_counter() - started
        assert repeat['written_count'] == 0 and not dml
        changed = [{**r, 'name': '容量修订'} if i == 0 else r for i, r in enumerate(unit_p)]
        started = time.perf_counter()
        with engine.begin() as conn:
            revision = mapping.write(conn, envelope, {**data, 'parents': changed})
        revised = time.perf_counter() - started
        assert revision['written_count'] == 1
        event.remove(engine, 'before_cursor_execute', capture)
        queries = dict(page='SELECT * FROM restricted_share_unlock FORCE INDEX(ix_date) ORDER BY unlock_date DESC,unified_code DESC,record_key DESC LIMIT 200',
            security="SELECT * FROM restricted_share_unlock FORCE INDEX(ix_security_date) WHERE unified_code='000000.SH' ORDER BY unlock_date DESC,record_key DESC LIMIT 200",
            detail="SELECT * FROM restricted_share_unlock_detail WHERE group_key='" + unit_p[0]['group_key'] + "' ORDER BY record_key LIMIT 10001",
            month="SELECT * FROM restricted_share_unlock_detail FORCE INDEX(ix_date) WHERE unlock_date>='2010-01-01' AND unlock_date<'2010-02-01' ORDER BY record_key LIMIT 100001",
            range="SELECT unified_code,unlock_date,shares FROM restricted_share_unlock FORCE INDEX(ix_date) WHERE unlock_date BETWEEN '2010-01-01' AND '2010-12-31' ORDER BY unlock_date DESC,unified_code DESC,record_key DESC LIMIT 200")
        timings, returned, plans, peaks, sizes = {}, {}, {}, {}, {}
        with engine.connect() as conn:
            version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            for label, query in queries.items():
                samples = []
                for _ in range(5):
                    started = time.perf_counter()
                    rows = conn.exec_driver_sql(query).all()
                    samples.append((time.perf_counter() - started) * 1000)
                timings[label], returned[label] = max(samples), len(rows)
                sizes[label] = len(json.dumps([list(r) for r in rows], default=str).encode())
                tracemalloc.start()
                conn.exec_driver_sql(query).all()
                peaks[label] = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
                plans[label] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + query).mappings()]
            for table in TABLE_COLUMNS:
                conn.exec_driver_sql('ANALYZE TABLE ' + table)
            allocation = {r['table_name']: dict(data=int(r['data_length']), indexes=int(r['index_length'])) for r in
                conn.execute(text('SELECT table_name AS table_name,data_length AS data_length,index_length AS index_length '
                    'FROM information_schema.tables WHERE table_schema=:db'), dict(db=database)).mappings()}
        allocated = sum(v['data'] + v['indexes'] for v in allocation.values())
        measurements = {**{k + '_ms': v for k, v in timings.items()}, 'allocated_bytes': allocated,
            'projected_1100000_bytes': allocated * 1100000 // 300000, 'import_seconds': imported,
            'repeat_seconds': repeated, 'revision_seconds': revised, 'message_bytes': message_bytes, 'query_peak_bytes': max(peaks.values())}
        limits = {**{k + '_ms': 5000 if k == 'month' else 100 for k in timings}, 'allocated_bytes': 768 * 1024**2,
            'projected_1100000_bytes': 2 * 1024**3, 'import_seconds': 300, 'repeat_seconds': 5,
            'revision_seconds': 5, 'message_bytes': 524288, 'query_peak_bytes': 32 * 1024**2}
        paths = ['src/empire/contracts/unlocks.py', 'src/empire/plugins/datasets/unlocks.py', 'src/empire/plugins/data/unlocks.py', 'scripts/measure_unlocks.py']
        report = dict(checked_at=stamp.isoformat(), conditions=dict(platform=platform.platform(), mysql=version,
            isolation='owned UUID database on independent13338 service', cache='first read then five warm reads; maximum reported',
            rows=dict(parents=100000, details=200000), projection='linear 1100000-row planning estimate; not a measured million-detail import'),
            reviewed_tradeoffs='Two typed business tables; request-group shared details; bounded month snapshot and message limits. No stored raw success bodies or duplicated per-parent details.',
            measurements=measurements, limits=limits, allocation=allocation, explain=plans, returned=returned, read_bytes=sizes,
            bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
            ddl_scopes={t: hashlib.sha256(ddl.encode()).hexdigest() for t, ddl in ddls.items()},
            passed=all(v <= limits[k] for k, v in measurements.items()))
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', 'utf8')
        print(json.dumps(dict(passed=report['passed'], measurements=measurements), ensure_ascii=False))
        if not report['passed']:
            raise ValueError('解禁容量验收超预算')
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
    parser.add_argument('--sample', required=True)
    parser.add_argument('--output', default='docs/evidence/unlocks-capacity-2026-10-14.json')
    run(parser.parse_args())
