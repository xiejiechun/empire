import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from tests.prefetch_source import prefetch_http

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly")]


def suspension_row(*, resumed=None, reason="重大事项"):
    return {
        "market": "SZ", "code": "000001", "name": "平安银行",
        "suspended_at": "2004-12-27T09:30+08:00", "resumed_at": resumed,
        "suspension_type": "full_day" if resumed is None or not resumed.startswith("2004-12-27")
        else "intraday",
        "source_note": "停牌", "reason": reason,
    }


@pytest.fixture
async def suspension_db():
    cfg = copy.deepcopy(load_config())
    token = uuid4().hex
    source = 'tdx'
    cfg["redis"]["namespace"] = "empire:test:" + token
    cfg["archive"]["interval_seconds"] = 3600
    manager = build_manager(cfg)
    query = manager.entries["data.suspensions"].plugin
    query.source, query.job_key, query.project_id = source, "suspension-test", "suspension-test"
    mysql = store = None
    try:
        await manager.start("pipeline.ingest")
        await manager.start("data.suspensions")
        await manager.start("infra.archive_confirmation")
        await asyncio.sleep(.02)
        ingest = manager.registry.get("ingest.publish")
        archive = manager.registry.get("archive.worker")
        mysql, store = manager.registry.get("mysql.store"), manager.registry.get("redis.store")

        async def publish(rows=None, *, start="2004-12-27", end="2004-12-27", observed=None,
                          flush=True, batch=None, page=1):
            rows = [] if rows is None else rows
            batch = batch or uuid4().hex
            first, last = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
            rows = [{**row, 'source_dates': row.get('source_dates', [start])} for row in rows]
            checked = [(first + timedelta(days=index)).isoformat()
                       for index in range((last - first).days + 1)]
            value = make_envelope(
                source=source, dataset="suspensions.period", job_key="suspension-test", schema_version=3,
                business_key=f"{batch}:{start}:{end}", run_id=batch, batch_id=batch,
                payload={"page": page, "period": start[:7], "start_date": start,
                         "end_date": end, "checked_dates": checked, "rows": rows},
            )
            if observed:
                value = value.model_copy(update={"observed_at": observed})
            state = await ingest.checkpoint("suspension-test")
            await ingest.publish_page([value], job_key="suspension-test",
                                      expected_revision=state["revision"], cursor={"page": page})
            if flush:
                await archive.flush()
            return value

        yield manager, query, publish
    finally:
        await manager.stop("pipeline.archive", cascade=True)
        if mysql:
            def cleanup():
                with mysql.engine.begin() as conn:
                    conn.execute(text("DELETE FROM suspension_event"), {"source": source})
                    conn.execute(text("DELETE FROM collection_state"), {"source": source})
            await mysql.control(cleanup)
        if store:
            keys = [key async for key in store.client.scan_iter(
                match=cfg["redis"]["namespace"] + ":*")]
            if keys:
                assert all(key.startswith("empire:test:" + token + ":") for key in keys)
                await store.client.delete(*keys)
        await manager.shutdown()


@pytest.mark.parametrize('note', ['停牌', ''])
async def test_insert_repeat_cache_hit_and_cache_loss_have_no_duplicate_dml(suspension_db, monkeypatch, note):
    manager, query, publish = suspension_db
    archive = manager.registry.get("archive.worker")
    mysql = manager.registry.get("mysql.store")
    store = manager.registry.get("redis.store")
    row = {**suspension_row(), 'source_note': note}
    await publish([row])
    assert len(await query.list_events()) == 1
    calls = []
    original = mysql.archive

    async def capture(records):
        calls.append(records)
        return await original(records)

    monkeypatch.setattr(mysql, "archive", capture)
    await publish([row])
    assert not calls and await store.client.xlen(store.stream) == 0
    await archive.fingerprints.invalidate("suspensions", query.source)
    writes = []

    def capture_sql(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) \
                and "suspension_event" in statement:
            writes.append(statement)

    event.listen(mysql.engine, "before_cursor_execute", capture_sql)
    try:
        await publish([row])
        assert len(calls) == 1 and not writes
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(mysql.engine, "before_cursor_execute", capture_sql)


