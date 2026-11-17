import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.core.config import load_config
from empire.features.margin.contract import JOB, digest
from scripts import migrate_margin_checkpoint as module
from tests.integration.test_margin_archive import pipeline, pytestmark  # noqa: F401
from tests.test_tdx_margin import response

OLD = ['600000.SH', '688256.SH']
NEW = OLD + ['920067.BJ']


def arguments(tmp_path, apply=True):
    previous = tmp_path / 'previous.json'
    previous.write_text(json.dumps(OLD))
    return SimpleNamespace(previous_scope=str(previous), apply=apply, backup=str(tmp_path/'backup.json'))


async def seed(c, store, worker):
    def request(*args, **kwargs):
        code = json.loads(kwargs['content'])['Params'][2]
        return httpx.Response(200, json=response() if code == '600000' else {'ErrorCode': -1})
    c.http.request.side_effect = request
    with pytest.raises(ValueError):
        await c.execute(codes=OLD)
    async with asyncio.timeout(10):
        while await store.client.xlen(store.stream):
            await worker.flush()
            await asyncio.sleep(.01)
    old = await store.client.hgetall(store.prefix + ':checkpoint:' + JOB)
    assert json.loads(old['cursor'])['index'] == 1
    return old


async def test_scope_restore_then_raw_pipeline_only_requests_missing_securities(pipeline, tmp_path):  # noqa: F811
    manager, c, q, store = pipeline
    old = await seed(c, store, manager.registry.get('archive.worker'))
    c.http.request.reset_mock()
    with pytest.raises(ValueError, match='显式维护'):
        await c.execute(codes=NEW, baseline_revision=int(old['revision']))
    assert c.http.request.call_count == 0
    assert await store.client.hgetall(store.prefix + ':checkpoint:' + JOB) == old
    assert (await module.migrate(load_config(), arguments(tmp_path, False), NEW))['changed']
    assert not (tmp_path/'backup.json').exists()
    dml = []
    def count(conn, cursor, sql, *args):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')):
            dml.append(sql)
    event.listen(Engine, 'before_cursor_execute', count)
    try:
        report = await module.migrate(load_config(), arguments(tmp_path), NEW)
    finally:
        event.remove(Engine, 'before_cursor_execute', count)
    assert not dml and report['batch_preserved'] and report['before_index'] == report['after_index'] == 1
    assert json.loads((tmp_path/'backup.json').read_text())['state'] == old
    assert not (await module.migrate(load_config(), arguments(tmp_path), NEW))['changed']
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=response())
    result = await asyncio.wait_for(c.execute(codes=NEW, baseline_revision=await c.checkpoint_revision()), 20)
    assert result['phase'] == 'complete' and result['batch_id'] == json.loads(old['cursor'])['batch_id']
    assert [json.loads(call.kwargs['content'])['Params'][2] for call in c.http.request.call_args_list] == ['688256', '920067']
    assert result['pages'] == result['index'] == 3 and result['scope_hash'] == digest(NEW)
    assert await q.history(OLD[0]) == await q.history(NEW[-1])
    assert await store.client.xlen(store.stream) == 0


@pytest.mark.parametrize('reason', ['pending', 'unconfirmed', 'revision', 'queue', 'backup'])
async def test_maintenance_refuses_pending_unknown_completion_and_commit_race(pipeline, tmp_path, monkeypatch, reason):  # noqa: F811
    manager, c, _, store = pipeline
    old = await seed(c, store, manager.registry.get('archive.worker'))
    args = arguments(tmp_path)
    if reason == 'pending':
        await store.client.xadd(store.stream, {'envelope': '{}'})
    elif reason == 'unconfirmed':
        await store.client.delete(store.prefix + ':archive:progress:' + JOB)
        # A wrong batch cannot authorize this checkpoint even when SQL is complete.
        cursor = json.loads(old['cursor'])
        cursor['batch_id'] = 'b'*32
        await store.client.hset(store.prefix + ':checkpoint:' + JOB, 'cursor', json.dumps(cursor))
        old = await store.client.hgetall(store.prefix + ':checkpoint:' + JOB)
    elif reason == 'backup':
        (tmp_path/'backup.json').write_text('existing')
    else:
        factory = module.create_client
        def client(settings):
            value = factory(settings)
            original = value.eval
            async def evaluate(script, *params):
                if "redis.call('HSET',KEYS[1],'cursor'" in script:
                    if reason == 'revision':
                        await value.hincrby(store.prefix + ':checkpoint:' + JOB, 'revision', 1)
                    else:
                        await value.xadd(store.stream, {'envelope': '{}'})
                return await original(script, *params)
            value.eval = evaluate
            return value
        monkeypatch.setattr(module, 'create_client', client)
    with pytest.raises((ValueError, FileExistsError)):
        await module.migrate(load_config(), args, NEW)
    assert await store.client.hget(store.prefix + ':checkpoint:' + JOB, 'cursor') == old['cursor']
