"""Explicitly archive Sina and prepare THS; preserves all business data and user plans."""
import argparse
import asyncio
import json

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.contracts.download_settings import DEFAULTS, validate_settings
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.collection.control import validate_policy
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.settings import SettingsStore


def plan(rows):
    base = {'enabled': True, 'mode': 'daily', 'interval_seconds': 86400,
            'daily_time': '18:00', 'request_retries': 2}
    sina = validate_policy({**rows.get(('task', 'sina-stocks'), {**base, 'enabled': False}), 'archived': True})
    ths = validate_policy(rows.get(('task', 'ths-stocks'), base))
    download = validate_settings(rows.get(('download', 'global'), DEFAULTS))
    download = validate_settings({**download, 'stock_response_bytes': max(download['stock_response_bytes'], 8 * 1024 * 1024)})
    return {('task', 'sina-stocks'): sina, ('task', 'ths-stocks'): ths,
            ('download', 'global'): download}


async def configure(cfg, apply):
    engine = make_engine(cfg['mysql'])
    client = create_client(cfg['redis'])
    prefix = cfg['redis']['namespace']
    lock = acquire_instance_lock() if apply else None
    try:
        pending = await client.xlen(prefix + ':ingest')
        with engine.begin() as conn:
            rows = {(kind, key): json.loads(payload) if isinstance(payload, str) else payload
                    for kind, key, payload in conn.execute(text('SELECT kind,setting_key,payload '
                        'FROM app_setting WHERE namespace=:namespace FOR UPDATE'), {'namespace': prefix})}
            changes = plan(rows)
            before = conn.execute(text('SELECT COUNT(*) FROM stock')).scalar_one()
            if apply:
                store = SettingsStore(None, prefix)
                for (kind, key), value in changes.items():
                    store.save_in_transaction(conn, kind, key, value)
            after = conn.execute(text('SELECT COUNT(*) FROM stock')).scalar_one()
            assert before == after
        # Only retired source-specific stock proofs; no queue or business deletion.
        if apply:
            keys = [f'{prefix}:archive:fingerprints:v1:stocks:{source}{suffix}'
                    for source in ('sina', 'ths') for suffix in ('', ':expiry')]
            await client.delete(*keys)
        return {'applied': apply, 'stock_before': before, 'stock_after': after,
                'pending': pending, 'sina_archived': changes[('task', 'sina-stocks')]['archived'],
                'sina_enabled_preserved': changes[('task', 'sina-stocks')]['enabled'],
                'ths_policy': changes[('task', 'ths-stocks')],
                'stock_response_bytes': changes[('download', 'global')]['stock_response_bytes']}
    finally:
        await client.aclose()
        engine.dispose()
        if lock:
            lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    cfg = {}
    try:
        cfg = load_config(args.config)
        print(json.dumps(asyncio.run(configure(cfg, args.apply)), ensure_ascii=False))
    except Exception as exc:
        raise SystemExit(redact(exc, cfg)) from None
