import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.initialize_yuanhang_limits import require_owned_pending


async def test_initialization_pending_scan_only_accepts_owned_jobs():
    store = SimpleNamespace(stream='test:ingest', client=SimpleNamespace(xrange=AsyncMock(side_effect=[
        [('1-0', {'envelope': json.dumps(dict(job_key='ths-yuanhang-limit-up-pool-v1'))})], []])))
    await require_owned_pending(store)
    assert store.client.xrange.call_args.kwargs['min'] == '(1-0'
    store.client.xrange = AsyncMock(return_value=[('2-0', {'envelope': json.dumps(dict(job_key='sina-news-v1'))})])
    with pytest.raises(RuntimeError, match='非本次'):
        await require_owned_pending(store)
