"""Explicit additive current-industry schema maintenance; never run at startup."""
import argparse
import asyncio
import json
import re
from pathlib import Path

from mysql_recovery_inventory import TABLES as INVENTORY
from mysql_recovery_inventory import table_identity
from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.datasets.industries import KEYS, TABLES
from empire.plugins.infra.mysql_store import make_engine, validate_tables
from empire.plugins.infra.redis_store import create_client


def migrate_schema(engine):
    existing = set(inspect(engine).get_table_names())
    def snapshot():
        with engine.connect() as conn:
            return {name: table_identity(conn, name, order)
                    for name, order in INVENTORY.items() if name in existing}
    before = snapshot()
    schema = (Path(__file__).resolve().parents[1] / 'sql/schema.sql').read_text(encoding='utf-8')
    with engine.begin() as conn:
        for name in TABLES:
            statement = re.search(r'CREATE TABLE IF NOT EXISTS ' + name + r' \(.*?;', schema, re.S).group()
            conn.execute(text(statement))
        validate_tables(conn, TABLES, KEYS)
    after = snapshot()
    if before != after:
        raise RuntimeError('行业结构维护前后既有业务内容不一致，请停止发布')
    return dict(created=sorted(set(TABLES) - existing), before=before, after=after,
                existing_data_unchanged=True)


async def run(config):
    cfg = load_config(config)
    lock = acquire_instance_lock()
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    try:
        if await client.xlen(cfg['redis'].get('namespace', 'empire') + ':ingest'):
            raise RuntimeError('待归档队列非空，拒绝结构维护')
        report = migrate_schema(engine)
        path = Path(__file__).resolve().parents[1] / 'build/industry-migration.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
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
