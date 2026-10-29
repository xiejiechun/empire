import asyncio,json,math
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import patch
from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.plugins.infra.routing import USE_PROXY,PROXY_FALLBACK,ROUTE_COUNTS
from empire.features.yuanhang import collector as runtime
from empire.sources.yuanhang_coverage import financial_proofs
from empire.sources.yuanhang_payload import financial_payload,digest
async def idle(self):await asyncio.Future()
async def main():
 lock=acquire_instance_lock();m=build_manager(load_config(Path('dist/EmpireDesktop/config.toml')));routes={};proofs={};out={}
 USE_PROXY.set(True);PROXY_FALLBACK.set(False);ROUTE_COUNTS.set(routes)
 try:
  with patch('empire.sources.yuanhang_service.IdentityService.watch',idle):
   await m.start('collector.yuanhang_financial');c=m.registry.get('collector.yuanhang_financial')
   state=await c.ingest.checkpoint(c.job_key);codes,through=await c.query.collection_scope();n=math.ceil(len(codes)*.05);start=state['cursor']['next_index'];selected=codes[start:start+n]
   original=runtime.prefetch_units;fetch=c.fetch
   @asynccontextmanager
   async def bounded(collector,units,download,**kw):
    async with original(collector,units[:n],download,**kw) as reads:yield reads
    raise asyncio.CancelledError('Development sample complete; preserve full-pool continuation')
   async def capture(unit,**kw):
    snapshot=await fetch(unit,**kw)
    proofs[unit[0]]=financial_proofs(financial_payload(snapshot,code=unit[0]))
    return snapshot
   c.fetch=capture
   with patch.object(runtime,'prefetch_units',bounded):
    try:await c.execute(baseline_revision=state['revision'])
    except asyncio.CancelledError:pass
   redis=c.ingest.redis
   async with asyncio.timeout(120):
    while await redis.client.xlen(redis.stream):await asyncio.sleep(.5)
   final=await c.ingest.checkpoint(c.job_key)
   assert final['cursor']['next_index']==start+len(selected)
   assert set(proofs)==set(selected)
   checks=[]
   for code in selected:
    problems=await c.query.audit_source_proofs(code,proofs[code],financial=True)
    assert not problems,(code,problems)
    checks.append({'code':code,'proof_hash':digest(proofs[code]),'rows':sum(p['row_count'] for p in proofs[code].values()),'problems':problems})
   out={'status':'sample_verified','population':len(codes),'population_hash':digest(codes),'target_fraction':.05,'selection':'fixed consecutive continuation sample, no replacement','selected':selected,'checks':checks,'routes':routes,'stats':c.stats,'pending':0,'checkpoint_after':final,'old_nonfinite_errors_cleared':False,'limitation':'Historical nonfinite response lacked field/raw evidence and has not reproduced; diagnostics improved, no numeric validation relaxed.'}
   print(json.dumps({'status':out['status'],'sample':len(checks),'next_index':final['cursor']['next_index'],'pending':0,'routes':routes}),flush=True)
 finally:
  Path('docs/evidence/financial-recovery-sample-2026-10-29.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  await m.shutdown();lock.unlock()
asyncio.run(main())
