"""Private 120-month capacity and formal query measurement; no production writes."""
import argparse
import asyncio
import hashlib
import json
import platform
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event, text

from empire.contracts.unlock_industries import COLUMNS, TABLE, digest
from empire.core.config import load_config
from empire.core.time import mysql_time
from empire.plugins.collectors.tdx_unlock_industries import UnlockIndustryCollector
from empire.plugins.collectors.tdx_unlock_industry_source import SOURCE_COLUMNS, parse_month
from empire.plugins.data.unlock_industries import UnlockIndustryDataPlugin
from empire.plugins.datasets.unlock_industries import UnlockIndustryDataset, read_month
from empire.plugins.infra.mysql_store import make_engine


async def run(args):
    settings = json.loads(Path(args.test_settings).read_text('utf-8-sig'))
    prod = load_config()['mysql']
    if (settings['host'], settings['port']) == (prod['host'], prod['port']):
        raise ValueError('容量放大仅允许独立测试服务')
    sample = json.loads(Path('docs/evidence/unlock-industries-source-2026-10-14.json').read_text('utf8'))
    seed = sample['results'][0]
    raw = dict(ErrorCode=0, ResultSets=[dict(ColName=SOURCE_COLUMNS, Content=seed['sample'], Count=len(seed['sample'])),
                                     dict(ColName=['sstart'], Content=[[seed['month']]], Count=1)])
    seed_row = parse_month(raw, seed['month'][:4] + '-' + seed['month'][4:] + '-01',
                          seed['basis'][:4] + '-' + seed['basis'][4:6] + '-' + seed['basis'][6:])[0]
    admin, engine, database = make_engine(settings), None, 'empire_unlockindustry_' + uuid4().hex + '_test'
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
        engine = make_engine({**settings, 'database': database})
        schema = Path('sql/schema.sql').read_text('utf8')
        ddl = re.search(r'CREATE TABLE IF NOT EXISTS ' + TABLE + r'\s*\([\s\S]*?;', schema)[0]
        names = (*COLUMNS, 'content_hash', 'version_observed_at')
        insert = text(f'INSERT INTO {TABLE}({",".join(names)}) VALUES(' + ','.join(':' + k for k in names) + ')')
        units, stamp, start = {}, datetime.now(UTC), time.perf_counter()
        with engine.begin() as conn:
            conn.exec_driver_sql(ddl)
            for index in range(120):
                unit = f'{2010 + index // 12}-{index % 12 + 1:02d}-01'
                rows = [{**seed_row, 'unlock_month': unit, 'industry': f'行业{i:03d}'} for i in range(100)]
                units[unit] = rows
                conn.execute(insert, [{**r, 'content_hash': digest(r), 'version_observed_at': mysql_time(stamp)} for r in rows])
        import_seconds = time.perf_counter() - start
        q = UnlockIndustryDataPlugin()
        async def read(fn, *args):
            return fn(*args)
        q.mysql = SimpleNamespace(read_engine=engine, read=read)
        page_ms, industry_ms, month_ms = [], [], []
        for _ in range(6):
            start = time.perf_counter()
            assert len((await q.list_records())['rows']) == 200
            page_ms.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            assert len((await q.list_records(industry='行业000'))['rows']) == 120
            industry_ms.append((time.perf_counter() - start) * 1000)
            with engine.connect() as conn:
                start = time.perf_counter()
                assert len(read_month(conn, '2010-01-01')[1]) == 100
                month_ms.append((time.perf_counter() - start) * 1000)
        c, mapping = UnlockIndustryCollector(), UnlockIndustryDataset()
        cursor = dict(batch_id='capacity', page=0, basis_date=seed_row['basis_date'])
        envelope = c.envelope(cursor, '2010-01-01', units['2010-01-01'])
        data = mapping.normalize(envelope) | {'archive_state': {}}
        writes = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if TABLE in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        with engine.begin() as conn:
            start = time.perf_counter()
            outcome = mapping.write(conn, envelope, data)
            repeat_seconds = time.perf_counter() - start
            assert outcome['written_count'] == 0 and not writes
            changed = [dict(r) for r in data['rows']]
            changed[0]['shares'] = str(int(changed[0]['shares']) + 1)
            newer = c.envelope(cursor, '2010-01-01', changed)
            start = time.perf_counter()
            outcome = mapping.write(conn, newer, mapping.normalize(newer) | {'archive_state': {}})
            revision_seconds = time.perf_counter() - start
            assert outcome['written_count'] == 1
        event.remove(engine, 'before_cursor_execute', capture)
        with engine.connect() as conn:
            assert conn.exec_driver_sql(f'SELECT COUNT(*) FROM {TABLE}').scalar_one() == 12000
            conn.exec_driver_sql(f'ANALYZE TABLE {TABLE}').all()
            conn.exec_driver_sql('SET SESSION information_schema_stats_expiry=0')
            allocated = conn.execute(text('SELECT DATA_LENGTH+INDEX_LENGTH FROM information_schema.tables '
                'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table'), {'table': TABLE}).scalar_one()
            mysql_version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            explains = [dict(r) for r in conn.exec_driver_sql(f'EXPLAIN SELECT {",".join(COLUMNS)} FROM {TABLE} '
                "WHERE industry='行业000' ORDER BY unlock_month DESC,industry DESC LIMIT 201").mappings()]
        measured = dict(page_ms=max(page_ms), industry_ms=max(industry_ms), month_ms=max(month_ms),
                        allocated_bytes=allocated, import_seconds=import_seconds, repeat_seconds=repeat_seconds,
                        revision_seconds=revision_seconds, message_bytes=len(envelope.model_dump_json().encode()))
        limits = dict(page_ms=100, industry_ms=100, month_ms=100, allocated_bytes=67108864,
                      import_seconds=60, repeat_seconds=5, revision_seconds=5, message_bytes=524288)
        paths = ['src/empire/contracts/unlock_industries.py', 'src/empire/plugins/collectors/tdx_unlock_industry_source.py',
                 'src/empire/plugins/collectors/tdx_unlock_industries.py', 'src/empire/plugins/datasets/unlock_industries.py',
                 'src/empire/plugins/data/unlock_industries.py', 'scripts/measure_unlock_industries.py']
        report = dict(checked_at=datetime.now(UTC).isoformat(), conditions=dict(platform=platform.platform(),
            mysql=mysql_version, rows=12000, months=120, cache='six reads including first; maximum reported', isolation='owned UUID database independent service'),
            reviewed_tradeoffs='Typed monthly current rows; old directory months retained; no daily snapshot history; bounded month transactions.',
            measurements=measured, limits=limits, explains=explains, ddl_scopes={TABLE: hashlib.sha256(ddl.encode()).hexdigest()},
            bindings={p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},
            passed=all(measured[k] <= v for k, v in limits.items()))
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), 'utf8')
        print(json.dumps(dict(passed=report['passed'], measurements=measured)))
        if not report['passed']:
            raise ValueError('行业容量预算未通过')
    finally:
        if engine:
            engine.dispose()
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS `{database}`')
        admin.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--output', default='docs/evidence/unlock-industries-capacity-2026-10-14.json')
    asyncio.run(run(parser.parse_args()))
