"""Explicit additive five-table maintenance; no application-startup DDL."""
import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config, project_root
from empire.core.redaction import redact
from empire.features.performance.contract import KINDS
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import shape


def maintain(engine, *, apply=False):
    root = project_root()
    sql = (root / 'sql/schema.sql').read_text('utf8')
    contract = json.loads((root / 'sql/schema-contract.json').read_text('utf8'))
    targets = {item[1] for item in KINDS.values()}
    report = dict(checked_at=datetime.now(UTC).isoformat(), mode='apply' if apply else 'preflight',
                  ddl_sha256=hashlib.sha256((root / 'sql/schema.sql').read_bytes()).hexdigest(), created=[])
    with engine.connect() as conn:
        existing = set(inspect(conn).get_table_names())
        kept = sorted(existing - targets)
        counts = {table: conn.execute(text(f'SELECT COUNT(*) FROM `{table}`')).scalar_one() for table in kept}
        for table in sorted(targets & existing):
            if shape(conn, table) != contract['tables'][table]:
                raise ValueError(f'目标表{table}已存在但契约不同；拒绝覆盖')
        missing = sorted(targets - existing)
        report.update(missing=missing, preserved_counts_before=counts)
        if apply:
            for table in missing:
                statement = re.search(r'CREATE TABLE IF NOT EXISTS ' + table + r'\s*\([\s\S]*?;', sql)[0]
                conn.exec_driver_sql(statement)
                conn.commit()  # MySQL DDL implicitly commits; report never claims rollback.
                report['created'].append(table)
            for table in sorted(targets):
                if shape(conn, table) != contract['tables'][table]:
                    raise ValueError(f'目标表{table}结构核验失败')
            after = {table: conn.execute(text(f'SELECT COUNT(*) FROM `{table}`')).scalar_one() for table in kept}
            if counts != after:
                raise ValueError('原有表行数发生变化，不能确认维护完成')
            report['preserved_counts_after'] = after
            report['target_counts'] = {table: conn.execute(text(f'SELECT COUNT(*) FROM `{table}`')).scalar_one() for table in sorted(targets)}
    report['passed'] = True
    return report


async def run(args, cfg):
    engine = make_engine(cfg['mysql'])
    lock, client = None, None
    try:
        if args.apply:
            lock = acquire_instance_lock()
            client = create_client(cfg['redis'])
            if await client.xlen(cfg['redis'].get('namespace', 'empire:dev') + ':ingest'):
                raise ValueError('待归档队列非空，拒绝结构维护；先通过正常归档清队')
        report = maintain(engine, apply=args.apply)
        if args.output:
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf8')
        print(json.dumps(report, ensure_ascii=False))
        return report
    finally:
        if client:
            await client.aclose()
        engine.dispose()
        if lock:
            lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--config')
    parser.add_argument('--output')
    options = parser.parse_args()
    configuration = load_config(options.config)
    try:
        asyncio.run(run(options, configuration))
    except Exception as exc:
        raise SystemExit(redact(exc, configuration)) from None
