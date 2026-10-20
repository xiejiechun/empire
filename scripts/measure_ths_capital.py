"""Bounded typed capital capacity in a UUID-owned, independent MySQL database."""
import argparse
import asyncio
import hashlib
import json
import platform
import re
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import event, text

from empire.contracts.data import make_envelope
from empire.contracts.preparation_scope import PreparationScope
from empire.core.config import load_config
from empire.features.ths_capital.contract import DATASET, JOB, PROJECT, TABLES
from empire.features.ths_capital.dataset import CapitalPageDataset, read_window
from empire.features.ths_capital.query import CapitalPageDataPlugin
from empire.features.ths_capital.source import parse
from empire.features.ths_capital.transport import SCHEMA, pack
from empire.plugins.infra.collection_state_unit import read_unit, save_unit
from scripts.capacity_session import CapacitySession
from tests.test_ths_capital import STOCK, source

INPUT_PATHS = (
    'src/empire/features/ths_capital/transport.py',
    'sql/business-schema.json',
    'src/empire/contracts/business_schema.py',
    'src/empire/features/ths_capital/contract.py',
    'src/empire/features/ths_capital/source.py',
    'src/empire/sources/html.py',
    'src/empire/features/ths_capital/dataset.py',
    'src/empire/features/ths_capital/query.py',
    'scripts/measure_ths_capital.py',
    'scripts/capacity_session.py',
    'tests/test_ths_capital.py',
)


