"""Finite real month acceptance through shared downloader, Redis, archive and formal SQL."""
import argparse
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.listing_status import COLUMNS, JOB, PROJECT, bounds, content, digest, months
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY
from empire.plugins.infra.settings import SettingsStore


async def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock()
    manager = build_manager(cfg)
    try:
        await manager.start('collector.tdx_listing_status')
        c, q, store = (manager.registry.get(k) for k in ('collector.tdx_listing_status', 'listing_status.query', 'redis.store'))
        if await store.client.xlen(store.stream):
            raise RuntimeError('待归档Stream不为零，拒绝有限验证')
        checkpoint = await c.ingest.checkpoint(JOB)
        if checkpoint['cursor'].get('phase') in ('fetch', 'awaiting_archive'):
            raise RuntimeError('已有活跃上市状态轮次，先继续原任务，不能用有限验证替换')
        wanted = sorted(set(args.months.split(',')))
        through = datetime.now(CHINA).date()
        if not 1 <= len(wanted) <= 6 or not set(wanted) <= set(months(through)):
            raise ValueError('有限验证须选择声明范围内的1至6个月份')
        original_plan = q.plan
        async def finite_plan(end, fresh=False):
            candidates = await original_plan(end, fresh=True)
            return [m for m in candidates if m in wanted]
        q.plan = finite_plan
        settings = await SettingsStore(q.mysql, cfg['redis']['namespace']).load('task')
        policy = settings.get(PROJECT, {})
        use, fallback = USE_PROXY.set(policy.get('use_proxy', True)), PROXY_FALLBACK.set(policy.get('proxy_fallback', True))
        c.request_retries = policy.get('request_retries', 2)
        daily, original_fetch = {}, c.fetch
        async def fetch(day):
            result = await original_fetch(day)
            daily[day] = result
            if len(daily) % 15 == 0:
                print(json.dumps(dict(stage='collecting', days=len(daily), day=day)), flush=True)
            return result
        c.fetch = fetch
        try:
            result = await asyncio.wait_for(c.execute(fresh=True, baseline_revision=checkpoint['revision']), 1200)
            proofs = (await q.state()).get('months', {})
            audit = {}
            for month in wanted:
                a, b = bounds(month, through)
                expected = sorted([r for day, (rows, _) in daily.items() if day[:7] == month for r in rows], key=lambda r: tuple(r[:4]))
                counts = [daily[(a + timedelta(days=i)).isoformat()][1] for i in range((b-a).days+1)]
                actual, after = [], None
                while True:
                    page = await q.list_events(start=a.isoformat(), end=b.isoformat(), after=after)
                    for row in page['rows']:
                        key = [row[k] for k in COLUMNS[:4]]
                        detail = await q.detail(key)
                        assert detail['found']
                        actual.append(key + [row['name'], detail['description']])
                    after = page['next']
                    if after is None:
                        break
                assert actual == expected and proofs[month]['digest'] == digest(content(expected, counts))
                checks = await q.preparation_check(dict(start=a.isoformat(), end=b.isoformat()))
                assert all(e.status == 'pass' for e in checks)
                audit[month] = dict(days=len(counts), events=len(expected), digest=proofs[month]['digest'],
                    types={kind: sum(r[2] == kind for r in expected) for kind in ('suspended','resumed','terminated')},
                    preparation=[vars(e) for e in checks])
            assert await store.client.xlen(store.stream) == 0
            state = await q.state()
            report = dict(checked_at=datetime.now(CHINA).isoformat(), production=True, project=PROJECT, job=JOB,
                months=audit, requests=len(daily), source_query_equal=True, pending=0, cursor=result,
                continuous_through=state.get('coverage_through'), full_history_complete=False,
                next_run='SQL缺失月份及最近一个月；普通任务仍需补全未采历史',
                limitation='仅所列完整月份的真实来源到正式查询验收，不证明其他月份、北交所或重新上市事件完整')
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
            print(json.dumps(dict(status=result['phase'], events=result['collected'], days=len(daily), pending=0, source_query_equal=True)), flush=True)
        finally:
            USE_PROXY.reset(use)
            PROXY_FALLBACK.reset(fallback)
    finally:
        await manager.shutdown()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--months', default='1990-12,2020-05,2021-08,2024-07')
    parser.add_argument('--output', default='docs/evidence/listing-status-live-2026-10-06.json')
    args = parser.parse_args()
    app = QCoreApplication([])
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
