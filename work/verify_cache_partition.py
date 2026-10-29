import asyncio,json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from datetime import UTC,datetime,timedelta
from empire.core.config import load_config
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.fingerprints import FingerprintCache,digest
from empire.features.yuanhang.dataset import FINGERPRINT_NAMESPACE,FINGERPRINT_VERSION
from scripts.split_yuanhang_fingerprint_cache import migrate
async def main():
 cfg=load_config(Path('dist/EmpireDesktop/config.toml').resolve());client=create_client(cfg['redis'])
 prefix='empire:test:cache-split:'+uuid4().hex
 cache=FingerprintCache(SimpleNamespace(client=client,prefix=prefix),{'fingerprint_max_entries':2},lambda _:FINGERPRINT_VERSION)
 ns=FINGERPRINT_NAMESPACE;old,new=cache.keys(ns,'ths_yuanhang'),cache.keys(ns,'ths_yuanhang:financial');v=[(datetime.now(UTC)-timedelta(minutes=1)).isoformat(timespec='microseconds')]
 proof={'hash':digest({'x':1}),'version':v}
 try:
  await cache.put(ns,'ths_yuanhang',{'000001.SZ:financial':proof})
  expiry=await client.zscore(old[1],'000001.SZ:financial')
  report=await migrate(cache,True);assert report['moved']==1
  assert await client.zscore(new[1],'000001.SZ:financial')==expiry
  assert await cache.peek(ns,'ths_yuanhang:financial',['000001.SZ:financial'])=={'000001.SZ:financial':proof}
  await cache.put(ns,'ths_yuanhang',{str(i):proof for i in range(10)})
  assert '000001.SZ:financial' in await cache.get(ns,'ths_yuanhang:financial',['000001.SZ:financial'])
  assert await client.hlen(old[0])==2
  await cache.put(ns,'ths_yuanhang',{'000001.SZ:financial':dict(hash=digest({'older':1}),version=v)})
  assert (await migrate(cache,True))['moved']==0
  assert (await cache.peek(ns,'ths_yuanhang:financial',['000001.SZ:financial']))['000001.SZ:financial']==proof
  await client.hset(old[0],'bad:financial','bad-json');await client.zadd(old[1],{'bad:financial':expiry})
  result=await migrate(cache,True);assert result['skipped']==1
  print(json.dumps(dict(isolated_redis=True,expiry_preserved=True,financial_survives_price_eviction=True,destination_not_overwritten=True,corruption_skipped=True)))
 finally:
  await client.delete(*old,*new);await client.aclose()
asyncio.run(main())
