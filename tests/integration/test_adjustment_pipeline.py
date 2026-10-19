"""Existing source contracts → shared archive → read-only factors, private schema only."""
import copy
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from empire.bootstrap import build_manager
from empire.contracts.adjustment import AdjustmentError
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.calendar.contract import month_dates
from empire.features.kaipanla.canonical import identity
from empire.features.kaipanla.dates import lifecycle
from empire.features.kaipanla.parser import parse as parse_quote
from empire.plugins.collectors.tdx_capital_source import parse as parse_capital
from empire.plugins.datasets.capital_actions import digest
from empire.plugins.datasets.capital_archive import chain
from tests.capital_samples import source as capital_source
from tests.test_kaipanla_intraday import STOCK
from tests.test_kaipanla_products import source as quote_source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private MySQL/Redis opt-in')]


@pytest.fixture
async def inputs():
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    manager = build_manager(cfg)
    store = None
    try:
        await manager.start('collector.kaipanla_quote')
        await manager.start('data.adjustment')
        q, store = manager.registry.get('adjustment.query'), manager.registry.get('redis.store')
        ingest, archive = manager.registry.get('ingest.publish'), manager.registry.get('archive.worker')
        now = datetime.now(UTC)-timedelta(minutes=30)

        async def publish(dataset, source, job, key, payload, stamp=now, schema=1):
            batch = uuid4().hex
            envelope = make_envelope(source=source, dataset=dataset, business_key=key, job_key=job,
                run_id=batch, batch_id=batch, payload=payload, schema_version=schema).model_copy(update={'observed_at': stamp})
            state = await ingest.checkpoint(job)
            await ingest.publish_page([envelope], job_key=job, expected_revision=state['revision'], cursor={'test': True})
            await archive.flush()

        for month in sorted({'2026-09', datetime.now(CHINA).strftime('%Y-%m')}):
            rows = [dict(trade_date=d.isoformat(), is_trade=d.weekday() < 5) for d in month_dates(month)]
            await publish('calendar.month', 'cninfo', 'cninfo-calendar-v1', month, dict(page=1, month=month, rows=rows))

        async def quote(day, value, stamp=now, clock=153807000, opening=None):
            body = quote_source('quote', day.replace('-', ''))
            body['real'].update(time=clock, last_px=value, open_px=value, high_px=value, low_px=value)
            if opening is not None:
                body['real']['open_px'] = opening
            row = {**parse_quote(body, '000001', date.fromisoformat(day), 'quote'), 'market': 'SZ', 'lifecycle': lifecycle(STOCK)}
            await publish('kaipanla.quote.day', 'kaipanla', 'kaipanla-quote-v1', identity(row), dict(page=1, rows=[row]), stamp)
            return row

        async def dividend(amount=10, stamp=now, ex_date='2026-09-02'):
            body = capital_source('dividends', amount=amount)
            raw = body['ResultSets'][0]['Content'][0]
            raw[1:4], raw[4:7], raw[12:15] = ['000001', '样本', 0], [0, 0, 0], ['2026-08-01', '2026-09-01', ex_date]
            rows = parse_capital('dividends', body, 10000, '2025-12-31')[0]
            await publish('dividends.unit', 'tdx', 'tdx-dividends-v1', 'SZ:000001',
                dict(page=1, unit='SZ:000001', rows=rows, manifest=None), stamp, schema=3)
            return rows

        async def rights(empty=True, stamp=now):
            rows, keys, rolling = [], [], digest([])
            if not empty:
                body = capital_source('rights_issues', code='000001')
                raw = body['ResultSets'][0]['Content'][0]
                raw[0], raw[3:7] = 0, ['2026-08-31', '2026-09-02', '2026-08-25', '2026-08-28']
                rows = parse_capital('rights_issues', body, 10000)[0]
                keys = ['SZ:000001']
                rolling = chain(rolling, keys[0], rows)
                await publish('rights_issues.unit', 'tdx', 'tdx-rights-issues-v1', keys[0],
                    dict(page=1, unit=keys[0], rows=rows, manifest=None), stamp)
            manifest = dict(units=len(keys), count=len(rows), scope_hash=digest(keys), digest=rolling)
            await publish('rights_issues.unit', 'tdx', 'tdx-rights-issues-v1', 'manifest',
                dict(page=2, unit='manifest', rows=[], manifest=manifest), stamp)

        await quote('2026-09-01', 10)
        await quote('2026-09-02', 9)
        await dividend()
        await rights()
        yield q, store, quote, dividend, rights, now, archive
    finally:
        if store:
            keys = [key async for key in store.client.scan_iter(match=cfg['redis']['namespace']+':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace']+':') for k in keys)
                await store.client.delete(*keys)
        await manager.shutdown()


