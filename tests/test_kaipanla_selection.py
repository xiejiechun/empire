"""Finite quote scope still uses shared control, checkpoints and ordered pipeline."""
import asyncio
from copy import deepcopy

import pytest

from empire.features.kaipanla.selection import validate_request
from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY
from tests.test_collection_control import setup
from tests.test_kaipanla_intraday import collector

REQUEST = dict(securities=['000001.SZ'], start='2021-01-05', end='2021-01-05', proxy_priority=True)


async def test_scope_is_checked_then_exact_day_published_and_same_scope_resumes():
    c = collector()
    # Use the same source/transport fixture; this test isolates scope, not quote parsing.
    c.validate_request = validate_request
    result = await c.execute(request=REQUEST)
    assert result['phase'] == 'complete' and result['request'] == REQUEST
    assert [e.raw_payload['rows'][0]['trade_date'] for e in c.ingest.published] == ['2021-01-05']
    c.ingest.state['cursor']['phase'] = 'awaiting_archive'
    before = deepcopy(c.ingest.state)
    with pytest.raises(ValueError,match='另一采集范围'):
        await c.execute(request={**REQUEST,'start':'2021-01-04'})
    assert c.ingest.state == before
    assert (await c.execute(request=REQUEST))['phase'] == 'complete'
    assert c.ingest.state['cursor']['last_review'] is None  # Not a full-pool weekly review.
    # A different request cannot reuse a completed cursor despite a newer revision.
    changed = {**REQUEST, 'start': '2021-01-04'}
    assert (await c.execute(request=changed))['request'] == changed


async def test_explicit_request_network_and_resume_do_not_save_daily_policy():
    control,c,_,_ = await setup()
    c.validate_request = validate_request
    await control.configure('stocks',{**control.state['jobs']['stocks']['policy'],
        'use_proxy':False,'proxy_fallback':False})
    saved = deepcopy(control.settings.mysql.data)
    seen = []
    execute = c.execute
    async def observe(**kwargs):
        seen.append((USE_PROXY.get(),PROXY_FALLBACK.get(),kwargs))
        return await execute(**kwargs)
    c.execute = observe
    try:
        await control.run('stocks',request=REQUEST)
        await asyncio.sleep(0)
        assert seen[0][:2] == (True,True)
        assert seen[0][2]['request'] == REQUEST
        with pytest.raises(ValueError,match='正在执行'):
            await control.run('stocks',request=REQUEST)
        assert control.settings.mysql.data == saved
        c.gate.set()
        await control.tasks['stocks']
        assert control.state['history'][0]['request'] == REQUEST
        assert control.state['jobs']['stocks']['policy']['use_proxy'] is False
        assert control.settings.mysql.data == saved
    finally:
        await control.stop()
