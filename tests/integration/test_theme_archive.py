"""Source normalization → real Redis → unified archive → official query."""
import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.themes.dataset import ThemeDailyDataset, ThemeDetailDataset
from empire.features.themes.detail_model import parse_detail
from empire.features.themes.storage_contract import map_detail
from empire.plugins.infra.redis_store import create_client
from tests.prefetch_source import prefetch_http
from tests.test_theme_detail_source import sample

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private MySQL/Redis opt-in')]


@pytest.fixture
async def themes():
    cfg = load_config()
    manager = build_manager(cfg)
    try:
        await manager.start('collector.theme_detail')
        await manager.start('collector.theme_list')
        q = manager.registry.get('themes.query')
        c = manager.registry.get('collector.theme_detail')
        c.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, json=sample())))
        q.identities = AsyncMock(return_value={'600001': '600001.SH'})
        row = dict(theme_id='148', source_theme_id='148', concept_id=None, name='示例题材', parent_id=None,
                   new_flag=0, rank_no=1, display_order=0, hot_score='10', change_rate='1.25', limit_up_count=1)
        await q.history.append([row], observed_at=datetime.now(UTC), round_id='baseline')
        yield manager, c, q, row
    finally:
        await manager.shutdown()
        client = create_client(cfg['redis'])
        prefix = cfg['redis']['namespace'] + ':'
        keys = [k async for k in client.scan_iter(match=prefix + '*')]
        assert all(k.startswith(prefix) for k in keys)
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def collect(c, **kw):
    return await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision(), **kw), 25)


async def test_detail_hot_cold_repeat_success_queue_cleanup_and_official_query(themes):
    manager, c, q, row = themes
    await collect(c)
    expected = map_detail(parse_detail(sample(), '148'), ['600001.SH'])
    assert (await q.detail('148'))['detail'] == expected
    assert await manager.registry.get('redis.store').client.xlen(manager.registry.get('redis.store').stream) == 0
    assert await q.detail_plan([row]) == []
    archive = manager.registry.get('archive.worker')
    calls, dml = [], []
    original = q.mysql.archive
    async def counted(records):
        calls.append(records)
        return await original(records)
    q.mysql.archive = counted
    def track(conn, cursor, statement, parameters, context, many):
        if 'theme_' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            dml.append(statement)
    event.listen(q.mysql.engine, 'before_cursor_execute', track)
    await collect(c, fresh=True)
    assert not calls and not dml
    await archive.fingerprints.invalidate(ThemeDetailDataset.FINGERPRINT_NAMESPACE, 'kaipanla')
    await collect(c, fresh=True)
    assert calls and not dml
    assert (await q.detail('148'))['detail'] == expected
    assert await manager.registry.get('redis.store').client.xlen(manager.registry.get('redis.store').stream) == 0


async def test_daily_shared_archive_and_old_message_does_not_replace_newer(themes):
    manager, _, q, row = themes
    c = manager.registry.get('collector.theme_list')
    from empire.core.time import CHINA
    now = datetime.now(UTC)
    day = now.astimezone(CHINA).date().isoformat()
    cursor = dict(batch_id='daily-test', page=0)
    event = c.envelope(cursor, day, {'day': day, 'rows': [row]}, observed=now)
    archive = manager.registry.get('archive.worker')
    mapping = ThemeDailyDataset()
    assert (await archive._archive_data(event, mapping.normalize(event)))['written_count'] == 1
    assert (await q.daily(day))['rows'] == [row]
    from datetime import timedelta
    prior = event.model_copy(update={'observed_at': now - timedelta(seconds=1),
                                    'raw_payload': {'page': 1, 'day': day, 'rows': [{**row, 'hot_score': '9'}]}})
    if prior.observed_at.astimezone(CHINA).date().isoformat() == day:
        assert (await archive._archive_data(prior, mapping.normalize(prior)))['written_count'] == 0
        assert (await q.daily(day))['rows'] == [row]


async def test_detail_old_source_is_acknowledged_and_validation_failure_keeps_checkpoint(themes):
    manager, c, q, _ = themes
    await collect(c)
    original = (await q.detail('148'))['detail']
    older = sample()
    older['UpdateTime'] = str(int(older['UpdateTime']) - 10)
    older['BriefIntro'] = '迟到旧内容'
    c.http.request.return_value = httpx.Response(200, json=older)
    await collect(c, fresh=True)
    assert (await q.detail('148'))['detail'] == original
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0
    before = await c.ingest.checkpoint(c.job_key)
    invalid = sample()
    invalid['StockList'][0]['Tag'][0]['Reason'] = '同条数不同理由'
    c.http.request.return_value = httpx.Response(200, json=invalid)
    with pytest.raises(ValueError):
        await collect(c, fresh=True)
    assert await c.ingest.checkpoint(c.job_key) == before
    assert (await q.detail('148'))['detail'] == original


async def test_commit_ack_failure_keeps_message_and_replay_has_no_business_dml(themes, monkeypatch):
    manager, c, q, _ = themes
    archive = manager.registry.get('archive.worker')
    store = manager.registry.get('redis.store')
    await archive.stop()
    archive.stop_event.clear()  # Manual flush only; resident loop remains stopped.
    state = await c.ingest.checkpoint(c.job_key)
    _, cursor = await c.collect_details(state, {}, fresh=False)
    assert cursor['phase'] == 'awaiting_archive'
    original_ack = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=ConnectionError('after commit')))
    with pytest.raises(ConnectionError):
        await archive.flush()
    expected = map_detail(parse_detail(sample(), '148'), ['600001.SH'])
    assert (await q.detail('148'))['detail'] == expected
    assert await store.client.xlen(store.stream) == 1
    dml = []
    def track(conn, cursor, statement, parameters, context, many):
        if 'theme_' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            dml.append(statement)
    event.listen(q.mysql.engine, 'before_cursor_execute', track)
    monkeypatch.setattr(archive, 'acknowledge', original_ack)
    await archive.flush()
    assert not dml
    assert await store.client.xlen(store.stream) == 0
    assert (await q.detail('148'))['detail'] == expected


async def test_all_detail_units_enqueue_while_archiver_is_stopped(themes):
    manager, c, q, row = themes
    await manager.registry.get('archive.worker').stop()
    manager.registry.get('archive.worker').stop_event.clear()
    rows = [row, {**row, 'theme_id': '149', 'source_theme_id': '149', 'name': '另一题材',
                  'rank_no': 2, 'display_order': 1}]
    from datetime import timedelta
    await q.history.append(rows, observed_at=datetime.now(UTC) + timedelta(seconds=1), round_id='two')
    values = [sample(), {**sample(), 'ID': '149', 'Name': '另一题材'}]
    c.http.request.side_effect = [httpx.Response(200, json=value) for value in values]
    state = await c.ingest.checkpoint(c.job_key)
    _, cursor = await asyncio.wait_for(c.collect_details(state, {}, fresh=False), 10)
    assert cursor['page'] == 2 and cursor['phase'] == 'awaiting_archive'
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 2
    assert not (await q.detail('148'))
    await manager.registry.get('archive.worker').flush()
    assert await store.client.xlen(store.stream) == 0
    for value in values:
        assert (await q.detail(value['ID']))['detail'] == map_detail(parse_detail(value, value['ID']), ['600001.SH'])
