"""Measure typed limit-pool storage in an independently owned SQL database."""
import argparse
import asyncio
import json
import time
import tracemalloc
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from capacity_session import CapacitySession
from schema_evidence_scope import objects
from sqlalchemy import event, text

from empire.core.config import load_config
from empire.features.yuanhang_limits.contract import MEMBER_FIELDS, TABLE_COLUMNS
from empire.features.yuanhang_limits.model import digest
from empire.features.yuanhang_limits.query import LimitQuery
from empire.features.yuanhang_limits.repository import (
    read_pool_head,
    replace_pool,
    replace_reason,
    upsert,
)
from empire.features.yuanhang_limits.wire import encode
from empire.plugins.infra.collection_state import save_state
from empire.plugins.infra.collection_state_unit import read_unit, save_unit
from empire.plugins.infra.mysql_store import initialize_database

LIMITS = {'list_p95_ms': 200, 'history_p95_ms': 300, 'reason_p95_ms': 200,
          'state_unit_update_p95_ms': 200, 'reason_plan_ms': 1000}


async def measure_planning(engine, observed):
    query = LimitQuery('capacity')

    async def read(operation):
        with engine.connect() as conn:
            return operation(conn)

    async def cache(*_):
        return {}

    query.read, query.cache_proofs = read, cache
    first, last = date(1990, 12, 19), date.today()
    rows = [dict(day=first + timedelta(days=i), flag=int(date(2024, 1, 1) <= first + timedelta(days=i)))
            for i in range((last-first).days+1)]
    with engine.begin() as conn:
        for start in range(0, len(rows), 500):
            conn.execute(text('INSERT INTO trade_calendar VALUES(:day,:flag,NOW(6))'), rows[start:start+500])
    versions = {(date(2024, 1, 1)+timedelta(days=i)).isoformat(): observed.isoformat() for i in range(200)}
    payload = dict(contract_version=1, units={f'{i:06}.SZ': dict(versions=versions) for i in range(1, 501)})
    with engine.begin() as conn:
        save_state(conn, 'capacity', 'ths-yuanhang-reason', 'ths_yuanhang', 'yuanhang.limits.reason', payload, {})
        state_bytes = conn.exec_driver_sql("SELECT JSON_STORAGE_SIZE(payload) FROM collection_state WHERE namespace='capacity'").scalar_one()
    del payload
    durations = []
    for index in range(31):
        started = time.perf_counter()
        with engine.begin() as conn:
            previous, exists = read_unit(conn, 'capacity', 'ths-yuanhang-reason', 'ths_yuanhang', '000001.SZ')
            changed = {**previous, 'units': {'000001.SZ': {'versions': {
                **previous['units']['000001.SZ']['versions'],
                '2024-01-01': (observed + timedelta(microseconds=index + 1)).isoformat()}}}}
            save_unit(conn, 'capacity', 'ths-yuanhang-reason', 'ths_yuanhang', 'yuanhang.limits.reason',
                      '000001.SZ', changed, previous, exists)
        durations.append(1000 * (time.perf_counter()-started))
    started = time.perf_counter()
    plan = await query.collection_plan('reason')
    elapsed = 1000 * (time.perf_counter()-started)
    assert len(plan['units']) == 256
    return dict(state_unit_update_p95_ms=sorted(durations[1:])[28], state_json_bytes=state_bytes,
                reason_plan_ms=elapsed, reason_plan_units=len(plan['units']))


def unit(day):
    rows = []
    for index in range(500):
        row = dict.fromkeys(MEMBER_FIELDS)
        row.update(unified_code=f'{index + 1:06}.SZ', source_market_id=33,
                   identity_basis='market_id', name='容量样本' + str(index), market_type='HS',
                   latest='10.15', change_rate='9.999999999999999999', turnover='123456789.25',
                   order_volume='123000', reason_type='来源原因摘要' * (1 + index % 20))
        rows.append(row)
    return dict(trade_date=day, pool_type='limit_up_pool', filter='HS,GEM2STAR,ST', source_total=500, rows=rows)


async def measure_queries(engine):
    query = LimitQuery('capacity')

    async def read(operation):
        return operation()

    query.mysql = SimpleNamespace(read_engine=engine, read=read)
    report = {}
    for name, call in (
        ('list', lambda: query.members('2024-01-01', 'limit_up_pool')),
        ('history', lambda: query.history('000001.SZ', '2024-01-01', '2025-12-31')),
        ('reason', lambda: query.reason('2024-01-01', '000001.SZ')),
    ):
        durations = []
        sizes = []
        for _ in range(31):
            start = time.perf_counter()
            result = await call()
            durations.append(1000 * (time.perf_counter() - start))
            sizes.append(len(json.dumps(result, default=str, ensure_ascii=False).encode()))
        report[name + '_first_read_ms'] = durations[0]
        report[name + '_p95_ms'] = sorted(durations[1:])[28]
        report[name + '_result_bytes'] = max(sizes)
        report[name + '_returned_rows'] = len(result['rows']) if name != 'reason' else int(result is not None)
    return report


