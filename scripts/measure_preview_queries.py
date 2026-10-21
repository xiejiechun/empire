"""Measure current preview queries in a UUID-owned schema on an isolated MySQL instance."""
import argparse
import asyncio
import copy
import hashlib
import json
import os
import platform
import re
import sys
import time
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from empire.core.config import load_config, project_root
from empire.features.kaipanla.normalization import digest, point_count, validate
from empire.features.kaipanla.query import KaipanlaProductDataPlugin
from empire.features.kaipanla.repository import head_record, read_day, write_day
from empire.features.kaipanla.storage_contract import MARKET_TABLES
from empire.plugins.infra.mysql_store import initialize_database
from scripts.capacity_session import CapacitySession, require_sample_kinds
from scripts.measure_capacity import latency
from scripts.measure_market_storage import memory
from tests.test_kaipanla_products import business_row

INPUT_PATHS = ['src/empire/features/kaipanla/storage_contract.py', 'src/empire/features/kaipanla/codec.py', 'src/empire/features/kaipanla/repository.py', 'src/empire/features/kaipanla/trade_blocks.py', 'src/empire/features/kaipanla/query.py', 'scripts/measure_preview_queries.py', 'docs/evidence/kaipanla-storage-capacity-2026-10-05.json', 'src/empire/features/kaipanla/contract.py', 'src/empire/features/kaipanla/dates.py', 'src/empire/features/kaipanla/alias_contract.py', 'src/empire/features/kaipanla/source_protocol.py', 'src/empire/features/kaipanla/pair_parser.py', 'src/empire/features/kaipanla/parser.py', 'src/empire/features/kaipanla/canonical.py', 'src/empire/features/kaipanla/normalization.py', 'src/empire/features/kaipanla/schema.py', 'src/empire/features/kaipanla/dataset.py', 'scripts/capacity_session.py', 'tests/test_kaipanla_products.py', 'scripts/measure_market_storage.py', 'scripts/measure_capacity.py', 'src/empire/features/kaipanla/api.py', 'src/empire/features/kaipanla/scope.py', 'src/empire/features/kaipanla/audit.py', 'src/empire/features/stocks/audit_rules.py', 'src/empire/features/stocks/api.py', 'src/empire/features/calendar/api.py', 'src/empire/features/calendar/contract.py', 'src/empire/features/suspensions/exclusions.py', 'src/empire/contracts/business_schema.py', 'sql/business-schema.json', 'src/empire/plugins/infra/schema_manifest.py', 'src/empire/plugins/infra/mysql_store.py', 'src/empire/plugins/infra/collection_state.py', 'src/empire/contracts/security.py', 'sql/schema.sql', 'sql/schema-contract.json']


def timed(fn, count=30):
    """Same 30-call timing protocol, retaining every observed sample."""
    values = []
    for _ in range(count):
        start = time.perf_counter()
        fn()
        values.append(time.perf_counter() - start)
    return {**latency(values), 'samples_ms': [value * 1000 for value in values]}


