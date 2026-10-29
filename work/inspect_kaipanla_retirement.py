import asyncio,json
from pathlib import Path
from sqlalchemy import text
from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
async def main():
 c=load_config(Path('dist/EmpireDesktop/config.toml').resolve());r=create_client(c['redis']);prefix=c['redis']['namespace'];e=make_engine(c['mysql'])
 objects=json.loads(Path('build/retired-kaipanla-objects.json').read_text());result={'tables':{},'redis':[]}
 with e.connect() as conn:
  existing=set(conn.execute(text('SHOW TABLES')).scalars())
  for table in objects['tables']:
   result['tables'][table]=conn.execute(text('SELECT COUNT(*) FROM `'+table+'`')).scalar_one() if table in existing else None
  result['settings']=list(conn.execute(text("SELECT setting_key FROM app_setting WHERE namespace=:ns AND kind='task' AND setting_key IN ('kaipanla-trend','kaipanla-auction','kaipanla-volume','kaipanla-trades','kaipanla-entrust','kaipanla-large-order','kaipanla-quote')"),dict(ns=prefix)).scalars())
 async for key in r.scan_iter(match=prefix+':*kaipanla*',count=100):
  if len(result['redis'])>=300:raise ValueError('key inventory exceeds bound')
  result['redis'].append(key.removeprefix(prefix+':'))
 result['queue_length']=await r.xlen(prefix+':ingest')
 await r.aclose();e.dispose();Path('build/kaipanla-retirement-inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False))
asyncio.run(main())
