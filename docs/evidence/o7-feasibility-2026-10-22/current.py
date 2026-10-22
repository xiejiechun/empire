"""Five fixed objects only; read-only SQL snapshots and formal queries."""
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from sqlalchemy import text
from preservation import guard
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.capital_actions.codec import decode
from empire.features.capital_actions.contract import digest
from empire.plugins.infra.collection_state import read_state

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
KEYS = {
 '30f7514d974c1e3f66915444ed357031bb811c75056b25b0618d47216ded7b23',
 'c8ed4edb9b8251f702415f05cad38d6cf781e1401dc9fee1ac92ce92c63b8090',
 'b0e7639683c95122acdf0cd28f870ba3a618204df59fd9d84ddd2a15417a28db',
 '5e1fbd1afaa48e760b265651e8a6266242a865cff2f1e538b80e4c49ae7fb7c0',
 '06f3f8004d4768bffdffc2f458e15f09d59bcbf0f9cf3b843ca546d22ff4dabd'}

async def main():
 result = dict(started_at=datetime.now(UTC).isoformat(), datasets={})
 manager = build_manager(load_config(ROOT/'config.toml'))
 try:
  await manager.start('infra.redis')
  store = manager.registry.get('redis.store')
  result['pending_before'] = await store.client.xlen(store.stream)
  for kind,codes in [('additional_issues',['600590','001228','601127']),('rights_issues',['300176'])]:
   await manager.start('data.'+kind)
   q=manager.registry.get(kind+'.query')
   params={f'c{i}':code+'.'+('SH' if code.startswith('6') else 'SZ') for i,code in enumerate(codes)}
   with q.mysql.read_engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
    conn.exec_driver_sql('START TRANSACTION READ ONLY')
    result['server_uuid']=conn.exec_driver_sql('SELECT @@server_uuid').scalar_one()
    rows=conn.execute(text(f'SELECT *,RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code FROM {q.table} WHERE unified_code IN ('+','.join(':'+k for k in params)+') ORDER BY record_key LIMIT 501'),params).mappings().all()
    assert len(rows)<501
    state=read_state(conn,q.namespace,q.project_id,q.source)
    selected=[dict(row=decode(r), content_hash=r['content_hash'],version_observed_at=str(r['version_observed_at'])) for r in rows if r['record_key'] in KEYS]
    data=dict(selected=selected,units={c:state.get('units',{}).get(('SH' if c.startswith('6') else 'SZ')+':'+c) for c in codes},formal_units={})
    conn.rollback()
   for code in codes:
    formal=await q.list_events(code=code,limit=500)
    expected=[decode(r) for r in rows if r['code']==code]
    assert sorted(formal,key=lambda r:r['record_key'])==sorted(expected,key=lambda r:r['record_key'])
    data['formal_units'][code]=dict(count=len(formal),digest=digest(sorted(formal,key=lambda r:r['record_key'])))
   cursor=await store.client.hget(f'{store.prefix}:checkpoint:{q.job_key}','cursor')
   data['checkpoint']=json.loads(cursor or '{}')
   result['datasets'][kind]=data
  assert {r['row']['record_key'] for d in result['datasets'].values() for r in d['selected']}==KEYS
  result['pending_after']=await store.client.xlen(store.stream)
 finally:
  await manager.shutdown()
 result['finished_at']=datetime.now(UTC).isoformat()
 (OUT/'current.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
 print('Five fixed keys and formal security units rechecked; no mutation.')

if __name__=='__main__':
 asyncio.run(main())
