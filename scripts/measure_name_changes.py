"""Isolated typed name-table load/query evidence, never production writes."""
import argparse
import hashlib
import json
import platform
import time
import tracemalloc
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.contracts.name_changes import SCHEMA_VERSION, identity, pack_rows
from empire.core.config import load_config, project_root
from empire.plugins.datasets.name_changes import NameDataset
from empire.plugins.infra.mysql_store import initialize_database, make_engine


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text('utf-8'))
    production = load_config()['mysql']
    if (settings.get('host'), settings.get('port')) == (production.get('host'), production.get('port')):
        raise ValueError('容量实验必须使用独立MySQL服务')
    admin = make_engine(settings)
    db = 'empire_' + uuid4().hex + '_test'
    engine, created = None, False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            created = True
        settings = {**settings, 'database': db}
        initialize_database(settings)
        engine = make_engine(settings)
        mapping, now = NameDataset('security'), datetime.now(UTC)
        rows = sorted([[f'{i % 5000:06d}.SH', (date(2020, 1, 1) + timedelta(days=i // 5000)).isoformat(),
                        '原名称' + str(i // 5000), '新名称' + str(i // 5000), 1, '证监会行业'+str(i%100), '通达信行业'+str(i%200)] for i in range(25000)], key=identity)
        batch = uuid4().hex
        e = make_envelope(source='tdx', dataset='names.security.market', business_key='SH',
            job_key=mapping.JOB, batch_id=batch, run_id=batch,
            schema_version=SCHEMA_VERSION, payload=dict(page=1, market='SH', through=now.date().isoformat(), **pack_rows(rows), source_count=len(rows)))
        normalized = mapping.normalize(e)
        data = {**normalized, 'archive_state': {}}
        tracemalloc.start()
        started = time.perf_counter()
        with engine.begin() as conn:
            initial = mapping.write(conn, e, data)
        import_seconds = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        with engine.begin() as conn:
            repeat = mapping.write(conn, e, data)
        revised = [list(r) for r in rows]
        revised[0][3] += '修订'
        revised.sort(key=identity)
        with engine.begin() as conn:
            revision = mapping.write(conn, e, {**data, 'rows': revised})
        sqls = {
            'page': "SELECT unified_code,event_date,old_name,new_name,source_occurrences,csrc_industry,tdx_industry FROM security_name_change WHERE name_kind='security' ORDER BY event_date,unified_code,record_key LIMIT 200",
            'security': "SELECT unified_code,event_date,old_name,new_name,csrc_industry,tdx_industry FROM security_name_change WHERE name_kind='security' AND unified_code='000001.SH' AND event_date BETWEEN '2020-01-01' AND '2026-10-05' ORDER BY event_date,record_key LIMIT 200",
            'coverage': "SELECT unified_code,event_date,old_name,new_name,source_occurrences,csrc_industry,tdx_industry FROM security_name_change WHERE name_kind='security' ORDER BY record_key LIMIT 30001",
        }
        timings, explain, actual = {}, {}, {}
        with engine.connect() as conn:
            version = conn.execute(text('SELECT VERSION()')).scalar_one()
            conn.exec_driver_sql('ANALYZE TABLE security_name_change')
            for name, sql in sqls.items():
                samples = []
                for _ in range(20):
                    started = time.perf_counter()
                    result = conn.exec_driver_sql(sql).all()
                    samples.append((time.perf_counter() - started) * 1000)
                timings[name] = sorted(samples)[18]
                actual[name] = dict(returned=len(result), read_bytes=len(json.dumps([list(r) for r in result], ensure_ascii=False, default=str).encode()))
                explain[name] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + sql).mappings()]
            allocation = conn.execute(text('SELECT data_length+index_length FROM information_schema.tables '
                'WHERE table_schema=:db AND table_name=\'security_name_change\''), {'db': db}).scalar_one()
        bindings = ['sql/schema.sql', 'sql/schema-contract.json', 'src/empire/contracts/name_changes.py',
                    'src/empire/plugins/datasets/name_changes.py', 'src/empire/plugins/data/name_changes.py',
                    'scripts/measure_name_changes.py']
        report = dict(bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in bindings},
            measurements=dict(page_p95_ms=timings['page'], security_p95_ms=timings['security'],
                coverage_p95_ms=timings['coverage'], import_seconds=import_seconds, allocated_bytes=int(allocation)),
            limits=dict(page_p95_ms=50, security_p95_ms=50, coverage_p95_ms=500, import_seconds=10, allocated_bytes=128 * 1024**2),
            conditions=dict(platform=platform.platform(), mysql=version, rows=25000, cache='first query unforced; subsequent hot repetitions', synthetic=True),
            reviewed_tradeoffs='紧凑事件字段有SQL索引；覆盖检查全读本类型至30000上限，普通页面200行。25000条是容量实验，不冒充可一次入队的真实响应；超单次消息预算明确失败。',
            explain=explain, queries=actual, python_peak_bytes=peak, initial=initial, repeat=repeat, revision=revision,
            cleanup='UUID-owned test database dropped in finally')
        report['passed'] = all(report['measurements'][k] <= limit for k, limit in report['limits'].items())
        if repeat['written_count'] != 0 or revision['written_count'] != 2:
            raise RuntimeError('重复或单条修订业务DML数量不符')
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps(dict(passed=report['passed'], measurements=report['measurements'])))
    finally:
        if engine:
            engine.dispose()
        if created:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{db}`')
        admin.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--output', default='docs/evidence/name-changes-capacity-2026-10-05.json')
    run(parser.parse_args())
