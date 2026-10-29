import asyncio,json,inspect
from pathlib import Path
from unittest.mock import patch
from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.plugins.infra.routing import USE_PROXY,PROXY_FALLBACK,ROUTE_COUNTS
from empire.sources import yuanhang_wire as wire
async def idle(self): await asyncio.Future()
original=wire.scalar
bad=[]
def scalar(cell,kind):
 try:return original(cell,kind)
 except ValueError as exc:
  f=inspect.currentframe().f_back
  bad.append({'cell':cell.hex(),'kind':kind,'field':f.f_locals.get('field'),'row':f.f_locals.get('row'),'prior':str(f.f_locals.get('point'))})
  raise
async def main():
 cfg=load_config(Path('dist/EmpireDesktop/config.toml')); lock=acquire_instance_lock(); m=build_manager(cfg)
 tokens=USE_PROXY.set(True),PROXY_FALLBACK.set(True),ROUTE_COUNTS.set({})
 try:
  with patch('empire.sources.yuanhang_service.IdentityService.watch',idle),patch.object(wire,'scalar',scalar):
   await m.start('collector.yuanhang_financial'); c=m.registry.get('collector.yuanhang_financial')
   codes,through=await c.query.collection_scope(); state=await c.ingest.checkpoint(c.job_key); code=codes[state['cursor']['next_index']]
   profiles=await c.identity.registry.load(); nodes=sorted(n for n in c.identity.online_codes() if n in profiles and profiles[n].provisioned)
   print(json.dumps({'code':code,'through':through,'nodes':len(nodes)}),flush=True)
   fetch=c.fetch
   async def traced(unit, **kw):
    try:return await fetch(unit,**kw)
    except Exception as e:
     print('FAILED',unit[0],type(e).__name__,str(e),json.dumps(bad),flush=True)
     raise
   c.fetch=traced
   try: await asyncio.wait_for(c.execute(baseline_revision=state['revision']),180)
   except Exception as e: print(type(e).__name__,str(e),flush=True)
   print(json.dumps(c.stats,ensure_ascii=False),flush=True)
   print(json.dumps({'bad':bad,'routes':ROUTE_COUNTS.get()}),flush=True)
 finally:
  await m.shutdown(); lock.unlock()
asyncio.run(main())
