"""Independent five-year forex SQL capacity; no production business writes."""
import argparse
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
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import event, text

from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.fx import dataset
from empire.features.fx.contract import DAILY_JOB, DATASET, SYMBOLS, TABLES
from empire.features.fx.query import FxDailyQuery
from scripts.capacity_session import CapacitySession
from scripts.schema_evidence_scope import objects

INPUTS = tuple('src/empire/features/fx/' + n + '.py' for n in ('contract', 'source', 'dataset', 'query')) + ('scripts/measure_fx.py',)


async def run(args):
    root = Path(__file__).resolve().parents[1]
    session = CapacitySession(load_config()['mysql'], json.loads(Path(args.test_settings).read_text('utf8')),
        root=root, subject='preview', output=args.report, input_paths=INPUTS)
    schema = (root / 'sql/schema.sql').read_text('utf8')
    statements = {t: re.search(r'CREATE TABLE IF NOT EXISTS ' + t + r'\s*\([\s\S]*?;', schema)[0] for t in TABLES}
    fixtures, writes = [], []
    for code in SYMBOLS:
        for year in range(2020, 2025):
            start, end = date(year, 1, 1), date(year, 12, 31)
            rows = [[(start + timedelta(days=i)).isoformat(), '6.1', '7', '5', '6.9'] for i in range((end - start).days + 1)]
            e = make_envelope(source='ths', dataset=DATASET, business_key=f'{code}:{year}', job_key=DAILY_JOB,
                batch_id='capacity', run_id='capacity', payload=dict(page=len(fixtures) + 1, code=code, year=year,
                    mode='full', source_count=len(rows), start=start.isoformat(), end=end.isoformat(), rows=rows))
            fixtures.append((e, dataset.normalize(e)))
    def capture(conn, cursor, sql, *args):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and 'fx_' in sql:
            writes.append(sql)
    with session:
        engine = session.engine
        with engine.begin() as conn:
            for ddl in statements.values():
                conn.exec_driver_sql(ddl)
        tracemalloc.start()
        started = time.perf_counter()
        for e, data in fixtures:
            with engine.begin() as conn:
                dataset.write(conn, e, dict(data, archive_state={}))
        imported = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        event.listen(engine, 'before_cursor_execute', capture)
        for e, data in fixtures:
            with engine.begin() as conn:
                dataset.write(conn, e, dict(data, archive_state={}))
        repeated = len(writes)
        e, data = fixtures[0]
        revised = {**data, 'rows': [list(r) for r in data['rows']], 'archive_state': {}}
        revised['rows'][0][4] = '6.8'
        with engine.begin() as conn:
            dataset.write(conn, e, revised)
        revision_dml = len(writes) - repeated
        event.remove(engine, 'before_cursor_execute', capture)
        q = FxDailyQuery()
        async def read(fn, *args):
            return fn(*args)
        q.mysql = SimpleNamespace(read_engine=engine, read=read)
        pages, coverage, years = [], [], []
        for _ in range(10):
            at = time.perf_counter()
            page = await q.browse(start='2024-01-01', end='2024-12-31', limit=200)
            pages.append((time.perf_counter() - at) * 1000)
            at = time.perf_counter()
            await q.inventory('2024-12-31')
            coverage.append((time.perf_counter() - at) * 1000)
            at = time.perf_counter()
            with engine.connect() as conn:
                annual = dataset.sql_rows(conn, 'USDCNH', 2024)
            years.append((time.perf_counter() - at) * 1000)
        plans = {}
        with engine.connect() as conn:
            for label, sql in dict(
                page="SELECT * FROM fx_daily_price WHERE trade_date BETWEEN '2024-01-01' AND '2024-12-31' ORDER BY trade_date DESC,unified_code LIMIT 200",
                security="SELECT * FROM fx_daily_price WHERE unified_code='USDCNH.FX' AND trade_date BETWEEN '2024-01-01' AND '2024-12-31' ORDER BY trade_date LIMIT 366",
                analysis="SELECT trade_date,AVG(close) FROM fx_daily_price WHERE trade_date BETWEEN '2024-01-01' AND '2024-12-31' GROUP BY trade_date",
            ).items():
                plans[label] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + sql).mappings()]
                plans[label + '_actual'] = [r[0] for r in conn.exec_driver_sql('EXPLAIN ANALYZE ' + sql)]
                plans[label + '_returned'] = len(conn.exec_driver_sql(sql).all())
            conn.exec_driver_sql('ANALYZE TABLE ' + ','.join(TABLES)).all()
            allocation = [dict(r) for r in conn.execute(text('SELECT table_name,data_length,index_length FROM information_schema.tables WHERE table_schema=:db'), dict(db=session.database)).mappings()]
        measured = dict(import_seconds=imported, repeated_business_dml=repeated,
            revision_dml=revision_dml, page_max_ms=max(pages), coverage_max_ms=max(coverage),
            annual_max_ms=max(years), allocated_bytes=sum(int(r['DATA_LENGTH']) + int(r['INDEX_LENGTH']) for r in allocation),
            peak_python_bytes=peak, page_bytes=len(json.dumps(page, default=str).encode()), annual_rows=len(annual))
        limits = dict(import_seconds=30, repeated_business_dml=0, revision_dml=2,
            page_max_ms=300, coverage_max_ms=300, annual_max_ms=300,
            allocated_bytes=16 * 1024**2, peak_python_bytes=32 * 1024**2, page_bytes=262144, annual_rows=366)
        session.report.update(dataset=DATASET, measurements=measured, limits=limits,
            bindings=session.frozen_inputs, ddl_scopes={t: hashlib.sha256(v.encode()).hexdigest() for t, v in statements.items()},
            schema_objects=objects(schema, json.loads((root / 'sql/schema-contract.json').read_text('utf8')),
                json.loads((root / 'sql/business-schema.json').read_text('utf8')), TABLES),
            explain=plans, conditions=dict(platform=platform.platform(), mysql=session.identity,
                synthetic=True, unit_count=len(fixtures), rows=sum(len(d['rows']) for _, d in fixtures),
                allocation=allocation, cache='First query not forced cold; nine warm; reported maximum of ten',
                peak='tracemalloc, excludes fixtures and driver/native RSS', real_sample='USDCNH full history verified separately'),
            reviewed_tradeoffs='Typed OHLC with range indexes; one annual proof per symbol/year; no minute storage; five-year synthetic calendar is capacity stress, not market calendar.')
        if repeated or revision_dml != 2 or any(measured[k] > v for k, v in limits.items()):
            raise ValueError('Forex capacity budget failed')
        session.measurements_complete = True
    print('PASS forex capacity', measured)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--test-settings', required=True)
    p.add_argument('--report', required=True)
    asyncio.run(run(p.parse_args()))
