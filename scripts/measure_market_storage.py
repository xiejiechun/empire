"""Read-only production sample, owned test databases and explicit synthetic scale experiment."""
import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import inspect, text

from empire.core.config import load_config
from empire.features.kaipanla.normalization import digest, validate
from empire.features.kaipanla.query import KaipanlaProductDataPlugin
from empire.features.kaipanla.repository import head_record, read_day, write_day
from empire.features.kaipanla.storage_contract import MARKET_TABLES, SERIES
from empire.plugins.infra.mysql_store import initialize_database, make_engine
from scripts.measure_capacity import latency, process_resources


def timed(fn, count=30):
    values = []
    for _ in range(count):
        start = time.perf_counter()
        fn()
        values.append(time.perf_counter()-start)
    return latency(values)


def memory(fn):
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def allocation(engine):
    with engine.connect() as c:
        for table in MARKET_TABLES:
            c.exec_driver_sql('ANALYZE TABLE '+table)
        rows = [dict(r) for r in c.execute(text('SELECT TABLE_NAME,DATA_LENGTH,INDEX_LENGTH FROM '
            'information_schema.tables WHERE table_schema=DATABASE()')).mappings()]
    return {'tables': rows, 'bytes': sum(r['DATA_LENGTH']+r['INDEX_LENGTH'] for r in rows)}


