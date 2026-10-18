"""Measure current preview queries in a UUID-owned schema on an isolated MySQL instance."""
import argparse
import asyncio
import copy
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from empire.contracts.market_storage import MARKET_TABLES
from empire.core.config import load_config, project_root
from empire.plugins.data.kaipanla_products import KaipanlaProductDataPlugin
from empire.plugins.datasets.kaipanla_products import digest, validate
from empire.plugins.datasets.market_repository import head_record, read_day, write_day
from empire.plugins.infra.mysql_store import initialize_database, make_engine
from scripts.measure_market_storage import memory, timed
from tests.test_kaipanla_products import business_row


def run(args):
    root = project_root()
    production = load_config()['mysql']
    settings = json.loads(Path(args.test_settings).read_text('utf-8'))
    if (settings['host'], settings['port']) == (production['host'], production['port']):
        raise ValueError('容量写入必须使用独立MySQL实例')
    source, admin = make_engine(production), make_engine(settings)
    database, engine, created = 'empire_preview_' + uuid4().hex + '_test', None, False
    samples = []
    try:
        with source.connect() as conn:
            conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            for kind in ('trend', 'auction', 'volume', 'trades', 'entrust', 'large_order', 'quote'):
                head = conn.execute(text('SELECT * FROM stock_market_day WHERE kind=:kind '
                    'ORDER BY trade_date DESC,unified_code LIMIT 1'), dict(kind=kind)).mappings().first()
                if head:
                    samples.append((read_day(conn, head), head['version_observed_at']))
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            created = True
        owned = {**settings, 'database': database}
        initialize_database(owned)
        engine = make_engine(owned)
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
        assert following()['seqs'] == list(range(200, 400))
        measurements = dict(max_page_p95_ms=timed(page)['p95_ms'], time_page_p95_ms=timed(window)['p95_ms'],
            next_page_p95_ms=timed(following)['p95_ms'], max_page_python_peak_bytes=memory(page))
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
        measurements['sample_full_day_p95_ms'] = max((s['latency']['p95_ms'] for s in sample_checks), default=0)
        paths = ['src/empire/contracts/market_storage.py', 'src/empire/plugins/datasets/market_mapping.py',
            'src/empire/plugins/datasets/market_repository.py', 'src/empire/plugins/datasets/trade_blocks.py',
            'src/empire/plugins/data/kaipanla_products.py', 'scripts/measure_preview_queries.py',
            'docs/evidence/kaipanla-storage-capacity-2026-10-05.json']
        ddl = (root/'sql/schema.sql').read_text('utf-8')
        limits = dict(max_page_p95_ms=10, time_page_p95_ms=10, next_page_p95_ms=10,
                      max_page_python_peak_bytes=350000, sample_full_day_p95_ms=100)
        report = dict(date='2026-10-11', scope='7种已归档证券日抽样及100000点同秒合成分笔；不代表全市场完整性',
            bindings={p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},
            ddl_scopes={t: hashlib.sha256(re.search(r'CREATE TABLE IF NOT EXISTS '+t+r'\s*\([\s\S]*?;', ddl).group().encode()).hexdigest() for t in MARKET_TABLES},
            measurements=measurements, limits=limits, samples=sample_checks,
            conditions='独立13331实例，30次热查询；一次有界正式查询，未启动采集；生产只读一致性快照',
            reviewed_tradeoffs='本次只改查询，结构/归档写入未变；原存储写入、20万业务头和空间基线保留在绑定的2026-10-05证据。当前页、时间窗及完整证券日重新测量。10ms为页面查询预算，100ms为有限整日预算，不承诺冷盘或全部历史容量。',
            cleanup='UUID私有库在finally删除，共享业务不写入')
        report['passed'] = all(measurements[k] <= v for k, v in limits.items())
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), 'utf-8')
        print(json.dumps(dict(passed=report['passed'], measurements=measurements)))
        if not report['passed']:
            raise RuntimeError('预览查询容量预算未通过')
    finally:
        if engine:
            engine.dispose()
        if created:
            assert database.endswith('_test')
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{database}`')
        source.dispose()
        admin.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--output', default='docs/evidence/preview-query-capacity-2026-10-11.json')
    run(parser.parse_args())
