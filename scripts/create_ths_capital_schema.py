"""Explicit additive eight-table maintenance, with queue/lock/inventory evidence."""
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
from empire.features.ths_capital.contract import TABLES as TARGETS
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import shape, validate_shapes


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    try:
        queue = await client.xlen(cfg['redis'].get('namespace', 'empire') + ':ingest')
        with engine.connect() as conn:
            report = dict(applied=False, queue=queue, exists={t: t in inspect(conn).get_table_names() for t in TARGETS},
                          ddl_scopes={t: hashlib.sha256((ddl(t) + ';').encode()).hexdigest() for t in TARGETS})
            if args.apply:
                if queue:
                    raise ValueError('待归档消息未清零，拒绝建表')
                if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                    raise ValueError('已有结构维护，拒绝并发')
                try:
                    def preserved():
                        return {k: v for k, v in inventory(conn, added_table='__none__').items() if k not in TARGETS}
                    report['before'] = preserved()
                    for table in TARGETS:
                        if report['exists'][table]:
                            validate_shapes(conn, [table])
                        else:
                            conn.exec_driver_sql(ddl(table))
                            conn.commit()
                    validate_shapes(conn, TARGETS)
                    report['after'] = preserved()
                    if report['before'] != report['after']:
                        raise ValueError('已有业务数量、结构或状态变化，不能确认维护完成')
                    report.update(applied=True, unchanged_existing_business=True,
                                  shapes={t: shape(conn, t) for t in TARGETS})
                finally:
                    conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
            if args.report:
                Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', 'utf8')
            print(json.dumps({k: v for k, v in report.items() if k not in ('before', 'after', 'shapes')}, ensure_ascii=False))
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
