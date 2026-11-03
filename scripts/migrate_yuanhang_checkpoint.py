"""Explicit conversion of old pool-plan checkpoints; no business/queue writes."""
import argparse
import asyncio
import copy
import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.yuanhang.contract import (
    FINANCIAL_JOB,
    FINANCIAL_PROJECT,
    PRICE_JOB,
    PRICE_PROJECT,
    SOURCE,
)
from empire.plugins.infra.collection_state import CollectionState
from empire.plugins.infra.mysql_store import MySQLPlugin, make_engine
from empire.plugins.infra.redis_store import create_client
from empire.sources.yuanhang_history import security_identity
from empire.sources.yuanhang_payload import digest


def upgrade(cursor, codes):
    result = copy.deepcopy(cursor)
    if not {'plans', 'work_codes'} & cursor.keys():
        return result
    if cursor.get('scope_hash') != digest(codes):
        raise ValueError('Checkpoint stock scope differs; conversion refused')
    work, plans, index = cursor['work_codes'], cursor['plans'], cursor['next_index']
    if (work != sorted(set(work)) or set(work) - set(codes) or set(plans) != set(work)
            or type(index) is not int or not 0 <= index <= len(work)):
        raise ValueError('Invalid old work plan; conversion refused')
    position = len(codes) if index == len(work) else codes.index(work[index])
    if cursor['phase'] in ('complete', 'awaiting_archive') and index != len(work):
        raise ValueError('Incomplete old work cannot be marked complete')
    if cursor.get('snapshot_hash') or cursor.get('next_year', 1900) != 1900:
        if index == len(work):
            raise ValueError('Partial security outside old work plan')
        result['current_plan'] = plans[work[index]]
    result.update(next_index=position, skipped_units=position-index,
                  force_full=bool(plans) and all(p.get('reason') == 'explicit_full_verification'
                                                for p in plans.values()))
    del result['plans'], result['work_codes']
    if len(json.dumps(result, ensure_ascii=False).encode()) > 16384:
        raise ValueError('Converted checkpoint still exceeds shared bound')
    return result


