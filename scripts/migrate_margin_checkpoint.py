"""Explicit margin scope recovery at a verified complete-security boundary."""
import argparse
import asyncio
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.margin.contract import CONTRACT, JOB, PROJECT, day, digest, security
from empire.plugins.infra.collection_state import CollectionState
from empire.plugins.infra.mysql_store import MySQLPlugin, make_engine
from empire.plugins.infra.redis_store import create_client


def validate_pool(codes):
    if (not isinstance(codes, list) or not 1 <= len(codes) <= 30000
            or any(not isinstance(code, str) for code in codes) or codes != sorted(set(codes))):
        raise ValueError('融资融券证券名单无效')
    for code in codes:
        security(code)


def rebind_scope(cursor, codes, previous_codes):
    validate_pool(codes)
    validate_pool(previous_codes)
    fields = {'phase', 'contract', 'scope_hash', 'batch_id', 'index', 'pages', 'collected', 'securities', 'through'}
    if (set(cursor) != fields or cursor['contract'] != CONTRACT or cursor['phase'] != 'fetch'
            or any(type(cursor[k]) is not int or cursor[k] < 0
                   for k in ('index', 'pages', 'collected', 'securities'))
            or not 0 <= cursor['index'] < cursor['securities'] <= 30000
            or cursor['pages'] < cursor['index'] or cursor['pages'] > 30000
            or not isinstance(cursor['batch_id'], str) or not re.fullmatch(r'[0-9a-f]{32}', cursor['batch_id'])):
        raise ValueError('仅支持完整证券边界的未完成融资融券断点')
    day(cursor['through'])
    if digest(codes) == cursor['scope_hash'] and cursor['securities'] == len(codes):
        return copy.deepcopy(cursor)
    if cursor['scope_hash'] != digest(previous_codes) or cursor['securities'] != len(previous_codes):
        raise ValueError('旧证券名单与融资融券断点不匹配')
    result = copy.deepcopy(cursor)
    completed = set(previous_codes[:cursor['index']])
    index = next((i for i, code in enumerate(codes) if code not in completed), len(codes))
    if completed.intersection(codes[index:]):
        raise ValueError('新增证券穿插已完成前缀，拒绝跳过或重复下载')
    result.update(scope_hash=digest(codes), securities=len(codes), index=index)
    if index == len(codes):
        result['phase'] = 'awaiting_archive'
    return result


async def migrate(cfg, args, codes):
    client = create_client(cfg['redis'])
    key, stream = cfg['redis']['namespace'] + ':checkpoint:' + JOB, cfg['redis']['namespace'] + ':ingest'
    mysql = None
    try:
        if await client.xlen(stream):
            raise ValueError('待归档队列非空，拒绝范围维护')
        path = Path(args.previous_scope)
        if path.stat().st_size > 512 * 1024:
            raise ValueError('旧证券名单文件超限')
        previous = json.loads(path.read_text(encoding='utf8'))
        old = await client.hgetall(key)
        cursor = json.loads(old.get('cursor', '{}'))
        new = rebind_scope(cursor, codes, previous)
        if new != cursor and cursor['pages']:
            mysql = MySQLPlugin(cfg['mysql'])
            await mysql.start(None)
            redis = SimpleNamespace(client=client, prefix=cfg['redis']['namespace'], stream=stream)
            progress = await CollectionState(mysql, redis.prefix).page_status(
                redis, 'tdx', JOB, PROJECT, cursor['batch_id'], cursor['pages'])
            if not progress or progress.get('status') != 'complete':
                raise ValueError('原批次全部入队页尚未确认成功归档')
        if args.apply and new != cursor:
            with Path(args.backup).open('x', encoding='utf8') as file:
                json.dump(dict(job=JOB, state=old, previous_codes=previous, current_codes=codes), file, indent=2)
            changed = await client.eval("""
                if redis.call('HGET',KEYS[1],'cursor') ~= ARGV[1]
                    or redis.call('HGET',KEYS[1],'revision') ~= ARGV[2]
                    or redis.call('XLEN',KEYS[2]) ~= 0 then return 0 end
                redis.call('HSET',KEYS[1],'cursor',ARGV[3],'revision',tonumber(ARGV[2])+1)
                return 1
            """, 2, key, stream, old['cursor'], old['revision'], json.dumps(new, ensure_ascii=False))
            if changed != 1:
                raise ValueError('断点或队列已变化，拒绝提交')
        if args.apply:
            saved = await client.hgetall(key)
            if json.loads(saved.get('cursor', '{}')) != new:
                raise ValueError('维护后断点回读不一致')
        return dict(job=JOB, applied=args.apply, changed=new != cursor, before_index=cursor['index'],
            after_index=new['index'], securities_before=cursor['securities'], securities_after=new['securities'],
            scope_before=cursor['scope_hash'], scope_after=new['scope_hash'],
            batch_preserved=cursor['batch_id'] == new['batch_id'], pending=0, business_dml=0)
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
            codes = list(conn.execute(text('SELECT unified_code FROM stock UNION SELECT unified_code '
                'FROM margin_security ORDER BY unified_code LIMIT 30001')).scalars())
        print(json.dumps(asyncio.run(migrate(cfg, args, codes))))
    finally:
        engine.dispose()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--previous-scope', required=True)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
