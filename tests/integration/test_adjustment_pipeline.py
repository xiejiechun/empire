"""Native facts -> shared archive -> one read-only snapshot of adjusted history."""
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.calendar.contract import month_dates
from empire.sources.yuanhang_payload import CONTRACT, digest
from tests.test_yuanhang_storage import envelope

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private UUID MySQL/Redis opt-in')]


@pytest.fixture
async def native_inputs():
    manager = build_manager(load_config())
    try:
        await manager.start('pipeline.ingest')
        await manager.start('pipeline.archive')
        await manager.start('data.adjustment')
        q, ingest, worker, redis = (manager.registry.get(k) for k in (
            'adjustment.query', 'ingest.publish', 'archive.worker', 'redis.store'))
        now = datetime.now(UTC)-timedelta(minutes=30)
        today = datetime.now(CHINA).date()
        previous_month = today.replace(day=1) - timedelta(days=1)
        with q.mysql.engine.begin() as conn:
            for month in sorted({'2026-09', today.strftime('%Y-%m'), previous_month.strftime('%Y-%m')}):
                for d in month_dates(month):
                    conn.execute(text('INSERT INTO trade_calendar(trade_date,is_trade,updated_at) VALUES(:d,:t,:now)'),
                                 dict(d=d, t=int(d.weekday()<5), now=now.replace(tzinfo=None)))

        async def publish(payload, financial=False, stamp=now):
            e = envelope(payload, financial_unit=financial, observed=stamp)
            e = e.model_copy(update=dict(batch_id=uuid4().hex, run_id=uuid4().hex))
            state = await ingest.checkpoint(e.job_key)
            await ingest.publish_page([e], job_key=e.job_key,
                expected_revision=state['revision'], cursor={'test': True})
            await worker.flush()

        def prices(value='10'):
            rows = [[d, v, v, v, v, '100', None] for d, v in (('2026-09-01',value),('2026-09-02','9'))]
            return dict(contract=CONTRACT, code='000001.SZ', native_market='USZA', year=2026,
                through='2026-09-30', history_first=rows[0][0], history_last=rows[-1][0],
                history_count=2, source_count=2, rows=rows, key_hash=digest([r[0] for r in rows]))

        def financial(cash='1', ratio='0', rp='0'):
            return dict(contract=CONTRACT, code='000001.SZ', native_market='USZA',
                actions=[['2026-09-02','0','0',ratio,rp,cash]],
                capital=[[kind,'1990-01-01','100'] for kind in ('circulating','free_float','total')])

        await publish(prices())
        await publish(financial(), True)
        yield q, redis, publish, prices, financial, now, worker
    finally:
        await manager.shutdown()


async def test_archive_to_readonly_query_no_business_dml_and_original_price(native_inputs):
    q, redis, *_ = native_inputs
    statements = []
    def capture(conn, cursor, statement, *args):
        statements.append(statement)
    event.listen(q.mysql.read_engine, 'before_cursor_execute', capture)
    try:
        first = await q.calculate('SZ','000001','2026-09-01','2026-09-02')
        assert first == await q.calculate('SZ','000001','2026-09-01','2026-09-02')
        assert first['rows'][0]['factor'] == '1'
        assert abs(Decimal(first['rows'][0]['forward_close'])-9) < Decimal('1e-45')
        assert all(s.lstrip().upper().startswith('SELECT') for s in statements)
        assert await redis.client.xlen(redis.stream) == 0
    finally:
        event.remove(q.mysql.read_engine, 'before_cursor_execute', capture)


async def test_inconsistent_source_ohlc_is_archived_marked_and_blocks_adjustment(native_inputs):
    from empire.features.yuanhang.query import YuanhangDataPlugin
    q, redis, publish, prices, _, now, _ = native_inputs
    payload = prices()
    payload['rows'][0][1:5] = ['7.65', '7.82', '7.65', '7.83']
    await publish(payload, stamp=now+timedelta(minutes=1))
    native = YuanhangDataPlugin()
    native.mysql = q.mysql
    row = (await native.prices('000001.SZ'))['rows'][0]
    assert row['high'] == Decimal('7.82') and row['close'] == Decimal('7.83') and row['quality_flags'] == 1
    assert await native.price_quality('000001.SZ') == {
        'ohlc_anomalies': 1, 'missing_volume': 0, 'missing_amount': 2, 'anomaly_dates': ['2026-09-01']}
    assert await native.audit_price(payload) == []
    assert await redis.client.xlen(redis.stream) == 0
    with pytest.raises(ValueError, match='来源OHLC关系异常'):
        await q.calculate('SZ', '000001', '2026-09-01', '2026-09-02')