def rebind_scope(cursor, codes, job, previous_codes=None):
    """Map only a cryptographically verified completed prefix to the new pool."""
    if (job not in (PRICE_JOB, FINANCIAL_JOB) or cursor.get('contract') != 2
            or cursor.get('phase') != 'collecting' or cursor.get('maintenance_scope') != 'recent'
            or cursor.get('force_full') is not False
            or 'current_plan' in cursor or cursor.get('snapshot_hash')
            or cursor.get('next_year') != 1900 or {'plans', 'work_codes', 'round_end', 'replan_recent'} & cursor.keys()):
        raise ValueError('Scope recovery requires a recent round at a complete-security boundary')
    if not isinstance(codes, list) or not 1 <= len(codes) <= 15000 or codes != sorted(set(codes)):
        raise ValueError('Invalid current stock pool')
    for code in codes:
        security_identity(code)
    for name in ('pages', 'collected', 'next_index', 'skipped_units'):
        if type(cursor.get(name)) is not int or cursor[name] < 0:
            raise ValueError('Invalid checkpoint counters')
    if (not isinstance(cursor.get('batch_id'), str) or not 1 <= len(cursor['batch_id']) <= 128
            or not isinstance(cursor.get('scope_hash'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', cursor['scope_hash'])
            or not isinstance(cursor.get('through'), str)
            or date.fromisoformat(cursor['through']).isoformat() != cursor['through']
            or not 0 <= cursor['skipped_units'] <= cursor['next_index'] <= 15000):
        raise ValueError('Missing checkpoint identity or cutoff')
    result = copy.deepcopy(cursor)
    if result['scope_hash'] != digest(codes):
        if (not isinstance(previous_codes, list) or not 1 <= len(previous_codes) <= 15000
                or previous_codes != sorted(set(previous_codes))
                or digest(previous_codes) != cursor['scope_hash']
                or cursor['next_index'] > len(previous_codes)):
            raise ValueError('Previous stock pool does not match the checkpoint digest')
        for code in previous_codes:
            security_identity(code)
        completed = set(previous_codes[:cursor['next_index']])
        index = next((i for i, code in enumerate(codes) if code not in completed), len(codes))
        if completed.intersection(codes[index:]):
            raise ValueError('New securities interrupt the completed prefix; refusing redundant replay')
        result.update(scope_hash=digest(codes), next_index=index, skipped_units=0)
    return result


async def migrate(cfg, args, codes):
    client = create_client(cfg['redis'])
    key = cfg['redis']['namespace'] + ':checkpoint:' + args.job
    mysql = None
    try:
        if await client.xlen(cfg['redis']['namespace'] + ':ingest'):
            raise ValueError('Pending archive queue is not empty')
        old = await client.hgetall(key)
        cursor = json.loads(old.get('cursor', '{}'))
        rebinding = getattr(args, 'rebind_scope', False)
        previous = None
        if rebinding:
            path = Path(args.previous_scope)
            if path.stat().st_size > 512 * 1024:
                raise ValueError('Previous stock pool file exceeds bound')
            previous = json.loads(path.read_text(encoding='utf-8'))
        new = rebind_scope(cursor, codes, args.job, previous) if rebinding else upgrade(cursor, codes)
        if rebinding and new != cursor and cursor['pages']:
            mysql = MySQLPlugin(cfg['mysql'])
            await mysql.start(None)
            redis = SimpleNamespace(client=client, prefix=cfg['redis']['namespace'],
                                    stream=cfg['redis']['namespace'] + ':ingest')
            progress = await CollectionState(mysql, redis.prefix).page_status(
                redis, SOURCE, args.job, PRICE_PROJECT if args.job == PRICE_JOB else FINANCIAL_PROJECT,
                cursor['batch_id'], cursor['pages'])
            if not progress or progress.get('status') != 'complete':
                raise ValueError('Queued pages are not confirmed archived; scope recovery refused')
        if args.apply and new != cursor:
            with Path(args.backup).open('x', encoding='utf-8') as file:
                json.dump(dict(job=args.job, state=old, current_codes=codes, previous_codes=previous),
                          file, ensure_ascii=False, indent=2)
            changed = await client.eval("""
                if redis.call('HGET',KEYS[1],'cursor') ~= ARGV[1]
                    or redis.call('HGET',KEYS[1],'revision') ~= ARGV[2]
                    or redis.call('XLEN',KEYS[2]) ~= 0 then return 0 end
                redis.call('HSET',KEYS[1],'cursor',ARGV[3],'revision',tonumber(ARGV[2])+1)
                return 1
            """, 2, key, cfg['redis']['namespace'] + ':ingest', old['cursor'], old['revision'],
                json.dumps(new, ensure_ascii=False))
            if changed != 1:
                raise ValueError('Checkpoint or queue changed; conversion refused')
        readback = await client.hgetall(key)
        if args.apply and json.loads(readback.get('cursor', '{}')) != new:
            raise ValueError('Converted checkpoint readback mismatch')
        return dict(job=args.job, applied=args.apply, changed=cursor != new,
                    rebind_scope=rebinding, scope_before=cursor.get('scope_hash'),
                    scope_after=new.get('scope_hash'), current_stock_count=len(codes),
                    before_bytes=len(old.get('cursor', '').encode()),
                    after_bytes=len(json.dumps(new, ensure_ascii=False).encode()),
                    before_index=cursor.get('next_index'), after_index=new.get('next_index'),
                    batch_preserved=cursor.get('batch_id') == new.get('batch_id'), pending=0, business_dml=0)
    finally:
        if mysql is not None:
            await mysql.stop()
        await client.aclose()


def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock()
    engine = make_engine(cfg['mysql'])
    try:
        with engine.connect() as conn:
            codes = list(conn.execute(text('SELECT unified_code FROM stock ORDER BY unified_code LIMIT 15001')).scalars())
            if not 1 <= len(codes) <= 15000:
                raise ValueError('Stock pool empty or exceeds bound')
        print(json.dumps(asyncio.run(migrate(cfg, args, codes))))
    finally:
        engine.dispose()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--job', choices=(PRICE_JOB, FINANCIAL_JOB), default=PRICE_JOB)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rebind-scope', action='store_true',
                        help='Map a verified completed prefix to the current stock pool')
    parser.add_argument('--previous-scope', help='JSON list matching the old checkpoint stock-pool digest')
    parser.add_argument('--backup', required=True)
    args = parser.parse_args()
    if args.rebind_scope != bool(args.previous_scope):
        parser.error('--rebind-scope and --previous-scope must be used together')
    try:
        run(args)
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
