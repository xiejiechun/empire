"""Explicit ST scope CHECK upgrade; preserve business rows, state and checkpoints."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.data import Envelope
from empire.core.config import load_config, project_root
from empire.core.redaction import redact
from empire.features.yuanhang_limits.contract import POOLS, SOURCE, dataset, job
from empire.features.yuanhang_limits.dataset import LimitDataset
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import RedisPlugin, create_client
from empire.plugins.infra.schema_manifest import manifest, shape, validate_shapes
from empire.plugins.pipeline.fingerprints import FingerprintCache

TABLE = 'yuanhang_limit_pool'
CHECK = 'ck_yuanhang_limit_pool_filter'


async def pending_scope(redis, stream):
    """Stopped application: unrelated owned messages stay in the original Stream."""
    targets = {(dataset(pool), job(pool)) for pool in POOLS}
    result, marker = {}, '-'
    while True:
        messages = await redis.xrange(stream, min=marker, count=256)
        if not messages:
            return result
        for _, fields in messages:
            envelope = Envelope.model_validate_json(fields['envelope'])
            if (envelope.dataset, envelope.job_key) in targets:
                raise ValueError('五池仍有待归档消息，先经原归档路径处理')
            if envelope.dataset in {key[0] for key in targets} or envelope.job_key in {key[1] for key in targets}:
                raise ValueError('五池待归档消息归属不一致，拒绝维护')
            result[envelope.dataset] = result.get(envelope.dataset, 0) + 1
        if sum(result.values()) > 100000:
            raise ValueError('待归档核查超过有界维护预算')
        marker = '(' + messages[-1][0]


def contents(conn):
    result = {}
    for table, order in ((TABLE, 'trade_date,pool_type'),
                         ('yuanhang_limit_member', 'trade_date,pool_type,unified_code'),
                         ('yuanhang_limit_reason', 'trade_date,unified_code'),
                         ('collection_state', 'namespace,project_id')):
        digest, count = hashlib.sha256(), 0
        with conn.execution_options(stream_results=True).execute(text(f'SELECT * FROM {table} ORDER BY {order}')) as rows:
            for row in rows:
                digest.update(json.dumps(list(row), default=str, separators=(',', ':')).encode() + b'\n')
                count += 1
        result[table] = dict(rows=count, sha256=digest.hexdigest())
    return result


def migrate(conn):
    expected, actual = manifest()['tables'][TABLE], shape(conn, TABLE)
    if actual == expected:
        return False
    if actual['checks'].get(CHECK) != "(filter_text='hs,gem2star')":
        raise ValueError('未知五池过滤约束，拒绝替换')
    actual['checks'][CHECK] = expected['checks'][CHECK]
    if actual != expected:
        raise ValueError('五池其他字段或约束不符，拒绝迁移')
    sql = (project_root() / 'sql/schema.sql').read_text('utf8')
    check = next(line.strip().rstrip(',') for line in sql.splitlines() if 'CONSTRAINT ' + CHECK + ' ' in line)
    conn.exec_driver_sql(f'ALTER TABLE {TABLE} DROP CHECK {CHECK}, ADD ' + check)
    conn.commit()
    validate_shapes(conn, (TABLE,))
    return True


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, redis = make_engine(cfg['mysql']), create_client(cfg['redis'])
    report = dict(applied=False)
    try:
        report['pending'] = await redis.xlen(cfg['redis']['namespace'] + ':ingest')
        report['preserved_pending'] = await pending_scope(redis, cfg['redis']['namespace'] + ':ingest')
        with engine.connect() as conn:
            if args.apply and conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                raise ValueError('另有SQL维护操作')
            try:
                report['before'] = contents(conn)
                if args.apply:
                    store = RedisPlugin(cfg['redis'])
                    store.client = redis
                    cache = FingerprintCache(store, cfg['archive'], lambda _: LimitDataset.FINGERPRINT_VERSION)
                    for pool in POOLS:
                        await cache.invalidate(LimitDataset(pool).FINGERPRINT_NAMESPACE, SOURCE)
                    report['changed'] = migrate(conn)
                    report['after'] = contents(conn)
                    if report['before'] != report['after']:
                        raise ValueError('已有业务或统一状态变化，停止交付')
                    report.update(applied=True, existing_business_unchanged=True, invalidated_pools=list(POOLS))
            finally:
                if args.apply:
                    conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
    finally:
        engine.dispose()
        await redis.aclose()
        if lock:
            lock.unlock()
        if args.report:
            with Path(args.report).open('x', encoding='utf8') as file:
                json.dump(report, file, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k not in ('before', 'after')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report')
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(arguments.config))) from None