async def test_explicit_volume_absence_does_not_invent_volume_or_block_price_only_adjustment(native_inputs):
    q, redis, publish, prices, _, now, _ = native_inputs
    before = await q.calculate('SZ','000001','2026-09-01','2026-09-02')
    payload = prices()
    payload['rows'][0][5] = None
    await publish(payload, stamp=now+timedelta(minutes=1))
    after = await q.calculate('SZ','000001','2026-09-01','2026-09-02')
    assert [r['forward_close'] for r in before['rows']] == [r['forward_close'] for r in after['rows']]
    assert await redis.client.xlen(redis.stream) == 0


async def test_price_and_event_revisions_late_old_and_commit_replay(native_inputs, monkeypatch):
    q, redis, publish, prices, financial, now, worker = native_inputs
    first = await q.calculate('SZ','000001','2026-09-01','2026-09-02')
    await publish(prices('11'), stamp=now+timedelta(minutes=2))
    revised = await q.calculate('SZ','000001','2026-09-01','2026-09-02')
    assert revised['input_hash'] != first['input_hash']
    await publish(prices(), stamp=now+timedelta(minutes=1))
    assert await q.calculate('SZ','000001','2026-09-01','2026-09-02') == revised
    await publish(financial('0.5'), True, now+timedelta(minutes=3))
    event_revision = await q.calculate('SZ','000001','2026-09-01','2026-09-02')
    assert event_revision['input_hash'] != revised['input_hash']
    acknowledge = worker.acknowledge
    from unittest.mock import AsyncMock
    monkeypatch.setattr(worker,'acknowledge',AsyncMock(side_effect=RuntimeError('ack failure')))
    with pytest.raises(RuntimeError, match='ack failure'):
        await publish(financial('0.5'), True, now+timedelta(minutes=4))
    assert await redis.client.xlen(redis.stream) == 1
    monkeypatch.setattr(worker,'acknowledge',acknowledge)
    await worker.flush()
    assert await redis.client.xlen(redis.stream) == 0


async def test_same_count_corruption_fails_and_missing_joint_proof_keeps_raw_only(native_inputs):
    q, _, _, _, _, _, _ = native_inputs
    with q.mysql.engine.begin() as conn:
        conn.execute(text("DELETE FROM yuanhang_series_proof WHERE series_kind='capital'"))
    result = await q.history('SZ','000001','2026-09-01','2026-09-02')
    assert '联合证明' in result['adjustment_problem']
    assert [r['close'] for r in result['rows']] == ['10','9']
    assert all(r['factor'] is None for r in result['rows'])
    with pytest.raises(ValueError, match='联合证明'):
        await q.calculate('SZ','000001','2026-09-01','2026-09-02')
    with q.mysql.engine.begin() as conn:
        conn.execute(text("UPDATE yuanhang_daily_price SET amount_yuan=1 WHERE trade_date='2026-09-01'"))
    with pytest.raises(ValueError, match='证明不匹配'):
        await q.history('SZ','000001','2026-09-01','2026-09-02')


async def test_sparse_complete_year_is_not_fabricated_into_calendar_days(native_inputs):
    q, _, publish, _, financial, now, _ = native_inputs
    await publish(financial('1','0.5','4'), True, now+timedelta(minutes=1))
    result = await q.calculate('SZ','000001','2026-09-01','2026-09-03')
    assert len(result['rows']) == 2
    assert abs(Decimal(result['rows'][-1]['reference'])-Decimal('11')/Decimal('1.5')) < Decimal('1e-26')
    with q.mysql.engine.begin() as conn:
        conn.execute(text('DELETE FROM yuanhang_price_year'))
    with pytest.raises(ValueError, match='年度证明'):
        await q.calculate('SZ','000001','2026-09-01','2026-09-03')


async def test_native_consolidation_null_capital_and_same_day_events_have_separate_usability(native_inputs):
    q, redis, publish, _, financial, now, _ = native_inputs
    p = financial('0')
    p['actions'][0][1] = '-0.5'
    p['capital'][0][2] = None
    await publish(p, True, now+timedelta(minutes=1))
    result = await q.calculate('SZ','000001','2026-09-01','2026-09-02')
    assert Decimal(result['rows'][-1]['reference']) == 20
    assert Decimal(result['rows'][-1]['factor']) == Decimal('0.5')
    p = financial('1')
    p['actions'].append(['2026-09-02','0','0.3','0','0','0.5'])
    from empire.sources.yuanhang_payload import action_key
    p['actions'].sort(key=lambda row:(row[0],action_key(row)))
    await publish(p, True, now+timedelta(minutes=2))
    with pytest.raises(ValueError,match='同日多条'):
        await q.calculate('SZ','000001','2026-09-01','2026-09-02')
    raw = await q.history('SZ','000001','2026-09-01','2026-09-02')
    assert '同日多条' in raw['adjustment_problem']
    assert [r['close'] for r in raw['rows']] == ['10','9']
    assert await redis.client.xlen(redis.stream) == 0