async def run(args):
    root, settings = Path(__file__).resolve().parents[1], json.loads(Path(args.test_settings).read_text('utf-8-sig'))
    prod = load_config()['mysql']
    capacity = CapacitySession(prod, settings, root=root, subject='ths-capital', output=args.report, input_paths=INPUT_PATHS)
    schema = (root / 'sql/schema.sql').read_text('utf8')
    targets = (*TABLES, 'collection_state', 'stock')
    statements = {t: re.search(r'CREATE TABLE IF NOT EXISTS ' + t + r'\s*\([\s\S]*?;', schema)[0] for t in targets}
    mapping, fixtures, dml = CapitalPageDataset(), [], []
    for i in range(700):
        security = f'{600000+i:06d}.SH'
        stock = dict(STOCK, code=security[:6], unified_code=security)
        value = parse(source(duplicate=True).replace('value="601139"', 'value="' + stock['code'] + '"').encode('gb18030'), stock)
        for row in value['rows']['capital_project']:
            row['description'] = '募投项目完整业务说明。' * 90
        e = make_envelope(source='ths', dataset=DATASET, schema_version=SCHEMA, job_key=JOB, business_key=security,
            batch_id=uuid4().hex, run_id=uuid4().hex, payload=dict(page=i+1, unit=security, **{**value, 'rows': pack(value['rows'])}, manifest=None))
        fixtures.append((e, mapping.normalize(e)))
    def capture(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and any(t in sql for t in TABLES):
            dml.append(sql)
    with capacity:
        database, engine = capacity.database, capacity.engine
        with engine.begin() as conn:
            for statement in statements.values():
                conn.exec_driver_sql(statement)
        tracemalloc.start()
        started = time.perf_counter()
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:code,:name)'),
                [dict(code=e.business_key, name='容量测试公司') for e, _ in fixtures])
        for e, data in fixtures:
            with engine.begin() as conn:
                previous, exists = read_unit(conn, 'capacity', PROJECT, 'ths', e.business_key)
                outcome = mapping.write(conn, e, {**data, 'archive_state': previous})
                payload = mapping.archive_state(e, data, outcome, previous)
                save_unit(conn, 'capacity', PROJECT, 'ths', DATASET, e.business_key, payload, previous, exists)
        imported = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        event.listen(engine, 'before_cursor_execute', capture)
        started = time.perf_counter()
        for e, data in fixtures:
            with engine.begin() as conn:
                previous, _ = read_unit(conn, 'capacity', PROJECT, 'ths', e.business_key)
                outcome = mapping.write(conn, e, {**data, 'archive_state': previous})
                if outcome['written_count']:
                    raise ValueError('重复采集产生业务写入')
        repeated = time.perf_counter() - started
        event.remove(engine, 'before_cursor_execute', capture)
        q = CapitalPageDataPlugin('capacity')
        async def read(fn, *a):
            return fn(*a)
        q.mysql = SimpleNamespace(engine=engine, read_engine=engine, read=read)
        page_ms, detail_ms, window_ms, plans = [], [], [], {}
        for i in range(10):
            started = time.perf_counter()
            page = await q.browse('capital_transaction', 'transfer', limit=100)
            page_ms.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            detail = await q.detail('capital_transaction', page['rows'][0]['record_key'])
            detail_ms.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            with engine.connect() as conn:
                window = read_window(conn, '600000.SH')
            window_ms.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        audit = q.audit(PreparationScope(codes=tuple(f'{600000+i:06d}' for i in range(700))))
        audit_ms = (time.perf_counter() - started) * 1000
        if not audit['complete']:
            raise ValueError('放大数据正式窗口审计失败')
        with engine.connect() as conn:
            for label, sql in dict(page="SELECT record_key,event_date,unified_code,target FROM capital_transaction WHERE section='transfer' ORDER BY event_date DESC,unified_code DESC,record_key DESC LIMIT 100",
                security="SELECT record_key,event_date FROM capital_transaction WHERE section='transfer' AND unified_code='600000.SH' ORDER BY event_date DESC,record_key DESC LIMIT 100",
                window="SELECT * FROM capital_transaction WHERE unified_code='600000.SH' AND in_window=1 ORDER BY record_key LIMIT 10001").items():
                plans[label] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + sql).mappings()]
                plans[label + '_actual_rows'] = len(conn.exec_driver_sql(sql).all())
            conn.exec_driver_sql('ANALYZE TABLE ' + ','.join(targets)).all()
            allocation = [dict(r) for r in conn.execute(text('SELECT table_name,data_length,index_length '
                'FROM information_schema.tables WHERE table_schema=:db'), dict(db=database)).mappings()]
            allocated = conn.execute(text('SELECT SUM(data_length+index_length) FROM information_schema.tables WHERE table_schema=:db'), dict(db=database)).scalar_one()
            state_bytes = conn.exec_driver_sql('SELECT OCTET_LENGTH(payload) FROM collection_state').scalar_one()
            version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            storage_mode = dict(conn.exec_driver_sql('SELECT @@innodb_file_per_table AS file_per_table,'
                '@@innodb_redo_log_capacity AS redo_capacity').mappings().one())
        measured = dict(import_seconds=imported, repeated_seconds=repeated, repeated_business_dml=len(dml),
            facts=sum(d['row_count'] for _, d in fixtures), page_p95_ms=max(page_ms), detail_p95_ms=max(detail_ms),
            window_p95_ms=max(window_ms), audit_ms=audit_ms, allocated_bytes=int(allocated), peak_python_bytes=peak,
            state_bytes=int(state_bytes), detail_bytes=len(json.dumps(detail, ensure_ascii=False).encode()),
            window_bytes=len(json.dumps(window, ensure_ascii=False).encode()))
        report = dict(checked_at=datetime.now(UTC).isoformat(), measurements=measured,
            limits=dict(import_seconds=30, repeated_business_dml=0, page_p95_ms=100, detail_p95_ms=100,
                window_p95_ms=100, audit_ms=10000, allocated_bytes=134217728, peak_python_bytes=134217728,
                state_bytes=2097152, detail_bytes=65536, window_bytes=1048576),
            conditions=dict(platform=platform.platform(), mysql=version, independent_test_service=True,
                synthetic=True, securities=700, actual_sample='docs/evidence/ths-capital-source-2026-10-16.json',
                cache='first unforced read and nine hot repetitions; maximum bounds P95', flush_log_at_trx_commit=capacity.identity['innodb_flush_log_at_trx_commit'],
                transactions='one complete security per transaction, matching formal archive', allocation=allocation,
                storage_mode=storage_mode,
                growth='6000 securities × 50 new facts/year × 5 years =1.5million facts; scaled allocated bytes separately reported'),
            reviewed_tradeoffs='八表按融资、项目、交易、报告期汇总、持仓、IPO、原事件与解除拆分；不存成功HTML或业务JSON。现行窗口标志仅成员变化写入，窗口外保留历史。测量不是生产历史覆盖或OS崩溃耐久性证明。',
            bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in INPUT_PATHS},
            ddl_scopes={t: hashlib.sha256(statements[t].encode()).hexdigest() for t in TABLES}, explain=plans,
            projected_five_year_bytes=int(allocated) * 1500000 // measured['facts'])
        capacity.report.update(report)
        if any(measured[k] > v for k, v in report['limits'].items()):
            raise ValueError('容量预算未通过：' + str(measured))
        capacity.measurements_complete = True
    print('PASS capital capacity', measured, str(capacity.output))
    return capacity.report



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--report', help='New report path; default is a unique build/capacity-reruns file')
    asyncio.run(run(parser.parse_args()))
