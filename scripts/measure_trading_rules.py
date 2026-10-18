"""Isolated rule DML and 10000-row typed future-history index stress experiment."""
import argparse
import hashlib
import json
import platform
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.contracts.trading_rules import KINDS, SOURCE, VALUE_COLUMNS
from empire.core.config import load_config, project_root
from empire.plugins.datasets.trading_rules import RuleDataset
from empire.plugins.infra.mysql_store import initialize_database, make_engine


def run(args):
    import sys
    sys.path.insert(0, str(project_root()))
    from tests.test_trading_rules import sample
    settings = json.loads(Path(args.test_settings).read_text('utf-8'))
    production = load_config()['mysql']
    if (settings.get('host'), settings.get('port')) == (production.get('host'), production.get('port')):
        raise ValueError('容量实验须使用隔离MySQL服务')
    root, db, admin = project_root(), 'empire_' + uuid4().hex + '_test', make_engine(settings)
    engine, created = None, False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            created = True
        settings = {**settings, 'database': db}
        initialize_database(settings)
        engine = make_engine(settings)
        initial, duplicate = 0, 0
        begin = time.perf_counter()
        for kind in KINDS:
            mapping = RuleDataset(kind)
            batch = uuid4().hex
            e = make_envelope(source=SOURCE, dataset='rules.' + kind + '.complete', business_key=kind,
                job_key=mapping.JOB, batch_id=batch, run_id=batch, payload=sample(kind)).model_copy(update={'observed_at': datetime.now(UTC)})
            data = {**mapping.normalize(e), 'archive_state': {}}
            with engine.begin() as conn:
                initial += mapping.write(conn, e, data)['written_count']
            with engine.begin() as conn:
                duplicate += mapping.write(conn, e, data)['written_count']
        import_seconds = time.perf_counter() - begin
        assert duplicate == 0
        # Synthetic future-history volume tests indexes, not current source coverage.
        with engine.connect() as conn:
            from empire.plugins.datasets.trading_rules import canonical
            template = {**canonical(conn.execute(text("SELECT * FROM trading_rule_value WHERE kind='tick_rules' LIMIT 1")).mappings().first()), 'kind': 'future_stress'}
        with engine.begin() as conn:
            records = [{**template, 'record_key': hashlib.sha256(str(i).encode()).hexdigest()} for i in range(10000)]
            conn.execute(text('INSERT INTO trading_rule_value(record_key,' + ','.join(VALUE_COLUMNS) + ') VALUES(:record_key,' + ','.join(':' + k for k in VALUE_COLUMNS) + ')'), records)
        sqls = {
            'page': "SELECT * FROM trading_rule_value WHERE kind='future_stress' ORDER BY record_key LIMIT 200",
            'detail': 'SELECT * FROM trading_rule_citation LIMIT 1',
            'coverage': "SELECT v.* FROM trading_rule_value v WHERE kind='future_stress' ORDER BY record_key LIMIT 1001",
        }
        measurements, plans, queries = dict(import_seconds=import_seconds), {}, {}
        with engine.connect() as conn:
            version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            conn.exec_driver_sql('ANALYZE TABLE trading_rule_value,trading_rule_citation')
            for name, sql in sqls.items():
                timings = []
                for _ in range(20):
                    start = time.perf_counter()
                    rows = conn.exec_driver_sql(sql).all()
                    timings.append(1000 * (time.perf_counter() - start))
                measurements[name + '_p95_ms'] = sorted(timings)[18]
                plans[name] = [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + sql).mappings()]
                queries[name] = dict(returned=len(rows), read_bytes=len(json.dumps([list(r) for r in rows], default=str).encode()))
            measurements['allocated_bytes'] = int(conn.execute(text("SELECT SUM(data_length+index_length) FROM information_schema.tables WHERE table_schema=:db AND table_name IN ('trading_rule_value','trading_rule_citation')"), {'db': db}).scalar_one())
        bindings = ['src/empire/contracts/trading_rules.py', 'src/empire/contracts/rule_review.py', 'src/empire/contracts/rule_bse_review.py',
            'src/empire/plugins/datasets/trading_rules.py', 'src/empire/plugins/data/trading_rules.py', 'scripts/measure_trading_rules.py']
        schema = (root / 'sql/schema.sql').read_text('utf-8')
        report = dict(ddl_scopes={t: hashlib.sha256(re.search(r'CREATE TABLE IF NOT EXISTS ' + t + r'\s*\([\s\S]*?;', schema)[0].encode()).hexdigest() for t in ('trading_rule_value', 'trading_rule_citation')},
            bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in bindings}, measurements=measurements,
            limits=dict(page_p95_ms=200, detail_p95_ms=200, coverage_p95_ms=500, import_seconds=5, allocated_bytes=64 * 1024**2),
            conditions=dict(platform=platform.platform(), mysql=version, actual_contract_rows=sum(len(sample(k)['rows']) for k in KINDS), stress_rows=10000,
                cache='first query unforced; following repetitions hot', synthetic=True),
            reviewed_tradeoffs='当前已审核参数走正式映射且重复零DML；10000行仅做隔离未来历史索引压力实验，不宣称当前来源有这些记录。单项准备扫描1001行，超过1000拒绝完整；规则新版本需显式审核契约。',
            explain=plans, queries=queries, initial_dml=initial, duplicate_dml=duplicate,
            cleanup='UUID-owned isolated test database dropped in finally')
        report['passed'] = all(measurements[k] <= v for k, v in report['limits'].items())
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps(dict(passed=report['passed'], measurements=measurements)))
    finally:
        if engine:
            engine.dispose()
        if created:
            assert db.endswith('_test') and db.startswith('empire_')
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{db}`')
        admin.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--output', default='docs/evidence/trading-rules-capacity-2026-10-12.json')
    run(parser.parse_args())