async def test_distinct_source_records_coexist_and_exact_replay_is_idempotent(suspension_db):
    manager, query, publish = suspension_db
    archive = manager.registry.get("archive.worker")
    earlier = datetime.now(UTC) - timedelta(minutes=10)
    await publish([suspension_row()], observed=earlier)
    resumed = "2004-12-28T09:30+08:00"
    await publish([suspension_row(resumed=resumed)], observed=earlier + timedelta(minutes=3))
    assert len(await query.list_events()) == 2
    await archive.fingerprints.invalidate("suspensions", query.source)
    await publish([suspension_row()], observed=earlier + timedelta(minutes=4))
    assert len(await query.list_events()) == 2
    await archive.fingerprints.invalidate("suspensions", query.source)
    await publish([suspension_row(resumed="2004-12-29T09:30+08:00", reason="旧响应")],
                  observed=earlier + timedelta(minutes=2))
    assert len(await query.list_events()) == 3
    await publish([suspension_row(resumed=resumed, reason='新说明')], observed=earlier + timedelta(minutes=5))
    await archive.fingerprints.invalidate('suspensions', query.source)
    await publish([suspension_row(resumed=resumed, reason='迟到旧说明')], observed=earlier)
    rows = await query.list_events()
    assert len(rows) == 5
    assert {row['reason'] for row in rows if (row['resumed_at'] or '').startswith('2004-12-28')} == {
        '重大事项', '新说明', '迟到旧说明'}


async def test_same_time_tdx_descriptions_archive_as_two_records(suspension_db):
    _, query, publish = suspension_db
    common = {
        'market': 'SH', 'code': '600113', 'name': '浙江东日',
        'suspended_at': '2004-12-27T09:30+08:00',
        'resumed_at': '2004-12-27T10:30+08:00', 'suspension_type': 'intraday',
    }
    await publish([
        {**common, 'source_note': '今起复牌', 'reason': '重要事项'},
        {**common, 'source_note': '停牌1小时', 'reason': '交易异常波动'},
    ])
    rows = await query.list_events(market='SH', code='600113')
    assert len(rows) == 2
    assert {(row['source_note'], row['reason']) for row in rows} == {
        ('今起复牌', '重要事项'), ('停牌1小时', '交易异常波动')}
    first = await query.list_events(market='SH', code='600113', limit=1)
    second = await query.list_events(market='SH', code='600113', limit=1, offset=1)
    assert first + second == rows
    assert await query.list_events(market='SZ', code='600113') == []
    with pytest.raises(ValueError, match='偏移'):
        await query.list_events(offset=-1)
    ascending = await query.list_events(sort_by='reason', direction='asc', limit=1)
    following = await query.list_events(sort_by='reason', direction='asc', limit=1, offset=1)
    descending = await query.list_events(sort_by='reason', direction='desc')
    assert ascending + following == list(reversed(descending))
    assert await query.list_events(start='2004-12-28', end='2004-12-28') == []
    with pytest.raises(ValueError, match='排序'):
        await query.list_events(sort_by='reason; DROP TABLE suspension_event')


async def test_empty_period_advances_coverage_but_gap_is_retained(suspension_db):
    manager, query, publish = suspension_db
    store = manager.registry.get("redis.store")
    await publish([])
    plan = await query.plan(datetime(2004, 12, 28).date())
    assert plan["start_date"] == "2004-12-27"
    with pytest.raises(Exception, match="覆盖存在日期缺口"):
        await publish([], start="2004-12-29", end="2004-12-29")
    assert await store.client.xlen(store.stream) == 1


