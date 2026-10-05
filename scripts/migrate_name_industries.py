"""Explicit additive industry columns; retain event identities and invalidate old proofs."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.datasets.name_changes import TABLE
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import validate_shapes
from empire.plugins.pipeline.fingerprints import FingerprintCache


def events(conn):
    rows = conn.exec_driver_sql(f'SELECT name_kind,record_key,unified_code,event_date,old_name,new_name,'
        f'source_occurrences FROM {TABLE} ORDER BY name_kind,record_key LIMIT 60001').all()
    if len(rows) >= 60000:
        raise ValueError('更名记录超过维护边界')
    return dict(count=len(rows), digest=hashlib.sha256(json.dumps([list(r) for r in rows],
        ensure_ascii=False, default=str).encode()).hexdigest())


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    namespace = cfg['redis'].get('namespace', 'empire')
    report = dict(applied=False, pending=await client.xlen(namespace + ':ingest'))
    try:
        with engine.connect() as conn:
            report['before'] = events(conn)
            report['missing_columns'] = sorted({'csrc_industry', 'tdx_industry'} -
                {r['name'] for r in inspect(conn).get_columns(TABLE)})
            if args.apply:
                if report['pending']:
                    raise RuntimeError('待归档必须清零，不能迁移旧消息')
                if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                    raise RuntimeError('另有SQL维护操作')
                try:
                    for column in report['missing_columns']:
                        conn.exec_driver_sql(f'ALTER TABLE {TABLE} ADD COLUMN {column} VARCHAR(200) '
                            'CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL')
                        conn.commit()
                    validate_shapes(conn, [TABLE])
                    report['after'] = events(conn)
                    if report['before'] != report['after']:
                        raise RuntimeError('原有事件内容变化，停止交付')
                    # Contract1 SQL proofs remain visible but cannot satisfy contract2 acceptance.
                    from types import SimpleNamespace
                    cache = FingerprintCache(SimpleNamespace(client=client, prefix=namespace), cfg.get('archive', {}), lambda _: None)
                    for kind in ('company', 'security'):
                        for version in (1, 2):
                            await cache.invalidate(f'tdx_names_{kind}_v{version}', 'tdx')
                    report.update(applied=True, original_events_preserved=True,
                        coverage='old contract1 cannot satisfy contract2; full source refresh required')
                finally:
                    conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
        if args.report:
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps(report, ensure_ascii=False))
    finally:
        engine.dispose()
        await client.aclose()
        if lock:
            lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