def run(args):
    root = project_root()
    production = load_config()['mysql']
    settings = json.loads(Path(args.test_settings).read_text('utf-8'))
    capacity = CapacitySession(production, settings, root=root, subject='preview', output=args.output, input_paths=INPUT_PATHS)
    samples = []
    kinds = ('trend', 'auction', 'volume', 'trades', 'entrust', 'large_order', 'quote')
    with capacity:
        source, engine = capacity.source_engine, capacity.engine
        with source.connect() as conn:
            conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            capacity.require_source(conn)
            for kind in kinds:
                head = conn.execute(text('SELECT * FROM stock_market_day WHERE kind=:kind '
                    'ORDER BY trade_date DESC,unified_code LIMIT 1'), dict(kind=kind)).mappings().first()
                if head:
                    samples.append((read_day(conn, head), head['version_observed_at']))
        capacity.report['sample_scope'] = dict(required_kinds=list(kinds),
            observed_kinds=[row['kind'] for row, _ in samples],
            missing_kinds=sorted(set(kinds) - {row['kind'] for row, _ in samples}))
        require_sample_kinds(samples, kinds)
        initialize_database(capacity.settings)
        with engine.begin() as conn:
            for row, observed in samples:
                write_day(conn, row, digest(row), observed)
            maximum = copy.deepcopy(business_row('trades'))
            maximum['code'], maximum['market'] = '999998', 'SH'
            maximum['data']['fb'] = [['09:30:00', 10, 1, 10, 0, 1, 0, i] for i in range(100000)]
            maximum['data'].update(Count=100000, total=100000)
            validate(maximum, storage_check=False)
            write_day(conn, maximum, digest(maximum), datetime(2026, 10, 11))
        async def read(fn, *values):
            return fn(*values)
        def query(kind):
            q = KaipanlaProductDataPlugin(kind)
            q.mysql = SimpleNamespace(read=read, read_engine=engine)
            return q
        trades = query('trades')
        def page():
            return asyncio.run(trades.page('SH', '999998', '2021-01-04'))
        def window():
            return asyncio.run(trades.page('SH', '999998', '2021-01-04', start_time='09:30:00', end_time='09:30:00'))
        first = page()
        assert len(first['points']) == 200 and first['seqs'] == list(range(200))
        def following():
            return asyncio.run(trades.page('SH', '999998', '2021-01-04', first['next_cursor']))
        second = following()
        assert second['seqs'] == list(range(200, 400))
        page_timings = dict(max_page=timed(page), time_page=timed(window), next_page=timed(following))
        measurements = {name + '_p95_ms': value['p95_ms'] for name, value in page_timings.items()}
        measurements['max_page_python_peak_bytes'] = memory(page)
        sample_checks = []
        for row, _ in samples:
            q = query(row['kind'])
            args_day = (row['market'], row['code'], row['trade_date'])
            def fn(q=q, values=args_day):
                return asyncio.run(q.day(*values))
            restored = fn()['data']
            assert digest(restored) == digest(row)
            stamp = date.fromisoformat(row['trade_date'])
            with engine.connect() as conn:
                assert read_day(conn, head_record(conn, row['kind'], row['code']+'.'+row['market'], stamp)) == row
            sample_checks.append(dict(kind=row['kind'], security=row['code']+'.'+row['market'], day=row['trade_date'], latency=timed(fn)))
        measurements['sample_full_day_p95_ms'] = max(s['latency']['p95_ms'] for s in sample_checks)
        ddl = (root/'sql/schema.sql').read_text('utf-8')
        limits = dict(max_page_p95_ms=10, time_page_p95_ms=10, next_page_p95_ms=10,
                      max_page_python_peak_bytes=350000, sample_full_day_p95_ms=100)
        report = dict(date=datetime.now(UTC).date().isoformat(), scope='7种已归档证券日抽样及100000点同秒合成分笔；不代表全市场完整性',
            bindings=dict(capacity.frozen_inputs),
            ddl_scopes={t: hashlib.sha256(re.search(r'CREATE TABLE IF NOT EXISTS '+t+r'\s*\([\s\S]*?;', ddl).group().encode()).hexdigest() for t in MARKET_TABLES},
            measurements=measurements, limits=limits, samples=sample_checks, page_timings=page_timings,
            correctness=dict(first_page_seqs=first['seqs'], next_page_seqs=second['seqs'],
                synthetic_same_second_points=point_count(maximum),
                source_query_kinds=[sample['kind'] for sample in sample_checks]),
            environment=dict(os=platform.platform(), machine=platform.machine(), processor=platform.processor(),
                logical_cpus=os.cpu_count(), python=sys.version,
                dependencies={name: version(name) for name in ('SQLAlchemy', 'PyMySQL')}),
            conditions=dict(test_server_port=capacity.identity['server_port'], mysql=capacity.identity['version'],
                fixture_version_observed_at='2026-10-11 fixed fixture version date, not execution date',
                repetitions=30, cache='30次热查询；一次有界正式查询，未启动采集；生产只读一致性快照'),
            reviewed_tradeoffs='本批组织迁移、显式表组和连接内公开查询，结构/归档写入语义未变；原存储写入、20万业务头和空间基线保留在绑定的2026-10-05证据。当前页、时间窗及完整证券日重新测量。10ms为页面查询预算，100ms为有限整日预算，不承诺冷盘或全部历史容量。',
            sample_scope=dict(required_kinds=list(kinds), observed_kinds=[row['kind'] for row, _ in samples]))
        capacity.report.update(report)
        if not all(measurements[k] <= v for k, v in limits.items()):
            raise RuntimeError('预览查询容量预算未通过')
        capacity.measurements_complete = True
    print(json.dumps(dict(passed=capacity.report['passed'], measurements=measurements, report=str(capacity.output))))
    return capacity.report



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--output', help='New report path; default is a unique build/capacity-reruns file')
    run(parser.parse_args())
