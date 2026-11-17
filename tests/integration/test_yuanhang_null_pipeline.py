"""Raw 211 NULL → next node → atomic queue, archive and typed queries."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import event

from empire.sources.yuanhang_history import MissingFinancialValue
from tests.integration.test_yuanhang_archive import native, pytestmark  # noqa: F401
from tests.test_yuanhang_null_rotation import packet
from tests.test_yuanhang_payload import CODE


def partial_packet(code):
    """Observed nine-point prelisting shape, encoded as a complete 211 frame."""
    import struct
    rows = [(20151211, 25000000., 0.), (20161215, 25000000., 9902916.),
            (20170630, 25000000., 9752916.), (20171011, 28000000., 12752916.),
            (20180104, 28000000., 13052916.), (20180601, 42000000., 19579374.),
            (20181231, 42000000., 19049874.), (20191122, 48500000., 25549874.),
            (20250311, 113275000., None)]
    descriptors = b''.join(struct.pack('<IBBH', f, 4 if f == 1 else 3, 0, 4 if f == 1 else 8)
                           for f in (1, 402, 407))
    data = b''.join(struct.pack('<id', day, total) +
                    (b'\xff' * 8 if circulating is None else struct.pack('<d', circulating))
                    for day, total, circulating in rows)
    security = ('USHA' if code.endswith('.SH') else 'USZA') + code[:6]
    extra = struct.pack('<IBBH', 5, 1, 0, 11) + security.encode() + b'\0'
    table = b'hx1.0\0' + struct.pack('<iIHHI', len(rows), 22 + len(descriptors), 20, 3, len(extra))
    table += descriptors + data + extra
    body = struct.pack('<I', len(table)) + table
    return struct.pack('<HiIHiB', 17, 1, 211, 1, len(body), 1) + body


@pytest.mark.parametrize('mode', ['prelisting', 'listed', 'existing'])
async def test_raw_partial_history_defers_only_with_exact_prelisting_and_recovers(native, monkeypatch, mode):  # noqa: F811
    import httpx

    manager, _, query, store, archive = native
    await manager.start('collector.yuanhang_financial')
    c = manager.registry.get('collector.yuanhang_financial')
    code, sibling = '688845.SH', CODE
    query.collection_scope = AsyncMock(return_value=([sibling, code], '2026-11-13'))
    c.identity.login = AsyncMock(return_value=SimpleNamespace(proxy_code='node-test', servers=['fixture']))
    original_status = c.confirmation.page_status
    async def status(*args):
        await archive.flush()
        return await original_status(*args)
    monkeypatch.setattr(c.confirmation, 'page_status', status)
    replies, recovering = [], mode == 'existing'
    securities = []
    async def exchange_frame(channel, request, **kwargs):
        selected = code if b'code=688845' in request else sibling
        securities.append(selected)
        return packet(selected) if selected == sibling or recovering else partial_packet(selected)
    monkeypatch.setattr('empire.sources.yuanhang_client.exchange_frame', exchange_frame)
    async def respond(endpoint, exchange, **kwargs):
        body = await exchange(SimpleNamespace(state={'yuanhang_authenticated': True}))
        response = SimpleNamespace(content=body, close=Mock(), reserve_decoded=Mock())
        replies.append(response)
        return response
    monkeypatch.setattr(c.http, 'request_stream', respond)
    metadata = AsyncMock(return_value=httpx.Response(200, json=dict(success=True,
        result=dict(count=1, pages=1, data=[dict(SECUCODE=code, SECURITY_CODE=code[:6],
            LISTING_STATE='0' if mode == 'listed' else '9',
            LISTING_DATE='2025-03-11 00:00:00' if mode == 'listed' else None)]))))
    monkeypatch.setattr(c.http, 'request', metadata)
    if mode == 'existing':
        await c.execute()
        before = await c.ingest.checkpoint(c.job_key)
        old = await query.capital_as_of(code, 'total', '2026-11-13')
        recovering = False
        with pytest.raises(ValueError, match='已归档'):
            await c.execute(fresh=True, baseline_revision=before['revision'])
        assert await query.capital_as_of(code, 'total', '2026-11-13') == old
    elif mode == 'listed':
        with pytest.raises(ValueError, match='point_count=9'):
            await c.execute()
    else:
        result = await c.execute()
        proof = result['deferred'][code]
        assert result['phase'] == 'complete' and result['pages'] == 1
        assert proof['point_count'] == 9 and proof['missing_fields'] == [380]
        assert proof['first_source_date'] == '2015-12-11' and proof['source_date'] == '2025-03-11'
        assert not await query.has_history(code, financial=True)
        assert await query.has_history(sibling, financial=True)
        assert len(replies) == 2 and metadata.await_count == 1
        # Prelisting exclusions are revisited on each ordinary financial round.
        recovering = True
        result = await c.execute(baseline_revision=await c.checkpoint_revision())
        assert len(replies) == 4 and result['deferred'] == {} and result['phase'] == 'complete'
        assert securities == [sibling, code, sibling, code]
        assert await query.has_history(code, financial=True)
        assert str((await query.capital_as_of(code, 'total', '2026-11-13'))['shares']) == '70120000.0000000000'
    if mode != 'prelisting':
        checkpoint = await c.ingest.checkpoint(c.job_key)
        assert checkpoint['cursor']['next_index'] == 1 and code not in checkpoint['cursor']['deferred']
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    assert all(response.close.call_count == 1 for response in replies)


async def test_raw_null_rotates_archives_replays_and_exhaustion_retains_data(native, monkeypatch):  # noqa: F811
    manager, _, query, store, archive = native
    await manager.start('collector.yuanhang_financial')
    c = manager.registry.get('collector.yuanhang_financial')
    c.request_retries = 2
    original_status = c.confirmation.page_status
    async def status(*args):
        await archive.flush()
        return await original_status(*args)
    monkeypatch.setattr(c.confirmation, 'page_status', status)
    c.identity.get_profiles = AsyncMock(return_value={n: SimpleNamespace(provisioned=True) for n in ('node001', 'node002')})
    c.identity.online_codes = lambda: {'node001', 'node002'}
    c.identity.login = AsyncMock(side_effect=lambda node, **kw: SimpleNamespace(proxy_code=node, servers=['fixture']))
    monkeypatch.setattr('empire.features.yuanhang.collector.retry_delay', lambda _: 0)
    replies, exhausted = [], False
    async def respond(endpoint, exchange, **kwargs):
        missing = exhausted or not replies
        response = SimpleNamespace(content=packet(CODE, missing=missing), close=Mock(), reserve_decoded=Mock())
        replies.append((kwargs['proxy_code'], kwargs['fresh_connection'], response))
        return response
    monkeypatch.setattr(c.http, 'request_stream', respond)
    assert (await c.execute())['phase'] == 'complete'
    assert [(node, fresh) for node, fresh, _ in replies] == [('node001', False), ('node002', True)]
    total = await query.capital_as_of(CODE, 'total', '2016-11-01')
    assert str(total['shares']) == '70120000.0000000000'
    assert await store.client.xlen(store.stream) == 0
    assert all(response.close.call_count == 1 for _, _, response in replies)
    writes = []
    def capture(conn, cursor, sql, *args):
        if 'yuanhang_' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(query.mysql.archive_engine, 'before_cursor_execute', capture)
    try:
        before = await c.ingest.checkpoint(c.job_key)
        assert (await c.execute(baseline_revision=before['revision']))['phase'] == 'complete'
        assert len(replies) == 2 and writes == []
        before = await c.ingest.checkpoint(c.job_key)
        exhausted = True
        with pytest.raises(MissingFinancialValue):
            await c.execute(fresh=True, baseline_revision=before['revision'])
        assert len(replies) == 5
        assert await c.ingest.checkpoint(c.job_key) == before
        assert await query.capital_as_of(CODE, 'total', '2016-11-01') == total
        assert writes == [] and await store.client.xlen(store.stream) == 0
        errors = await c.records.list_error_summaries(c.project_id)
        record = await c.records.get_error(c.project_id, errors['rows'][0]['id'])
        detail = record['metadata']
        assert detail['attempt'] == 3 and detail['remaining_retries'] == 0
        assert {row['node'] for row in detail['null_observations']} == {'node001', 'node002'}
        assert all(response.close.call_count == 1 for _, _, response in replies)
    finally:
        event.remove(query.mysql.archive_engine, 'before_cursor_execute', capture)
