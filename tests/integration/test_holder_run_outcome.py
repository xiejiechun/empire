"""Real holder collector outcome through shared control, Redis and SQL query."""
import asyncio
import json

import httpx

from empire.contracts.holders import report_key
from empire.plugins.collectors.ths_holders_source import parse
from tests.integration import test_holder_archive as archive_tests
from tests.test_holder_identity_gaps import mixed_bonds
from tests.test_ths_holders import STOCK, source

holders = archive_tests.holders
pytestmark = archive_tests.pytestmark


async def test_source_gap_run_persisted_after_archive_and_recovery(holders):
    manager, collector, query, store, _ = holders
    control = manager.entries['collection.control'].plugin
    # Keep this isolated test scheduler scoped to the actual holder contribution.
    control.definitions = {collector.project_id: control.definitions[collector.project_id]}
    await manager.start('collection.control')
    await control.configure(collector.project_id, dict(enabled=True, mode='manual',
        interval_seconds=86400, daily_time='18:00', request_retries=0,
        use_proxy=True, proxy_fallback=True))
    collector.http.request.side_effect = lambda *a, **kw: httpx.Response(
        200, content=mixed_bonds().encode('gb18030'))
    await control.run(collector.project_id)
    await asyncio.wait_for(control.tasks[collector.project_id], 20)
    saved = json.loads(await store.client.get(control.key))
    row = saved['history'][0]
    assert row['status'] == 'source_gap' and not row['error']
    assert '名称为空' in row['notice']
    assert row['result']['source_gap_units'] == row['result']['source_identity_gaps'] == 1
    assert row['result']['failed_units'] == 0
    assert await store.client.xlen(store.stream) == 0
    expected = parse(source(), query.kind, STOCK)[0]
    assert await query.detail(report_key(expected)) == expected
    collector.http.request.side_effect = lambda *a, **kw: httpx.Response(
        200, content=source().encode('gb18030'))
    await control.run(collector.project_id)
    await asyncio.wait_for(control.tasks[collector.project_id], 20)
    saved = json.loads(await store.client.get(control.key))
    assert saved['history'][0]['status'] == 'complete'
    assert not saved['jobs'][collector.project_id]['notice']
    assert saved['history'][1] == row
    assert await store.client.xlen(store.stream) == 0