async def test_commit_ack_failure_replays_safely_and_sql_outage_retains_message(
        suspension_db, monkeypatch):
    manager, query, publish = suspension_db
    archive = manager.registry.get("archive.worker")
    mysql = manager.registry.get("mysql.store")
    store = manager.registry.get("redis.store")
    original_ack = archive.acknowledge

    async def ack_failure(ids):
        raise ConnectionError("after commit")

    monkeypatch.setattr(archive, "acknowledge", ack_failure)
    with pytest.raises(ConnectionError):
        await publish([suspension_row()])
    assert len(await query.list_events()) == 1 and await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive, "acknowledge", original_ack)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    await archive.fingerprints.invalidate("suspensions", query.source)
    original_archive = mysql.archive

    async def offline(records):
        raise ConnectionError("SQL offline")

    monkeypatch.setattr(mysql, "archive", offline)
    with pytest.raises(ConnectionError):
        await publish([suspension_row(reason="新原因")])
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(mysql, "archive", original_archive)
    await archive.flush()
    assert {row['reason'] for row in await query.list_events()} == {"重大事项", "新原因"}


async def test_preparation_reports_partial_history(suspension_db):
    manager, query, publish = suspension_db
    from empire.core.time import CHINA
    today = datetime.now(CHINA).date()
    with manager.registry.get('mysql.store').engine.begin() as conn:
        conn.execute(text('INSERT INTO trade_calendar VALUES(:day,:flag,NOW())'),
                     [dict(day=today,flag=0),dict(day=today-timedelta(days=1),flag=1)])
    await publish([suspension_row()])
    checks = {item.criterion: item for item in await query.preparation_check()}
    assert checks["fields"].status == "pass" and checks["keys"].status == "pass"
    assert checks["coverage"].status == "fail"
    assert "2004-12-27" in checks["coverage"].measured


async def test_legacy_missing_source_day_is_repaired_and_query_verified_after_replay(suspension_db, monkeypatch):
    manager, query, publish = suspension_db
    archive = manager.registry.get('archive.worker')
    mysql = manager.registry.get('mysql.store')
    store = manager.registry.get('redis.store')
    row = {**suspension_row(resumed='2004-12-27T10:30+08:00'), 'code': '600423', 'market': 'SH'}
    await publish([row])
    await archive.fingerprints.invalidate('suspensions', query.source)
    # The isolated test owns this source; emulate a preserved pre-migration row.
    with mysql.engine.begin() as conn:
        conn.execute(text('UPDATE suspension_event SET source_dates_known=FALSE'))
        conn.execute(text('DELETE FROM suspension_source_date'))
    assert await query.list_events(code='600423', start='2004-12-27', end='2004-12-27') == []
    checks = {c.criterion: c for c in await query.preparation_check()}
    assert checks['fields'].status == 'fail' and checks['quality'].status == 'fail'
    from empire.plugins.collectors.tdx_suspensions import API_URL, TdxSuspensionCollector
    collector = TdxSuspensionCollector()
    collector.ingest = manager.registry.get('ingest.publish')
    response = httpx.Response(200, request=httpx.Request('POST', API_URL), json={
        'ErrorCode': 0, 'ResultSets': [
            {'Count': 1, 'ColName': ['sc', 'code', 'name', 'fprq', 'sj', 'sjcontent', 'tprq'],
             'Content': [[1, '600423', row['name'], '2004-12-27 10:30', '停牌', '重大事项',
                          '2004-12-27 09:30']]},
            {'Count': 1, 'ColName': ['page', 'sflag', 'sdate', 'stype'],
             'Content': [[1, 'mrtbts', '2004-12-27', 'hstfp']]},
            {'Count': 1, 'ColName': ['count'], 'Content': [[1]]},
        ]})
    collector.http = prefetch_http(response_policy=lambda _: None,
                                     request=AsyncMock(return_value=response))
    collected, _ = await collector._collect_day('2004-12-27')
    assert collected == [row]
    original_ack = archive.acknowledge
    async def fail_ack(ids):
        raise ConnectionError('after SQL commit')
    monkeypatch.setattr(archive, 'acknowledge', fail_ack)
    with pytest.raises(ConnectionError):
        await publish(collected)
    assert len(await query.list_events(code='600423', start='2004-12-27', end='2004-12-27')) == 1
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive, 'acknowledge', original_ack)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    async def no_sql(records):
        raise AssertionError('trusted repeat must not access MySQL')
    monkeypatch.setattr(mysql, 'archive', no_sql)
    await publish([row])
    assert len(await query.list_events(code='600423', start='2004-12-27', end='2004-12-27')) == 1