def run(args):
    import asyncio
    source_settings = load_config(args.config)['mysql']
    settings = json.loads(Path(args.test_settings).read_text('utf-8'))
    if (settings['host'], settings['port']) == (source_settings['host'], source_settings['port']):
        raise ValueError('容量实验必须使用独立MySQL实例')
    source = make_engine(source_settings)
    with source.connect() as c:
        c.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        if 'payload' not in {r['name'] for r in inspect(c).get_columns('stock_market_day')}:
            raise ValueError('此容量入口输入为迁移前v1快照，不自动猜测旧表路径')
        rows = [dict(r) for r in c.execute(text('SELECT * FROM stock_market_day ORDER BY kind,unified_code,trade_date LIMIT 10001')).mappings()]
        if len(rows) > 10000:
            raise ValueError('样本超过有界入口，请使用指定范围的实验方案')
    source.dispose()
    admin = make_engine(settings, read_timeout=3600)
    db = 'empire_market_'+uuid4().hex+'_test'
    report = {'scope': 'actual stored sample; synthetic scale is not source/coverage acceptance',
              'units': len(rows), 'databases': [db], 'resources_before': process_resources()}
    with admin.begin() as c:
        c.exec_driver_sql(f'CREATE DATABASE `{db}` CHARACTER SET utf8mb4')
    cfg = {**settings, 'database': db}
    initialize_database(cfg)
    engine = make_engine(cfg, read_timeout=3600)
    with engine.begin() as c:
        ddl = Path('sql/legacy/market-day-v1.sql').read_text('utf-8').split('\n', 1)[1]
        c.exec_driver_sql(ddl.replace('stock_market_day', 'legacy_market_day'))
    start = time.perf_counter()
    for r in rows:
        with engine.begin() as c:
            c.execute(text('SELECT content_hash FROM legacy_market_day WHERE kind=:kind AND unified_code=:unified_code AND trade_date=:trade_date FOR UPDATE'), r).first()
            c.execute(text('INSERT INTO legacy_market_day VALUES(:kind,:unified_code,:trade_date,:payload,:content_hash,:version_observed_at)'), r)
    report['old_insert_seconds'] = time.perf_counter()-start
    start = time.perf_counter()
    for r in rows:
        with engine.begin() as c:
            write_day(c, json.loads(r['payload']), r['content_hash'], r['version_observed_at'])
    report['new_insert_seconds'] = time.perf_counter()-start
    print('actual sample inserted', report['units'], flush=True)
    with engine.connect() as c:
        for r in rows:
            assert digest(read_day(c, head_record(c, r['kind'], r['unified_code'], r['trade_date']))) == r['content_hash']
        c.exec_driver_sql('ANALYZE TABLE legacy_market_day')
    report['allocation'] = allocation(engine)
    query = KaipanlaProductDataPlugin('trades')
    async def execute(fn, *params):
        return fn(*params)
    query.mysql = SimpleNamespace(read_engine=engine, read=execute)
    sample = max((r for r in rows if r['kind']=='trades'), key=lambda r: len(r['payload']))
    security, day = sample['unified_code'], sample['trade_date']
    def old_day():
        with engine.connect() as c:
            body = c.execute(text('SELECT payload FROM legacy_market_day WHERE kind=:kind AND unified_code=:unified_code AND trade_date=:trade_date'), sample).scalar_one()
        row = json.loads(body)
        validate(row, storage_check=False)
        digest(row)
        return row
    def new_day():
        return asyncio.run(query.day(security[-2:], security[:6], day.isoformat()))
    def page():
        return asyncio.run(query.page(security[-2:], security[:6], day.isoformat()))
    report['latency'] = {'old_day': timed(old_day), 'new_day': timed(new_day), 'new_page': timed(page)}
    first_page = page()
    report['latency']['next_page'] = timed(lambda: asyncio.run(query.page(
        security[-2:], security[:6], day.isoformat(), first_page['next_cursor'])))
    report['latency']['time_page'] = timed(lambda: asyncio.run(query.page(
        security[-2:], security[:6], day.isoformat(), start_time='09:30:00', end_time='10:00:00')))
    report['python_peak_bytes'] = {'old_day': memory(old_day), 'new_day': memory(new_day), 'page': memory(page)}
    def repeat():
        with engine.begin() as c:
            return write_day(c, json.loads(sample['payload']), sample['content_hash'], sample['version_observed_at'])
    report['cold_repeat'] = timed(repeat)
    import copy
    from datetime import timedelta
    original = json.loads(sample['payload'])
    revision = copy.deepcopy(original)
    revision['data']['fb'][0][1] += 1
    def revise():
        with engine.begin() as c:
            assert write_day(c, revision, digest(revision), sample['version_observed_at']+timedelta(seconds=1))[1] == 2
        with engine.begin() as c:
            assert write_day(c, original, digest(original), sample['version_observed_at']+timedelta(seconds=1))[1] == 2
    report['single_block_revision_pair'] = timed(revise)
    report['coverage'] = timed(lambda: query._covered(security[-2:], security[:6], day, day))
    maximum = copy.deepcopy(original)
    maximum.update(code='999998', market='SH', source_code=None, aliases={})
    maximum['data']['fb'] = [list(original['data']['fb'][0]) for _ in range(100000)]
    maximum['data'].update(Count=100000, total=100000)
    validate(maximum, storage_check=False)
    with engine.begin() as c:
        write_day(c, maximum, digest(maximum), sample['version_observed_at'])
    def max_page():
        return asyncio.run(query.page('SH', '999998', day.isoformat()))
    report['maximum_synthetic'] = {'points': 100000, 'blocks': 500,
        'page_latency': timed(max_page), 'page_python_peak_bytes': memory(max_page)}
    report['resources_after_sample'] = process_resources()
    Path(args.output).write_text(json.dumps(report, default=str, indent=2), encoding='utf-8')
    if args.scale:
        scale_db = 'empire_market_'+uuid4().hex+'_test'
        report['databases'].append(scale_db)
        with admin.begin() as c:
            c.exec_driver_sql(f'CREATE DATABASE `{scale_db}` CHARACTER SET utf8mb4')
        scale_cfg = {**settings, 'database': scale_db}
        initialize_database(scale_cfg)
        scale_engine = make_engine(scale_cfg, read_timeout=3600)
        with scale_engine.begin() as c:
            c.exec_driver_sql('CREATE TABLE capacity_keys (target_security VARCHAR(9),source_security VARCHAR(9),PRIMARY KEY(target_security))')
            securities = sorted({r['unified_code'] for r in rows})
            c.execute(text('INSERT INTO capacity_keys VALUES(:target,:source)'),
                      [dict(target=f'{700000+i:06}.SH', source=securities[i % len(securities)]) for i in range(500)])
            c.exec_driver_sql('CREATE TABLE capacity_days (trade_date DATE PRIMARY KEY)')
            from datetime import date, timedelta
            c.execute(text('INSERT INTO capacity_days VALUES(:day)'),
                      [dict(day=date(2026, 7, 1)+timedelta(days=i)) for i in range(60)])
        scale_times = {}
        for table in MARKET_TABLES:
            start = time.perf_counter()
            with scale_engine.begin() as c:
                columns = [r['name'] for r in inspect(c).get_columns(table)]
                kind = next((k for k, (t, _) in SERIES.items() if table==t), 'quote')
                expressions = ['k.target_security' if col=='unified_code' else 'd.trade_date' if col=='trade_date' else 'b.`'+col+'`' for col in columns]
                # One actual day template per source security/kind. Synthetic labels deliberately
                # do not claim real observations or valid canonical content hashes.
                grouped = f'(SELECT kind,unified_code,MIN(trade_date) day FROM `{db}`.stock_market_day GROUP BY kind,unified_code)'
                join = 'h.unified_code=b.unified_code AND h.day=b.trade_date'
                join += ' AND h.kind=b.kind' if table=='stock_market_day' else " AND h.kind='"+kind+"'"
                c.exec_driver_sql(f'INSERT INTO `{table}` ('+','.join('`'+x+'`' for x in columns)+') SELECT '+
                    ','.join(expressions)+f' FROM `{db}`.`{table}` b JOIN '+grouped+' h ON '+join+
                    ' JOIN capacity_keys k ON k.source_security=b.unified_code CROSS JOIN capacity_days d')
            scale_times[table] = time.perf_counter()-start
            print('synthetic expanded', table, round(scale_times[table], 2), flush=True)
        report['synthetic'] = {'planned_securities': 500, 'days': 60,
                               'restriction': 'SQL shape/load experiment; source gaps retained by templates; hashes not coverage proofs',
                               'insert_seconds': scale_times, 'allocation': allocation(scale_engine)}
        with scale_engine.connect() as c:
            report['synthetic']['counts'] = {t: c.exec_driver_sql('SELECT COUNT(*) FROM '+t).scalar_one() for t in MARKET_TABLES}
            report['synthetic']['explain'] = [dict(r) for r in c.exec_driver_sql("EXPLAIN SELECT unified_code,last_px FROM stock_daily_quote WHERE trade_date='2026-07-01'").mappings()]
        report['resources_after_scale'] = process_resources()
        scale_engine.dispose()
    report['measurement_conditions'] = 'warm cache, MySQL 8.4.9 private port; 30 repetitions; not cold disk/full-history load'
    report['insert_measurement'] = '1016 independent transactions; both check head; old JSON INSERT vs new mapping+typed batch INSERT, not end-to-end collector throughput'
    report['comparison'] = {'day_p95_ratio': report['latency']['new_day']['p95_ms']/report['latency']['old_day']['p95_ms'],
                            'insert_time_ratio': report['new_insert_seconds']/report['old_insert_seconds']}
    Path(args.output).write_text(json.dumps(report, default=str, indent=2), encoding='utf-8')
    engine.dispose()
    # Keep owned experiment databases named in report for inspection; explicit cleanup later.
    admin.dispose()
    print('report', args.output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--output', default='build/kaipanla-optimization/capacity.json')
    parser.add_argument('--scale', action='store_true')
    run(parser.parse_args())