def run(args):
    root = Path(__file__).resolve().parents[1]
    cfg = load_config()
    settings = json.loads(Path(args.test_mysql).read_text('utf8'))
    paths = [str(p.relative_to(root)).replace('\\', '/') for p in
             (root / 'src/empire/features/yuanhang_limits').glob('*.py')]
    paths.append('src/empire/sources/security_identity.py')
    paths += ['scripts/measure_yuanhang_limits_capacity.py', 'sql/schema.sql',
              'src/empire/plugins/infra/collection_state.py', 'src/empire/plugins/infra/collection_state_unit.py']
    with CapacitySession(cfg['mysql'], settings, root=root, subject='preview',
                         output=args.output, input_paths=paths) as session:
        session.report['bindings'] = session.frozen_inputs
        initialize_database(session.settings)
        observed = datetime.now(UTC)
        tracemalloc.start()
        started = time.perf_counter()
        packed = []
        for offset in range(500):
            day = (date(2024, 1, 1) + timedelta(days=offset)).isoformat()
            value = unit(day)
            if offset < 30:
                packed.append(len(encode(value)))
            with session.engine.begin() as conn:
                replace_pool(conn, value, observed, None)
        pool_seconds = time.perf_counter() - started
        started = time.perf_counter()
        reason_example = None
        for offset in range(200):
            day = (date(2024, 1, 1) + timedelta(days=offset)).isoformat()
            reasons = []
            for index in range(500):
                value = dict(trade_date=day, unified_code=f'{index + 1:06}.SZ', name='容量样本' + str(index),
                             reason_text='来源原因正文' * (1 + index % 100), reason_kind='来源分类', availability='available')
                if reason_example is None:
                    reason_example = value
                reasons.append(dict(value, content_sha256=digest(value), observed_at=observed.replace(tzinfo=None)))
            with session.engine.begin() as conn:
                upsert(conn, 'yuanhang_limit_reason', ('trade_date', 'unified_code'), reasons)
        reason_seconds = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        writes = []

        def track(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement.split()[0])

        event.listen(session.engine, 'before_cursor_execute', track)
        value = unit('2024-01-01')
        with session.engine.begin() as conn:
            assert replace_pool(conn, value, observed, read_pool_head(conn, value['trade_date'], value['pool_type'])) == 0
            previous = conn.execute(text('SELECT * FROM yuanhang_limit_reason WHERE trade_date=:d AND unified_code=:c'),
                                    dict(d=reason_example['trade_date'], c=reason_example['unified_code'])).mappings().one()
            assert replace_reason(conn, reason_example, observed, previous) == 0
        assert not writes
        value['rows'][0]['name'] = '修订后的名称'
        started = time.perf_counter()
        with session.engine.begin() as conn:
            assert replace_pool(conn, value, observed, read_pool_head(conn, value['trade_date'], value['pool_type'])) == 2
        revision_ms = 1000 * (time.perf_counter() - started)
        event.remove(session.engine, 'before_cursor_execute', track)
        with session.engine.connect() as conn:
            for table in TABLE_COLUMNS:
                conn.exec_driver_sql('ANALYZE TABLE ' + table)
            counts = {table: conn.exec_driver_sql('SELECT COUNT(*) FROM ' + table).scalar_one() for table in TABLE_COLUMNS}
            space = [dict(r) for r in conn.execute(text('SELECT table_name,table_rows,data_length,index_length '
                'FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE :prefix'),
                dict(prefix='yuanhang_limit_%')).mappings()]
            plans = {}
            for label, sql in {
                'list': "SELECT * FROM yuanhang_limit_member WHERE trade_date='2024-01-01' AND pool_type='limit_up_pool' AND unified_code>'' ORDER BY unified_code LIMIT 201",
                'history': "SELECT * FROM yuanhang_limit_member WHERE unified_code='000001.SZ' AND trade_date BETWEEN '2024-01-01' AND '2025-12-31' ORDER BY trade_date,pool_type LIMIT 501",
                'reason': "SELECT * FROM yuanhang_limit_reason WHERE trade_date='2024-01-01' AND unified_code='000001.SZ'",
                'coverage': "SELECT trade_date,contract_version,content_sha256 FROM yuanhang_limit_pool WHERE pool_type='limit_up_pool' ORDER BY trade_date LIMIT 36601",
            }.items():
                plans[label] = {'estimate': [dict(r) for r in conn.exec_driver_sql('EXPLAIN ' + sql).mappings()],
                                'actual': conn.exec_driver_sql('EXPLAIN ANALYZE ' + sql).scalar_one()}
        assert counts == dict(yuanhang_limit_pool=500, yuanhang_limit_member=250000, yuanhang_limit_reason=100000)
        measurements = asyncio.run(measure_queries(session.engine))
        measurements.update(asyncio.run(measure_planning(session.engine, observed)))
        measurements.update(pool_import_seconds=pool_seconds, reason_bulk_import_seconds=reason_seconds,
                            python_traced_peak_bytes=peak, revision_ms=revision_ms,
                            packed_unit_max_bytes=max(packed))
        session.report.update(bindings=session.frozen_inputs, limits=LIMITS, measurements=measurements,
            schema_objects=objects((root / 'sql/schema.sql').read_text('utf8'),
                json.loads((root / 'sql/schema-contract.json').read_text('utf8')),
                json.loads((root / 'sql/business-schema.json').read_text('utf8')), [*TABLE_COLUMNS, 'collection_state']),
            exact_counts=counts, allocated_space=space, query_plans=plans, unchanged_business_dml=0,
            conditions={'sample': 'Synthetic 500 dates x 500 members; 200 dates x 500 reasons. Separate real proxy acceptance report required.',
                        'cache': 'First read after import; subsequent 30 warm reads. Server caches not flushed; not a cold-cache claim.',
                        'import': 'Formal typed pool repository; reason bulk upsert isolates SQL capacity, not end-to-end archive throughput.',
                        'memory': 'tracemalloc Python allocations during sequential imports; not whole-process RSS or production concurrency.'},
            reviewed_tradeoffs=['DECIMAL(48,24) preserves source precision at extra row cost.',
                                'Two query directions require secondary member index.',
                                'Reason text stored once per security day, separate from pool browsing.'])
        assert all(measurements[k] <= v for k, v in LIMITS.items())
        session.measurements_complete = True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-mysql', required=True)
    parser.add_argument('--output', required=True)
    run(parser.parse_args())
