"""Explicit retirement of seven market products; theme data and shared services are excluded."""
import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import bindparam, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.archive_queue import SCAN_WINDOW

KINDS = ('trend', 'auction', 'volume', 'trades', 'entrust', 'large_order', 'quote')
PROJECTS = tuple('kaipanla-' + k.replace('_', '-') for k in KINDS)
DATASETS = tuple('kaipanla.' + k + '.day' for k in KINDS)
TABLES = ('stock_daily_quote_level', 'stock_daily_quote', 'stock_intraday_trade_block',
          'stock_intraday_trend', 'stock_large_order_trend', 'stock_minute_entrust',
          'stock_minute_volume', 'stock_opening_auction', 'stock_market_day')


def exclusive_keys(prefix):
    keys = []
    for kind, project in zip(KINDS, PROJECTS, strict=True):
        keys.extend(f'{prefix}:collection:{category}:{project}' for category in
                    ('errors', 'errors-revision', 'archives', 'archives-revision'))
        keys.extend((f'{prefix}:checkpoint:{project}-v1', f'{prefix}:archive:progress:{project}-v1'))
        key = f'{prefix}:archive:fingerprints:v1:kaipanla_{kind}_v1:kaipanla'
        keys.extend((key, key + ':expiry'))
    return keys


async def queued(client, stream):
    if await client.xlen(stream) > 100000:
        raise ValueError('Queue exceeds retirement scan bound; no changes made')
    ids, cursor = [], '-'
    while True:
        rows, _, oversized, _ = await client.eval(SCAN_WINDOW, 1, stream, cursor, '+', 50, 8 * 1024 * 1024)
        if not rows:
            if oversized:
                raise ValueError('Queue message exceeds scan bound; no changes made')
            return ids
        for ident, pairs in rows:
            raw = dict(zip(pairs[::2], pairs[1::2])).get('envelope', '')
            header = json.loads(raw)
            if header.get('dataset') in DATASETS:
                if header.get('source') != 'kaipanla' or header.get('job_key') not in {p+'-v1' for p in PROJECTS}:
                    raise ValueError('Ambiguous retired message ownership; no changes made')
                ids.append(ident)
        cursor = '(' + rows[-1][0]


async def run(config, apply=False, delete_business=False):
    cfg = load_config(config)
    lock = acquire_instance_lock()
    client, engine = create_client(cfg['redis']), make_engine(cfg['mysql'])
    prefix = cfg['redis']['namespace']
    try:
        ids = await queued(client, prefix + ':ingest')
        if apply and ids and not delete_business:
            raise ValueError('Retired pending messages exist; explicit business-data decision required')
        keys = [k for k in exclusive_keys(prefix) if await client.exists(k)]
        control_key = prefix + ':collection:control:v1'
        raw = await client.get(control_key)
        control = json.loads(raw) if raw else None
        report = dict(pending=len(ids), exclusive_keys=len(keys), applied=apply,
                      business_deleted=delete_business and apply, tables_present=[], settings_removed=0)
        with engine.begin() as conn:
            existing = set(conn.execute(text('SHOW TABLES')).scalars())
            report['tables_present'] = [t for t in TABLES if t in existing]
            if apply:
                query = text("DELETE FROM app_setting WHERE namespace=:ns AND kind='task' "
                             "AND setting_key IN :projects").bindparams(bindparam('projects', expanding=True))
                report['settings_removed'] = conn.execute(query, dict(ns=prefix, projects=PROJECTS)).rowcount
                if delete_business:
                    query = text('DELETE FROM collection_state WHERE namespace=:ns AND project_id IN :projects')
                    conn.execute(query.bindparams(bindparam('projects', expanding=True)), dict(ns=prefix, projects=PROJECTS))
        if apply:
            if control:
                control['jobs'] = {k: v for k, v in control.get('jobs', {}).items() if k not in PROJECTS}
                control['history'] = [r for r in control.get('history', []) if r.get('task_id') not in PROJECTS]
                # Compare before write, despite owning the desktop lock.
                replaced = await client.eval("if redis.call('GET',KEYS[1]) == ARGV[1] then "
                    "redis.call('SET',KEYS[1],ARGV[2]); return 1 else return 0 end", 1,
                    control_key, raw, json.dumps(control, ensure_ascii=False))
                if not replaced:
                    raise ValueError('Concurrent scheduler change; retry retirement before starting client')
            if keys:
                await client.delete(*keys)
            if delete_business:
                # DDL is explicit, idempotent maintenance, never application startup.
                with engine.connect() as conn:
                    for table in report['tables_present']:
                        conn.execute(text('DROP TABLE IF EXISTS `' + table + '`'))
                    conn.commit()
                for offset in range(0, len(ids), 100):
                    await client.xdel(prefix + ':ingest', *ids[offset:offset+100])
        return report
    finally:
        await client.aclose()
        engine.dispose()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--delete-business', action='store_true')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.config, args.apply, args.delete_business)), ensure_ascii=False))
