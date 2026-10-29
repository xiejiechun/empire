"""Explicit holder ratio CHECK upgrade; no business rows or runtime state are rewritten."""
import argparse
import asyncio
import copy
import json
from pathlib import Path

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import manifest, shape, validate_shapes
from scripts.create_name_change_schema import ddl
from scripts.migrate_holder_source_rows import inventory

CHANGES = {'holder_report': ('ck_holder_totals', 'between0and511', 'between0and255'),
           'holder_member': ('ck_holder_member_values', '(ratiobetween0and99999.9999)', '(ratiobetween0and100)')}


def pending_changes(conn):
    changes = []
    for table, (check, new, old) in CHANGES.items():
        expected = manifest()['tables'][table]
        previous = copy.deepcopy(expected)
        previous['checks'][check] = previous['checks'][check].replace(new, old)
        actual = shape(conn, table)
        if actual == expected:
            continue
        if actual != previous:
            raise ValueError('未知持有人结构，拒绝替换约束：' + table)
        changes.append((table, check))
    return changes


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    result = {'applied': False, 'business_dml': 0}
    try:
        result['pending'] = await client.xlen(cfg['redis']['namespace'] + ':ingest')
        if result['pending']:
            raise ValueError('共享待归档非零，等待正常归档完成后维护')
        with engine.connect() as conn:
            if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                raise ValueError('结构维护锁忙')
            conn.commit()
            try:
                changes = pending_changes(conn)
                result['changes'] = changes
                result['before'] = inventory(conn, verify=True)
                conn.commit()
                if args.apply:
                    for table, check in changes:
                        declaration = next(line.strip().rstrip(',') for line in ddl(table).splitlines()
                                           if 'CONSTRAINT ' + check + ' ' in line)
                        conn.exec_driver_sql(f'ALTER TABLE {table} DROP CHECK {check}, ADD ' + declaration)
                        conn.commit()
                    validate_shapes(conn, CHANGES)
                    result['applied'] = True
                result['after'] = inventory(conn, verify=True)
                if result['before'] != result['after']:
                    raise ValueError('约束维护前后业务内容或观测版本改变')
                result['facts_preserved'] = True
            finally:
                conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf8')
        print('PASS holder ratio constraints; business facts and versions preserved')
        return result
    finally:
        engine.dispose()
        await client.aclose()
        if lock:
            lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
