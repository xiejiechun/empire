"""Explicit stopped-application business schema maintenance; never invoked at startup."""
import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from empire.contracts.business_schema import FIXED_SOURCES, TABLES
from empire.core.config import load_config
from empire.core.redaction import Redactor
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client


def inspect_database(engine, redactor=None):
    redactor = redactor or Redactor()
    report = {'tables': {}, 'failures': [], 'read_only': True}
    with engine.connect() as conn:
        conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        try:
            report['version'] = str(conn.execute(text('SELECT VERSION()')).scalar_one())
            metadata = inspect(conn)
            existing = set(metadata.get_table_names())
            for table in TABLES:
                if table not in existing:
                    report['failures'].append(f'缺少已登记业务表 {table}')
                    continue
                columns = {v['name'] for v in metadata.get_columns(table)}
                entry = {'ddl': conn.exec_driver_sql(f'SHOW CREATE TABLE `{table}`').first()[1],
                         'primary_key': metadata.get_pk_constraint(table)['constrained_columns'],
                         'indexes': metadata.get_indexes(table)}
                report['tables'][table] = entry
                if table in FIXED_SOURCES:
                    if 'source' not in columns:
                        entry['source_storage'] = 'dataset-declaration'
                        continue
                    # A leading source index permits a distinct-prefix probe, without a body scan.
                    sources = conn.execute(text(f'SELECT /*+ MAX_EXECUTION_TIME(15000) */ DISTINCT source '
                                                f'FROM `{table}`')).scalars().all()
                    entry['sources'] = redactor.value(sources)
                    extras = [s for s in sources if s != FIXED_SOURCES[table]]
                    for source in extras:
                        count = conn.execute(text(f'SELECT /*+ MAX_EXECUTION_TIME(15000) */ COUNT(*) '
                            f'FROM `{table}` WHERE source=:source'), {'source': source}).scalar_one()
                        report['failures'].append(f'{table} 额外来源 {redactor.text(source)}：{count} 行')
            report['state_sizes'] = [dict(r) for r in conn.execute(text(
                'SELECT project_id,JSON_STORAGE_SIZE(payload) AS bytes FROM collection_state '
                "WHERE project_id IN ('ths-income','ths-balance','ths-cashflow')")).mappings()]
        finally:
            conn.rollback()
    report['passed'] = not report['failures']
    report['migration_ready'] = False
    report['limitations'] = [
        'preflight 为只读结构/来源检查，不能单独作为完整迁移准入证明',
        '未核对全量业务键/正文/版本集合、目标键冲突、来源日期及覆盖证明',
        '结构迁移使用 migrate/resume/verify/rollback；仅在正常停机、队列为空并通过全量核验后切换',
    ]
    return report


async def inspect_queue(settings):
    client = create_client(settings)
    prefix = settings.get('namespace', 'empire')
    try:
        # Redis may continue changing while Empire runs. This is an observation, not a stop-write gate.
        return {'stream_length': await client.xlen(prefix + ':ingest'),
                'snapshot_atomic_with_sql': False, 'drained_for_migration': False}
    finally:
        await client.aclose()


async def run(args):
    cfg = load_config(args.config)
    if args.command != 'preflight':
        return await maintain(args, cfg)
    redactor = Redactor.from_config(cfg)
    report = {'captured_at': datetime.now(UTC).isoformat(), 'command': 'preflight',
              'target': {k: cfg['mysql'].get(k) for k in ('host', 'port', 'database')},
              'production_changed': False, 'migration_ready': False}
    engine = make_engine(cfg['mysql'])
    try:
        try:
            report['sql'] = inspect_database(engine, redactor)
        except Exception as exc:
            report['sql'] = {'passed': False, 'error': redactor.text(exc), 'read_only': True}
        try:
            report['redis'] = await inspect_queue(cfg['redis'])
        except Exception as exc:
            report['redis'] = {'error': redactor.text(exc)}
        path = Path(args.report).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(redactor.value(report), ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(json.dumps({'report': str(path), 'source_check_passed': report['sql'].get('passed', False),
                          'migration_ready': False, 'production_changed': False}, ensure_ascii=False))
        return 0 if report['sql'].get('passed') else 1
    finally:
        engine.dispose()


async def maintain(args, cfg):
    from PySide6.QtCore import QCoreApplication

    from empire.__main__ import acquire_instance_lock
    from scripts.business_migration_engine import migrate, rollback, verify
    app = QCoreApplication.instance() or QCoreApplication([])
    lock = acquire_instance_lock()
    engine = make_engine(cfg['mysql'], read_timeout=3600)
    try:
        queue = await inspect_queue(cfg['redis'])
        if queue['stream_length']:
            raise RuntimeError('待归档业务未排空，必须经原归档路径成功处理后重试')
        path = Path(args.journal).resolve()
        if args.command == 'status':
            result = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'phase': 'not_started'}
        elif args.command in ('migrate', 'resume'):
            result = migrate(engine, path)
        elif args.command == 'verify':
            result = verify(engine, path)
        else:
            result = rollback(engine, path)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    finally:
        engine.dispose()
        lock.unlock()
        del app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['preflight', 'migrate', 'verify', 'status', 'resume', 'rollback'])
    parser.add_argument('--journal', default='build/mysql-upgrade-final/migration.json')
    parser.add_argument('--config', help='显式配置覆盖；默认项目根目录 config.toml')
    parser.add_argument('--report', default='build/mysql-upgrade-20261003/preflight.json')
    try:
        raise SystemExit(asyncio.run(run(parser.parse_args())))
    except Exception as exc:
        print(Redactor().text(exc))
        raise SystemExit(1) from None
