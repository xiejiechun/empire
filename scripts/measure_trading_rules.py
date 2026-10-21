"""Owned rule DML and original 10000-row future-history index stress experiment."""
import copy
import hashlib
import json
import platform
import re
import sys
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import event, text

from empire.contracts.data import make_envelope
from empire.core.config import project_root
from empire.features.trading_rules.contract import KINDS, SOURCE, VALUE_COLUMNS
from empire.features.trading_rules.dataset import (
    RuleDataset,
    canonical,
    canonical_payload,
    read_snapshot,
)
from empire.plugins.infra.mysql_store import make_engine

QUERIES = {
    'page': "SELECT * FROM trading_rule_value WHERE kind='future_stress' ORDER BY record_key LIMIT 200",
    'detail': 'SELECT * FROM trading_rule_citation LIMIT 1',
    'coverage': "SELECT v.* FROM trading_rule_value v WHERE kind='future_stress' ORDER BY record_key LIMIT 1001",
}


def measure(storage):
    # CLI execution starts on scripts/, while the reviewed synthetic fixture
    # lives in the repository's tests package as in the original protocol.
    sys.path.insert(0, str(project_root()))
    from tests.test_trading_rules import sample
    root = project_root()
    engine, db = make_engine(storage.settings), storage.database
    try:
        initial, duplicate, samples, expected = 0, 0, {}, {}
        business_dml = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if 'trading_rule_' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                business_dml.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        begin = time.perf_counter()
        for kind in KINDS:
            mapping = RuleDataset(kind)
            batch = uuid4().hex
            e = make_envelope(source=SOURCE, dataset='rules.' + kind + '.complete', business_key=kind,
                job_key=mapping.JOB, batch_id=batch, run_id=batch, payload=sample(kind)).model_copy(update={'observed_at': datetime.now(UTC)})
            data = {**mapping.normalize(e), 'archive_state': {}}
            samples[kind] = (e, data)
            expected[kind] = canonical_payload(kind, sample(kind))
            with engine.begin() as conn:
                initial += mapping.write(conn, e, data)['written_count']
            business_dml.clear()
            with engine.begin() as conn:
                duplicate += mapping.write(conn, e, data)['written_count']
            assert not business_dml
        import_seconds = time.perf_counter() - begin
        assert duplicate == 0
        # One legitimate metadata revision of an existing value. All kinds and
        # citation fields are compared, rather than accepting matching counts.
        kind = 'tick_rules'
        e, data = samples[kind]
        revised = copy.deepcopy(data)
        revised['rows'][0]['text_value'] += '；容量修订'
        with engine.begin() as conn:
            changed = RuleDataset(kind).write(conn, e, revised)['written_count']
        assert changed == 1
        expected[kind]['rows'] = revised['rows']
        with engine.connect() as conn:
            for current in KINDS:
                rows, refs = read_snapshot(conn, current)
                assert rows == expected[current]['rows'] and refs == expected[current]['citations']
            template = {**canonical(conn.execute(text("SELECT * FROM trading_rule_value WHERE kind='tick_rules' LIMIT 1")).mappings().first()), 'kind': 'future_stress'}
        # Original synthetic future-history size and shapes; not source coverage.
        records = [{**template, 'record_key': hashlib.sha256(str(i).encode()).hexdigest()} for i in range(10000)]
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO trading_rule_value(record_key,' + ','.join(VALUE_COLUMNS) + ') VALUES(:record_key,' + ','.join(':' + k for k in VALUE_COLUMNS) + ')'), records)
        measurements, plans, queries, raw = dict(import_seconds=import_seconds), {}, {}, {}
        with engine.connect() as conn:
            version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            conn.exec_driver_sql('ANALYZE TABLE trading_rule_value,trading_rule_citation')
            for name, sql in QUERIES.items():
                timings = []
                for _ in range(20):
                    start = time.perf_counter()
                    rows = conn.exec_driver_sql(sql).all()
                    timings.append(1000 * (time.perf_counter() - start))
                raw[name] = timings
                measurements[name + '_p95_ms'] = sorted(timings)[18]
                plans[name] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + sql).mappings()]
                queries[name] = dict(returned=len(rows), read_bytes=len(json.dumps([list(r) for r in rows], default=str).encode()),
                                     estimated_scan_rows=sum(r['rows'] or 0 for r in plans[name]), first_ms=timings[0])
            actual = [canonical(r) for r in conn.exec_driver_sql("SELECT * FROM trading_rule_value WHERE kind='future_stress' ORDER BY record_key").mappings()]
            assert actual == sorted(records, key=lambda r: r['record_key'])
            measurements['allocated_bytes'] = int(conn.execute(text("SELECT SUM(data_length+index_length) FROM information_schema.tables WHERE table_schema=:db AND table_name IN ('trading_rule_value','trading_rule_citation')"), {'db': db}).scalar_one())
        bindings = ['src/empire/features/trading_rules/' + n + '.py' for n in ('contract', 'review', 'bse_review', 'dataset', 'query')]
        bindings += ['scripts/measure_trading_rules.py', 'scripts/trading_rule_capacity.py', 'scripts/source_test_storage.py',
                     'scripts/source_verification.py', 'tests/test_trading_rules.py', 'tests/rule_samples.py', 'tests/rule_bse_samples.py']
        schema = (root / 'sql/schema.sql').read_text('utf-8')
        report = dict(ddl_scopes={t: hashlib.sha256(re.search(r'CREATE TABLE IF NOT EXISTS ' + t + r'\s*\([\s\S]*?;', schema)[0].encode()).hexdigest() for t in ('trading_rule_value', 'trading_rule_citation')},
            bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in bindings}, measurements=measurements,
            limits=dict(page_p95_ms=200, detail_p95_ms=200, coverage_p95_ms=500, import_seconds=5, allocated_bytes=64 * 1024**2),
            conditions=dict(platform=platform.platform(), mysql=version, actual_contract_rows=sum(len(sample(k)['rows']) for k in KINDS), stress_rows=10000,
                cache='first query unforced; following repetitions hot; original 20 samples, sorted index18 P95', synthetic=True),
            reviewed_tradeoffs='当前77审核参数用正式映射，逐kind参数及引用完整内容相同、重复零DML、单参数修订；10000行仅隔离未来历史索引压力，不宣称来源覆盖。原查询、20次P95及预算保持。',
            explain=plans, queries=queries, samples=raw, initial_dml=initial, duplicate_dml=duplicate, revised_dml=changed,
            correctness=dict(all_seven_kinds_and_citations_equal=True, stress_full_rows_equal=len(actual), repeated_business_dml=0))
        report['passed'] = all(measurements[k] <= v for k, v in report['limits'].items())
        return report
    finally:
        engine.dispose()


if __name__ == '__main__':
    from trading_rule_capacity import main
    raise SystemExit(main())
