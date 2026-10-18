"""Real complete catalogue → shared archive → formal current-member audit, Empire closed."""
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.indices import PROJECT
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.datasets.indices import digest
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore


async def run(args):
    cfg = load_config(args.config)
    lock, m = acquire_instance_lock(), build_manager(cfg)
    try:
        await m.start('collector.ths_indices')
        c, q, store = m.registry.get('collector.ths_indices'), m.registry.get('indices.query'), m.registry.get('redis.store')
        if await store.client.xlen(store.stream):
            raise RuntimeError('待归档Stream不为零，拒绝开始完整验证')
        settings = await SettingsStore(q.mysql, cfg['redis']['namespace']).load('task')
        policy = settings.get(PROJECT, {})
        c.request_retries = policy.get('request_retries', 2)
        network = {}
        use, fallback, counts = USE_PROXY.set(policy.get('use_proxy', True)), PROXY_FALLBACK.set(policy.get('proxy_fallback', True)), ROUTE_COUNTS.set(network)
        captures = {}
        original = c.publish
        async def publish(state, cursor, dataset, identity, payload):
            captures[identity] = dict(hash=digest(payload['catalog'] if identity == 'catalog' else [payload['available'], payload['members']]),
                count=len(payload['catalog'] if identity == 'catalog' else payload['members']), available=payload.get('available'))
            result = await original(state, cursor, dataset, identity, payload)
            if len(captures) % 50 == 0:
                print(json.dumps(dict(completed=cursor['next_index'], total=len(cursor['codes']), members=cursor['collected'], unavailable=cursor['unavailable'])), flush=True)
            return result
        c.publish = publish
        try:
            result = await asyncio.wait_for(c.execute(fresh=True, baseline_revision=await c.checkpoint_revision()), 3600)
            heads, complete, _, unavailable, unknown, count, _, proofs = await q.mysql.read(q.snapshot_audit)
            assert complete, 'SQL集合及逐指数证明未通过'
            assert captures and all(proofs[k]['hash'] == v['hash'] and proofs[k]['count'] == v['count'] for k, v in captures.items())
            pending = await store.client.xlen(store.stream)
            assert pending == 0
            report = dict(checked_at=datetime.now(CHINA).isoformat(), project=PROJECT, production=True,
                catalogue_count=len(heads), member_count=count, unavailable=unavailable, unknown_identity_count=unknown,
                source_query_equal=True, source_units_checked=len(captures), unit_proofs=captures,
                cursor=result, pending=pending, network=network, preparation=[vars(e) for e in await q.preparation_check()],
                limitations='仅同花顺当前目录与实际成员响应；来源暂无不表示真实零成员，目录分组不冒充官方分类，不还原历史调样')
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
            print(json.dumps({k: report[k] for k in ('catalogue_count', 'member_count', 'source_units_checked', 'pending', 'network')}, ensure_ascii=False))
        finally:
            USE_PROXY.reset(use)
            PROXY_FALLBACK.reset(fallback)
            ROUTE_COUNTS.reset(counts)
    finally:
        await m.shutdown()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--output', default='docs/evidence/indices-live-2026-10-09.json')
    args = parser.parse_args()
    app = QCoreApplication([])
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
