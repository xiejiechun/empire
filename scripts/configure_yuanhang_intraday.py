"""Explicitly save the five pools' 60-second schedule; no business data or DDL."""
import argparse
import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.yuanhang_limits.contract import POOLS, project
from empire.plugins.collection.control import validate_policy
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.settings import SettingsStore


def intraday_policy(existing):
    defaults = dict(enabled=True, mode='interval', interval_seconds=60, daily_time='18:00',
                    request_retries=2, use_proxy=True, proxy_fallback=True, archived=False)
    return validate_policy({**defaults, **(existing or {}), 'mode': 'interval', 'interval_seconds': 60})


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    client = create_client(cfg['redis'])
    engine = make_engine(cfg['mysql'])
    namespace = cfg['redis']['namespace']
    store = SettingsStore(SimpleNamespace(engine=engine), namespace)
    try:
        cached = await client.get(f'{namespace}:collection:control:v1')
        jobs = (json.loads(cached).get('jobs', {}) if cached else {})
        report = dict(applied=args.apply, retention_hours=72, projects={})
        with engine.begin() as conn:
            for pool in POOLS:
                ident = project(pool)
                raw = conn.execute(text('SELECT payload FROM app_setting WHERE namespace=:ns '
                    "AND kind='task' AND setting_key=:key FOR UPDATE"), dict(ns=namespace, key=ident)).scalar_one_or_none()
                old = json.loads(raw) if isinstance(raw, str) else raw
                updated = intraday_policy(old or jobs.get(ident, {}).get('policy'))
                if args.apply:
                    store.save_in_transaction(conn, 'task', ident, updated)
                report['projects'][ident] = updated
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()
        await client.aclose()
        if lock:
            lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true', help='正常关闭Empire后保存；下次启动读取SQL策略')
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(arguments.config))) from None
