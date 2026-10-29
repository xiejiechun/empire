import asyncio,json,hashlib
from pathlib import Path
from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.plugins.infra.routing import USE_PROXY,PROXY_FALLBACK,ROUTE_COUNTS
from empire.features.performance.contract import monthly_plan,digest,identity
async def main():
 lock=acquire_instance_lock(); m=build_manager(load_config(Path('dist/EmpireDesktop/config.toml')));routes={}; expected={};out={}
 USE_PROXY.set(True);PROXY_FALLBACK.set(False);ROUTE_COUNTS.set(routes)
 try:
  await m.start('collector.tdx_shareholder_changes');c=m.registry.get('collector.tdx_shareholder_changes')
  state=await c.ingest.checkpoint(c.job_key); periods=monthly_plan(state['cursor']['latest']);sample=periods[375:398]
  assert state['cursor']['phase']=='complete'
  result=state['cursor']
  for month in sample:
   expected[month]=(await c.fetch(month))[0]
  q=c.query;checks=[]
  for month in sample:
   after=None;actual=[]
   import calendar
   y,mo=map(int,month[:7].split('-'));end=f'{y}-{mo:02d}-{calendar.monthrange(y,mo)[1]}'
   while True:
    page=await q.list_records(start=month,end=end,after=after,limit=200)
    actual.extend(page['rows']);after=page['next']
    if after is None:break
   rows=expected[month];fields=set(rows[0]) if rows else set();actual=[{k:r[k] for k in fields} for r in actual]
   a=sorted(rows,key=lambda r:identity(c.kind,r));b=sorted(actual,key=lambda r:identity(c.kind,r))
   assert a==b,(month,len(a),len(b))
   checks.append({'month':month,'count':len(a),'content_hash':digest(a)})
  pending=await c.ingest.redis.client.xlen(c.ingest.redis.stream);assert pending==0
  cleared=await c.records.clear_errors(c.project_id,['4317c888e2d142649d72cded82561088'])
  out=dict(status='complete',result=result,sample={'population':len(periods),'fraction':23/len(periods),'selection':'fixed 23 complete months starting at failed month; remaining months normal recovery','months':sample},checks=checks,pending=pending,routes=routes,cleaned_error_ids=['4317c888e2d142649d72cded82561088'],cleaned_count=cleared)
  print(json.dumps(out,ensure_ascii=False),flush=True)
 finally:
  Path('docs/evidence/shareholder-recovery-2026-10-29.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  await m.shutdown();lock.unlock()
asyncio.run(main())
