"""Partial Redis effects and a lost actual XDEL reply preserve business results."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import event
from test_archive_units import manual_worker
from test_news_archive import news_db as news_db

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit integration opt-in required')]


@pytest.mark.parametrize('stage', ['read_pipeline_partial', 'history_partial', 'ack_reply_lost'])
async def test_partial_redis_effects_and_actual_ack_reply_loss(news_db, monkeypatch, stage):
    manager, publish, query = news_db
    worker = await manual_worker(manager)
    store, mysql = manager.registry.get('redis.store'), manager.registry.get('mysql.store')
    records = manager.registry.get('collection.records')
    batch, expected = uuid4().hex, set()
    for page in range(1, 5):
        value = await publish(100 + page, page=page, batch=batch, flush=False)
        expected.add(value.event_id + ':complete')

    if stage == 'read_pipeline_partial':
        original = store.client.pipeline

        class PartialReads:
            def __init__(self, *args, **kwargs):
                self.pipe = original(*args, **kwargs)

            async def __aenter__(self):
                await self.pipe.__aenter__()
                return self

            async def __aexit__(self, *args):
                return await self.pipe.__aexit__(*args)

            def xrange(self, *args, **kwargs):
                self.pipe.xrange(*args, **kwargs)
                return self

            async def execute(self):
                assert len(self.pipe.command_stack) == 4
                # Execute a real first read, then lose the remaining response.
                self.pipe.command_stack[:] = self.pipe.command_stack[:1]
                assert len(await self.pipe.execute()) == 1
                raise ConnectionError('injected partial Redis response')

        monkeypatch.setattr(store.client, 'pipeline', PartialReads)
        target, attribute = store.client, 'pipeline'
    elif stage == 'history_partial':
        original = records.add_archives

        async def partial_history(project, rows):
            if len(rows) > 1:
                await original(project, rows[:2])
                raise ConnectionError('injected partial Redis response')
            return await original(project, rows)

        monkeypatch.setattr(records, 'add_archives', partial_history)
        target, attribute = records, 'add_archives'
    else:
        original = store.client.xdel

        async def lost_reply(*args, **kwargs):
            assert await original(*args, **kwargs) == 4
            raise ConnectionError('injected partial Redis response')

        monkeypatch.setattr(store.client, 'xdel', lost_reply)
        target, attribute = store.client, 'xdel'

    with pytest.raises(ConnectionError, match='partial Redis'):
        await worker.flush()
    monkeypatch.setattr(target, attribute, original)
    assert await store.client.xlen(store.stream) == (0 if stage == 'ack_reply_lost' else 4)
    assert (await query.list_news())['total'] == (0 if stage == 'read_pipeline_partial' else 4)

    def forbidden(*args):
        raise AssertionError('committed replay must not access SQL')

    engines = (mysql.engine, mysql.read_engine, mysql.archive_engine)
    if stage != 'read_pipeline_partial':
        for engine in engines:
            event.listen(engine, 'before_cursor_execute', forbidden)
    try:
        await worker.flush()
    finally:
        if stage != 'read_pipeline_partial':
            for engine in engines:
                event.remove(engine, 'before_cursor_execute', forbidden)
    assert await store.client.xlen(store.stream) == 0
    assert not worker.queue.ids
    assert {row['news_id'] for row in (await query.list_news())['rows']} == {101, 102, 103, 104}
    completed = [row for row in await records.list_archives('news-test') if row['status'] == 'complete']
    assert len(completed) == 4 and {row['id'] for row in completed} == expected
