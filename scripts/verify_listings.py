"""Bounded real source → shared queue/archive → formal SQL acceptance, Empire closed."""
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.listings import JOB, PROJECT, digest
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.plugins.infra.settings import SettingsStore


async def run(args):
    cfg=load_config(args.config)
    lock=acquire_instance_lock()
    manager=build_manager(cfg)
    try:
        await manager.start('collector.ths_listings')
        collector=manager.registry.get('collector.ths_listings')
        query=manager.registry.get('listings.query')
        store=manager.registry.get('redis.store')
        if await store.client.xlen(store.stream):
            raise RuntimeError('待归档Stream不为零，拒绝开始有限验证')
        stocks,existing,proof=await query.plan()
        wanted=set(args.codes.split(','))
        selected=[s for s in stocks if s['code'] in wanted]
        if {s['code'] for s in selected}!=wanted or not 1<=len(selected)<=20:
            raise ValueError('有限样本必须全部属于当前池，且不超过20证券')
        settings=await SettingsStore(query.mysql,cfg['redis']['namespace']).load('task')
        policy=settings.get(PROJECT,{})
        from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY
        use=USE_PROXY.set(policy.get('use_proxy',True))
        fallback=PROXY_FALLBACK.set(policy.get('proxy_fallback',True))
        collector.request_retries=policy.get('request_retries',2)
        async def plan():
            return selected,existing,proof
        query.plan=plan
        hashes,details={},{}
        original=collector.fetch
        async def fetch(stock):
            row,observed,url=await original(stock)
            hashes[row['unified_code']]=digest(row)
            details[row['unified_code']]=dict(listing_date=row['listing_date'],history_bytes=len((row['history'] or '').encode()),
                null_fields=[k for k,v in row.items() if v is None],content_hash=digest(row))
            return row,observed,url
        collector.fetch=fetch
        try:
            result=await asyncio.wait_for(collector.execute(fresh=True,baseline_revision=await collector.checkpoint_revision()),300)
            for code,checksum in hashes.items():
                assert digest(await query.detail(code))==checksum,'来源与正式查询不一致'
            assert len(hashes)==len(selected)
            pending=await store.client.xlen(store.stream)
            assert pending==0
            report=dict(checked_at=datetime.now(CHINA).isoformat(),project=PROJECT,job=JOB,production=True,
                scope=[s['code']+'.'+s['market'] for s in selected],source_query_equal=True,details=details,
                cursor=result,pending=pending,preparation=[vars(e) for e in await query.preparation_check({'codes':list(wanted)})],
                limitation='有限真实证券验证；不是全市场采完，不包含从未采集退市证券')
            Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
            print(json.dumps(dict(status=result['phase'],securities=len(hashes),pending=pending,source_query_equal=True)))
        finally:
            USE_PROXY.reset(use)
            PROXY_FALLBACK.reset(fallback)
    finally:
        await manager.shutdown()
        lock.unlock()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--codes',default='000001,000002,000032,600000,600519,300750,688981,920009')
    parser.add_argument('--output',default='docs/evidence/listings-live-2026-10-06.json')
    app=QCoreApplication([])
    asyncio.run(run(parser.parse_args()))
