"""Explicit additive name-event schema maintenance; never called by application startup."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config, project_root
from empire.core.redaction import redact
from empire.features.name_changes.dataset import TABLE
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import shape, validate_shapes


def ddl(table=TABLE):
    sql = (project_root() / 'sql/schema.sql').read_text('utf-8')
    return sql[sql.index('CREATE TABLE IF NOT EXISTS ' + table):].split(';', 1)[0]


def inventory(conn, added_table=TABLE):
    result = {}
    for table in inspect(conn).get_table_names():
        if table != added_table:
            result[table] = dict(rows=conn.exec_driver_sql(f'SELECT COUNT(*) FROM `{table}`').scalar_one(),
                ddl_hash=hashlib.sha256(conn.exec_driver_sql(f'SHOW CREATE TABLE `{table}`').first()[1].encode()).hexdigest())
    states = conn.execute(text('SELECT namespace,project_id,payload FROM collection_state ORDER BY namespace,project_id')).all()
    result['state_digest'] = hashlib.sha256(json.dumps([list(r) for r in states], default=str).encode()).hexdigest()
    return result


async def run(args, table=TABLE):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, redis = make_engine(cfg['mysql']), create_client(cfg['redis'])
    try:
        queue = await redis.xlen(cfg['redis'].get('namespace', 'empire') + ':ingest')
        with engine.connect() as conn:
            report = dict(applied=False, queue=queue, table=table,
                          exists=table in inspect(conn).get_table_names(),
                          ddl_sha256=hashlib.sha256(ddl(table).encode()).hexdigest())
            if args.apply:
                if queue:
                    raise RuntimeError('待归档消息未清零，拒绝建表')
                if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                    raise RuntimeError('已有数据库维护，拒绝并发')
                try:
                    report['before'] = inventory(conn, table)
                    conn.exec_driver_sql(ddl(table))
                    conn.commit()
                    validate_shapes(conn, [table])
                    report['after'] = inventory(conn, table)
                    if report['before'] != report['after']:
                        raise RuntimeError('已有业务数量、结构或状态内容变化，停止交付')
                    report.update(applied=True, shape=shape(conn, table), unchanged_existing_business=True)
                finally:
                    conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
            if args.report:
                path = Path(args.report)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), 'utf-8')
            print(json.dumps({k: v for k, v in report.items() if k not in ('before', 'after', 'shape')}, ensure_ascii=False))
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
