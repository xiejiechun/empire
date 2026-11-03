import json
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from empire.core.config import load_config
from empire.features.yuanhang.contract import FINANCIAL_JOB, PRICE_JOB
from empire.sources.yuanhang_payload import daily_years, digest
from scripts import migrate_yuanhang_checkpoint as module
from tests.integration.test_yuanhang_archive import native, publish, pytestmark  # noqa: F401
from tests.test_yuanhang_payload import CODE, bar, snapshot
from tests.test_yuanhang_storage import envelope


async def seed(c, store, job=PRICE_JOB):
    state = await c.ingest.checkpoint(job)
    cursor = dict(contract=2, phase='collecting', maintenance_scope='recent', force_full=False,
        scope_hash=digest([CODE, '688888.SH']), next_index=1, skipped_units=0, next_year=1900,
        snapshot_hash='', pages=1, collected=1, batch_id='test', through='2023-12-31',
        run_date='2023-12-31', deferred={})
    await c.ingest.advance_checkpoint(job_key=job, expected_revision=state['revision'], cursor=cursor)
    return await store.client.hgetall(store.prefix + ':checkpoint:' + job)


def args(tmp_path, apply=True, job=PRICE_JOB):
    previous = tmp_path / 'previous.json'
    previous.write_text(json.dumps([CODE, '688888.SH']))
    return SimpleNamespace(job=job, rebind_scope=True, previous_scope=str(previous),
                           apply=apply, backup=str(tmp_path / 'backup.json'))


async def test_drained_rebind_keeps_sql_and_batch_and_replans_only_missing_stock(native, tmp_path):  # noqa: F811
    _, c, q, store, archive = native
    payload = daily_years(snapshot((bar('2023-12-29'),)), code=CODE, through=date(2023, 12, 31))[0]
    await publish(c, archive, envelope(payload))
    old = await seed(c, store)
    codes = [CODE, '688999.SH']
    preview = await module.migrate(load_config(), args(tmp_path, False), codes)
    assert preview['changed'] and preview['before_index'] == preview['after_index'] == 1
    assert await store.client.hgetall(store.prefix + ':checkpoint:' + PRICE_JOB) == old
    assert not (tmp_path / 'backup.json').exists()
    writes = []
    def count(conn, cursor, sql, *unused):
        if sql.startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')):
            writes.append(sql)
    # Observe all maintenance engines, not just the collector's engine.
    from sqlalchemy.engine import Engine
    event.listen(Engine, 'before_cursor_execute', count)
    try:
        report = await module.migrate(load_config(), args(tmp_path), codes)
    finally:
        event.remove(Engine, 'before_cursor_execute', count)
    assert report['changed'] and report['batch_preserved'] and not writes
    saved = await c.ingest.checkpoint(PRICE_JOB)
    assert saved['cursor'] == {**json.loads(old['cursor']), 'scope_hash': digest(codes)}
    assert saved['revision'] == int(old['revision']) + 1
    assert json.loads((tmp_path / 'backup.json').read_text())['state'] == old
    recent = await q.daily_plans(store.prefix, codes, '2023-12-31', scope='recent')
    assert all(p['mode'] == 'skip' for p in recent.values())
    backfill = await q.daily_plans(store.prefix, codes, '2023-12-31', scope='backfill')
    assert backfill[CODE]['mode'] == 'skip' and backfill[codes[1]]['mode'] == 'full'
    assert not (await module.migrate(load_config(), args(tmp_path), codes))['changed']
    assert await store.client.xlen(store.stream) == 0


async def test_financial_recovery_confirms_its_own_project_and_keeps_processed_prefix(native, tmp_path):  # noqa: F811
    _, c, _, store, archive = native
    await publish(c, archive, envelope(financial_unit=True))
    old = await seed(c, store, FINANCIAL_JOB)
    report = await module.migrate(load_config(), args(tmp_path, job=FINANCIAL_JOB), [CODE, '688999.SH'])
    assert report['changed'] and report['batch_preserved']
    assert report['before_index'] == report['after_index'] == 1
    saved = await c.ingest.checkpoint(FINANCIAL_JOB)
    assert saved['cursor']['pages'] == 1 and saved['cursor']['batch_id'] == json.loads(old['cursor'])['batch_id']
    assert await store.client.xlen(store.stream) == 0


@pytest.mark.parametrize('reason', ['pending', 'unconfirmed'])
async def test_missing_archive_completion_cannot_rebind(native, tmp_path, reason):  # noqa: F811
    _, c, _, store, _ = native
    old = await seed(c, store)
    if reason == 'pending':
        await store.client.xadd(store.stream, {'envelope': '{}'})
    with pytest.raises(ValueError, match='queue is not empty|not confirmed archived'):
        await module.migrate(load_config(), args(tmp_path), [CODE, '688999.SH'])
    assert await store.client.hgetall(store.prefix + ':checkpoint:' + PRICE_JOB) == old
    assert not (tmp_path / 'backup.json').exists()


@pytest.mark.parametrize('race', ['revision', 'queue'])
async def test_last_moment_checkpoint_or_queue_change_refuses_rebind(native, tmp_path, monkeypatch, race):  # noqa: F811
    _, c, _, store, archive = native
    payload = daily_years(snapshot((bar('2023-12-29'),)), code=CODE, through=date(2023, 12, 31))[0]
    await publish(c, archive, envelope(payload))
    old = await seed(c, store)
    factory = module.create_client
    def client(settings):
        value = factory(settings)
        original = value.eval
        async def evaluate(script, *params):
            if "redis.call('HSET',KEYS[1],'cursor'" in script:
                if race == 'revision':
                    await value.hincrby(store.prefix + ':checkpoint:' + PRICE_JOB, 'revision', 1)
                else:
                    await value.xadd(store.stream, {'envelope': '{}'})
            return await original(script, *params)
        value.eval = evaluate
        return value
    monkeypatch.setattr(module, 'create_client', client)
    with pytest.raises(ValueError, match='Checkpoint or queue changed'):
        await module.migrate(load_config(), args(tmp_path), [CODE, '688999.SH'])
    assert await store.client.hget(store.prefix + ':checkpoint:' + PRICE_JOB, 'cursor') == old['cursor']
    assert json.loads((tmp_path / 'backup.json').read_text())['state'] == old
