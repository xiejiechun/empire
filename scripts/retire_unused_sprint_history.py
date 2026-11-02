"""Explicitly remove the never-run duplicate sprint task's temporary schedule."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from scripts.release import require_stopped
from scripts.release_lock import ReleaseLock

RETIRED = 'ths-yuanhang-sprint-limit-up-history'


def validate_unused(control, *, states, settings, keys, pending):
    job = control.get('jobs', {}).get(RETIRED)
    runs = [row for row in control.get('history', []) if row.get('task_id') == RETIRED]
    if (states or settings or keys or pending or runs or
            job and (job.get('active') or job.get('last_status') != 'idle')):
        raise ValueError('退役项目存在执行/配置/业务证据或队列未清空，拒绝移除；需另行核查恢复')


async def retire(config, *, apply):
    cfg = load_config(config)
    ns = cfg['redis']['namespace']
    engine = make_engine(cfg['mysql'])
    try:
        with engine.connect() as conn:
            params = dict(ns=ns, ident=RETIRED)
            states = conn.execute(text('SELECT COUNT(*) FROM collection_state '
                'WHERE namespace=:ns AND project_id=:ident'), params).scalar_one()
            settings = conn.execute(text("SELECT COUNT(*) FROM app_setting WHERE namespace=:ns "
                "AND kind='task' AND setting_key=:ident"), params).scalar_one()
    finally:
        engine.dispose()
    client = create_client(cfg['redis'])
    try:
        key = ns + ':collection:control:v1'
        async with client.pipeline(transaction=True) as pipe:
            await pipe.watch(key)
            raw = await pipe.get(key)
            control = json.loads(raw or '{}')
            keys = [value async for value in client.scan_iter(match=ns + ':*' + RETIRED + '*')]
            pending = await client.xlen(ns + ':ingest')
            validate_unused(control, states=states, settings=settings, keys=keys, pending=pending)
            present = RETIRED in control.get('jobs', {})
            if apply and present:
                del control['jobs'][RETIRED]
                pipe.multi()
                pipe.set(key, json.dumps(control, ensure_ascii=False))
                await pipe.execute()
            return dict(applied=apply, removed=bool(apply and present), states=states,
                        settings=settings, keys=keys, pending=pending, business_writes=0)
    finally:
        await client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with ReleaseLock(root) as lock:
        require_stopped(lock, root)
        result = asyncio.run(retire(args.config, apply=args.apply))
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS unused sprint history task retirement', result)


if __name__ == '__main__':
    main()
