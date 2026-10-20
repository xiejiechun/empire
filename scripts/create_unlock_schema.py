"""Explicit additive unlock tables; stop Empire and require an empty archive queue."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from create_name_change_schema import ddl, inventory
from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.unlocks.dataset import TABLE_COLUMNS
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import validate_shapes


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, redis = make_engine(cfg['mysql']), create_client(cfg['redis'])
    try:
        queue = await redis.xlen(cfg['redis'].get('namespace', 'empire') + ':ingest')
        with engine.connect() as conn:
            targets = tuple(TABLE_COLUMNS)
            report = dict(applied=False, queue=queue, tables=targets,
                exists={t: t in inspect(conn).get_table_names() for t in targets},
                ddl_sha256={t: hashlib.sha256(ddl(t).encode()).hexdigest() for t in targets})
            if args.apply:
                if queue:
                    raise RuntimeError('待归档消息未清零，拒绝建表')
                if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                    raise RuntimeError('已有数据库维护，拒绝并发')
                try:
                    validate_shapes(conn, [t for t in targets if report['exists'][t]])
                    before = inventory(conn)
                    report['before'] = {k: v for k, v in before.items() if k not in targets}
                    for table in targets:
                        conn.exec_driver_sql(ddl(table))
                        conn.commit()
                    validate_shapes(conn, targets)
                    after = inventory(conn)
                    report['after'] = {k: v for k, v in after.items() if k not in targets}
                    if report['before'] != report['after']:
                        raise RuntimeError('原业务数量、结构或统一状态变化；停止交付')
                    report.update(applied=True, unchanged_existing_business=True)
                finally:
                    conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
            if args.report:
                Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), 'utf-8')
            print(json.dumps({k: v for k, v in report.items() if k not in ('before', 'after')}, ensure_ascii=False))
    finally:
        engine.dispose()
        await redis.aclose()
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
