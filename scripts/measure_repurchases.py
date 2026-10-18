"""UUID-owned database on an independent test MySQL service; no production writes."""
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
from empire.contracts.repurchases import COLUMNS, DATASET, JOB, validate
from empire.core.config import load_config, project_root
from empire.plugins.data.repurchases import LIST_COLUMNS
from empire.plugins.datasets import repurchases as mapping
from empire.plugins.infra.mysql_store import make_engine


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text('utf-8-sig'))
    production = load_config()['mysql']
    if (settings['host'], settings['port']) == (production['host'], production['port']):
        raise ValueError('容量测试必须使用独立MySQL服务')
    seed = json.loads(Path(args.source_proof).read_text('utf-8'))['first']
    admin, engine, created = make_engine(settings), None, False
    db = 'empire_repurchase_' + uuid4().hex + '_test'
    sql = (root/'sql/schema.sql').read_text('utf-8')
    statement = re.search(r'CREATE TABLE IF NOT EXISTS stock_repurchase_plan\s*\([\s\S]*?;', sql)[0]
    envelope = make_envelope(source='eastmoney', dataset=DATASET, job_key=JOB,
                             batch_id=uuid4().hex, run_id=uuid4().hex, business_key='capacity', payload={})
    def group(offset, revised=False):
        result = []
        for i in range(offset, min(offset+500, 50000)):
            r = {**seed, 'plan_id': str(i+1), 'unified_code': f'{i%5000:06d}.SH',
                 'plan_date': (date(2020, 1, 1)+timedelta(days=i//5000)).isoformat(),
                 'remark': ('来源说明'*140) + ('修订' if revised and i == 0 else '')}
            result.append(validate(r))
        return sorted(result, key=lambda r: r['plan_id'])
    def load(conn, revised=False):
        written = 0
        for offset in range(0, 50000, 500):
            rows = group(offset, revised)
            written += mapping.write(conn, envelope, dict(rows=rows, row_count=len(rows)))['written_count']
        return written
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
            created = True
        engine = make_engine({**settings, 'database': db})
        with engine.begin() as conn:
            conn.exec_driver_sql(statement)
        tracemalloc.start()
        start = time.perf_counter()
        with engine.begin() as conn:
            initial = load(conn)
        seconds = time.perf_counter()-start
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        dml = []
        def record(conn, cursor, sql, parameters, context, executemany):
            if 'stock_repurchase_plan' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                dml.append(sql)
        event.listen(engine, 'before_cursor_execute', record)
        with engine.begin() as conn:
            repeat = load(conn)
        assert not dml and repeat == 0
        with engine.begin() as conn:
            revised = load(conn, True)
        assert revised == 1
        event.remove(engine, 'before_cursor_execute', record)
        queries = {
            'page': f'SELECT {",".join(LIST_COLUMNS)} FROM stock_repurchase_plan ORDER BY plan_date DESC,plan_id DESC LIMIT 200',
            'security': f'SELECT {",".join(LIST_COLUMNS)} FROM stock_repurchase_plan WHERE unified_code=\'000001.SH\' AND plan_date>=\'2020-01-01\' ORDER BY plan_date DESC,plan_id DESC LIMIT 200',
            'progress': f'SELECT {",".join(LIST_COLUMNS)} FROM stock_repurchase_plan WHERE progress_code=\'006\' ORDER BY plan_date DESC,plan_id DESC LIMIT 200',
            'detail': f'SELECT {",".join(COLUMNS)} FROM stock_repurchase_plan WHERE plan_id=\'1\'',
            'coverage': 'SELECT plan_id,content_hash FROM stock_repurchase_plan ORDER BY plan_id LIMIT 100000',
        }
        timings, plans, actual = {}, {}, {}
        with engine.connect() as conn:
            conn.exec_driver_sql('ANALYZE TABLE stock_repurchase_plan')
            version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            for key, query in queries.items():
                samples = []
                for _ in range(10):
                    start = time.perf_counter()
                    rows = conn.exec_driver_sql(query).all()
                    samples.append((time.perf_counter()-start)*1000)
                timings[key] = sorted(samples)[-1]
                plans[key] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN '+query).mappings()]
                actual[key] = dict(returned=len(rows), read_bytes=len(json.dumps([list(r) for r in rows], ensure_ascii=False, default=str).encode()),
                                  estimated_scan_rows=sum(r['rows'] or 0 for r in plans[key]), first_ms=samples[0])
            allocated = conn.execute(text('SELECT data_length+index_length FROM information_schema.tables WHERE table_schema=:db AND table_name=\'stock_repurchase_plan\''), {'db':db}).scalar_one()
            version_rows = conn.exec_driver_sql('SELECT COUNT(*) FROM stock_repurchase_plan').scalar_one()
        bindings = ['src/empire/contracts/repurchases.py', 'src/empire/plugins/datasets/repurchases.py',
                    'src/empire/plugins/data/repurchases.py', 'scripts/measure_repurchases.py']
        report = dict(checked_at=datetime.now(UTC).isoformat(),
            bindings={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in bindings},
            ddl_scopes={'stock_repurchase_plan':hashlib.sha256(statement.encode()).hexdigest()},
            measurements=dict(page_p95_ms=timings['page'], security_p95_ms=timings['security'],
                progress_p95_ms=timings['progress'], detail_p95_ms=timings['detail'], coverage_p95_ms=timings['coverage'],
                import_seconds=seconds, allocated_bytes=int(allocated), repeated_business_dml=repeat),
            limits=dict(page_p95_ms=100, security_p95_ms=100, progress_p95_ms=100, detail_p95_ms=100,
                coverage_p95_ms=1000, import_seconds=60, allocated_bytes=256*1024**2, repeated_business_dml=0),
            conditions=dict(platform=platform.platform(), mysql=version, rows=version_rows, source_sample='normalized live first plan; 2100-byte synthetic remark; 5000 securities/10 dates',
                            cache='first unforced, nine hot repetitions; max of ten conservatively bounds P95', synthetic=True, independent_test_service=True),
            reviewed_tradeoffs='一次方案一行typed存储；索引对应范围/状态/证券查询，TEXT不进入列表。完整审计有界200行逐批读取，轻量头覆盖扫描与正文审计不同；5万行放大实验不是生产覆盖声明。',
            explain=plans, queries=actual, python_peak_bytes=peak, initial_rows_written=initial,
            revised_rows_written=revised, cleanup='only UUID-owned test database dropped')
        report['passed'] = all(report['measurements'][k] <= maximum for k, maximum in report['limits'].items())
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
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
    parser.add_argument('--source-proof', default='build/repurchase-source-proof.json')
    parser.add_argument('--output', default='docs/evidence/repurchase-capacity-2026-10-12.json')
    run(parser.parse_args())
