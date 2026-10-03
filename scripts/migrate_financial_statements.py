"""Explicit additive migration; protects existing data with count and content inventories."""
import argparse
import asyncio
import json
import re
from pathlib import Path

from mysql_recovery_inventory import TABLES, table_identity
from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.mysql_store import make_engine, validate_tables
from empire.plugins.infra.redis_store import create_client

NEW_TABLES = ('income_statement', 'balance_statement', 'cashflow_statement')


def migrate_schema(engine):
    existing = set(inspect(engine).get_table_names())
    protected = {name: order for name, order in TABLES.items() if name in existing}
    def snapshot():
        with engine.connect() as conn:
            return {name: table_identity(conn, name, order) for name, order in protected.items()}
    before = snapshot()
    sql = (Path(__file__).resolve().parents[1] / 'sql/schema.sql').read_text(encoding='utf-8')
    statements = {name: re.search(r'CREATE TABLE IF NOT EXISTS ' + name + r' \(.*?;', sql, re.S).group()
                  for name in NEW_TABLES}
    with engine.begin() as conn:
        for statement in statements.values():
            conn.execute(text(statement))
        validate_tables(conn, {name: {'source', 'market', 'code', 'report_date',
            'payload', 'content_hash', 'version_observed_at'} for name in NEW_TABLES},
            {name: ['source', 'market', 'code', 'report_date'] for name in NEW_TABLES})
    after = snapshot()
    if before != after:
        raise RuntimeError('已有业务数据核对不一致；请停止发布')
    return {'created': sorted(set(NEW_TABLES) - existing), 'before': before, 'after': after,
            'existing_data_unchanged': True}


async def run(config):
    cfg = load_config(config)
    lock = acquire_instance_lock()
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    try:
        if await client.xlen(cfg['redis'].get('namespace', 'empire') + ':ingest'):
            raise RuntimeError('待归档队列非空；结构维护拒绝执行')
        report = migrate_schema(engine)
        path = Path(__file__).resolve().parents[1] / 'build/financial-migration.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        await client.aclose()
        engine.dispose()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.config))
    except Exception as exc:
        print(redact(exc))
        raise SystemExit(1) from None
