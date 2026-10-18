"""Explicit additive security-alias maintenance; Empire closed and queue empty."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config, project_root
from empire.core.redaction import redact
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import validate_shapes

TABLES = ('security_code_alias',)


def inventory(conn):
    result = {}
    for table in inspect(conn).get_table_names():
        if table not in TABLES:
            result[table] = dict(rows=conn.exec_driver_sql(f'SELECT COUNT(*) FROM `{table}`').scalar_one(),
                ddl=hashlib.sha256(conn.exec_driver_sql(f'SHOW CREATE TABLE `{table}`').first()[1].encode()).hexdigest())
    rows = conn.execute(text('SELECT namespace,project_id,payload FROM collection_state ORDER BY namespace,project_id')).all()
    result['state_digest'] = hashlib.sha256(json.dumps([list(r) for r in rows], default=str).encode()).hexdigest()
    return result


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, redis = make_engine(cfg['mysql']), create_client(cfg['redis'])
    try:
        pending = await redis.xlen(cfg['redis'].get('namespace', 'empire') + ':ingest')
        sql = (project_root() / 'sql/schema.sql').read_text('utf8')
        with engine.connect() as conn:
            report = dict(applied=False, pending=pending, tables=TABLES)
            if args.apply:
                if pending:
                    raise RuntimeError('待归档必须清零，拒绝建表')
                if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                    raise RuntimeError('另有SQL维护操作')
                try:
                    report['before'] = inventory(conn)
                    for table in TABLES:
                        ddl = sql[sql.index('CREATE TABLE IF NOT EXISTS ' + table + ' ('):].split(';', 1)[0]
                        conn.exec_driver_sql(ddl)
                    conn.commit()
                    validate_shapes(conn, TABLES)
                    report['after'] = inventory(conn)
                    if report['before'] != report['after']:
                        raise RuntimeError('已有业务内容或状态发生变化，停止交付')
                    report.update(applied=True, existing_business_unchanged=True)
                finally:
                    conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
            if args.report:
                Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
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
