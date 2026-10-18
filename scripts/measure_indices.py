"""UUID-owned capacity and formal query measurement on an independent MySQL service."""
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

from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.contracts.indices import JOB, PROJECT
from empire.core.config import load_config, project_root
from empire.plugins.data.indices import IndexDataPlugin
from empire.plugins.datasets import indices
from empire.plugins.infra.collection_state import save_state
from empire.plugins.infra.mysql_store import initialize_database, make_engine


def run(args):
    root = project_root()
    settings = json.loads(Path(args.test_settings).read_text('utf8'))
    production = load_config()['mysql']
    if (settings.get('host'), settings.get('port')) == (production.get('host'), production.get('port')):
        raise ValueError('容量实验必须使用独立MySQL服务')
    admin, database, engine, created = make_engine(settings), 'empire_' + uuid4().hex + '_test', None, False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4')
            created = True
        settings = {**settings, 'database': database}
        initialize_database(settings)
        engine, observed, state = make_engine(settings), datetime.now(UTC), {}
        catalog = [dict(code=f'{i:06d}', name=f'容量指数{i}', group='实验') for i in range(100)]
        def archive(dataset, key, payload):
            nonlocal state
            e = make_envelope(source='ths', dataset=dataset, business_key=key, job_key=JOB,
                              batch_id='measure', run_id='measure', payload=payload).model_copy(update={'observed_at': observed})
            data = indices.normalize(e)
            with engine.begin() as conn:
                outcome = indices.write(conn, e, {**data, 'archive_state': state})
                new = indices.archive_state(e, data, outcome, state)
                save_state(conn, 'capacity', PROJECT, 'ths', dataset, new, state)
                state = new
            return outcome
        started = time.perf_counter()
        archive('index.catalog', 'catalog', dict(page=1, catalog=catalog))
        for i, row in enumerate(catalog):
            archive('index.members', row['code'], dict(page=i + 2, code=row['code'], available=True,
                    members=[[f'{n:06d}', '容量证券'] for n in range(1, 1001)]))
        import_seconds = time.perf_counter() - started
        repeat = archive('index.members', '000000', dict(page=2, code='000000', available=True,
                         members=[[f'{n:06d}', '容量证券'] for n in range(1, 1001)]))
        revision = archive('index.members', '000000', dict(page=2, code='000000', available=True,
                           members=[[f'{n:06d}', '名称修订' if n == 1 else '容量证券'] for n in range(1, 1001)]))
        assert repeat['written_count'] == 0 and revision['written_count'] == 2
        async def read(callback):
            return callback()
        q = IndexDataPlugin('capacity')
        q.mysql = SimpleNamespace(read_engine=engine, read=read)
        async def measures():
            result = {}
            for name, callback in [('catalog_p95_ms', lambda: q.browse()), ('members_p95_ms', lambda: q.browse('members')),
                    ('search_p95_ms', lambda: q.browse('members', '000001')),
                    ('cursor_p95_ms', lambda: q.browse('members', after=['000050', '000500']))]:
                samples = []
                for _ in range(20):
                    started = time.perf_counter()
                    await callback()
                    samples.append((time.perf_counter() - started) * 1000)
                result[name] = sorted(samples)[18]
            started = time.perf_counter()
            audited = q.snapshot_audit()
            assert audited[1] and audited[5] == 100000
            result['audit_seconds'] = time.perf_counter() - started
            return result
        measurements = asyncio.run(measures())
        with engine.connect() as conn:
            conn.exec_driver_sql('ANALYZE TABLE stock_index,stock_index_member')
            allocation = conn.execute(text('SELECT SUM(DATA_LENGTH+INDEX_LENGTH) FROM information_schema.TABLES '
                'WHERE TABLE_SCHEMA=:schema AND TABLE_NAME IN (\'stock_index\',\'stock_index_member\')'), {'schema': database}).scalar_one()
            version = conn.exec_driver_sql('SELECT VERSION()').scalar_one()
            explains = {name: [dict(r) for r in conn.exec_driver_sql(sql).mappings()] for name, sql in {
                'member_page': 'EXPLAIN SELECT * FROM stock_index_member ORDER BY index_code,source_code LIMIT 200',
                'security_reverse': "EXPLAIN SELECT * FROM stock_index_member WHERE source_code='000001' ORDER BY index_code LIMIT 200",
            }.items()}
        measurements.update(import_seconds=import_seconds, allocated_bytes=int(allocation),
                            state_bytes=len(json.dumps(state).encode()))
        paths = ['src/empire/contracts/indices.py', 'src/empire/plugins/datasets/indices.py',
                 'src/empire/plugins/data/indices.py', 'scripts/measure_indices.py']
        schema = (root / 'sql/schema.sql').read_text('utf8')
        report = dict(bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
            ddl_scopes={t: hashlib.sha256(re.search(r'CREATE TABLE IF NOT EXISTS ' + t + r'\s*\([\s\S]*?;', schema).group().encode()).hexdigest()
                        for t in indices.TABLES}, measurements=measurements,
            limits=dict(catalog_p95_ms=50, members_p95_ms=50, search_p95_ms=50, cursor_p95_ms=50,
                        audit_seconds=3, import_seconds=20, allocated_bytes=512 * 1024**2, state_bytes=8 * 1024**2),
            conditions=dict(platform=platform.platform(), mysql=version, indices=100, members=100000,
                synthetic=True, first_query='unforced cache', repeats=20, audited_key_set=True,
                repeat_business_dml=repeat['written_count'], revision_writes=revision['written_count']),
            reviewed_tradeoffs='当前关系不按日累积；成员批写、主键游标、证券反查索引。来源不确定市场保留来源身份；详细准备扫描全部关系，普通页面不扫描正文。十倍到100万的512MiB是设计预算，实测只证明100000关系样本；扩大范围前重新测量。',
            explain=explains, cleanup='UUID-owned schema dropped in finally')
        report['passed'] = all(measurements[k] <= v for k, v in report['limits'].items())
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(dict(passed=report['passed'], measurements=measurements)))
        if not report['passed']:
            raise RuntimeError('指数容量预算未通过')
    finally:
        if engine:
            engine.dispose()
        if created:
            assert database.endswith('_test')
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{database}`')
        admin.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-settings', required=True)
    parser.add_argument('--output', default='docs/evidence/indices-capacity-2026-10-09.json')
    run(parser.parse_args())
