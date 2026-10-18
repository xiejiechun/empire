"""Explicit constraint upgrade for source tenth-place ties; preserve business."""
import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from create_name_change_schema import ddl
from migrate_holder_task import business_inventory
from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.data import Envelope
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.datasets.holders import HolderDataset
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import validate_shapes
from empire.plugins.pipeline.fingerprints import FingerprintCache


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    prefix = cfg['redis'].get('namespace', 'empire')
    report = dict(checked_at=datetime.now(UTC).isoformat(), applied=False)
    try:
        report['pending'] = await client.xlen(prefix + ':ingest')
        if args.apply and report['pending']:
            messages = await client.xrange(prefix + ':ingest', count=101)
            if len(messages) != report['pending'] or len(messages) > 100:
                raise ValueError('待归档超出本次可核实范围')
            for _, fields in messages:
                envelope = Envelope.model_validate_json(fields['envelope'])
                if envelope.dataset != 'holders.reports' or envelope.job_key != 'ths-holders-v1':
                    raise ValueError('待归档包含其他任务，拒绝结构维护')
                HolderDataset().normalize(envelope)
            report['retained_valid_holder_messages'] = len(messages)
        with engine.connect() as conn:
            if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                raise ValueError('结构维护锁忙')
            try:
                report['before'] = business_inventory(conn)
                try:
                    validate_shapes(conn, ['holder_report', 'holder_member'])
                    report['already_current'] = True
                except RuntimeError:
                    old = conn.execute(text("SELECT CHECK_CLAUSE FROM information_schema.check_constraints WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_NAME='ck_holder_counts'")).scalar_one()
                    normalized = ''.join(old.lower().replace('`', '').split()).replace('(', '').replace(')', '')
                    if normalized != 'member_countbetween1and10andexit_countbetween0and20':
                        raise ValueError('未知旧持有人约束，拒绝替换') from None
                    report['already_current'] = False
                    if args.apply:
                        contract = next(line.strip().rstrip(',') for line in ddl('holder_report').splitlines() if 'CONSTRAINT ck_holder_counts ' in line)
                        conn.exec_driver_sql('ALTER TABLE holder_report DROP CHECK ck_holder_counts, ADD ' + contract)
                        conn.commit()
                        validate_shapes(conn, ['holder_report', 'holder_member'])
                report['after'] = business_inventory(conn)
                if report['before'] != report['after']:
                    raise ValueError('约束维护改变业务内容')
                if args.apply:
                    from types import SimpleNamespace
                    archive_cfg = cfg.get('archive', {})
                    cache = FingerprintCache(SimpleNamespace(client=client, prefix=prefix), archive_cfg,
                                             lambda _: HolderDataset.FINGERPRINT_VERSION)
                    await cache.invalidate(HolderDataset().FINGERPRINT_NAMESPACE, 'ths')
                    report['applied'] = True
            finally:
                conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf8')
        print('PASS holder ties constraint maintenance; business preserved')
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
