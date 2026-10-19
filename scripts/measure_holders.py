"""Typed holder capacity in a UUID-owned database on an independent MySQL."""
import argparse
import copy
import hashlib
import json
import platform
import re
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import event, text

from empire.contracts.data import make_envelope
from empire.contracts.preparation_scope import PreparationScope
from empire.core.config import load_config, project_root
from empire.features.holders.contract import KINDS, digest, report_key
from empire.features.holders.dataset import HolderDataset, read_reports
from empire.features.holders.query import HolderDataPlugin
from empire.features.holders.source import parse
from empire.plugins.infra.collection_state import save_state
from scripts.capacity_session import CapacitySession
from tests.test_ths_holders import STOCK, source

INPUT_PATHS = (
    'src/empire/features/holders/audit.py',
    'src/empire/features/holders/contract.py',
    'src/empire/features/holders/dataset.py',
    'src/empire/features/holders/query.py',
    'src/empire/features/holders/source.py',
    'src/empire/sources/html.py',
    'scripts/measure_holders.py',
    'scripts/capacity_session.py',
    'tests/test_ths_holders.py',
)


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text('utf-8-sig'))
    prod = load_config()['mysql']
    capacity = CapacitySession(prod, settings, root=root, subject='holders', output=args.report, input_paths=INPUT_PATHS)
    sql = (root / 'sql/schema.sql').read_text('utf8')
    mapping = HolderDataset()
    seeds = {kind: parse(source(), kind, STOCK)[0] for kind in KINDS}
    def unit(i, *, revision=False):
        security = f'{i:06d}.SH'
        reports = {kind: [] for kind in KINDS}
        for index, period in enumerate(('2025-03-31', '2025-06-30', '2025-09-30', '2025-12-31')):
            kind = tuple(KINDS)[index % 3]
            r = copy.deepcopy(seeds[kind])
            r.update(unified_code=security, instrument_name=security, instrument_key=digest(security), report_date=period)
            for m in r['members']:
                m['holder_name'] = ('容量验证持有人' * 35) + str(m['seq']) + ('修订' if revision and i == 0 and m['seq'] == 1 else '')
            reports[kind].append(r)
        return security, reports
    envelope = make_envelope(source='ths', dataset='holders.reports', schema_version=5, job_key=mapping.JOB,
        batch_id=uuid4().hex, run_id=uuid4().hex, business_key='capacity', payload={})
    def load(conn, *, revision=False):
        written = 0
        for i in range(2500):
            key, reports = unit(i, revision=revision)
            payload = dict(page=i+1, unit=key, reports=reports, manifest=None, gaps=[])
            e = make_envelope(source='ths', dataset='holders.reports', schema_version=5, job_key=mapping.JOB,
                batch_id=envelope.batch_id, run_id=envelope.run_id, business_key=key, payload=payload)
            data = mapping.normalize(e)
            written += mapping.write(conn, e, {**data, 'archive_state': {}})['written_count']
        return written
    with capacity:
        db, engine = capacity.database, capacity.engine
        statements = {}
        with engine.begin() as conn:
            for table in ('holder_report', 'holder_member'):
                statements[table] = re.search(r'CREATE TABLE IF NOT EXISTS ' + table + r'\s*\([\s\S]*?;', sql)[0]
                conn.exec_driver_sql(statements[table])
            for table in ('stock', 'collection_state'):
                conn.exec_driver_sql(re.search(r'CREATE TABLE IF NOT EXISTS ' + table + r'\s*\([\s\S]*?;', sql)[0])
        tracemalloc.start()
        started = time.perf_counter()
        with engine.begin() as conn:
            initial_written = load(conn)
        imported = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        dml = []
        def capture(conn, cursor, stmt, params, context, many):
            if stmt.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                dml.append(stmt)
        event.listen(engine, 'before_cursor_execute', capture)
        with engine.begin() as conn:
            repeated = load(conn)
        repeated_dml = len(dml)
        with engine.begin() as conn:
            security, reports = unit(0, revision=True)
            e = envelope.model_copy(update={'observed_at': datetime.now(UTC)})
            revised = mapping.write(conn, e, dict(unit=security, reports=reports, page=1, row_count=44, archive_state={}))['written_count']
        event.remove(engine, 'before_cursor_execute', capture)
        proofs, rolling = {}, digest([])
        kind_manifests = {kind: dict(count=0, digest=digest([])) for kind in KINDS}
        for i in range(2500):
            security, reports = unit(i, revision=i == 0)
            e = envelope.model_copy(update={'raw_payload': dict(page=i+1, unit=security, reports=reports, manifest=None, gaps=[])})
            data = mapping.normalize(e)
            state = mapping.archive_state(e, data, {'confirmed': [security]}, {})
            proofs[security] = state['units'][security]
            rolling = digest([rolling, security, digest(reports), sum(map(len, reports.values()))])
            for kind, rows in reports.items():
                old = kind_manifests[kind]
                kind_manifests[kind] = dict(count=old['count'] + len(rows),
                    digest=digest([old['digest'], security, digest(rows), len(rows)]))
        keys = list(proofs)
        state = dict(contract_version=4, units=proofs, manifest=dict(securities=keys, units=len(keys),
            count=10000, digest=rolling, scope_hash=digest(keys), kinds=kind_manifests,
            observed_at=envelope.observed_at.isoformat()))
        state_bytes = len(json.dumps(state).encode())
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:code,:name)'),
                         [dict(code=key, name='容量验证') for key in keys])
            save_state(conn, 'holder-capacity', mapping.PROJECT, 'ths', 'holders.reports', state, {})
        tracemalloc.start()
        started = time.perf_counter()
        audit_timings = {}
        for kind in KINDS:
            audit_started = time.perf_counter()
            query = HolderDataPlugin(kind, 'holder-capacity')
            query.mysql = type('Store', (), {'read_engine': engine})()
            audit = query.audit(PreparationScope())
            if not audit['complete'] or audit['reports'] != kind_manifests[kind]['count']:
                raise ValueError('正式完整集合查询未通过容量审计')
            audit_timings[kind] = (time.perf_counter() - audit_started) * 1000
        combined_audit_ms = (time.perf_counter() - started) * 1000
        audit_ms = max(audit_timings.values())
        audit_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        measured, plans = {}, {}
        queries = dict(page="SELECT report_key,unified_code,report_date,member_count,exit_count FROM holder_report WHERE kind='top_holders' ORDER BY report_date DESC,unified_code DESC,report_key DESC LIMIT 100",
            security="SELECT report_key,report_date FROM holder_report WHERE kind='top_holders' AND unified_code='000001.SH' ORDER BY report_date DESC,report_key DESC LIMIT 100",
            coverage="SELECT report_key,content_hash,member_count,exit_count FROM holder_report WHERE kind='top_holders' ORDER BY report_key LIMIT 10000")
        with engine.connect() as conn:
            for name, query in queries.items():
                plans[name] = [dict(r) for r in conn.execute(text('EXPLAIN ' + query)).mappings()]
                timings = []
                for _ in range(10):
                    started = time.perf_counter()
                    rows = conn.execute(text(query)).all()
                    timings.append((time.perf_counter() - started) * 1000)
                measured[name + '_p95_ms'] = max(timings)
                measured[name + '_returned'] = len(rows)
            key = report_key(unit(1)[1]['top_holders'][0])
            timings = []
            for _ in range(10):
                started = time.perf_counter()
                values = read_reports(conn, [key])
                timings.append((time.perf_counter() - started) * 1000)
            measured['detail_p95_ms'] = max(timings)
            measured['detail_bytes'] = len(json.dumps(values, ensure_ascii=False).encode())
            # Worst bounded notice: all 200 current and 200 exited identities.
            maximum = copy.deepcopy(seeds['top_holders'])
            maximum.update(report_type='change_notice', total_quantity=None, total_quantity_scale=None,
                           total_quantity_decimals=None, total_ratio=None)
            seed = maximum['members'][0]
            maximum['members'] = [{**seed, 'member_group': group, 'seq': i,
                'holder_name': ('最大名单持有人' * 50) + str(i),
                'ratio': None if group == 'exited' else seed['ratio']} for group in ('current','exited') for i in range(1,201)]
            maximum_data = dict(page=1, unit=STOCK['unified_code'], reports={kind: [maximum] if kind == 'top_holders' else [] for kind in KINDS}, manifest=None, gaps=[])
            e = envelope.model_copy(update={'raw_payload': maximum_data, 'observed_at': datetime.now(UTC)})
            normalized = mapping.normalize(e)
            conn.commit()
            with conn.begin():
                mapping.write(conn, e, {**normalized, 'archive_state': {}})
            timings = []
            for _ in range(10):
                started = time.perf_counter()
                largest = read_reports(conn, [report_key(maximum)])
                timings.append((time.perf_counter() - started) * 1000)
            if largest != [maximum]:
                raise ValueError('最大名单正式详情不等于来源规范集合')
            measured['maximum_detail_p95_ms'] = max(timings)
            measured['maximum_detail_bytes'] = len(json.dumps(largest, ensure_ascii=False).encode())
            conn.exec_driver_sql('ANALYZE TABLE holder_report,holder_member').all()
            allocated = conn.execute(text("SELECT SUM(data_length+index_length) FROM information_schema.tables WHERE table_schema=:db AND table_name IN ('holder_report','holder_member')"), {'db': db}).scalar_one()
            mysql = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            heads = conn.exec_driver_sql('SELECT COUNT(*) FROM holder_report').scalar_one()
            members = conn.exec_driver_sql('SELECT COUNT(*) FROM holder_member').scalar_one()
        measured.update(import_seconds=imported, initial_written=initial_written, peak_python_bytes=peak, allocated_bytes=int(allocated),
            repeated_business_dml=repeated_dml, repeated_written=repeated, revised_written=revised,
            formal_audit_ms=audit_ms, formal_combined_audit_ms=combined_audit_ms,
            audit_peak_python_bytes=audit_peak, state_bytes=state_bytes)
        report = dict(checked_at=datetime.now(UTC).isoformat(),
            bindings={p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in INPUT_PATHS},
            ddl_scopes={t: hashlib.sha256(s.encode()).hexdigest() for t, s in statements.items()}, measurements=measured,
            limits=dict(page_p95_ms=100, security_p95_ms=100, coverage_p95_ms=1000, detail_p95_ms=100,
                detail_bytes=1048576, maximum_detail_p95_ms=100, maximum_detail_bytes=1048576, import_seconds=180, peak_python_bytes=134217728,
                allocated_bytes=536870912, repeated_business_dml=0, repeated_written=0,
                formal_audit_ms=30000, formal_combined_audit_ms=90000,
                audit_peak_python_bytes=134217728, state_bytes=8388608),
            conditions=dict(platform=platform.platform(), mysql=mysql, reports=heads, members=members,
                source='minimal source-semantic fixture; 2500 issuers × 4 periods distributed across all three kinds; long 281-character holder names',
                real_sample='docs/evidence/ths-holders-source-2026-10-13.json',
                cache='first unforced SQL read + nine hot repetitions; maximum bounds P95',
                independent_test_service=True, synthetic=True, innodb_flush_log_at_trx_commit=capacity.identity['innodb_flush_log_at_trx_commit'],
                audit_timings_ms=audit_timings,
                audit_budget='each independent formal query <=30s; three sequential queries <=90s'),
            reviewed_tradeoffs='按报告实体共两表，基础股/张数字及舍入精度可SQL查询。父头列表不读名字正文，单详情有界。来源窗口外保留历史，较旧修订不保证发现。容量放大不是生产覆盖，未模拟OS崩溃耐久性。', explain=plans)
        capacity.report.update(report)
        if any(measured[k] > v for k, v in report['limits'].items()):
            raise ValueError('持有人容量或性能预算不通过：' + str(measured))
        capacity.measurements_complete = True
    print('PASS holder capacity', heads, 'reports', members, 'members', imported, 'seconds', allocated, 'bytes', str(capacity.output))
    return capacity.report



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--report', help='New report path; default is a unique build/capacity-reruns file')
    options = parser.parse_args()
    run(options)
