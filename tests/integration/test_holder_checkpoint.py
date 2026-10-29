"""Owned Redis migration leaves business data, other caches and history untouched."""
import json
import os
from types import SimpleNamespace

import pytest

from empire.core.config import load_config
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.fingerprints import FingerprintCache
from scripts.migrate_holder_checkpoint import JOB, migrate

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to private SQL/Redis')]


async def test_old_frontier_retired_atomically_and_old_cache_forced_to_sql(tmp_path):
    cfg = load_config()
    prefix = cfg['redis']['namespace']
    client = create_client(cfg['redis'])
    key, stream = prefix + ':checkpoint:' + JOB, prefix + ':ingest'
    cache = FingerprintCache(SimpleNamespace(prefix=prefix), {}, None)
    hashes, expiry = cache.keys('ths_holders', 'ths')
    other = cache.keys('other', 'ths')[0]
    history = prefix + ':test-history'
    original = dict(revision='7', cursor=json.dumps(dict(phase='fetch', index=1853)))
    args = SimpleNamespace(apply=True, backup=str(tmp_path / 'checkpoint.json'))
    try:
        await client.hset(key, mapping=original)
        await client.hset(hashes, '300398.SZ', 'old proof')
        await client.zadd(expiry, {'300398.SZ': 9999999999})
        await client.hset(other, 'retained', 'yes')
        await client.set(history, 'retained history')
        pending = await client.xadd(stream, {'body': 'pending'})
        with pytest.raises(ValueError, match='queue'):
            await migrate(cfg, args)
        assert await client.hgetall(key) == original
        await client.xdel(stream, pending)
        result = await migrate(cfg, args)
        assert result['fingerprint_invalidation'] and result['business_dml'] == 0
        assert await client.hgetall(key) == dict(revision='8', cursor='{}')
        assert not await client.exists(hashes, expiry)
        assert await client.hget(other, 'retained') == 'yes'
        assert await client.get(history) == 'retained history'
        assert json.loads((tmp_path / 'checkpoint.json').read_text(encoding='utf-8'))['state'] == original
        assert not (await migrate(cfg, args))['changed']
    finally:
        await client.delete(key, stream, hashes, expiry, other, history)
        await client.aclose()
