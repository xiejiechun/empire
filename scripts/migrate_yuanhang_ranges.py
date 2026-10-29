"""Explicit price coverage-state migration; no DDL or price/financial fact writes."""
import argparse
import asyncio
import copy
import json
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.features.yuanhang.contract import PRICE_PROJECT, SOURCE
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.sources.yuanhang_payload import CONTRACT, digest
from empire.sources.yuanhang_ranges import expand_versions


def upgrade(previous, heads):
    result = copy.deepcopy(previous)
    units = result.setdefault('units', {})
    grouped = {}
    for head in heads:
        grouped.setdefault(head['unified_code'], []).append(head)
    if set(units) - set(grouped):
        raise ValueError('Price state without annual proof; migration refused')
    for code, years in grouped.items():
        old = units.get(code)
        if not old:
            raise ValueError('Annual proof without archived version; migration refused')
        if 'price_ranges' in old:
            for year, segments in old['price_ranges'].items():
                expand_versions(segments, int(year))
            continue
        versions = old.get('versions', {})
        if {str(h['quote_year']) for h in years} != set(versions):
            raise ValueError('Annual proof and archived versions differ')
        ranges, checked = {}, {}
        for h in years:
            year = str(h['quote_year'])
            if h['contract_version'] != CONTRACT or h['source_count'] != h['row_count']:
                raise ValueError('Unsupported annual proof contract')
            observed = datetime.fromisoformat(versions[year])
            if observed.tzinfo is None:
                raise ValueError('Unknown archived version timezone')
            version = observed.astimezone(UTC).isoformat(timespec='microseconds')
            cutoff = min(str(old['verified_through']), year + '-12-31')
            if (date.fromisoformat(cutoff).year != int(year) or cutoff < year + '-01-01'
                    or cutoff > datetime.now(CHINA).date().isoformat()
                    or cutoff < str(h['verified_through'])):
                raise ValueError('Invalid migrated coverage cutoff')
            ranges[year] = [[year + '-01-01', cutoff, version]]
            checked[year] = version
        units[code] = dict(price_ranges=ranges, full_checked=checked, native_market=old['native_market'])
    result['contract_version'] = 6
    return result


async def queue_empty(cfg):
    redis = create_client(cfg['redis'])
    try:
        if await redis.xlen(cfg['redis']['namespace'] + ':ingest'):
            raise ValueError('Pending archive queue is not empty')
    finally:
        await redis.aclose()


def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock()
    engine = make_engine(cfg['mysql'])
    try:
        asyncio.run(queue_empty(cfg))
        with engine.begin() as conn:
            params = dict(ns=cfg['redis']['namespace'], project=PRICE_PROJECT)
            row = conn.execute(text('SELECT source,payload FROM collection_state WHERE namespace=:ns '
                                    'AND project_id=:project FOR UPDATE'), params).mappings().one()
            if row['source'] != SOURCE:
                raise ValueError('Unexpected price source')
            previous = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
            heads = [dict(r) for r in conn.execute(text('SELECT * FROM yuanhang_price_year '
                'ORDER BY unified_code,quote_year LIMIT 2250001')).mappings()]
            if len(heads) > 2250000:
                raise ValueError('Annual proof count exceeds declared bounds')
            before = digest(json.loads(json.dumps(heads, default=str)))
            count = conn.execute(text('SELECT COUNT(*) FROM yuanhang_daily_price')).scalar_one()
            new = upgrade(previous, heads)
            # Preserve metadata for explicit rollback; never back up success bodies.
            backup = Path(args.backup)
            if args.apply and new != previous:
                with backup.open('x', encoding='utf-8') as out:
                    json.dump(previous, out, ensure_ascii=False)
                conn.execute(text('UPDATE collection_state SET payload=:payload WHERE namespace=:ns '
                                  'AND project_id=:project'), {**params, 'payload': json.dumps(new)})
            readback = conn.execute(text('SELECT payload FROM collection_state WHERE namespace=:ns '
                                        'AND project_id=:project'), params).scalar_one()
            if args.apply and json.loads(readback) != new:
                raise ValueError('Migrated state readback mismatch')
            after_heads = [dict(r) for r in conn.execute(text('SELECT * FROM yuanhang_price_year '
                'ORDER BY unified_code,quote_year LIMIT 2250001')).mappings()]
            if before != digest(json.loads(json.dumps(after_heads, default=str))):
                raise ValueError('Annual business proof changed during state migration')
            if count != conn.execute(text('SELECT COUNT(*) FROM yuanhang_daily_price')).scalar_one():
                raise ValueError('Price fact count changed during state migration')
            report = dict(applied=args.apply, changed=new != previous, prices=count, annual_proofs=len(heads),
                          proof_digest=before, securities=len(new['units']),
                          serialized_state_bytes=len(json.dumps(new).encode()), business_dml=0)
        print(json.dumps(report))
    finally:
        engine.dispose()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