async def test_archive_to_query_and_repeated_computation_has_no_business_dml(inputs):
    q, store, _, _, _, _, _ = inputs
    sql = []
    def capture(conn, cursor, statement, params, context, many):
        sql.append(statement)
    event.listen(q.mysql.read_engine, 'before_cursor_execute', capture)
    try:
        first = await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
        assert first == await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
        assert first['rows'][0]['factor'] == '1'
        assert abs(Decimal(first['rows'][0]['forward_close'])-Decimal('9')) < Decimal('1e-45')
        assert all(statement.lstrip().upper().startswith('SELECT') for statement in sql)
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.read_engine, 'before_cursor_execute', capture)


async def test_revision_old_response_and_commit_replay_propagate_only_accepted_inputs(inputs, monkeypatch):
    q, store, _, dividend, _, now, archive = inputs
    old = await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
    await dividend(5, now+timedelta(minutes=2))
    # Amount changes are distinct source plan identities, not automatically a
    # source-ID revision. The old retained plan makes the proof mismatch rather
    # than being silently discarded by a factor calculator.
    with pytest.raises(AdjustmentError, match='完整单元'):
        await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
    await dividend(10, now+timedelta(minutes=1))
    with pytest.raises(AdjustmentError):
        await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
    assert old['rows']
    acknowledge = archive.acknowledge
    from unittest.mock import AsyncMock
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ack failure')))
    with pytest.raises(RuntimeError, match='ack failure'):
        await dividend(5, now+timedelta(minutes=3))
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive, 'acknowledge', acknowledge)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0


async def test_price_revision_recomputes_hash_and_late_old_does_not_roll_back(inputs):
    q, _, quote, _, _, now, _ = inputs
    first = await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
    await quote('2026-09-01', 11, now+timedelta(minutes=2))
    new = await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
    assert first['input_hash'] != new['input_hash'] and first['rows'] != new['rows']
    await quote('2026-09-01', 10, now+timedelta(minutes=1))
    assert await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02') == new


async def test_rights_combination_and_missing_close_not_silently_filled(inputs):
    q, _, quote, _, rights, now, _ = inputs
    await rights(False, now+timedelta(minutes=1))
    result = await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
    assert abs(Decimal(result['rows'][-1]['reference'])-Decimal('10.8')/Decimal('1.3')) < Decimal('1e-26')
    with pytest.raises(AdjustmentError, match='交易日集合'):
        await q.calculate('SZ', '000001', '2026-09-01', '2026-09-03')
    await quote('2026-09-02', 9, now+timedelta(minutes=2), clock=145900000)
    with pytest.raises(AdjustmentError, match='收盘后'):
        await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')


async def test_raw_chart_remains_valid_when_archived_ex_date_is_unknown(inputs):
    q, store, quote, dividend, _, now, _ = inputs
    await dividend(stamp=now+timedelta(minutes=2), ex_date=None)
    history = await q.history('SZ', '000001', '2026-09-01', '2026-09-02')
    assert '缺少除权除息日期' in history['adjustment_problem']
    assert [r['close'] for r in history['rows']] == ['10', '9']
    assert all(r['factor'] is None and r['forward_close'] is None for r in history['rows'])
    with pytest.raises(AdjustmentError, match='缺少除权除息日期'):
        await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
    await quote('2026-09-02', 9, now+timedelta(minutes=3), clock=145900000)
    with pytest.raises(AdjustmentError, match='收盘后'):
        await q.history('SZ', '000001', '2026-09-01', '2026-09-02')
    assert await store.client.xlen(store.stream) == 0


async def test_invalid_archived_open_stays_a_gap_and_blocks_all_adjustment(inputs):
    q, store, quote, _, _, now, _ = inputs
    await quote('2026-09-02', 9, now+timedelta(minutes=2), clock=150300870, opening=0)
    history = await q.history('SZ', '000001', '2026-09-01', '2026-09-02')
    assert len(history['rows']) == 2 and history['rows'][-1]['date'] == '2026-09-02'
    assert history['rows'][0]['close'] == '10' and history['rows'][-1]['close'] is None
    assert '2026-09-02' in history['adjustment_problem'] and '缺口' in history['adjustment_problem']
    assert all(row['factor'] is None and row['forward_close'] is None for row in history['rows'])
    with pytest.raises(AdjustmentError):
        await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')
    assert await store.client.xlen(store.stream) == 0
