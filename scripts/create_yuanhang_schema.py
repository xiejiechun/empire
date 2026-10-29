"""Explicit additive native history tables; Empire closed and archive queue empty."""
import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.yuanhang.contract import TABLE_COLUMNS
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import manifest, normalize_check, shape, validate_shapes
from scripts.create_name_change_schema import ddl, inventory
from scripts.yuanhang_financial_schema import financial_revision

OLD_PRICE_CHECK = ('low > 0 AND low <= open AND low <= close AND high >= open AND high >= close '
                   'AND volume_shares >= 0 AND (amount_yuan IS NULL OR amount_yuan >= 0)')


def nullable_volume_revision(conn):
    """Only the exact prior nonnullable-volume shape may change; preserve facts."""
    table = 'yuanhang_daily_price'
    expected, actual = manifest()['tables'][table], shape(conn, table)
    if actual == expected:
        return False
    old = deepcopy(expected)
    old['columns']['volume_shares']['nullable'] = False
    if actual != old:
        raise RuntimeError('原日线表不是已知成交量非空结构，拒绝修改')
    conn.exec_driver_sql('ALTER TABLE yuanhang_daily_price MODIFY volume_shares DECIMAL(28,10) NULL')
    conn.commit()
    validate_shapes(conn, [table])
    return True


def quality_revision(conn):
    """Only the exact former strict CHECK may become source-preserving positive prices."""
    table = 'yuanhang_daily_price'
    expected = manifest()['tables'][table]
    actual = shape(conn, table)
    if actual == expected:
        return False
    old = {**expected, 'checks': {'ck_yuanhang_price_values': normalize_check(OLD_PRICE_CHECK)}}
    # MySQL reports parenthesized expressions; compare their operators/identifiers.
    def clean(s):
        return s.replace('(', '').replace(')', '')
    if ({k: v for k, v in actual.items() if k != 'checks'} != {k: v for k, v in old.items() if k != 'checks'}
            or set(actual['checks']) != set(old['checks'])
            or any(clean(actual['checks'][k]) != clean(v) for k, v in old['checks'].items())):
        raise RuntimeError('原日线表不是已知严格OHLC结构，拒绝修改')
    check = ddl(table).split('CONSTRAINT ck_yuanhang_price_values ', 1)[1].rsplit(')', 1)[0].strip()
    conn.exec_driver_sql('ALTER TABLE yuanhang_daily_price DROP CHECK ck_yuanhang_price_values, '
                        'ADD CONSTRAINT ck_yuanhang_price_values ' + check)
    conn.commit()
    validate_shapes(conn, [table])
    return True


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, redis = make_engine(cfg['mysql']), create_client(cfg['redis'])
    try:
        pending = await redis.xlen(cfg['redis'].get('namespace', 'empire') + ':ingest')
        with engine.connect() as conn:
            targets = tuple(TABLE_COLUMNS)
            database, server = conn.execute(text('SELECT DATABASE(),@@server_uuid')).one()
            data_directory = conn.execute(text('SELECT @@datadir')).scalar_one()
            free = shutil.disk_usage(data_directory).free if Path(data_directory).exists() else None
            report = dict(applied=False, pending=pending, tables=targets, database=database,
                server_uuid=server, mysql_disk_free_bytes=free,
                exists={t: t in inspect(conn).get_table_names() for t in targets},
                ddl_sha256={t: hashlib.sha256(ddl(t).encode()).hexdigest() for t in targets})
            if args.apply:
                if pending:
                    raise RuntimeError('待归档消息未清零，拒绝建表')
                if free is not None and free < 10 * 1024**3:
                    raise RuntimeError('MySQL磁盘剩余不足10GiB，拒绝初始化历史表')
                if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                    raise RuntimeError('已有数据库维护，拒绝并发')
                try:
                    existing = [t for t in targets if report['exists'][t]]
                    validate_shapes(conn, [t for t in existing if not (
                        ((args.source_quality or args.nullable_volume) and t == 'yuanhang_daily_price')
                        or (args.financial_history and t in ('yuanhang_corporate_action', 'yuanhang_capital')))])
                    before = inventory(conn, added_table=None)
                    report['before'] = before
                    report['nullable_volume_revision'] = nullable_volume_revision(conn) if args.nullable_volume else False
                    report['source_quality_revision'] = quality_revision(conn) if args.source_quality else False
                    report['financial_revision'] = financial_revision(conn) if args.financial_history else dict(changed=[])
                    for table in targets:
                        conn.exec_driver_sql(ddl(table))
                        conn.commit()
                    validate_shapes(conn, targets)
                    after = inventory(conn, added_table=None)
                    report['after'] = after
                    compared = {k: v for k, v in after.items() if k in before}
                    if report['source_quality_revision'] or report['nullable_volume_revision']:
                        compared['yuanhang_daily_price'] = {**compared['yuanhang_daily_price'],
                            'ddl_hash': before['yuanhang_daily_price']['ddl_hash']}
                    for table in report['financial_revision']['changed']:
                        compared[table] = {**compared[table], 'ddl_hash': before[table]['ddl_hash']}
                    if before != compared:
                        raise RuntimeError('原业务数量、结构或统一状态变化，停止交付')
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
    parser.add_argument('--source-quality', action='store_true', help='仅将已知旧严格OHLC约束改为保留正数来源原值')
    parser.add_argument('--nullable-volume', action='store_true', help='仅将已知旧成交量非空字段改为保留源NULL')
    parser.add_argument('--financial-history', action='store_true', help='显式迁移同日多权息、纯缩股及未知流通股')
    parser.add_argument('--report')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
