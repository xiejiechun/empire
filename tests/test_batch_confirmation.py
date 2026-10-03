import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from empire.plugins.infra.collection_state import CollectionState


async def test_final_marker_cannot_hide_pending_earlier_page_or_ack_failure():
    value = {'batch_id': 'batch', 'page': 3, 'status': 'complete'}
    client = SimpleNamespace(get=AsyncMock(return_value=json.dumps(value)), xrange=AsyncMock())
    redis = SimpleNamespace(prefix='test', stream='test:ingest', client=client)
    mysql = SimpleNamespace(control=AsyncMock())
    state = CollectionState(mysql, redis.prefix)
    record = ('1-0', {'envelope': json.dumps({
        'source': 'source', 'job_key': 'job', 'batch_id': 'batch', 'raw_payload': {'page': 1}})})
    client.xrange.return_value = [record]
    assert await state.page_status(redis, 'source', 'job', 'project', 'batch', 3) is None
    client.xrange.return_value = []
    assert await state.page_status(redis, 'source', 'job', 'project', 'batch', 3) == value
    mysql.control.assert_not_awaited()


async def test_other_batches_do_not_block_and_scan_uses_bounded_windows():
    value = {'batch_id': 'batch', 'page': 3, 'status': 'complete'}
    client = SimpleNamespace(get=AsyncMock(return_value=json.dumps(value)), xrange=AsyncMock(
        side_effect=[[('1-0', {'envelope': json.dumps({
            'source': 'other', 'job_key': 'other', 'batch_id': 'other'})})], []]))
    redis = SimpleNamespace(prefix='test', stream='test:ingest', client=client)
    state = CollectionState(SimpleNamespace(control=AsyncMock()), redis.prefix)
    assert await state.page_status(redis, 'source', 'job', 'project', 'batch', 3) == value
    assert client.xrange.call_args.kwargs['min'] == '(1-0'
    assert client.xrange.call_args.kwargs['count'] == 32