async def test_calendar_query_uses_source_day_and_late_dates_preserve_new_content(suspension_db):
    manager, query, publish = suspension_db
    earlier = datetime.now(UTC) - timedelta(minutes=10)
    base = {**suspension_row(), 'code': '000411', 'name': '英特集团'}
    await publish([base], observed=earlier)
    resumed = {**base, 'resumed_at': '2004-12-31T09:30+08:00',
               'source_note': '今起复牌', 'reason': '修改对价方案的沟通结果公告'}
    await publish([resumed], start='2004-12-28', end='2004-12-31',
                  observed=earlier + timedelta(minutes=4))
    assert len(await query.list_events(code='000411', start='2004-12-27', end='2004-12-27')) == 1
    rows = await query.list_events(code='000411', start='2004-12-28', end='2004-12-28')
    assert len(rows) == 1 and rows[0]['resumed_at'] is not None
    assert rows[0]['suspended_at'].startswith('2004-12-27')
    # An older observation on another source date must survive a newer cache proof.
    await publish([{**resumed, 'name': '迟到旧名称'}], start='2005-01-01', end='2005-01-01',
                  observed=earlier + timedelta(minutes=2))
    rows = await query.list_events(code='000411', start='2005-01-01', end='2005-01-01')
    assert len(rows) == 1 and rows[0]['name'] == '英特集团'
    assert len(await query.list_events(code='000411', start='2004-12-28', end='2004-12-28')) == 1
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0


async def test_completion_waits_for_successful_queue_cleanup(suspension_db, monkeypatch):
    manager, query, publish = suspension_db
    archive = manager.registry.get('archive.worker')
    confirmation = manager.registry.get('archive.confirmation')
    original = archive.acknowledge
    async def fail_cleanup(ids):
        raise RuntimeError('injected cleanup failure')
    monkeypatch.setattr(archive, 'acknowledge', fail_cleanup)
    value = await publish([suspension_row()], flush=False)
    with pytest.raises(RuntimeError, match='injected cleanup failure'):
        await archive.flush()
    assert await confirmation.page_status(
        query.source, query.job_key, query.project_id, value.batch_id, 1) is None
    monkeypatch.setattr(archive, 'acknowledge', original)
    await archive.flush()
    assert (await confirmation.page_status(
        query.source, query.job_key, query.project_id, value.batch_id, 1))['status'] == 'complete'


async def test_full_initialization_real_ingest_checkpoint_and_redis_loss(suspension_db):
    from empire.plugins.collectors.tdx_suspensions import TdxSuspensionCollector

    manager, query, _ = suspension_db
    collector = TdxSuspensionCollector(today=lambda: datetime(2026, 9, 29).date())
    collector.source, collector.job_key, collector.project_id = query.source, query.job_key, query.project_id
    collector.ingest = manager.registry.get('ingest.publish')
    collector.query = query
    collector.confirmation = manager.registry.get('archive.confirmation')
    collector.records = manager.registry.get('collection.records')
    async def collect(day, **options):
        if day == '2005-01-01':
            raise asyncio.CancelledError
        return [], 1
    collector.http = prefetch_http()
    collector.download_day = collect
    with pytest.raises(asyncio.CancelledError):
        await collector.execute()
    checkpoint = await collector.ingest.checkpoint(query.job_key)
    assert checkpoint['cursor']['period_index'] == 1
    assert 'periods' not in checkpoint['cursor']
    store = manager.registry.get('redis.store')
    await manager.registry.get('archive.worker').flush()
    assert await store.client.xlen(store.stream) == 0
    # Only this test owns this checkpoint. Simulate its loss without restarting Redis.
    await store.client.delete(f'{store.prefix}:checkpoint:{query.job_key}')
    plan = await query.plan(datetime(2026, 9, 29).date())
    assert plan['start_date'] == '2004-12-31'
    assert plan['periods'][1]['start_date'] == '2005-01-01'
