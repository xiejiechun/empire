"""Explicit additive listing maintenance, using existing locked schema workflow."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from create_name_change_schema import run
from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.listings import JOB, TABLE
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import validate_shapes
from empire.plugins.pipeline.fingerprints import FingerprintCache
from empire.plugins.pipeline.ingest import IngestPlugin


async def upgrade_dates(args):
    """Retain rows; change only two CHECKs and rebuild contract2 proofs by collection."""
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, client = make_engine(cfg['mysql']), create_client(cfg['redis'])
    namespace = cfg['redis']['namespace']
    report = dict(applied=False, project='ths-listings')
    def content(conn):
        rows = conn.exec_driver_sql('SELECT * FROM stock_listing ORDER BY unified_code LIMIT 15001').all()
        if len(rows) > 15000:
            raise ValueError('上市资料超过维护边界')
        return dict(count=len(rows), digest=hashlib.sha256(json.dumps([list(r) for r in rows], default=str).encode()).hexdigest())
    try:
        report['pending'] = await client.xlen(namespace + ':ingest')
        with engine.connect() as conn:
            report['before'] = content(conn)
            if args.apply:
                if report['pending']:
                    raise RuntimeError('待归档必须清零，不能修改上市约束')
                if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                    raise RuntimeError('另有SQL维护操作')
                try:
                    if args.upgrade_history_limit:
                        conn.exec_driver_sql("ALTER TABLE stock_listing DROP CHECK ck_listing_history, "
                            "ADD CONSTRAINT ck_listing_history CHECK (history IS NULL OR OCTET_LENGTH(history) <= 262144)")
                    else:
                        conn.exec_driver_sql("ALTER TABLE stock_listing DROP CHECK ck_listing_dates, DROP CHECK ck_listing_contract, "
                        "ADD CONSTRAINT ck_listing_dates CHECK (listing_date >= '1900-01-01' AND (establish_date IS NULL OR establish_date >= '1900-01-01')), "
                        "ADD CONSTRAINT ck_listing_contract CHECK (contract_version IN (1, 2))")
                    conn.commit()
                    validate_shapes(conn, [TABLE])
                    report['after'] = content(conn)
                    if report['before'] != report['after']:
                        raise RuntimeError('原有上市内容变化，停止交付')
                    if args.upgrade_history_limit:
                        report.update(applied=True, original_content_preserved=True, checkpoint_preserved=True,
                                      history_max_bytes=262144, coverage='Existing contract2 proofs unchanged; retry retained failed position')
                        return write_report(args, report)
                    store = SimpleNamespace(client=client, prefix=namespace)
                    cache = FingerprintCache(store, cfg.get('archive', {}), lambda _: None)
                    await cache.invalidate('ths_listings_v1', 'ths')
                    await cache.invalidate('ths_listings_v2', 'ths')
                    ingest = IngestPlugin({})
                    ingest.redis = store
                    state = await ingest.checkpoint(JOB)
                    await ingest.advance_checkpoint(job_key=JOB, expected_revision=state['revision'], cursor={})
                    report.update(applied=True, original_content_preserved=True, coverage='contract1 remains stored; contract2 full refresh required')
                finally:
                    conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
        write_report(args, report)
    finally:
        engine.dispose()
        await client.aclose()
        if lock:
            lock.unlock()

def write_report(args, report):
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report')
    upgrades = parser.add_mutually_exclusive_group()
    upgrades.add_argument('--upgrade-date-contract', action='store_true')
    upgrades.add_argument('--upgrade-history-limit', action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(upgrade_dates(args) if args.upgrade_date_contract or args.upgrade_history_limit else run(args, table=TABLE))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
