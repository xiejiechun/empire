import asyncio,json
from datetime import datetime,UTC
from pathlib import Path
from types import SimpleNamespace
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.fingerprints import FingerprintCache
async def main():
 cfg=load_config(Path('dist/EmpireDesktop/config.toml').resolve())
 m=build_manager(cfg);cat=m.entries['dataset.astock'].plugin
 client=create_client(cfg['redis']);prefix=cfg['redis'].get('namespace','empire:dev')
 cache=FingerprintCache(SimpleNamespace(client=client,prefix=prefix),cfg.get('archive',{}),cat.fingerprint_version)
 result=dict(checked_at=datetime.now(UTC).isoformat(),ttl=cache.ttl,limit=cache.limit,buckets=[],projects={})
 for c in cat.contributions:
  for project in c.projects.values():
   result['projects'].setdefault(project,[]).append(dict(namespace=c.namespace,datasets=sorted(c.datasets),mode=c.mode))
 for namespace in sorted(cat.namespaces):
  keys=[key async for key in client.scan_iter(match=f'{prefix}:archive:fingerprints:v1:{namespace}:*') if not key.endswith(':expiry')]
  for key in keys:
   source=key.split(f':{namespace}:',1)[1]
   stamp=(await client.time())[0]
   pipe=client.pipeline(transaction=True);pipe.hlen(key);pipe.zcard(key+':expiry');pipe.zcount(key+':expiry',stamp+1,stamp+cache.ttl);pipe.zrangebyscore(key+':expiry',stamp+1,stamp+cache.ttl,start=0,num=3)
   hashes,indexed,unexpired,ids=await pipe.execute()
   trusted=await cache.peek(namespace,source,ids)
   result['buckets'].append(dict(namespace=namespace,source=source,hashes=hashes,indexed=indexed,unexpired_index=unexpired,sample_size=len(ids),valid_sample=len(trusted)))
 await client.aclose()
 Path('docs/evidence/redis-filter-live-2026-10-29.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:result[k] for k in ('checked_at','ttl','limit')},ensure_ascii=False));print('buckets',len(result['buckets']),'full',sum(b['hashes']>=cache.limit for b in result['buckets']))
asyncio.run(main())
